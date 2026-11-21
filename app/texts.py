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
        "fallback": "Точный ответ даст менеджер. Передал ему вопрос, он напишет сюда в рабочее время.",
        "handoff_note": "Передал вопрос менеджеру, он напишет сюда в рабочее время.",
        "lead_start": "Оформлю заявку.",
        "lead_done": "Передал заявку менеджеру: {summary}. Он позвонит на {phone}, подтвердит время и пришлёт договор.",
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
        "fallback": "A manager will answer this. I passed him your question, he will reply here during working hours.",
        "handoff_note": "I passed your question to a manager, he will reply here during working hours.",
        "lead_start": "Let's place your order.",
        "lead_done": "Your order is with the manager: {summary}. He will call {phone}, confirm the time "
        "and send the contract.",
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
