"""Telegram: консультант в чате.

Служебная команда /ad (в меню её нет) показывает объявления: бот отвечает так,
будто клиент написал из выбранного объявления на площадке.
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
from app.followup import Followup
from app.learning import Learner
from app.notify import ManagerNotifier, manager_message, telegram_client, tell_manager

HELP = (
    "Что я умею:\n"
    "• называю цены и считаю сумму за несколько смен со скидкой;\n"
    "• подбираю технику под ваши работы;\n"
    "• отвечаю про наличие, доставку, оплату и отмену;\n"
    "• оформляю заявку: спрошу адрес, дату и телефон и передам менеджеру.\n\n"
    "Цены беру только из прайса. Чего в прайсе нет, уточняю у менеджера. Понимаю русский и английский.\n\n"
    "/reset начать заново\n"
    "/help эта справка\n\n"
    "Или нажмите пример вопроса внизу."
)

EXAMPLES = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Какая техника есть и почём?"), KeyboardButton(text="Сколько выйдет JCB на 5 смен?")],
        [KeyboardButton(text="Чем выкопать яму под септик в узком дворе?"), KeyboardButton(text="Есть бульдозер?")],
        [
            KeyboardButton(text="Оператор и доставка входят в цену?"),
            KeyboardButton(text="Хочу заказать кран на завтра"),
        ],
    ],
    resize_keyboard=True,
    input_field_placeholder="Вопрос про технику, цены или условия",
)


def build_router(
    consultant: Consultant,
    notifier: ManagerNotifier,
    followup: Followup | None = None,
    learner: Learner | None = None,
    manager_chat_id: int | None = None,
) -> Router:
    """learner и manager_chat_id: бот предлагает менеджеру выучить новое слово или ответ."""
    router = Router()
    current_ad: dict[int, int | None] = {}
    waiting_answer: dict[int, str] = {}  # менеджер нажал «Ответить»: ждём от него текст

    async def suggest(message: Message, text: str, reply) -> None:
        if learner is None or manager_chat_id is None:
            return
        s = learner.notice(consultant.catalog, text, reply)
        if s is None:
            return
        if s.kind == "alias":
            buttons = [("Запомнить", f"learn:yes:{s.id}"), ("Нет", f"learn:no:{s.id}")]
        else:
            buttons = [("Ответить", f"learn:answer:{s.id}"), ("Пропустить", f"learn:no:{s.id}")]
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in buttons]])
        try:
            await message.bot.send_message(manager_chat_id, s.text, reply_markup=kb)
        except Exception:
            learner.reject(s.id)

    @router.callback_query(F.data.startswith("learn:"))
    async def learn(call: CallbackQuery) -> None:
        _, action, sid = call.data.split(":", 2)
        await call.answer()
        await call.message.edit_reply_markup(reply_markup=None)
        if action == "yes":
            await call.message.answer(learner.accept(sid))
        elif action == "answer":
            waiting_answer[call.message.chat.id] = sid
            await call.message.answer("Напишите ответ одним сообщением. Бот будет отвечать так всем клиентам.")
        else:
            await call.message.answer(learner.reject(sid))

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        # Новый разговор: забываем выбранное объявление и историю
        current_ad.pop(message.from_user.id, None)
        consultant.reset(str(message.chat.id))
        if followup is not None:
            followup.forget(str(message.chat.id))
        await message.answer(
            f"Здравствуйте! Я ИИ-помощник компании «{consultant.catalog.company['name']}»: аренда спецтехники "
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
        if followup is not None:
            followup.forget(str(message.chat.id))
        await message.answer("Начнём заново. Спросите про технику, цены или условия.")

    @router.message(Command("ad"))
    async def choose_ad(message: Message) -> None:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=i.name, callback_data=f"ad:{i.avito_item_id}")]
                for i in consultant.catalog.items
            ]
        )
        await message.answer("Из какого объявления пишете?", reply_markup=kb)

    @router.callback_query(F.data.startswith("ad:"))
    async def set_ad(call: CallbackQuery) -> None:
        avito_id = int(call.data.split(":", 1)[1])
        current_ad[call.from_user.id] = avito_id
        item = consultant.catalog.by_avito_id(avito_id)
        await call.answer()
        await call.message.answer(f"Пишете из объявления: {item.name}. Задайте вопрос.")

    @router.message(F.text)
    async def chat(message: Message) -> None:
        if learner is not None and message.chat.id in waiting_answer:
            # Менеджер отвечает на «В прайсе нет ответа»: это не вопрос клиента, а урок для бота
            await message.answer(learner.accept(waiting_answer.pop(message.chat.id), message.text))
            return
        chat_id = str(message.chat.id)
        avito_id = current_ad.get(message.from_user.id)
        item = consultant.catalog.by_avito_id(avito_id)
        reply = await consultant.answer(chat_id, message.text, avito_id)
        user = message.from_user
        client = telegram_client(user.id, user.full_name, user.username)
        # Сначала менеджеру: клиенту уже пообещали «передал», уведомление не должно потеряться
        await tell_manager(
            notifier,
            manager_message(reply, consultant.catalog, "Telegram", client, message.text, item.name if item else None),
        )
        await message.answer(reply.text)
        if followup is not None:
            followup.seen(
                chat_id,
                "Telegram",
                client,
                message.text,
                lead=consultant.lead_of(chat_id),
                manager_notified=bool(reply.handoff_reason or reply.lead),
                item_name=item.name if item else None,
            )
        await suggest(message, message.text, reply)

    return router
