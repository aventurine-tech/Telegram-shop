"""The 18+ question (D-27): asked once, before the menu and the catalog, of everyone who has not answered it.

It follows the language picker in the router order, so a person first chooses a language and is then asked their age
in that language. Until they answer "Yes", every message and button leads back to the question. The terms, the
privacy policy, help, support and the language choice stay reachable, and so does "Delete my data".

The question is asked only while the shop is for adults (ADULTS_ONLY, on by default) or for trade customers
(BUSINESS_ONLY).
"""
from aiogram import F, Router
from aiogram.enums.chat_type import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, TelegramObject
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.methods.read import check_user_cached, invalidate_user_cache
from bot.database.methods.update import set_age_confirmed
from bot.handlers.user.legal import adults_only, business_only
from bot.handlers.user.main import _delete_quietly, open_main_menu, register_if_new
from bot.i18n import localize
from bot.logger_mesh import logger

router = Router()

# What a person may open before answering: the texts the question points at, help, support and the language choice.
OPEN_COMMANDS = ("/terms", "/privacy", "/help", "/support", "/paysupport", "/language")
# Buttons that work before the answer: the question's own, the language picker's, and the ones under /terms and
# /privacy (Close, My data, Delete my data), so that someone who answers "No" can still have their data removed.
OPEN_CALLBACKS = ("age:yes", "age:no", "close", "legal_privacy", "my_data", "my_data_erase", "my_data_erase_yes")


def gate_enabled() -> bool:
    return adults_only() or business_only()


async def needs_age(user_id: int) -> bool:
    """Whether this person must still answer the 18+ question. Someone without a language is asked that first."""
    if not gate_enabled():
        return False
    row = await check_user_cached(user_id)
    return bool(row and row.get("language") and not row.get("age_confirmed_at"))


class NeedsAge(BaseFilter):
    """Passes for a private-chat update from someone who has chosen a language but not yet confirmed their age."""

    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        if user is None:
            return False
        if isinstance(event, Message):
            if event.chat.type != ChatType.PRIVATE:
                return False
            command = (event.text or "").split(maxsplit=1)[0].split("@", 1)[0].lower() if event.text else ""
            if command in OPEN_COMMANDS:
                return False
        elif isinstance(event, CallbackQuery):
            data = event.data or ""
            if data in OPEN_CALLBACKS or data.startswith("lang:"):
                return False
            if event.message is not None and event.message.chat.type != ChatType.PRIVATE:
                return False
        else:
            return False
        return await needs_age(user.id)


def age_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=localize("btn.age.yes"), callback_data="age:yes")
    kb.button(text=localize("btn.age.no"), callback_data="age:no")
    kb.adjust(1)
    return kb.as_markup()


async def ask_age(message: Message) -> None:
    await message.answer(localize("age.ask"), reply_markup=age_keyboard())


@router.message(NeedsAge())
async def message_before_age(message: Message, state: FSMContext):
    """Anything typed before the answer (/start included) gets the question; a flow in progress is dropped."""
    await state.clear()
    await ask_age(message)
    await _delete_quietly(message)


@router.callback_query(NeedsAge())
async def callback_before_age(call: CallbackQuery):
    """A button from an older screen, pressed by someone who has not answered yet."""
    await call.answer()
    if call.message:
        await ask_age(call.message)


@router.callback_query(F.data == "age:yes")
async def age_confirmed(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    role_data = await register_if_new(user_id)
    if not await set_age_confirmed(user_id):
        logger.warning("could not save the age confirmation of user %s", user_id)
        await call.answer(localize("errors.something_wrong"), show_alert=True)
        return
    await invalidate_user_cache(user_id)
    await state.clear()
    await call.answer()
    await _delete_quietly(call.message)
    await open_main_menu(call.message, user_id, role_data)


@router.callback_query(F.data == "age:no")
async def age_declined(call: CallbackQuery):
    """Nothing is saved: the person is told why the bot stays closed, and is asked again if they come back."""
    await call.answer()
    try:
        await call.message.edit_text(localize("age.denied"))
    except TelegramBadRequest:              # the same text is already there
        pass
