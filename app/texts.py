"""Все фразы, которые бот пишет клиенту сам, без модели. По-русски и по-английски."""

import re

CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)
LATIN = re.compile(r"[a-z]", re.IGNORECASE)


def lang_of(text: str) -> str:
    """Английский, только если в сообщении латиница и ни одной русской буквы."""
    if not CYRILLIC.search(text) and LATIN.search(text):
        return "en"
    return "ru"


TEXTS = {
    "ru": {
        "labels": {
            "works": "Работы",
            "address": "Адрес",
            "date": "Когда",
            "name": "Имя",
            "phone": "Телефон",
            "shifts": "смен",
            "discount": "со скидкой {pct}%",
            "extra": "Доставка и переработка считаются отдельно.",
            "per_shift": "{price} ₽ за смену",
        },
        "fallback": "Точный ответ даст менеджер. Передал ему вопрос, он напишет сюда в рабочее время.",
        "handoff_note": "Передал вопрос менеджеру, он напишет сюда в рабочее время.",
        "lead_start": "Оформлю заявку.",
        "lead_done": "Передал заявку менеджеру.\n{details}\n\nМенеджер позвонит, подтвердит время и пришлёт договор.",
        "lead_done_no_phone": "Передал заявку менеджеру.\n{details}\n\n"
        "Менеджер напишет вам сюда, подтвердит время и пришлёт договор.",
        "lead_cancelled": "Хорошо, заявку отменил. Если будут вопросы, пишите.",
        "bad_phone": "Не разобрал номер. Напишите его так: +7 900 123-45-67.",
        "bad_item": "Такой техники нет. В парке: {items}. Какая подойдёт?",
        "questions": {
            "item": "Какая техника нужна?",
            "works": "Что нужно сделать на объекте?",
            "address": "Какой адрес объекта?",
            "date": "На какую дату и время подать технику?",
            "name": "Как к вам обращаться?",
            "phone": "Оставьте телефон: менеджер позвонит и подтвердит заказ.",
        },
    },
    "en": {
        "labels": {
            "works": "Work",
            "address": "Address",
            "date": "When",
            "name": "Name",
            "phone": "Phone",
            "shifts": "shifts",
            "discount": "with {pct}% discount",
            "extra": "Delivery and overtime are extra.",
            "per_shift": "{price} ₽ per shift",
        },
        "fallback": "A manager will answer this. I passed him your question, he will reply here during working hours.",
        "handoff_note": "I passed your question to a manager, he will reply here during working hours.",
        "lead_start": "Let's place your order.",
        "lead_done": "Your order is with the manager.\n{details}\n\nThe manager will call you, confirm the time "
        "and send the contract.",
        "lead_done_no_phone": "Your order is with the manager.\n{details}\n\nThe manager will write to you here, "
        "confirm the time and send the contract.",
        "lead_cancelled": "OK, order cancelled. Write if you have questions.",
        "bad_phone": "I couldn't read the number. Please write it like this: +7 900 123-45-67.",
        "bad_item": "We don't have that machine. Our fleet: {items}. Which one suits you?",
        "questions": {
            "item": "Which machine do you need?",
            "works": "What needs to be done on site?",
            "address": "What is the site address?",
            "date": "What date and time should the machine arrive?",
            "name": "What is your name?",
            "phone": "Please leave your phone number: a manager will call and confirm the order.",
        },
    },
}
