"""Чаты Авито через официальный API мессенджера.

Авито присылает новые сообщения на вебхук, бот отвечает через API.
Запросы собраны по документации developers.avito.ru; на боевом аккаунте
их нужно проверить с доступами заказчика.
"""

import logging
import time

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from app.agent import Consultant
from app.notify import ManagerNotifier, avito_client, handoff_message

log = logging.getLogger("avito")

API = "https://api.avito.ru"


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
        """Из какого объявления пришёл покупатель."""
        r = await self.http.get(f"/messenger/v2/accounts/{self.user_id}/chats/{chat_id}", headers=await self._auth())
        r.raise_for_status()
        value = (r.json().get("context") or {}).get("value") or {}
        return value.get("id")

    async def subscribe(self, url: str) -> None:
        r = await self.http.post("/messenger/v3/webhook", json={"url": url}, headers=await self._auth())
        r.raise_for_status()


async def handle_event(
    event: dict, avito: AvitoClient, consultant: Consultant, notifier: ManagerNotifier
) -> str | None:
    """Обрабатывает одно событие вебхука. Возвращает отправленный ответ или None."""
    payload = event.get("payload") or {}
    value = payload.get("value") or {}
    if payload.get("type") != "message" or value.get("type") != "text":
        return None
    if value.get("author_id") == avito.user_id:
        return None  # своё сообщение, отвечать не нужно
    chat_id, text = value["chat_id"], (value.get("content") or {}).get("text", "").strip()
    if not text:
        return None
    item_id = value.get("item_id") or await avito.chat_item_id(chat_id)
    reply = await consultant.answer(f"avito:{chat_id}", text, item_id)
    await avito.send_message(chat_id, reply.text)
    if reply.lead is not None:
        await notifier.notify(reply.lead.card(consultant.catalog, "Авито", avito_client(chat_id)))
    elif reply.handoff_reason:
        item = consultant.catalog.by_avito_id(item_id)
        await notifier.notify(
            handoff_message("Авито", avito_client(chat_id), reply.handoff_reason, text, item.name if item else None)
        )
    return reply.text


def build_app(avito: AvitoClient, consultant: Consultant, notifier: ManagerNotifier, secret: str) -> FastAPI:
    app = FastAPI(title="Avito AI consultant")

    async def process(event: dict) -> None:
        try:
            await handle_event(event, avito, consultant, notifier)
        except Exception:
            log.exception("Не удалось обработать сообщение из Авито")

    @app.post("/avito/webhook")
    async def webhook(request: Request, background: BackgroundTasks, token: str = "") -> dict:
        if secret and token != secret:
            raise HTTPException(status_code=403)
        background.add_task(process, await request.json())
        return {"ok": True}  # Авито ждёт быстрый ответ, сам ответ покупателю уходит в фоне

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    return app
