"""Вебхук для Авито: uvicorn app.run_avito:app --port 8000

Адрес для Авито: https://ваш-домен/avito/webhook/<AVITO_WEBHOOK_SECRET>
"""

import logging

from aiogram import Bot

from app.agent import Consultant
from app.catalog import DEFAULT_LEARNED, load_catalog
from app.channels.avito import AvitoClient, ManagerLearning, build_app
from app.config import Settings
from app.followup import Followup
from app.learning import Learner
from app.notify import LogNotifier, TelegramNotifier
from app.storage import SqliteStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
s = Settings()
if not (s.avito_client_id and s.avito_client_secret and s.avito_user_id):
    raise SystemExit("Заполните AVITO_CLIENT_ID, AVITO_CLIENT_SECRET и AVITO_USER_ID в .env")
if not s.avito_webhook_secret:
    raise SystemExit(
        "Заполните AVITO_WEBHOOK_SECRET в .env: длинная случайная строка, она станет частью адреса вебхука"
    )

manager_bot = Bot(s.telegram_bot_token) if s.telegram_bot_token and s.manager_chat_id else None
notifier = (
    TelegramNotifier(manager_bot, s.manager_chat_id) if manager_bot else LogNotifier(logging.getLogger("manager"))
)
catalog = load_catalog(learned=DEFAULT_LEARNED)
consultant = Consultant(catalog, s.make_llm(), store=SqliteStore(s.state_path))  # заявки переживут перезапуск
followup = Followup(catalog, notifier, s.followup_minutes)


def relearn() -> None:
    # Менеджер одобрил правку в Telegram: бот сразу отвечает по обновлённому прайсу
    fresh = load_catalog(learned=DEFAULT_LEARNED)
    consultant.reload(fresh)
    followup.catalog = fresh


learning = (
    ManagerLearning(manager_bot, s.manager_chat_id, Learner(DEFAULT_LEARNED, on_change=relearn))
    if manager_bot
    else None
)
app = build_app(
    AvitoClient(s.avito_client_id, s.avito_client_secret, s.avito_user_id),
    consultant,
    notifier,
    s.avito_webhook_secret,
    followup,
    learning,
    s.avito_pause_hours,
)
