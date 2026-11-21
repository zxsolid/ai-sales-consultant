"""Состояние чатов на диске: история, начатая заявка, пауза бота.

Без этого после перезапуска бот забывает, о чём говорил с клиентом,
а начатые заявки пропадают. SQLite хватает одному процессу; для нескольких
процессов нужен общий Redis или Postgres с тем же интерфейсом.
"""

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Protocol


class ChatStore(Protocol):
    def load(self, chat_id: str) -> dict | None: ...
    def save(self, chat_id: str, data: dict) -> None: ...
    def delete(self, chat_id: str) -> None: ...


class MemoryStore:
    """Для тестов и демо: живёт, пока работает процесс."""

    def __init__(self):
        self.data: dict[str, dict] = {}

    def load(self, chat_id: str) -> dict | None:
        return json.loads(json.dumps(self.data[chat_id])) if chat_id in self.data else None

    def save(self, chat_id: str, data: dict) -> None:
        self.data[chat_id] = json.loads(json.dumps(data, ensure_ascii=False))

    def delete(self, chat_id: str) -> None:
        self.data.pop(chat_id, None)


class SqliteStore:
    def __init__(self, path: Path | str):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS chats (chat_id TEXT PRIMARY KEY, data TEXT, updated REAL)")
        self._db.commit()

    def load(self, chat_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT data FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, chat_id: str, data: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO chats (chat_id, data, updated) VALUES (?, ?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET data = excluded.data, updated = excluded.updated",
                (chat_id, json.dumps(data, ensure_ascii=False), time.time()),
            )
            self._db.commit()

    def delete(self, chat_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
            self._db.commit()
