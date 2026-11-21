"""Вебхук для Авито: uvicorn app.run_avito:app --port 8000"""

import logging

from aiogram import Bot

from app.agent import Consultant
from app.catalog import load_catalog
from app.channels.avito import AvitoClient, build_app
from app.config import Settings
from app.notify import LogNotifier, TelegramNotifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
s = Settings()
if not (s.avito_client_id and s.avito_client_secret and s.avito_user_id):
    raise SystemExit("Заполните AVITO_CLIENT_ID, AVITO_CLIENT_SECRET и AVITO_USER_ID в .env")

notifier = (
    TelegramNotifier(Bot(s.telegram_bot_token), s.manager_chat_id)
    if s.telegram_bot_token and s.manager_chat_id
    else LogNotifier(logging.getLogger("manager"))
)
app = build_app(
    AvitoClient(s.avito_client_id, s.avito_client_secret, s.avito_user_id),
    Consultant(load_catalog(), s.make_llm()),
    notifier,
    s.avito_webhook_secret,
)
