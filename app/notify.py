"""Сообщения менеджеру. Пишем в HTML, чтобы клиент в карточке был ссылкой."""

import logging
from html import escape
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.agent import Reply
    from app.catalog import Catalog

log = logging.getLogger("manager")


class ManagerNotifier(Protocol):
    async def notify(self, text: str) -> None: ...


def telegram_client(user_id: int, full_name: str, username: str | None) -> str:
    """Имя клиента ссылкой на его профиль: менеджер нажимает и пишет ему в Telegram."""
    link = f"https://t.me/{username}" if username else f"tg://user?id={user_id}"
    name = escape(full_name or username or str(user_id))
    return f'<a href="{link}">{name}</a>' + (f" @{escape(username)}" if username else "")


def avito_client(chat_id: str) -> str:
    """Ссылка на чат в мессенджере Авито. Формат ссылки проверить на боевом аккаунте."""
    return f'<a href="https://www.avito.ru/profile/messenger/channel/{escape(chat_id)}">чат в Авито</a>'


def conversation(recent: list[str]) -> str:
    return "Переписка: " + escape(" → ".join(f"«{m[:200]}»" for m in recent))


def handoff_message(
    source: str,
    client: str,
    reason: str,
    recent: list[str],
    item_name: str | None = None,
    interest: list[str] | None = None,
) -> str:
    """Что хочет клиент: о какой технике речь и что он писал. client уже готовый HTML."""
    lines = [f"🔥 Клиент ждёт менеджера ({source})", f"Клиент: {client}", f"Причина: {escape(reason)}"]
    if item_name:
        lines.append(f"Пишет из объявления: {escape(item_name)}")
    if interest:
        lines.append("Интересуется: " + escape(", ".join(interest)))
    lines.append(conversation(recent))
    return "\n".join(lines)


def manager_message(
    reply: "Reply", catalog: "Catalog", source: str, client: str, text: str, item_name: str | None
) -> str | None:
    """Что написать менеджеру после ответа клиенту. None: писать нечего."""
    if reply.lead is not None:
        title = (
            "🔥 Новая заявка" if reply.lead_status == "done" else f"🔥 Клиент ждёт менеджера: {reply.handoff_reason}"
        )
        card = reply.lead.card(catalog, source, client, title)
        return card if reply.lead_status == "done" else card + "\n" + conversation(reply.recent or [text])
    if reply.handoff_reason:
        return handoff_message(source, client, reply.handoff_reason, reply.recent or [text], item_name, reply.interest)
    return None


async def tell_manager(notifier: ManagerNotifier, message: str | None) -> None:
    """Если Telegram недоступен, заявка не пропадает: целиком пишем её в лог."""
    if not message:
        return
    try:
        await notifier.notify(message)
    except Exception:
        log.exception("Не удалось написать менеджеру. Сообщение:\n%s", message)


class TelegramNotifier:
    """Пишет менеджеру в Telegram. Работает и для чатов из Авито."""

    def __init__(self, bot, chat_id: int):
        self.bot, self.chat_id = bot, chat_id

    async def notify(self, text: str) -> None:
        await self.bot.send_message(self.chat_id, text, parse_mode="HTML", disable_web_page_preview=True)


class LogNotifier:
    """Если чат менеджера не задан, уведомления просто пишутся в лог."""

    def __init__(self, logger):
        self.logger = logger

    async def notify(self, text: str) -> None:
        self.logger.info("Менеджеру: %s", text)
