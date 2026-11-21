from app import guard

CONTEXT = (
    "Мини-экскаватор Kubota U27. Цена смены 18000 ₽. Переработка 2300 ₽ в час. "
    "Скидки: от 5 смен подряд скидка 5%, от 10 смен подряд скидка 10%. "
    "Отменить заказ бесплатно можно не позже чем за 12 часов до подачи."
)


def test_price_from_catalog_passes():
    assert guard.check("Смена Kubota U27 стоит 18 000 ₽.", CONTEXT, "сколько стоит?").ok


def test_invented_price_is_caught():
    result = guard.check("Смена стоит 15 000 ₽.", CONTEXT, "сколько стоит?")
    assert result.unknown_numbers == [15000.0]
    assert "15000" in result.explain()


def test_invented_discount_is_caught():
    result = guard.check("Для вас скидка 15%.", CONTEXT, "скидка будет?")
    assert result.unknown_numbers == [15.0]


def test_total_from_catalog_price_and_user_count_passes():
    answer = "5 смен по 18 000 ₽ со скидкой 5% выйдет 85 500 ₽."
    assert guard.check(answer, CONTEXT, "нужен на 5 смен").ok


def test_total_with_wrong_math_is_caught():
    result = guard.check("5 смен выйдет 80 000 ₽.", CONTEXT, "нужен на 5 смен")
    assert result.unknown_numbers == [80000.0]


def test_numbers_from_question_can_be_repeated():
    assert guard.check("Подачу на 7 утра уточнит менеджер.", CONTEXT, "можно к 7 утра?").ok


def test_model_name_is_not_glued_to_price():
    assert guard.parse_numbers("Kubota U27 18 000 ₽") == {27.0, 18000.0}


def test_promise_not_in_rules_is_caught():
    result = guard.check("Гарантируем подачу через час.", CONTEXT, "когда приедете?")
    assert result.risky_phrases == ["гарантир"]


def test_negated_promise_is_fine():
    assert guard.check("Точное время подачи не гарантирую, его подтвердит менеджер.", CONTEXT, "?").ok


def test_promise_from_rules_is_fine():
    assert guard.check("Отменить бесплатно можно за 12 часов до подачи.", CONTEXT, "отмена?").ok


def test_booking_promise_is_caught():
    result = guard.check("Готово, забронировал на понедельник.", CONTEXT, "беру на понедельник")
    assert result.risky_phrases == ["забронировал"]
