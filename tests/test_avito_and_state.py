"""Авито: менеджер перехватывает чат, повтор отправки, обучение. Состояние переживает перезапуск."""

import json

import httpx
import pytest
import respx

from app.agent import Consultant
from app.catalog import load_catalog
from app.channels.avito import API, AvitoClient, ManagerLearning, SeenMessages, handle_event
from app.learning import Learner
from app.llm import ScriptedLLM
from app.storage import MemoryStore, SqliteStore

ME, BUYER = 1001, 2002


class Notes:
    def __init__(self):
        self.sent: list[str] = []

    async def notify(self, text: str) -> None:
        self.sent.append(text)


class FakeBot:
    def __init__(self):
        self.sent: list[str] = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append(text)


def event(text, author=BUYER, mid="m-in-1"):
    value = {"id": mid, "chat_id": "chat-1", "author_id": author, "type": "text", "content": {"text": text}}
    value["item_id"] = 4012345602
    return {"payload": {"type": "message", "value": value}}


def turn(intent, reply, **order):
    return json.dumps({"intent": intent, "order": order, "need_manager": False, "reply": reply}, ensure_ascii=False)


@pytest.fixture
def avito_api():
    with respx.mock(base_url=API, assert_all_called=False) as router:
        router.post("/token").respond(json={"access_token": "t1", "expires_in": 86400})
        router.post(f"/messenger/v1/accounts/{ME}/chats/chat-1/messages").respond(json={"id": "bot-msg-1"})
        yield router


async def test_bot_goes_quiet_when_manager_writes(avito_api):
    consultant = Consultant(load_catalog(), ScriptedLLM(lambda m: turn("question", "Смена 18 000 ₽.")))
    avito, bot_sent = AvitoClient("id", "secret", ME), SeenMessages()
    assert await handle_event(event("Почём миник?"), avito, consultant, Notes(), bot_sent=bot_sent)
    # Наш ответ вернулся вебхуком: это не менеджер, паузы нет
    await handle_event(
        event("Смена 18 000 ₽.", author=ME, mid="bot-msg-1"), avito, consultant, Notes(), bot_sent=bot_sent
    )
    assert not consultant.is_paused("avito:chat-1")
    # Менеджер пишет сам: бот замолкает в этом чате
    await handle_event(
        event("Добрый день, это Олег, менеджер", author=ME, mid="m-own-2"),
        avito,
        consultant,
        Notes(),
        bot_sent=bot_sent,
    )
    assert consultant.is_paused("avito:chat-1")
    assert (
        await handle_event(
            event("Олег, а когда подъедете?", mid="m-in-3"), avito, consultant, Notes(), bot_sent=bot_sent
        )
        is None
    )


async def test_bot_echo_without_id_is_not_mistaken_for_manager(avito_api):
    avito_api.post(f"/messenger/v1/accounts/{ME}/chats/chat-1/messages").respond(json={})
    consultant = Consultant(load_catalog(), ScriptedLLM(lambda m: turn("question", "Смена 18 000 ₽.")))
    avito, bot_sent = AvitoClient("id", "secret", ME), SeenMessages()
    await handle_event(event("Почём миник?"), avito, consultant, Notes(), bot_sent=bot_sent)
    await handle_event(event("Смена 18 000 ₽.", author=ME, mid="x"), avito, consultant, Notes(), bot_sent=bot_sent)
    assert not consultant.is_paused("avito:chat-1")


async def test_send_is_retried_when_avito_fails():
    with respx.mock(base_url=API) as router:
        router.post("/token").respond(json={"access_token": "t1", "expires_in": 86400})
        send = router.post(f"/messenger/v1/accounts/{ME}/chats/chat-1/messages")
        send.side_effect = [httpx.Response(502), httpx.ConnectError("сеть"), httpx.Response(200, json={"id": "ok"})]
        avito = AvitoClient("id", "secret", ME)
        avito.retry_delay = 0
        assert await avito.send_message("chat-1", "привет") == "ok"
        assert send.call_count == 3


async def test_client_error_is_not_retried():
    with respx.mock(base_url=API) as router:
        router.post("/token").respond(json={"access_token": "t1", "expires_in": 86400})
        send = router.post(f"/messenger/v1/accounts/{ME}/chats/chat-1/messages").respond(400)
        avito = AvitoClient("id", "secret", ME)
        avito.retry_delay = 0
        with pytest.raises(httpx.HTTPStatusError):
            await avito.send_message("chat-1", "привет")
        assert send.call_count == 1


async def test_avito_chat_teaches_bot_through_manager_telegram(avito_api, tmp_path):
    answer = {
        "intent": "question",
        "order": {"item": "Kubota U27"},
        "machine_word": "копалка",
        "reply": "Смена 18 000 ₽.",
    }
    consultant = Consultant(load_catalog(), ScriptedLLM(lambda m: json.dumps(answer, ensure_ascii=False)))
    bot = FakeBot()
    learning = ManagerLearning(bot, 42, Learner(tmp_path / "learned.yaml"))
    await handle_event(event("почём копалка?"), AvitoClient("id", "secret", ME), consultant, Notes(), learning=learning)
    assert bot.sent and "копалка" in bot.sent[0]


async def test_order_survives_restart(tmp_path):
    store = SqliteStore(tmp_path / "state.sqlite")
    llm = ScriptedLLM(lambda m: turn("order", "Что будете делать?", item="JCB", shifts=5))
    first = Consultant(load_catalog(), llm, store=store)
    await first.answer("c1", "Беру JCB на 5 смен")
    # Процесс перезапустили: новый объект, та же база
    second = Consultant(load_catalog(), llm, store=SqliteStore(tmp_path / "state.sqlite"))
    lead = second.lead_of("c1")
    assert lead is not None and lead.item.id == "jcb-3cx" and lead.shifts == 5
    assert second._user_messages("c1") == ["Беру JCB на 5 смен"]


async def test_pause_and_reset_are_stored():
    store = MemoryStore()
    c = Consultant(load_catalog(), ScriptedLLM(lambda m: "ок"), store=store)
    c.pause("c1", 3600)
    assert Consultant(load_catalog(), ScriptedLLM(lambda m: "ок"), store=store).is_paused("c1")
    c.reset("c1")
    assert store.load("c1") is None
