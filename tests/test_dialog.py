"""Основной режим: модель сама понимает клиента и ведёт заявку, код проверяет факты."""

import json

import pytest

from app.agent import Consultant
from app.catalog import load_catalog
from app.llm import ScriptedLLM


@pytest.fixture
def catalog():
    return load_catalog()


def turn(intent, reply, need_manager=False, **order):
    return json.dumps(
        {"intent": intent, "order": order, "need_manager": need_manager, "reply": reply}, ensure_ascii=False
    )


def script(*answers):
    queue = list(answers)
    return ScriptedLLM(lambda messages: queue.pop(0))


async def test_live_order_from_question_to_done(catalog):
    llm = script(
        turn("question", "Смена автокрана 32 000 ₽. Подсказать по заявке?"),
        turn("order", "Отлично, на 10 смен. Что будете делать краном?", item="Автокран", shifts=10),
        turn(
            "order",
            "Понял. Как к вам обращаться?",
            works="монтаж плит",
            address="Химки, Ленина 3",
            date="1 декабря, 8:00",
        ),
        turn("order", "Стас, оставьте телефон: менеджер позвонит.", name="Стас"),
        turn("order", "Спасибо!", name="Стас"),
    )
    bot = Consultant(catalog, llm)
    await bot.answer("c1", "Сколько стоит автокран?")
    r = await bot.answer("c1", "давай оформим на 10 дней")
    assert r.lead_status == "collecting"
    assert r.text == "Отлично, на 10 смен. Что будете делать краном?"
    await bot.answer("c1", "монтаж плит, Химки Ленина 3, первого декабря к 8")
    r = await bot.answer("c1", "Стас")
    assert r.text == "Стас, оставьте телефон: менеджер позвонит."
    r = await bot.answer("c1", "+7 916 123-45-67")
    assert r.lead_status == "done" and r.handoff_reason == "новая заявка"
    assert "Автокран Ивановец 25 т, 10 смен: 288 000 ₽ со скидкой 10%" in r.text
    assert "Телефон: +79161234567" in r.text


async def test_state_of_order_reaches_model(catalog):
    llm = script(turn("order", "Что будете делать?", item="JCB"), turn("question", "Смена 22 000 ₽."))
    bot = Consultant(catalog, llm)
    await bot.answer("c1", "Беру JCB")
    await bot.answer("c1", "а сколько смена?")
    system = llm.calls[1][0]["content"]
    assert "Заявка идёт. Известно: техника: Экскаватор-погрузчик JCB 3CX." in system
    assert "Не хватает: что сделать, адрес, когда подать, имя, телефон." in system


async def test_answer_mid_order_gets_next_question(catalog):
    llm = script(turn("order", "Какие работы?", item="JCB"), turn("question", "Смена 22 000 ₽."))
    bot = Consultant(catalog, llm)
    await bot.answer("c1", "Беру JCB")
    r = await bot.answer("c1", "а сколько смена")
    assert r.text == "Смена 22 000 ₽. Что нужно сделать на объекте?"
    assert r.lead_status == "collecting"


async def test_client_changes_mind_and_leaves(catalog):
    llm = script(turn("order", "Какие работы?", item="JCB"), turn("decline", "Хорошо, пишите, когда решите."))
    bot = Consultant(catalog, llm)
    await bot.answer("c1", "Беру JCB")
    r = await bot.answer("c1", "не, пока дорого, подумаю")
    assert r.lead_status is None and bot.lead_of("c1") is None


async def test_manager_mid_order_gets_what_was_collected(catalog):
    llm = script(turn("order", "Какие работы?", item="JCB"), turn("manager", "Сейчас позову менеджера."))
    bot = Consultant(catalog, llm)
    await bot.answer("c1", "Беру JCB")
    r = await bot.answer("c1", "можно живого человека")
    assert r.handoff_reason == "просит человека"
    assert r.lead_status == "handoff" and r.lead.item.id == "jcb-3cx"


async def test_unknown_answer_calls_manager(catalog):
    llm = script(turn("question", "Уточню у менеджера, есть ли скидки для школ.", need_manager=True))
    r = await Consultant(catalog, llm).answer("c1", "Есть скидки для школ?")
    assert r.handoff_reason == "бот не нашёл ответа в прайсе"
    assert r.text == "Уточню у менеджера, есть ли скидки для школ."  # без второй фразы про менеджера


async def test_unknown_answer_without_manager_word_gets_note(catalog):
    llm = script(turn("question", "Такого в прайсе нет.", need_manager=True))
    r = await Consultant(catalog, llm).answer("c1", "Работаете ночью?")
    assert r.text == "Такого в прайсе нет. Передал вопрос менеджеру, он напишет сюда в рабочее время."


async def test_bargain_is_just_a_question(catalog):
    llm = script(turn("question", "Скидка 5% от 5 смен и 10% от 10 смен."))
    r = await Consultant(catalog, llm).answer("c1", "а дешевле никак?")
    assert r.handoff_reason is None


async def test_model_cannot_invent_phone_or_machine(catalog):
    llm = script(turn("order", "Какие работы?", item="Бульдозер", phone="+7 999 000-00-00"))
    bot = Consultant(catalog, llm)
    await bot.answer("c1", "хочу заказать бульдозер")
    lead = bot.lead_of("c1")
    assert lead.item is None and lead.phone is None


async def test_invented_price_in_reply_is_rewritten(catalog):
    llm = script(turn("question", "Смена крана 28 000 ₽."), turn("question", "Смена крана 32 000 ₽."))
    r = await Consultant(catalog, llm).answer("c1", "Почём кран?")
    assert r.text == "Смена крана 32 000 ₽."
    assert r.guard_failures


async def test_broken_json_falls_back_to_keywords(catalog):
    llm = ScriptedLLM(lambda messages: "Смена крана 32 000 ₽.")
    r = await Consultant(catalog, llm).answer("c1", "Почём кран?")
    assert r.text == "Смена крана 32 000 ₽."


async def test_shifts_from_words_win_over_model(catalog):
    llm = script(turn("order", "Какие работы?", item="кран", shifts=1))
    bot = Consultant(catalog, llm)
    await bot.answer("c1", "давайте кран на 3 смены")
    assert bot.lead_of("c1").shifts == 3


async def test_machine_from_earlier_message_stays_in_context(catalog):
    llm = script(
        turn("question", "Смена 32 000 ₽."), turn("question", "Скидка 10%."), turn("question", "4000 ₽ в час.")
    )
    bot = Consultant(catalog, llm)
    await bot.answer("c1", "сколько стоит автокран?")
    await bot.answer("c1", "какие скидки бывают?")
    r = await bot.answer("c1", "хочу взять на 10 смен, переработка по какой ставке?")
    assert "переработка 4000 ₽ в час" in llm.calls[2][0]["content"]
    assert r.guard_failures == []


async def test_service_words_are_rewritten(catalog):
    llm = script(turn("question", "В предоставленных данных этого нет."), turn("question", "В нашем прайсе этого нет."))
    r = await Consultant(catalog, llm).answer("c1", "Есть ли у вас бульдозер?")
    assert r.text == "В нашем прайсе этого нет."
