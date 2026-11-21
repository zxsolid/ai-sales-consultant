import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.agent import Consultant
from app.catalog import load_catalog
from app.channels.avito import API, AvitoClient, build_app, handle_event
from app.llm import OpenAICompatible, ScriptedLLM, YandexGPT

ME = 1001
BUYER = 2002


class Notes:
    def __init__(self):
        self.sent: list[str] = []

    async def notify(self, text: str) -> None:
        self.sent.append(text)


def event(text="Сколько стоит?", author=BUYER, item_id=4012345602, kind="text"):
    value = {"chat_id": "chat-1", "author_id": author, "user_id": ME, "type": kind, "content": {"text": text}}
    if item_id:
        value["item_id"] = item_id
    return {"payload": {"type": "message", "value": value}}


@pytest.fixture
def mock_avito():
    with respx.mock(base_url=API, assert_all_called=False) as router:
        router.post("/token").respond(json={"access_token": "t1", "expires_in": 86400})
        router.post(f"/messenger/v1/accounts/{ME}/chats/chat-1/messages").respond(json={"id": "m1"})
        router.get(f"/messenger/v2/accounts/{ME}/chats/chat-1").respond(
            json={"context": {"type": "item", "value": {"id": 4012345603}}}
        )
        yield router


def make(reply="Смена 18 000 ₽. Какой адрес?"):
    llm = ScriptedLLM(lambda messages: reply)
    return Consultant(load_catalog(), llm), llm


async def test_avito_reply_is_sent_to_chat(mock_avito):
    consultant, llm = make()
    notes = Notes()
    avito = AvitoClient("id", "secret", ME)
    sent = await handle_event(event(), avito, consultant, notes)
    assert sent == "Смена 18 000 ₽. Какой адрес?"
    send = mock_avito.calls[-1].request
    assert send.headers["Authorization"] == "Bearer t1"
    assert b'"text":"' in send.content
    assert "Kubota U27" in llm.calls[0][0]["content"]  # объявление попало в контекст
    assert notes.sent == []


async def test_own_and_non_text_messages_are_ignored(mock_avito):
    consultant, llm = make()
    avito = AvitoClient("id", "secret", ME)
    assert await handle_event(event(author=ME), avito, consultant, Notes()) is None
    assert await handle_event(event(kind="image"), avito, consultant, Notes()) is None
    assert llm.calls == []


async def test_item_is_taken_from_chat_when_event_has_none(mock_avito):
    consultant, llm = make("Смена крана 32 000 ₽.")
    await handle_event(event(item_id=None), AvitoClient("id", "secret", ME), consultant, Notes())
    assert "Автокран Ивановец 25 т" in llm.calls[0][0]["content"].split("ДАННЫЕ:")[1].splitlines()[1]


async def test_manager_gets_lead_card_when_order_is_complete(mock_avito):
    extracted = (
        '{"works": "траншея под кабель", "address": "Мытищи, Мира 5", "date": "понедельник 9:00", "name": "Олег"}'
    )
    llm = ScriptedLLM(lambda messages: extracted)
    consultant = Consultant(load_catalog(), llm)
    notes = Notes()
    avito = AvitoClient("id", "secret", ME)
    first = await handle_event(event("Беру на понедельник к 9, Мытищи Мира 5"), avito, consultant, notes)
    assert first == "Оформлю заявку. Оставьте телефон: менеджер позвонит и подтвердит заказ."
    assert notes.sent == []
    done = await handle_event(event("+7 916 123-45-67"), avito, consultant, notes)
    assert done.startswith("Передал заявку менеджеру: Мини-экскаватор Kubota U27")
    card = notes.sent[0]
    assert card.startswith("🔥 Новая заявка (Авито)")
    assert "Техника: Мини-экскаватор Kubota U27" in card
    assert "Телефон: +79161234567" in card
    assert "Имя: Олег" in card


async def test_token_is_reused(mock_avito):
    avito = AvitoClient("id", "secret", ME)
    await avito.send_message("chat-1", "a")
    await avito.send_message("chat-1", "b")
    assert mock_avito.routes[0].call_count == 1


def test_webhook_checks_secret(mock_avito):
    consultant, _ = make()
    app = build_app(AvitoClient("id", "secret", ME), consultant, Notes(), secret="s3cret")
    with TestClient(app) as client:
        assert client.post("/avito/webhook", json=event()).status_code == 403
        assert client.post("/avito/webhook?token=s3cret", json=event()).json() == {"ok": True}
    assert mock_avito.routes[1].call_count == 1  # ответ ушёл в фоне


@respx.mock
async def test_yandexgpt_request_format():
    route = respx.post(YandexGPT.URL).respond(
        json={"result": {"alternatives": [{"message": {"role": "assistant", "text": " Привет "}}]}}
    )
    llm = YandexGPT("key", "folder1")
    text = await llm.complete([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}])
    assert text == "Привет"
    req = route.calls[0].request
    assert req.headers["Authorization"] == "Api-Key key"
    assert req.headers["x-folder-id"] == "folder1"
    body = httpx.Response(200, content=req.content).json()
    assert body["modelUri"] == "gpt://folder1/yandexgpt/latest"
    assert body["messages"] == [{"role": "system", "text": "s"}, {"role": "user", "text": "u"}]


@respx.mock
async def test_openai_compatible_request_format():
    route = respx.post("https://example.test/v1/chat/completions").respond(
        json={"choices": [{"message": {"content": "Ок"}}]}
    )
    llm = OpenAICompatible("k", "some-model", base_url="https://example.test/v1/")
    assert await llm.complete([{"role": "user", "content": "u"}]) == "Ок"
    assert route.calls[0].request.headers["Authorization"] == "Bearer k"


def test_manager_sees_client_as_link():
    from app.notify import avito_client, handoff_message, telegram_client

    assert telegram_client(42, "Олег <Иванов>", "oleg") == '<a href="https://t.me/oleg">Олег &lt;Иванов&gt;</a> @oleg'
    assert telegram_client(42, "Олег", None) == '<a href="tg://user?id=42">Олег</a>'
    assert avito_client("u2i-abc").startswith('<a href="https://www.avito.ru/profile/messenger/channel/u2i-abc">')
    text = handoff_message("Telegram", telegram_client(42, "Олег", None), "торгуется", "А <b>дешевле</b>?", None)
    assert "Сообщение: А &lt;b&gt;дешевле&lt;/b&gt;?" in text
