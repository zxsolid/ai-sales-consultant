import pytest

from app import handoff
from app.catalog import load_catalog
from app.knowledge import Knowledge


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("Беру JCB на понедельник", "готов заказать"),
        ("Хочу заказать кран на завтра", "готов заказать"),
        ("Пришлите счёт на оплату", "просит договор или счёт"),
        ("Нужен договор", "просит договор или счёт"),
        ("мой номер +7 916 123-45-67", "оставил телефон"),
        ("89161234567 звоните", "оставил телефон"),
        ("Дайте менеджера", "просит человека"),
        ("Перезвоните мне", "просит человека"),
        ("I want to book the crane", "готов заказать"),
        ("Send me the contract", "просит договор или счёт"),
        ("Can I talk to a manager?", "просит человека"),
        ("Can I cancel the order?", None),
        ("А дешевле никак?", "торгуется"),
        ("Кран опоздал, хочу вернуть деньги", "жалоба"),
    ],
)
def test_handoff_reasons(text, reason):
    assert handoff.detect(text) == reason


@pytest.mark.parametrize(
    "text",
    ["Сколько стоит кран с оператором?", "Какой расчет за переработку?", "Каток свободен?", "Что такое трал?"],
)
def test_ordinary_questions_do_not_call_manager(text):
    assert handoff.detect(text) is None


@pytest.fixture(scope="module")
def knowledge():
    return Knowledge(load_catalog())


@pytest.mark.parametrize(
    ("query", "doc"),
    [
        ("почём кран", "item:crane-25"),
        ("камаз сколько за смену", "item:kamaz-20"),
        ("что взять для септика у дома", "item:kubota-u27"),
        ("можно отменить заказ?", "policy:cancel"),
        ("работаете в Твери?", "policy:region"),
        ("без предоплаты можно?", "policy:payment"),
        ("какая скидка на 10 смен", "policy:discounts"),
        ("How much is the crane?", "item:crane-25"),
        ("Do you deliver the backhoe loader?", "policy:delivery"),
        ("Can I cancel the order?", "policy:cancel"),
        ("Any discount for 10 shifts?", "policy:discounts"),
    ],
)
def test_search_finds_right_document(knowledge, query, doc):
    assert doc in [d for d, _ in knowledge.search(query)]


def test_price_list_lists_whole_fleet():
    text = load_catalog().price_list()
    assert "Автокран Ивановец 25 т: 32000 ₽" in text
    assert "Каток Bomag 7 т: 19000 ₽ за смену, переработка 2400 ₽ в час (сейчас нет в наличии)" in text
    assert text.endswith("Другой техники нет.")
