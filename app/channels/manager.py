"""Чат менеджера в Telegram: предложения выучить новое слово или ответ.

Работает для любого канала клиента: и для Telegram, и для Авито.
Менеджер нажимает «Запомнить» или «Ответить», правка ложится в data/learned.yaml.
"""

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.catalog import Catalog
from app.learning import Learner


async def send_suggestion(bot, manager_chat_id: int | None, learner: Learner | None, catalog: Catalog, text, reply):
    """Если в сообщении клиента есть чему поучиться, предложить это менеджеру."""
    if learner is None or manager_chat_id is None or bot is None:
        return
    s = learner.notice(catalog, text, reply)
    if s is None:
        return
    if s.kind == "alias":
        buttons = [("Запомнить", f"learn:yes:{s.id}"), ("Нет", f"learn:no:{s.id}")]
    else:
        buttons = [("Ответить", f"learn:answer:{s.id}"), ("Пропустить", f"learn:no:{s.id}")]
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in buttons]])
    try:
        await bot.send_message(manager_chat_id, s.text, reply_markup=kb)
    except Exception:
        learner.reject(s.id)


def build_learning_router(learner: Learner) -> Router:
    """Кнопки «Запомнить», «Ответить», «Пропустить» и ответ менеджера текстом."""
    router = Router()
    waiting: dict[int, str] = {}  # менеджер нажал «Ответить»: ждём от него текст

    @router.callback_query(F.data.startswith("learn:"))
    async def learn(call: CallbackQuery) -> None:
        _, action, sid = call.data.split(":", 2)
        await call.answer()
        await call.message.edit_reply_markup(reply_markup=None)
        if action == "yes":
            await call.message.answer(learner.accept(sid))
        elif action == "answer":
            waiting[call.message.chat.id] = sid
            await call.message.answer("Напишите ответ одним сообщением. Бот будет отвечать так всем клиентам.")
        else:
            await call.message.answer(learner.reject(sid))

    @router.message(F.text, lambda m: m.chat.id in waiting)
    async def answer(message: Message) -> None:
        # Это не вопрос клиента, а урок для бота
        await message.answer(learner.accept(waiting.pop(message.chat.id), message.text))

    return router
