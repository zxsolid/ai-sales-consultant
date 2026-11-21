"""Когда звать живого менеджера.

Бот консультирует, но не продаёт: бронь, договор, торг и жалобы ведёт человек.
"""

import re

RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "готов заказать",
        re.compile(
            r"\b(бер[уё]м?|заказ(ать|ываю|ываем|ем)|закаж(у|ем)|оформ(ить|им|ляем|ляйте|ите)|заброниру\w*"
            r"|i'?ll take it|want to (order|book|rent)|book it)\b"
        ),
    ),
    ("просит договор или счёт", re.compile(r"\b(договор\w*|сч[её]т\w*|реквизит\w*|contract|invoice)\b")),
    ("оставил телефон", re.compile(r"(?<![\d+])(?:\+7|8|7)[\s.(-]*\d{3}[\s.)-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)")),
    (
        "просит человека",
        re.compile(r"\b(менеджер\w*|живо\w* человек\w*|позвоните|перезвоните|созвон\w*|manager|call me)\b"),
    ),
    ("торгуется", re.compile(r"\b(дешевле|торг\w*|уступ\w*|скин(ете|ьте)|cheaper)\b")),
    ("жалоба", re.compile(r"\b(жалоб\w*|претензи\w*|верн\w* деньг\w*|обманул\w*|опоздал\w*|complaint|refund)\b")),
)

# Этим маркером модель просит позвать менеджера, когда не знает ответа
MODEL_MARKER = "[[MANAGER]]"


def detect(text: str) -> str | None:
    low = text.lower()
    for reason, pattern in RULES:
        if pattern.search(low):
            return reason
    return None
