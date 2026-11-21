"""Поговорить с ботом в терминале, без Telegram: python -m app.chat_cli [номер объявления]"""

import asyncio
import sys

from app.agent import Consultant
from app.catalog import load_catalog
from app.config import Settings


async def main() -> None:
    ad = int(sys.argv[1]) if len(sys.argv) > 1 else None
    bot = Consultant(load_catalog(), Settings().make_llm())
    print("Пишите вопросы покупателя. Пустая строка — выход.")
    while text := input("\nПокупатель: ").strip():
        reply = await bot.answer("cli", text, ad)
        print(f"Бот: {reply.text}")
        if reply.handoff_reason:
            print(f"   [менеджеру: {reply.handoff_reason}]")
        if reply.guard_failures:
            print(f"   [переписано: {'; '.join(reply.guard_failures)}]")


if __name__ == "__main__":
    asyncio.run(main())
