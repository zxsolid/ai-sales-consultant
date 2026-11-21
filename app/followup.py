"""Упущенные клиенты: спросил про технику или начал заявку, но замолчал.

Через заданное время тишины бот пишет менеджеру, кто это был, чем интересовался
и на каком шаге заявки остановился. Одно уведомление на одну паузу клиента.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from html import escape

from app.catalog import Catalog
from app.lead import Lead
from app.notify import ManagerNotifier

log = logging.getLogger("followup")

STEP = {
    "item": "какая техника",
    "works": "что сделать на объекте",
    "address": "адрес",
    "date": "дата",
    "name": "имя",
    "phone": "телефон",
}


@dataclass
class Visit:
    source: str
    client: str  # HTML-ссылка на профиль или чат
    last_at: float
    items: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    lead: Lead | None = None
    manager_knows: bool = False  # менеджер уже получил заявку или вызов по этому клиенту
    notified: bool = False


class Followup:
    def __init__(
        self,
        catalog: Catalog,
        notifier: ManagerNotifier,
        idle_minutes: float = 30,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.catalog, self.notifier = catalog, notifier
        self.idle = idle_minutes * 60
        self.clock = clock
        self.visits: dict[str, Visit] = {}

    def seen(
        self,
        chat_id: str,
        source: str,
        client: str,
        text: str,
        lead: Lead | None = None,
        manager_notified: bool = False,
        item_name: str | None = None,
    ) -> None:
        """Отметить сообщение клиента. lead: незаконченная заявка, если она есть."""
        visit = self.visits.get(chat_id)
        if visit is None or visit.notified:
            visit = self.visits[chat_id] = Visit(source, client, self.clock())
        visit.last_at = self.clock()
        visit.messages = [*visit.messages, text][-3:]
        item = self.catalog.find_item(text)
        for name in (item_name, item.name if item else None, lead.item.name if lead and lead.item else None):
            if name and name not in visit.items:
                visit.items.append(name)
        visit.lead = lead
        visit.manager_knows = visit.manager_knows or manager_notified

    def forget(self, chat_id: str) -> None:
        self.visits.pop(chat_id, None)

    def due(self) -> list[tuple[str, Visit]]:
        now = self.clock()
        return [
            (chat_id, v)
            for chat_id, v in self.visits.items()
            if not v.notified and not v.manager_knows and (v.items or v.lead) and now - v.last_at >= self.idle
        ]

    @staticmethod
    def message(visit: Visit) -> str:
        lines = [f"💤 Ушёл без заявки ({visit.source})", f"Клиент: {visit.client}"]
        if visit.items:
            lines.append("Интересовался: " + escape(", ".join(visit.items)))
        lead = visit.lead
        if lead is not None:
            got = [
                f"{label}: {getattr(lead, f)}"
                for f, label in (
                    ("works", "работы"),
                    ("address", "адрес"),
                    ("date", "когда"),
                    ("name", "имя"),
                    ("phone", "телефон"),
                )
                if getattr(lead, f)
            ]
            step = STEP.get(lead.asked or "", "начало")
            lines.append(escape(f"Заявка: остановился на вопросе «{step}». " + ", ".join(got)).rstrip(". "))
        lines.append("Последние сообщения: " + escape(", ".join(f"«{m}»" for m in visit.messages)))
        return "\n".join(lines)

    async def check(self) -> int:
        sent = 0
        for _, visit in self.due():
            visit.notified = True
            try:
                await self.notifier.notify(self.message(visit))
                sent += 1
            except Exception:
                log.exception("Не удалось написать менеджеру про ушедшего клиента")
        return sent

    async def run(self, every_seconds: float = 60) -> None:
        while True:
            await asyncio.sleep(every_seconds)
            await self.check()
