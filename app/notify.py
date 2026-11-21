from typing import Protocol


class ManagerNotifier(Protocol):
    async def notify(self, text: str) -> None: ...


def handoff_message(source: str, chat_id: str, reason: str, question: str, item_name: str | None) -> str:
    lines = [f"🔥 Клиент ждёт менеджера ({source})", f"Причина: {reason}"]
    if item_name:
        lines.append(f"Пишет из объявления: {item_name}")
    lines += [f"Чат: {chat_id}", f"Сообщение: {question}"]
    return "\n".join(lines)


class TelegramNotifier:
    """Пишет менеджеру в Telegram. Работает и для чатов из Авито."""

    def __init__(self, bot, chat_id: int):
        self.bot, self.chat_id = bot, chat_id

    async def notify(self, text: str) -> None:
        await self.bot.send_message(self.chat_id, text)


class LogNotifier:
    """Если чат менеджера не задан, уведомления просто пишутся в лог."""

    def __init__(self, logger):
        self.logger = logger

    async def notify(self, text: str) -> None:
        self.logger.info("Менеджеру: %s", text)
