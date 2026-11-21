"""Заявка: бот сам собирает данные клиента и передаёт менеджеру готовую карточку.

Что клиент уже написал, бот берёт из сообщения и не переспрашивает.
Чего не хватает, спрашивает по одному вопросу.
"""

import json
import re
from dataclasses import dataclass, fields
from html import escape

from app.catalog import Catalog, Item, parse_shifts
from app.llm import LLM
from app.texts import TEXTS

# Российский номер: +7/8/7 и 10 цифр или просто 10 цифр с 9 в начале. Иностранный: + и 10–14 цифр.
# Границы (?<!\d) и (?!\d) нужны, чтобы ИНН и ОГРН не читались как телефон.
PHONE = re.compile(
    r"(?<![\d+])(?:(?:\+7|8|7)[\s.(-]*\d{3}|\(?9\d{2})[\s.)-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)"
    r"|\+(?!7)\d[\d\s().-]{8,16}\d(?!\d)"
)
# Отмена: короткий ответ или фраза, которая с неё начинается. «Копать не надо» — не отмена.
CANCEL = re.compile(
    r"^\W*(отмен\w*|не надо|не нужно|нет|стоп|хватит|передумал\w*|cancel\w*|stop|no|never ?mind)\b", re.IGNORECASE
)
# Вопрос без знака вопроса: «а сколько это будет стоить»
QUESTION = re.compile(
    r"\?\s*$|^\W*(а\s+)?(сколько|почём|почем|можно ли|какая|какой|какие|есть ли|how much|can i|do you|is there)\b",
    re.IGNORECASE,
)
MAX_FIELD = 300  # длинный ответ клиента обрезаем: карточка не должна упираться в лимит Telegram
MAX_PHONE_TRIES = 2

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
    raw = m.group(0)
    digits = re.sub(r"\D", "", raw)
    if raw.lstrip().startswith("+") and not digits.startswith("7"):
        return "+" + digits
    return "+7" + digits[-10:]


def clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_FIELD else text[: MAX_FIELD - 1] + "…"


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
    phone_tries: int = 0

    def missing(self) -> list[str]:
        gave_up_phone = self.phone_tries >= MAX_PHONE_TRIES
        return [f for f in QUESTIONS if getattr(self, f) in (None, "") and not (f == "phone" and gave_up_phone)]

    def summary(self) -> str:
        parts = [self.item.name if self.item else None, self.date, self.address]
        return ", ".join(p for p in parts if p)

    def card(self, catalog: Catalog, source: str, client: str, title: str = "🔥 Новая заявка") -> str:
        """Карточка менеджеру в HTML. client: ссылка на профиль клиента или на чат."""
        lines = [f"{escape(title)} ({source})", f"Клиент: {client}"]
        if self.item:
            lines.append(f"Техника: {escape(self.item.name)}")
            if not self.item.available:
                lines.append(escape(f"⚠️ Сейчас нет в наличии: {self.item.unavailable_note}".rstrip(": ")))
            if self.shifts:
                lines.append(escape(catalog.quote(self.item, self.shifts).replace("Итог по прайсу: ", "Расчёт: ")))
        labels = {"works": "Работы", "address": "Адрес", "date": "Когда", "name": "Имя", "phone": "Телефон"}
        lines += [f"{label}: {escape(getattr(self, f))}" for f, label in labels.items() if getattr(self, f)]
        if not self.phone:
            lines.append("Телефон: клиент не оставил, пишите в чат")
        return "\n".join(lines)


def fill_from_text(lead: Lead, text: str, catalog: Catalog) -> None:
    """То, что видно без модели: машина, число смен, телефон. Уже заполненное не трогает.

    Смены из сообщения про другую машину не берём: «JCB на 10 смен?», потом «беру кран».
    """
    found = catalog.find_item(text)
    lead.item = lead.item or found
    if found is None or found == lead.item:
        lead.shifts = lead.shifts or parse_shifts(text)
    lead.phone = lead.phone or normalize_phone(text)


async def extract(llm: LLM, user_messages: list[str]) -> dict[str, str]:
    """Адрес, дату, работы и имя достаёт модель. Ошибку разбора не считаем бедой: бот просто спросит."""
    text = "\n".join(f"- {m}" for m in user_messages)
    try:
        raw = await llm.complete([{"role": "user", "content": EXTRACT_PROMPT + text}])
        data = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
    except Exception:  # сбой сети или кривой JSON: бот просто спросит сам
        return {}
    if not isinstance(data, dict):
        return {}
    allowed = {f.name for f in fields(Lead)} & {"works", "address", "date", "name"}
    return {k: clip(str(v)) for k, v in data.items() if k in allowed and v not in (None, "", "null")}


def accept_answer(lead: Lead, text: str, catalog: Catalog) -> bool:
    """Записывает ответ на последний вопрос. False, если ответ не подошёл: нет номера или такой техники."""
    field_name = lead.asked
    fill_from_text(lead, text, catalog)
    if field_name == "phone":
        if lead.phone is None:
            lead.phone_tries += 1
        return lead.phone is not None
    if field_name == "item":
        return lead.item is not None
    if field_name and text.strip():
        setattr(lead, field_name, clip(text))
    return True
