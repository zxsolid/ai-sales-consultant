import json

import pytest

from app.agent import BAD_ITEM, BAD_PHONE, LEAD_CANCELLED, Consultant
from app.catalog import load_catalog
from app.lead import EXTRACT_PROMPT, normalize_phone
from app.llm import ScriptedLLM


@pytest.fixture
def catalog():
    return load_catalog()


def model(extracted: dict | None = None, answer: str = "Смена 22 000 ₽."):
    """Модель для тестов: на просьбу достать данные отдаёт JSON, на остальное — ответ консультанта."""

    def reply(messages):
        if messages[0]["content"].startswith(EXTRACT_PROMPT):
            return json.dumps(extracted or {}, ensure_ascii=False)
        return answer

    return ScriptedLLM(reply)


@pytest.mark.parametrize(
    ("text", "phone"),
    [
        ("+7 916 123-45-67", "+79161234567"),
        ("8(916)1234567", "+79161234567"),
        ("мой номер 79161234567, звоните", "+79161234567"),
        ("позвоните завтра", None),
    ],
)
def test_phone_is_normalized(text, phone):
    assert normalize_phone(text) == phone


async def test_bot_asks_only_what_is_missing(catalog):
    bot = Consultant.legacy(catalog, model({"date": "понедельник", "address": "Мытищи, Мира 5"}))
    r = await bot.answer("c1", "Беру JCB на понедельник, Мытищи, Мира 5")
    assert r.text == "Оформлю заявку. Что нужно сделать на объекте?"
    r = await bot.answer("c1", "Выкопать траншею")
    assert r.text == "Как к вам обращаться?"
    r = await bot.answer("c1", "Олег")
    assert r.text == "Оставьте телефон: менеджер позвонит и подтвердит заказ."
    r = await bot.answer("c1", "+7 916 123-45-67")
    assert r.lead_status == "done"
    assert r.handoff_reason == "новая заявка"
    assert r.text.splitlines() == [
        "Передал заявку менеджеру.",
        "Экскаватор-погрузчик JCB 3CX: 22 000 ₽ за смену. Доставка и переработка считаются отдельно.",
        "Работы: Выкопать траншею",
        "Адрес: Мытищи, Мира 5",
        "Когда: понедельник",
        "Имя: Олег",
        "Телефон: +79161234567",
        "",
        "Менеджер позвонит, подтвердит время и пришлёт договор.",
    ]


async def test_card_has_everything_and_the_quote(catalog):
    bot = Consultant.legacy(
        catalog, model({"works": "котлован", "address": "Химки", "date": "завтра 8:00", "name": "Анна"})
    )
    r = await bot.answer("c1", "Беру JCB на 5 смен, телефон +7 916 123-45-67")
    assert r.lead_status == "done"
    card = r.lead.card(catalog, "Telegram", '<a href="https://t.me/anna">Анна</a>')
    assert card.splitlines() == [
        "🔥 Новая заявка (Telegram)",
        'Клиент: <a href="https://t.me/anna">Анна</a>',
        "Техника: Экскаватор-погрузчик JCB 3CX",
        "Расчёт: 5 смен по 22 000 ₽, скидка 5%, итого 104 500 ₽. Доставка и переработка отдельно.",
        "Работы: котлован",
        "Адрес: Химки",
        "Когда: завтра 8:00",
        "Имя: Анна",
        "Телефон: +79161234567",
    ]


async def test_wrong_phone_is_asked_again(catalog):
    bot = Consultant.legacy(catalog, model({"works": "котлован", "address": "Химки", "date": "завтра", "name": "Анна"}))
    await bot.answer("c1", "Беру кран")
    r = await bot.answer("c1", "позвоните попозже")
    assert r.text == BAD_PHONE
    r = await bot.answer("c1", "89161234567")
    assert r.lead_status == "done"


async def test_unknown_machine_is_asked_again(catalog):
    bot = Consultant.legacy(catalog, model({"works": "снос", "address": "Химки", "date": "завтра", "name": "Анна"}))
    r = await bot.answer("c1", "Хочу заказать технику на завтра")
    assert r.text == "Оформлю заявку. Какая техника нужна?"
    r = await bot.answer("c1", "бульдозер")
    assert r.text.startswith(BAD_ITEM.split("{")[0])
    r = await bot.answer("c1", "тогда камаз")
    assert r.text == "Оставьте телефон: менеджер позвонит и подтвердит заказ."


async def test_question_during_lead_is_answered_and_lead_goes_on(catalog):
    bot = Consultant.legacy(catalog, model({}, answer="Смена 22 000 ₽."))
    await bot.answer("c1", "Беру JCB")
    r = await bot.answer("c1", "А сколько стоит смена?")
    assert r.text == "Смена 22 000 ₽. Что нужно сделать на объекте?"
    assert r.lead_status == "collecting"


async def test_client_can_cancel_lead(catalog):
    bot = Consultant.legacy(catalog, model({}))
    await bot.answer("c1", "Беру JCB")
    r = await bot.answer("c1", "Не надо, передумал")
    assert r.text == LEAD_CANCELLED
    r = await bot.answer("c1", "Почём кран?")
    assert r.lead_status is None


async def test_broken_extraction_does_not_break_lead(catalog):
    llm = ScriptedLLM(lambda m: "не знаю" if m[0]["content"].startswith(EXTRACT_PROMPT) else "ок")
    r = await Consultant.legacy(catalog, llm).answer("c1", "Беру JCB")
    assert r.text == "Оформлю заявку. Что нужно сделать на объекте?"


async def test_question_about_cancelling_does_not_cancel_lead(catalog):
    bot = Consultant.legacy(catalog, model({}, answer="Отменить можно бесплатно за 12 часов."))
    await bot.answer("c1", "Беру JCB")
    r = await bot.answer("c1", "А отменить потом можно?")
    assert r.lead_status == "collecting"


async def test_lead_in_english(catalog):
    bot = Consultant.legacy(
        catalog, model({"works": "trench", "address": "Khimki", "date": "Monday 9am", "name": "John"})
    )
    r = await bot.answer("c1", "I want to book the crane for 2 days")
    assert (
        r.text == "Let's place your order. Please leave your phone number: a manager will call and confirm the order."
    )
    r = await bot.answer("c1", "+7 916 123-45-67")
    assert r.text.startswith("Your order is with the manager.\nАвтокран Ивановец 25 т, 2 shifts: 64 000 ₽.")
    assert r.lead.shifts == 2


async def test_yes_to_offer_starts_lead_with_what_client_said(catalog):
    bot = Consultant.legacy(
        catalog, model({"address": "Химки", "date": "01.12.2026"}, answer="Автокран свободен. Оформить заявку?")
    )
    await bot.answer("c1", "Нужен автокран, Химки")
    await bot.answer("c1", "01.12.2026")
    r = await bot.answer("c1", "Да")
    assert r.lead_status == "collecting"
    assert r.handoff_reason is None
    assert r.text == "Оформлю заявку. Что нужно сделать на объекте?"
    assert bot._leads["c1"].item.id == "crane-25"


async def test_yes_without_offer_is_a_normal_answer(catalog):
    bot = Consultant.legacy(catalog, model({}, answer="Смена 32 000 ₽. Какой адрес?"))
    await bot.answer("c1", "Почём кран?")
    r = await bot.answer("c1", "Да")
    assert r.lead_status is None


@pytest.mark.parametrize(
    ("answer", "starts"),
    [
        ("Да", True),
        ("конечно", True),
        ("Давайте", True),
        ("Yes", True),
        ("Я подумаю", False),
        ("да нет, потом", False),
        ("Да, а доставка сколько?", False),
        ("Пока не надо", False),
    ],
)
async def test_which_answers_to_offer_start_lead(catalog, answer, starts):
    bot = Consultant.legacy(catalog, model({}, answer="Автокран свободен. Оформить заявку?"))
    await bot.answer("c1", "Нужен автокран")
    r = await bot.answer("c1", answer)
    assert (r.lead_status == "collecting") is starts
