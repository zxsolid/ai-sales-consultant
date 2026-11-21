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

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from app.agent import Consultant
from app.followup import Followup
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

    async def send_message(self, chat_id: str, text: str) -> None:
        r = await self.http.post(
            f"/messenger/v1/accounts/{self.user_id}/chats/{chat_id}/messages",
            json={"message": {"text": text}, "type": "text"},
            headers=await self._auth(),
        )
        r.raise_for_status()

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


class SeenMessages:
    """Авито может прислать одно событие дважды. Второй раз не отвечаем."""

    def __init__(self, size: int = 1000):
        self._order: deque[str] = deque(maxlen=size)
        self._ids: set[str] = set()

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
) -> str | None:
    """Обрабатывает одно событие вебхука. Возвращает отправленный ответ или None."""
    payload = event.get("payload") or {}
    value = payload.get("value") or {}
    if payload.get("type") != "message" or value.get("type") != "text":
        return None
    if value.get("author_id") == avito.user_id:
        return None  # своё сообщение, отвечать не нужно
    chat_id, text = str(value.get("chat_id", "")), (value.get("content") or {}).get("text", "").strip()
    if not text or not CHAT_ID.match(chat_id):
        return None
    if seen is not None and not seen.first_time(value.get("id")):
        return None
    item_id = value.get("item_id") or await avito.chat_item_id(chat_id)
    item = consultant.catalog.by_avito_id(item_id)
    key = f"avito:{chat_id}"
    reply = await consultant.answer(key, text, item_id)
    client = avito_client(chat_id)
    # Сначала менеджеру: если Авито не примет ответ, заявка всё равно дойдёт
    await tell_manager(
        notifier, manager_message(reply, consultant.catalog, "Авито", client, text, item.name if item else None)
    )
    await avito.send_message(chat_id, reply.text)
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
    return reply.text


def build_app(
    avito: AvitoClient,
    consultant: Consultant,
    notifier: ManagerNotifier,
    secret: str,
    followup: Followup | None = None,
) -> FastAPI:
    if not secret:
        raise ValueError("Без секрета вебхук примет события от кого угодно. Задайте AVITO_WEBHOOK_SECRET.")
    seen = SeenMessages()

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(followup.run()) if followup is not None else None
        yield
        if task is not None:
            task.cancel()

    app = FastAPI(title="AI consultant: Avito", lifespan=lifespan)

    async def process(event: dict) -> None:
        try:
            await handle_event(event, avito, consultant, notifier, followup, seen)
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
