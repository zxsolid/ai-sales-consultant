"""Демо в Telegram: бот ведёт себя так же, как в чате Авито.

Команда /ad показывает список объявлений, кнопка выбирает объявление —
так бот знает, из какого объявления пришёл покупатель.
"""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.agent import Consultant
from app.notify import ManagerNotifier, handoff_message


def build_router(consultant: Consultant, notifier: ManagerNotifier) -> Router:
    router = Router()
    current_ad: dict[int, int | None] = {}
    catalog = consultant.catalog

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        await message.answer(
            f"Здравствуйте! Я консультант компании «{catalog.company['name']}»: аренда спецтехники "
            "с оператором по Москве и области. Спросите про цены, сроки или условия.\n\n"
            "Для демо: /ad — выбрать объявление, из которого вы пишете, /reset — начать заново."
        )

    @router.message(Command("reset"))
    async def reset(message: Message) -> None:
        consultant.reset(str(message.chat.id))
        current_ad.pop(message.from_user.id, None)
        await message.answer("Начнём заново. Спросите про технику, цены или условия.")

    @router.message(Command("ad"))
    async def choose_ad(message: Message) -> None:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=i.name, callback_data=f"ad:{i.avito_item_id}")] for i in catalog.items
            ]
        )
        await message.answer("Из какого объявления пишете?", reply_markup=kb)

    @router.callback_query(F.data.startswith("ad:"))
    async def set_ad(call: CallbackQuery) -> None:
        avito_id = int(call.data.split(":", 1)[1])
        current_ad[call.from_user.id] = avito_id
        item = catalog.by_avito_id(avito_id)
        await call.answer()
        await call.message.answer(f"Пишете из объявления: {item.name}. Задайте вопрос.")

    @router.message(F.text)
    async def chat(message: Message) -> None:
        avito_id = current_ad.get(message.from_user.id)
        reply = await consultant.answer(str(message.chat.id), message.text, avito_id)
        await message.answer(reply.text)
        if reply.handoff_reason:
            item = catalog.by_avito_id(avito_id)
            await notifier.notify(
                handoff_message(
                    "Telegram",
                    str(message.chat.id),
                    reply.handoff_reason,
                    message.text,
                    item.name if item else None,
                )
            )

    return router
