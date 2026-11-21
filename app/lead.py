"""Заявка: бот сам собирает данные клиента и передаёт менеджеру готовую карточку.

Что клиент уже написал, бот берёт из сообщения и не переспрашивает.
Чего не хватает, спрашивает по одному вопросу.
"""

import json
import re
from dataclasses import dataclass, fields

from app.catalog import Catalog, Item, parse_shifts
from app.llm import LLM
from app.texts import TEXTS

PHONE = re.compile(r"(?:\+7|8|7)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}")
CANCEL = re.compile(r"\b(отмен\w*|не надо|передумал\w*|не нужно|cancel\w*|never ?mind)\b", re.IGNORECASE)

# Порядок вопросов. Сами вопросы лежат в app/texts.py
QUESTIONS = tuple(TEXTS["ru"]["questions"])

EXTRACT_PROMPT = """Клиент хочет заказать аренду спецтехники. Достань из его сообщений данные для заявки.
Верни только JSON без пояснений:
{"works": "что нужно сделать", "address": "адрес объекта", "date": "дата и время подачи", "name": "имя клиента"}
Если чего-то в сообщениях нет, поставь null. Ничего не придумывай.

Сообщения клиента:
"""


def normalize_phone(text: str) -> str | None:
    m = PHONE.search(text)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(0))
    return "+7" + digits[-10:]


@dataclass
class Lead:
    item: Item | None = None
    shifts: int | None = None
    works: str | None = None
    address: str | None = None
    date: str | None = None
    name: str | None = None
    phone: str | None = None
    asked: str | None = None  # какой вопрос задали последним
    lang: str = "ru"

    def missing(self) -> list[str]:
        return [f for f in QUESTIONS if getattr(self, f) in (None, "")]

    def summary(self) -> str:
        parts = [self.item.name if self.item else None, self.date, self.address]
        return ", ".join(p for p in parts if p)

    def card(self, catalog: Catalog, source: str, chat_id: str) -> str:
        lines = [f"🔥 Новая заявка ({source})"]
        if self.item:
            lines.append(f"Техника: {self.item.name}")
            if self.shifts:
                lines.append(catalog.quote(self.item, self.shifts).replace("Итог по прайсу: ", "Расчёт: "))
        labels = {"works": "Работы", "address": "Адрес", "date": "Когда", "name": "Имя", "phone": "Телефон"}
        lines += [f"{label}: {getattr(self, f)}" for f, label in labels.items() if getattr(self, f)]
        lines.append(f"Чат: {chat_id}")
        return "\n".join(lines)


def fill_from_text(lead: Lead, text: str, catalog: Catalog) -> None:
    """То, что видно без модели: машина, число смен, телефон."""
    lead.item = lead.item or catalog.find_item(text)
    lead.shifts = lead.shifts or parse_shifts(text)
    lead.phone = lead.phone or normalize_phone(text)


async def extract(llm: LLM, user_messages: list[str]) -> dict[str, str]:
    """Адрес, дату, работы и имя достаёт модель. Ошибку разбора не считаем бедой: бот просто спросит."""
    text = "\n".join(f"- {m}" for m in user_messages)
    try:
        raw = await llm.complete([{"role": "user", "content": EXTRACT_PROMPT + text}])
        data = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
    except (ValueError, KeyError):
        return {}
    allowed = {f.name for f in fields(Lead)} & {"works", "address", "date", "name"}
    return {k: str(v).strip() for k, v in data.items() if k in allowed and v not in (None, "", "null")}


def accept_answer(lead: Lead, text: str, catalog: Catalog) -> bool:
    """Записывает ответ на последний вопрос. False, если ответ не подошёл: нет номера или такой техники."""
    field_name = lead.asked
    fill_from_text(lead, text, catalog)
    if field_name == "phone":
        return lead.phone is not None
    if field_name == "item":
        return lead.item is not None
    if field_name and text.strip():
        setattr(lead, field_name, text.strip())
    return True
