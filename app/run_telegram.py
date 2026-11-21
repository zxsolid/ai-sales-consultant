"""Запуск демо в Telegram: python -m app.run_telegram"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from app.agent import Consultant
from app.catalog import DEFAULT_LEARNED, load_catalog
from app.channels.telegram import build_router
from app.config import Settings
from app.followup import Followup
from app.learning import Learner
from app.notify import LogNotifier, TelegramNotifier


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = Settings()
    if not s.telegram_bot_token:
        raise SystemExit("Заполните TELEGRAM_BOT_TOKEN в .env")
    bot = Bot(s.telegram_bot_token)
    catalog = load_catalog(learned=DEFAULT_LEARNED)
    consultant = Consultant(catalog, s.make_llm())
    notifier = (
        TelegramNotifier(bot, s.manager_chat_id) if s.manager_chat_id else LogNotifier(logging.getLogger("manager"))
    )
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать разговор"),
            BotCommand(command="reset", description="Начать диалог заново"),
            BotCommand(command="help", description="Что умеет бот"),
        ]
    )
    # Текст, который видно до первого сообщения боту
    await bot.set_my_description(
        "Демо ИИ-консультанта по прайсу. Компания выдуманная: аренда спецтехники. Бот называет цены, "
        "считает сумму со скидкой, подбирает технику, оформляет заявку и передаёт её менеджеру. "
        "Цены берёт только из прайса."
    )
    await bot.set_my_short_description("ИИ-консультант по прайсу: цены, расчёт, подбор техники, заявка менеджеру")
    dp = Dispatcher()
    followup = Followup(catalog, notifier, s.followup_minutes)

    def relearn() -> None:
        # Менеджер одобрил правку: бот сразу отвечает по обновлённому прайсу
        fresh = load_catalog(learned=DEFAULT_LEARNED)
        consultant.reload(fresh)
        followup.catalog = fresh

    learner = Learner(DEFAULT_LEARNED, on_change=relearn)
    dp.include_router(build_router(consultant, notifier, followup, learner, s.manager_chat_id))
    watcher = asyncio.create_task(followup.run())  # раз в минуту ищет клиентов, которые ушли без заявки
    try:
        await dp.start_polling(bot)
    finally:
        watcher.cancel()


if __name__ == "__main__":
    asyncio.run(main())
