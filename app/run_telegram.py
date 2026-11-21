"""Запуск демо в Telegram: python -m app.run_telegram"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

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
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать разговор"),
            BotCommand(command="ad", description="Выбрать объявление, из которого пишете"),
            BotCommand(command="reset", description="Начать диалог заново"),
            BotCommand(command="help", description="Что умеет бот"),
        ]
    )
    # Текст, который видно до первого сообщения боту
    await bot.set_my_description(
        "Демо ИИ-консультанта для чатов Авито: аренда спецтехники. Отвечает по прайсу, считает сумму "
        "со скидкой, подбирает технику, не выдумывает цены и зовёт менеджера, когда клиент готов заказать."
    )
    await bot.set_my_short_description("ИИ-консультант по аренде спецтехники: цены, расчёт, подбор, менеджер")
    dp = Dispatcher()
    dp.include_router(build_router(consultant, notifier))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
