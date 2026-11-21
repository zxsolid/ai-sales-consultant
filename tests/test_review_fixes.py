"""Сценарии из код-ревью: каждый раньше ломал заявку или проверку цифр."""

import json

import httpx
import pytest

from app.agent import Consultant, with_note
from app.catalog import load_catalog, parse_shifts
from app.lead import EXTRACT_PROMPT, normalize_phone
from app.llm import ScriptedLLM


@pytest.fixture
def catalog():
    return load_catalog()


def model(extracted=None, answer="Смена 22 000 ₽."):
    def reply(messages):
        if messages[0]["content"].startswith(EXTRACT_PROMPT):
            return json.dumps(extracted or {}, ensure_ascii=False)
        return answer() if callable(answer) else answer

    return ScriptedLLM(reply)


async def test_fresh_machine_wins_over_old_one(catalog):
    bot = Consultant(catalog, model())
    await bot.answer("c1", "Сколько JCB на 10 смен?")
    r = await bot.answer("c1", "Беру кран на 1 день")
    lead = bot.lead_of("c1")
    assert lead.item.id == "crane-25" and lead.shifts == 1
    assert r.lead_status == "collecting"


async def test_machine_in_text_wins_over_ad(catalog):
    bot = Consultant(catalog, model())
    await bot.answer("c1", "Беру кран", avito_item_id=4012345601)  # объявление JCB
    assert bot.lead_of("c1").item.id == "crane-25"


async def test_thanks_after_lead_is_not_a_second_lead(catalog):
    full = {"works": "монтаж", "address": "Химки", "date": "завтра", "name": "Анна"}
    bot = Consultant(catalog, model(full, answer="Пожалуйста! Ждём вас."))
    r = await bot.answer("c1", "Беру кран, +7 916 123-45-67")
    assert r.lead_status == "done"
    r = await bot.answer("c1", "Спасибо, жду договор")
    assert r.lead_status is None and r.handoff_reason is None


@pytest.mark.parametrize(
    "text",
    [
        "Сколько стоит заказать кран на 3 смены?",
        "А договор вы заключаете?",
        "Как оформить заказ?",
        "Пока не беру, просто смотрю цены",
        "ОГРНИП 318774600012345",
        "8 800 555 35 35 это ваш номер?",
    ],
)
async def test_questions_and_numbers_do_not_start_lead(catalog, text):
    r = await Consultant(catalog, model()).answer("c1", text)
    assert r.lead_status is None


@pytest.mark.parametrize("text", ["нет", "Нет, спасибо", "стоп", "no thanks"])
async def test_client_can_leave_lead(catalog, text):
    bot = Consultant(catalog, model())
    await bot.answer("c1", "Беру JCB")
    r = await bot.answer("c1", text)
    assert r.lead_status is None and bot.lead_of("c1") is None


async def test_dont_need_inside_answer_is_not_cancel(catalog):
    bot = Consultant(catalog, model())
    await bot.answer("c1", "Беру JCB")
    await bot.answer("c1", "Вывезти грунт, копать не надо")
    assert bot.lead_of("c1").works == "Вывезти грунт, копать не надо"


async def test_asking_for_manager_mid_lead_reaches_manager(catalog):
    bot = Consultant(catalog, model())
    await bot.answer("c1", "Беру JCB")
    r = await bot.answer("c1", "Позовите менеджера")
    assert r.handoff_reason == "просит человека"
    assert r.lead_status == "handoff" and r.lead.item.id == "jcb-3cx"


async def test_question_without_question_mark_mid_lead(catalog):
    bot = Consultant(catalog, model(answer="Смена 22 000 ₽."))
    await bot.answer("c1", "Беру JCB")
    r = await bot.answer("c1", "а сколько это будет стоить")
    assert r.text == "Смена 22 000 ₽. Что нужно сделать на объекте?"
    assert bot.lead_of("c1").works is None


async def test_promise_to_ask_manager_reaches_manager(catalog):
    bot = Consultant(catalog, model(answer="Уточню у менеджера и вернусь. [[MANAGER]]"))
    r = await bot.answer("c1", "Есть ли скидки для школ?")
    assert r.handoff_reason == "бот не нашёл ответа в прайсе"


async def test_manager_is_not_pinged_twice_about_same_chat(catalog):
    bot = Consultant(catalog, model(answer="Уточню у менеджера. [[MANAGER]]"))
    first = await bot.answer("c1", "Есть ли скидки для школ?")
    second = await bot.answer("c1", "А для больниц?")
    assert first.handoff_reason and second.handoff_reason is None
    human = await bot.answer("c1", "Дайте менеджера")
    assert human.handoff_reason == "просит человека"  # просьбу человека передаём всегда


async def test_bargain_is_answered_without_manager(catalog):
    r = await Consultant(catalog, model(answer="Скидка 5% от 5 смен, 10% от 10 смен.")).answer("c1", "А дешевле никак?")
    assert r.handoff_reason is None


def test_note_goes_before_question():
    note = "Передал вопрос менеджеру."
    assert (
        with_note("Есть КамАЗ. Какая техника нужна?", note)
        == "Есть КамАЗ. Передал вопрос менеджеру. Какая техника нужна?"
    )
    assert with_note("Есть КамАЗ.", note) == "Есть КамАЗ. Передал вопрос менеджеру."


@pytest.mark.parametrize("text", ["916 123-45-67", "+375 29 123-45-67", "+1 415 555 2671", "+7.916.123.45.67"])
def test_more_phone_formats(text):
    assert normalize_phone(text) is not None


async def test_lead_goes_without_phone_after_two_tries(catalog):
    full = {"works": "монтаж", "address": "Химки", "date": "завтра", "name": "Анна"}
    bot = Consultant(catalog, model(full))
    await bot.answer("c1", "Беру кран")
    await bot.answer("c1", "позвоните в телеграм")
    r = await bot.answer("c1", "пишите сюда")
    assert r.lead_status == "done"
    assert "Менеджер напишет вам сюда" in r.text
    assert "Телефон: клиент не оставил, пишите в чат" in r.lead.card(catalog, "Telegram", "x")


async def test_model_down_still_answers_and_calls_manager(catalog):
    def boom(messages):
        raise httpx.ConnectError("нет сети")

    r = await Consultant(catalog, ScriptedLLM(boom)).answer("c1", "Почём кран?")
    assert r.text.startswith("Точный ответ даст менеджер")
    assert r.handoff_reason == "модель недоступна"


async def test_model_down_does_not_block_lead(catalog):
    def boom(messages):
        raise httpx.ConnectError("нет сети")

    r = await Consultant(catalog, ScriptedLLM(boom)).answer("c1", "Беру JCB")
    assert r.lead_status == "collecting"


async def test_ok_from_russian_client_keeps_russian(catalog):
    bot = Consultant(catalog, model(answer="Кран свободен. Оформить заявку?"))
    await bot.answer("c1", "Нужен кран")
    r = await bot.answer("c1", "Ok")
    assert r.text.startswith("Оформлю заявку.")


@pytest.mark.parametrize("text", ["Ок, спасибо, я понял", "Хочу сначала узнать про доставку", "Можно дешевле"])
async def test_not_every_reply_to_offer_is_yes(catalog, text):
    bot = Consultant(catalog, model(answer="Кран свободен. Оформить заявку?"))
    await bot.answer("c1", "Нужен кран")
    r = await bot.answer("c1", text)
    assert r.lead_status is None


async def test_rules_text_is_not_an_offer(catalog):
    bot = Consultant(catalog, model(answer="Чтобы оформить заявку, менеджер уточняет адрес и дату."))
    await bot.answer("c1", "Как у вас заказать?")
    r = await bot.answer("c1", "Ок")
    assert r.lead_status is None


async def test_follow_up_question_keeps_quote(catalog):
    answers = iter(["5 смен JCB: 104 500 ₽.", "Итого 104 500 ₽, трал по МКАД 4500 ₽."])
    bot = Consultant(catalog, model(answer=lambda: next(answers)))
    await bot.answer("c1", "Нужен JCB на 5 смен подряд, сколько выйдет?")
    r = await bot.answer("c1", "А с доставкой в пределах МКАД?")
    assert r.guard_failures == []


async def test_unavailable_machine_is_flagged_in_card(catalog):
    full = {"works": "укатка", "address": "Химки", "date": "завтра", "name": "Анна"}
    bot = Consultant(catalog, model(full))
    r = await bot.answer("c1", "Беру каток на завтра, +7 916 123-45-67")
    assert "⚠️ Сейчас нет в наличии: в ремонте до 5 декабря" in r.lead.card(catalog, "Telegram", "x")


def test_in_three_days_is_not_three_shifts():
    assert parse_shifts("привезите через 3 дня") is None


async def test_same_chat_messages_are_processed_in_order(catalog):
    import asyncio

    bot = Consultant(catalog, model())
    await bot.answer("c1", "Беру JCB")
    await asyncio.gather(bot.answer("c1", "Выкопать траншею под кабель"), bot.answer("c1", "Мытищи, Мира 5"))
    lead = bot.lead_of("c1")
    assert lead.works == "Выкопать траншею под кабель" and lead.address == "Мытищи, Мира 5"


@pytest.mark.parametrize("text", ["давай оформим на 10 дней", "Оформите на завтра", "Закажу кран"])
async def test_more_ways_to_say_order(catalog, text):
    bot = Consultant(catalog, model(answer="Кран 32 000 ₽. Оформить заявку?"))
    await bot.answer("c1", "Сколько стоит автокран?")
    r = await bot.answer("c1", text)
    assert r.lead_status == "collecting"
    assert bot.lead_of("c1").item.id == "crane-25"


def test_price_of_another_machine_is_caught(catalog):
    assert catalog.mixed_up_prices("Переработка автокрана Ивановец стоит 2400 рублей в час.")
    assert catalog.mixed_up_prices("Смена крана 16 000 ₽.")
    assert not catalog.mixed_up_prices("Переработка автокрана 4000 ₽ в час.")
    assert not catalog.mixed_up_prices("Кран 32 000 ₽, а КамАЗ 16 000 ₽.")


async def test_mixed_up_price_is_rewritten(catalog):
    answers = iter(["Переработка автокрана стоит 2400 ₽ в час.", "Переработка автокрана стоит 4000 ₽ в час."])
    bot = Consultant(catalog, model(answer=lambda: next(answers)))
    r = await bot.answer("c1", "Сколько стоит переработка автокрана?")
    assert r.text.startswith("Переработка автокрана стоит 4000 ₽")
    assert "другой машины" in r.guard_failures[0]
