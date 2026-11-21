"""Вебхук для Авито: uvicorn app.run_avito:app --port 8000

Адрес для Авито: https://ваш-домен/avito/webhook/<AVITO_WEBHOOK_SECRET>
"""

import logging

from aiogram import Bot

from app.agent import Consultant
from app.catalog import DEFAULT_LEARNED, load_catalog
from app.channels.avito import AvitoClient, build_app
from app.config import Settings
from app.followup import Followup
from app.notify import LogNotifier, TelegramNotifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
s = Settings()
if not (s.avito_client_id and s.avito_client_secret and s.avito_user_id):
    raise SystemExit("Заполните AVITO_CLIENT_ID, AVITO_CLIENT_SECRET и AVITO_USER_ID в .env")
if not s.avito_webhook_secret:
    raise SystemExit(
        "Заполните AVITO_WEBHOOK_SECRET в .env: длинная случайная строка, она станет частью адреса вебхука"
    )

notifier = (
    TelegramNotifier(Bot(s.telegram_bot_token), s.manager_chat_id)
    if s.telegram_bot_token and s.manager_chat_id
    else LogNotifier(logging.getLogger("manager"))
)
catalog = load_catalog(learned=DEFAULT_LEARNED)  # чему научили менеджеры в Telegram
app = build_app(
    AvitoClient(s.avito_client_id, s.avito_client_secret, s.avito_user_id),
    Consultant(catalog, s.make_llm()),
    notifier,
    s.avito_webhook_secret,
    Followup(catalog, notifier, s.followup_minutes),
)
