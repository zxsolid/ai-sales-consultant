import pytest

from app.agent import FALLBACK, HANDOFF_NOTE, Consultant
from app.catalog import load_catalog
from app.handoff import MODEL_MARKER
from app.llm import ScriptedLLM

KUBOTA_AD = 4012345602


@pytest.fixture
def catalog():
    return load_catalog()


def answers(*replies):
    """Модель, которая по очереди отвечает заданными текстами."""
    queue = list(replies)
    return ScriptedLLM(lambda messages: queue.pop(0))


async def test_good_answer_goes_to_customer(catalog):
    llm = answers("Смена автокрана 32 000 ₽. Какой адрес объекта?")
    reply = await Consultant(catalog, llm).answer("c1", "Почём кран?")
    assert reply.text == "Смена автокрана 32 000 ₽. Какой адрес объекта?"
    assert reply.handoff_reason is None
    assert reply.guard_failures == []
    assert "item:crane-25" in reply.sources
    assert len(llm.calls) == 1


async def test_invented_price_is_rewritten(catalog):
    llm = answers("Смена крана 28 000 ₽.", "Смена крана 32 000 ₽.")
    reply = await Consultant(catalog, llm).answer("c1", "Почём кран?")
    assert reply.text == "Смена крана 32 000 ₽."
    assert len(reply.guard_failures) == 1
    # Вторая попытка получила подсказку, что именно не так
    assert "28000" in llm.calls[1][-1]["content"]


async def test_bot_gives_up_and_calls_manager_instead_of_lying(catalog):
    llm = answers("Бульдозер стоит 40 000 ₽.", "Бульдозер стоит 45 000 ₽.")
    reply = await Consultant(catalog, llm).answer("c1", "Бульдозер есть?")
    assert reply.text == FALLBACK
    assert reply.handoff_reason == "бот не смог ответить без выдумок"
    assert len(reply.guard_failures) == 2


async def test_model_marker_calls_manager(catalog):
    llm = answers(f"Такого вопроса нет в прайсе, уточню у менеджера. {MODEL_MARKER}")
    reply = await Consultant(catalog, llm).answer("c1", "Есть ли у вас скидки для школ?")
    assert MODEL_MARKER not in reply.text
    assert reply.handoff_reason == "бот не нашёл ответа в данных"
    assert reply.text.endswith(HANDOFF_NOTE)


async def test_ready_to_order_calls_manager(catalog):
    llm = answers("Отлично, уточните адрес объекта.")
    reply = await Consultant(catalog, llm).answer("c1", "Беру JCB на понедельник")
    assert reply.handoff_reason == "готов заказать"
    assert reply.text == f"Отлично, уточните адрес объекта. {HANDOFF_NOTE}"


async def test_ad_context_reaches_model(catalog):
    llm = answers("Смена 18 000 ₽.")
    reply = await Consultant(catalog, llm).answer("c1", "Сколько стоит?", KUBOTA_AD)
    system = llm.calls[0][0]["content"]
    assert "Покупатель пишет из объявления: Мини-экскаватор Kubota U27" in system
    assert reply.sources[0] == "item:kubota-u27"


async def test_price_list_is_always_in_context(catalog):
    llm = answers("Здравствуйте!")
    await Consultant(catalog, llm).answer("c1", "Добрый день")
    assert "Вся техника в парке" in llm.calls[0][0]["content"]


async def test_follow_up_question_uses_previous_one(catalog):
    llm = answers("Смена автокрана 32 000 ₽.", "Переработка 4 000 ₽ в час.")
    bot = Consultant(catalog, llm)
    await bot.answer("c1", "Сколько стоит автокран?")
    reply = await bot.answer("c1", "А переработка?")
    assert reply.guard_failures == []
    assert "item:crane-25" in reply.sources
    # Модель видит прошлый вопрос и ответ
    roles = [m["role"] for m in llm.calls[1]]
    assert roles == ["system", "user", "assistant", "user"]


async def test_chats_do_not_mix(catalog):
    llm = answers("Ответ 1.", "Ответ 2.")
    bot = Consultant(catalog, llm)
    await bot.answer("c1", "Почём кран?")
    await bot.answer("c2", "Почём каток?")
    assert len(llm.calls[1]) == 2  # system + новый вопрос, без истории первого чата


async def test_bot_gets_ready_quote_instead_of_counting(catalog):
    llm = answers("5 смен JCB со скидкой 5% выйдут 104 500 ₽.")
    reply = await Consultant(catalog, llm).answer("c1", "Нужен JCB на 5 смен подряд, сколько выйдет?")
    system = llm.calls[0][0]["content"]
    assert "Расчёт для покупателя: Экскаватор-погрузчик JCB 3CX, смен подряд: 5" in system
    assert "итого 104500 ₽" in system
    assert reply.sources[0] == "quote"
    assert reply.guard_failures == []


async def test_quote_without_discount_uses_item_from_ad(catalog):
    llm = answers("3 смены выйдут 54 000 ₽.")
    await Consultant(catalog, llm).answer("c1", "Нужен на 3 дня", KUBOTA_AD)
    assert (
        "Мини-экскаватор Kubota U27, смен подряд: 3, цена смены 18000 ₽, скидки нет, итого 54000 ₽"
        in (llm.calls[0][0]["content"])
    )


async def test_wrong_total_is_rewritten(catalog):
    llm = answers("5 смен выйдут 110 000 ₽ с учётом скидки 5%.", "5 смен выйдут 104 500 ₽.")
    reply = await Consultant(catalog, llm).answer("c1", "Нужен JCB на 5 смен подряд")
    assert reply.text == "5 смен выйдут 104 500 ₽."
    assert "110000" in reply.guard_failures[0]


async def test_marker_after_full_answer_is_ignored(catalog):
    # YandexGPT ставил маркер даже после полного ответа про отмену заказа
    llm = answers(
        f"Отменить бесплатно можно за 12 часов до подачи, позже 30% смены. Какая техника нужна? {MODEL_MARKER}"
    )
    reply = await Consultant(catalog, llm).answer("c1", "Если погода испортится, можно отменить?")
    assert reply.handoff_reason is None
    assert MODEL_MARKER not in reply.text
    assert HANDOFF_NOTE not in reply.text
