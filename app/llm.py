"""Клиенты языковых моделей. Агенту нужен один метод: complete(messages) -> str."""

from collections.abc import Callable
from typing import Protocol

import httpx

Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": "..."}


class LLM(Protocol):
    async def complete(self, messages: list[Message]) -> str: ...


class YandexGPT:
    """YandexGPT через Foundation Models API (Yandex Cloud)."""

    URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

    def __init__(
        self,
        api_key: str,
        folder_id: str,
        model: str = "yandexgpt",
        temperature: float = 0.2,
        client: httpx.AsyncClient | None = None,
    ):
        self.api_key, self.folder_id, self.model = api_key, folder_id, model
        self.temperature = temperature
        self.client = client or httpx.AsyncClient(timeout=60)

    async def complete(self, messages: list[Message]) -> str:
        body = {
            "modelUri": f"gpt://{self.folder_id}/{self.model}/latest",
            "completionOptions": {"stream": False, "temperature": self.temperature, "maxTokens": "800"},
            "messages": [{"role": m["role"], "text": m["content"]} for m in messages],
        }
        r = await self.client.post(
            self.URL,
            json=body,
            headers={"Authorization": f"Api-Key {self.api_key}", "x-folder-id": self.folder_id},
        )
        r.raise_for_status()
        return r.json()["result"]["alternatives"][0]["message"]["text"].strip()


class OpenAICompatible:
    """Любой сервис с API как у OpenAI: OpenAI, OpenRouter, локальные модели и т. п."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        temperature: float = 0.2,
        client: httpx.AsyncClient | None = None,
    ):
        self.api_key, self.model, self.base_url = api_key, model, base_url.rstrip("/")
        self.temperature = temperature
        self.client = client or httpx.AsyncClient(timeout=60)

    async def complete(self, messages: list[Message]) -> str:
        r = await self.client.post(
            f"{self.base_url}/chat/completions",
            json={"model": self.model, "messages": messages, "temperature": self.temperature},
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


class ScriptedLLM:
    """Модель для тестов: отвечает функцией от сообщений и запоминает, что ей прислали."""

    def __init__(self, reply: Callable[[list[Message]], str]):
        self.reply = reply
        self.calls: list[list[Message]] = []

    async def complete(self, messages: list[Message]) -> str:
        self.calls.append(messages)
        return self.reply(messages)
