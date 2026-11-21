"""Telegram: тот же консультант, что и в чатах Авито.

Команда /ad показывает объявления. Клиент выбирает одно, и бот отвечает так,
будто клиент написал из этого объявления на Авито.
"""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from app.agent import Consultant
from app.notify import ManagerNotifier, handoff_message

HELP = (
    "Что я умею:\n"
    "• называю цены и считаю сумму за несколько смен со скидкой;\n"
    "• подбираю технику под ваши работы;\n"
    "• отвечаю про наличие, доставку, оплату и отмену;\n"
    "• оформляю заявку: спрошу адрес, дату и телефон и передам менеджеру.\n\n"
    "Цены беру только из прайса. Чего в прайсе нет, уточняю у менеджера. Понимаю русский и английский.\n\n"
    "/ad написать как из объявления на Авито\n"
    "/reset начать заново\n"
    "/help эта справка\n\n"
    "Или нажмите пример вопроса внизу."
)

EXAMPLES = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Сколько стоит автокран?"), KeyboardButton(text="Нужен JCB на 5 смен, сколько выйдет?")],
        [KeyboardButton(text="Что взять для септика на узком участке?"), KeyboardButton(text="Бульдозер есть?")],
        [KeyboardButton(text="Можно без предоплаты?"), KeyboardButton(text="Беру JCB на понедельник")],
        [KeyboardButton(text="How much is the crane for 2 days?")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Вопрос про технику, цены или условия",
)


def build_router(consultant: Consultant, notifier: ManagerNotifier) -> Router:
    router = Router()
    current_ad: dict[int, int | None] = {}
    catalog = consultant.catalog

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        # Новый разговор: забываем выбранное объявление и историю
        current_ad.pop(message.from_user.id, None)
        consultant.reset(str(message.chat.id))
        await message.answer(
            f"Здравствуйте! Я ИИ-помощник компании «{catalog.company['name']}»: аренда спецтехники "
            f"с оператором по Москве и области.\n\n{HELP}",
            reply_markup=EXAMPLES,
        )

    @router.message(Command("help"))
    async def help_(message: Message) -> None:
        await message.answer(HELP, reply_markup=EXAMPLES)

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
        if reply.lead is not None:
            await notifier.notify(reply.lead.card(catalog, "Telegram", str(message.chat.id)))
        elif reply.handoff_reason:
            item = catalog.by_avito_id(avito_id)
            await notifier.notify(
                handoff_message(
                    "Telegram", str(message.chat.id), reply.handoff_reason, message.text, item.name if item else None
                )
            )

    return router
