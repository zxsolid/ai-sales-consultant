"""Чаты Авито через официальный API мессенджера.

Авито присылает новые сообщения на вебхук, бот отвечает через API.
Запросы собраны по документации developers.avito.ru; на боевом аккаунте
их нужно проверить с доступами заказчика.
"""

import asyncio
import contextlib
import hmac
import logging
import re
import time
from collections import deque
from dataclasses import dataclass

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from app.agent import Consultant
from app.channels.manager import build_learning_router, send_suggestion
from app.followup import Followup
from app.learning import Learner
from app.notify import ManagerNotifier, avito_client, manager_message, tell_manager

log = logging.getLogger("avito")

API = "https://api.avito.ru"
# chat_id идёт в URL запроса к API с токеном продавца: пускаем только безопасные символы
CHAT_ID = re.compile(r"^[\w~-]{1,128}$")


class AvitoClient:
    def __init__(self, client_id: str, client_secret: str, user_id: int, http: httpx.AsyncClient | None = None):
        self.client_id, self.client_secret, self.user_id = client_id, client_secret, user_id
        self.http = http or httpx.AsyncClient(base_url=API, timeout=30)
        self._token: str | None = None
        self._expires_at = 0.0
        self.retry_delay = 1.0

    async def _auth(self) -> dict[str, str]:
        if not self._token or time.monotonic() > self._expires_at - 60:
            r = await self.http.post(
                "/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )
            r.raise_for_status()
            data = r.json()
            self._token = data["access_token"]
            self._expires_at = time.monotonic() + int(data.get("expires_in", 3600))
        return {"Authorization": f"Bearer {self._token}"}

    async def send_message(self, chat_id: str, text: str, attempts: int = 3) -> str | None:
        """Отправить ответ в чат. Сеть моргнула или Авито ответил 5xx/429: пробуем ещё раз.

        Возвращает id отправленного сообщения: по нему бот отличает свои сообщения от сообщений менеджера.
        """
        for attempt in range(1, attempts + 1):
            try:
                r = await self.http.post(
                    f"/messenger/v1/accounts/{self.user_id}/chats/{chat_id}/messages",
                    json={"message": {"text": text}, "type": "text"},
                    headers=await self._auth(),
                )
                if r.status_code == 429 or r.status_code >= 500:
                    raise httpx.HTTPStatusError("Авито временно недоступен", request=r.request, response=r)
                r.raise_for_status()
                try:
                    return str(r.json().get("id") or "") or None
                except ValueError:
                    return None
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                retryable = (
                    isinstance(e, httpx.TransportError)
                    or e.response.status_code == 429
                    or (e.response.status_code >= 500)
                )
                if not retryable or attempt == attempts:
                    raise
                log.warning("Не отправил ответ в чат %s (попытка %d), повторю", chat_id, attempt)
                await asyncio.sleep(self.retry_delay * attempt)
        return None

    async def chat_item_id(self, chat_id: str) -> int | None:
        """Из какого объявления пришёл покупатель. Если API не ответил, отвечаем без объявления."""
        try:
            r = await self.http.get(
                f"/messenger/v2/accounts/{self.user_id}/chats/{chat_id}", headers=await self._auth()
            )
            r.raise_for_status()
        except httpx.HTTPError:
            log.warning("Не узнал объявление чата %s", chat_id)
            return None
        value = (r.json().get("context") or {}).get("value") or {}
        return value.get("id")

    async def subscribe(self, url: str) -> None:
        r = await self.http.post("/messenger/v3/webhook", json={"url": url}, headers=await self._auth())
        r.raise_for_status()


@dataclass
class ManagerLearning:
    """Обучение для Авито: предложения уходят менеджеру в Telegram, кнопки обрабатывает тот же бот."""

    bot: object
    manager_chat_id: int
    learner: Learner


class SeenMessages:
    """Авито может прислать одно событие дважды. Второй раз не отвечаем."""

    def __init__(self, size: int = 1000):
        self._order: deque[str] = deque(maxlen=size)
        self._ids: set[str] = set()

    def __contains__(self, key: str) -> bool:
        return key in self._ids

    def first_time(self, message_id: str | None) -> bool:
        if not message_id:
            return True
        if message_id in self._ids:
            return False
        if len(self._order) == self._order.maxlen:
            self._ids.discard(self._order[0])
        self._order.append(message_id)
        self._ids.add(message_id)
        return True


async def handle_event(
    event: dict,
    avito: AvitoClient,
    consultant: Consultant,
    notifier: ManagerNotifier,
    followup: Followup | None = None,
    seen: SeenMessages | None = None,
    bot_sent: SeenMessages | None = None,
    learning: "ManagerLearning | None" = None,
    pause_hours: float = 12,
) -> str | None:
    """Обрабатывает одно событие вебхука. Возвращает отправленный ответ или None."""
    payload = event.get("payload") or {}
    value = payload.get("value") or {}
    if payload.get("type") != "message" or value.get("type") != "text":
        return None
    chat_id, text = str(value.get("chat_id", "")), (value.get("content") or {}).get("text", "").strip()
    if not CHAT_ID.match(chat_id):
        return None
    key = f"avito:{chat_id}"
    if value.get("author_id") == avito.user_id:
        # Сообщение с аккаунта продавца: либо ответ бота, либо менеджер пишет клиенту сам
        message_id = str(value.get("id") or "")
        if bot_sent is None:
            return None
        if (message_id and message_id in bot_sent) or f"{chat_id}:{text}" in bot_sent:
            return None  # это наш ответ вернулся вебхуком
        if text:
            log.info("Менеджер пишет в чат %s сам, бот молчит %g ч", chat_id, pause_hours)
            consultant.pause(key, pause_hours * 3600)
            if followup is not None:
                followup.forget(key)
        return None
    if not text:
        return None
    if seen is not None and not seen.first_time(value.get("id")):
        return None
    if consultant.is_paused(key):
        return None  # чат ведёт менеджер
    item_id = value.get("item_id") or await avito.chat_item_id(chat_id)
    item = consultant.catalog.by_avito_id(item_id)
    reply = await consultant.answer(key, text, item_id)
    client = avito_client(chat_id)
    # Сначала менеджеру: если Авито не примет ответ, заявка всё равно дойдёт
    await tell_manager(
        notifier, manager_message(reply, consultant.catalog, "Авито", client, text, item.name if item else None)
    )
    sent_id = await avito.send_message(chat_id, reply.text)
    if bot_sent is not None:
        # Запомнить: это написал бот, а не менеджер. Текст на случай, если Авито не вернул id
        bot_sent.first_time(f"{chat_id}:{reply.text}")
        if sent_id:
            bot_sent.first_time(sent_id)
    if followup is not None:
        followup.seen(
            key,
            "Авито",
            client,
            text,
            lead=consultant.lead_of(key),
            manager_notified=bool(reply.handoff_reason or reply.lead),
            item_name=item.name if item else None,
        )
    if learning is not None:
        await send_suggestion(learning.bot, learning.manager_chat_id, learning.learner, consultant.catalog, text, reply)
    return reply.text


def build_app(
    avito: AvitoClient,
    consultant: Consultant,
    notifier: ManagerNotifier,
    secret: str,
    followup: Followup | None = None,
    learning: ManagerLearning | None = None,
    pause_hours: float = 12,
) -> FastAPI:
    if not secret:
        raise ValueError("Без секрета вебхук примет события от кого угодно. Задайте AVITO_WEBHOOK_SECRET.")
    seen, bot_sent = SeenMessages(), SeenMessages()

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        tasks = []
        if followup is not None:
            tasks.append(asyncio.create_task(followup.run()))
        if learning is not None:
            # Кнопки «Запомнить» и «Ответить» в чате менеджера: тот же процесс слушает Telegram
            from aiogram import Dispatcher

            dp = Dispatcher()
            dp.include_router(build_learning_router(learning.learner))
            tasks.append(asyncio.create_task(dp.start_polling(learning.bot, handle_signals=False)))
        yield
        for task in tasks:
            task.cancel()

    app = FastAPI(title="AI consultant: Avito", lifespan=lifespan)

    async def process(event: dict) -> None:
        try:
            await handle_event(event, avito, consultant, notifier, followup, seen, bot_sent, learning, pause_hours)
        except Exception:
            log.exception("Не удалось обработать сообщение из Авито")

    # Секрет в пути, а не в ?token=: так он не попадает в access-лог uvicorn вместе с query
    @app.post("/avito/webhook/{token}")
    async def webhook(token: str, request: Request, background: BackgroundTasks) -> dict:
        if not hmac.compare_digest(token.encode(), secret.encode()):
            raise HTTPException(status_code=403)
        background.add_task(process, await request.json())
        return {"ok": True}  # Авито ждёт быстрый ответ, сам ответ покупателю уходит в фоне

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    return app
