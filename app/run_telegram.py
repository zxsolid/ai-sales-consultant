"""Запуск демо в Telegram: python -m app.run_telegram"""

import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.agent import Consultant
from app.catalog import load_catalog
from app.channels.telegram import build_router
from app.config import Settings
from app.notify import LogNotifier, TelegramNotifier


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = Settings()
    if not s.telegram_bot_token:
        raise SystemExit("Заполните TELEGRAM_BOT_TOKEN в .env")
    bot = Bot(s.telegram_bot_token)
    consultant = Consultant(load_catalog(), s.make_llm())
    notifier = (
        TelegramNotifier(bot, s.manager_chat_id) if s.manager_chat_id else LogNotifier(logging.getLogger("manager"))
    )
    dp = Dispatcher()
    dp.include_router(build_router(consultant, notifier))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
