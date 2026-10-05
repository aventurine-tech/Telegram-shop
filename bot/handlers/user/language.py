"""Language picker: shown first to anyone who has not chosen a language, and from the profile."""
from aiogram import Router, F
from aiogram.enums.chat_type import ChatType
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, TelegramObject

from bot.database.methods.read import check_user_cached, invalidate_user_cache
from bot.database.methods.update import set_user_language
from bot.handlers.user.main import (
    register_if_new, open_main_menu, show_profile, start_payload, _delete_quietly, send_bottom_nav,
)
from bot.i18n import localize, use_language, LANGUAGES, LANGUAGE_CODES
from bot.keyboards.inline import language_keyboard
from bot.logger_mesh import logger

router = Router()

_LABELS = dict(LANGUAGES)


class NoLanguage(BaseFilter):
    """Passes for a private-chat update from someone who has not picked a language (or has no row yet)."""

    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        if user is None:
            return False
        if isinstance(event, Message):
            if event.chat.type != ChatType.PRIVATE:
                return False
        elif isinstance(event, CallbackQuery):
            # The picker's own buttons must reach their handler, language or not.
            if (event.data or "").startswith("lang:"):
                return False
        row = await check_user_cached(user.id)
        return not (row and row.get("language"))


def _parse_choice(data: str | None) -> tuple[str, str | None] | None:
    """``lang:<code>[:<referral id>]`` -> (code, payload); None when malformed."""
    parts = (data or "").split(":")
    if len(parts) not in (2, 3) or parts[0] != "lang" or parts[1] not in LANGUAGE_CODES:
        return None
    if len(parts) == 3:
        if not (parts[2].isdigit() and len(parts[2]) <= 20):
            return None
        return parts[1], parts[2]
    return parts[1], None


@router.message(F.text.startswith("/start"), NoLanguage())
async def start_without_language(message: Message, state: FSMContext):
    """/start from someone who has not chosen yet: ask first, carrying the referral payload in the buttons."""
    await state.clear()
    await message.answer(
        localize("language.picker.title"),
        reply_markup=language_keyboard(payload=start_payload(message.text)),
    )
    await _delete_quietly(message)


@router.message(F.text, NoLanguage())
async def text_without_language(message: Message):
    """Any other first contact is answered with the picker as well."""
    await message.answer(localize("language.picker.title"), reply_markup=language_keyboard())


@router.callback_query(NoLanguage())
async def callback_without_language(call: CallbackQuery):
    """A button from a stale keyboard, pressed by someone who has not chosen a language."""
    await call.answer()
    if call.message:
        await call.message.answer(localize("language.picker.title"), reply_markup=language_keyboard())


@router.callback_query(F.data == "profile_language")
async def profile_language(call: CallbackQuery):
    """Change the language from the profile."""
    await call.message.edit_text(localize("language.picker.title"), reply_markup=language_keyboard(back_to="profile"))


@router.callback_query(F.data.startswith("lang:"))
async def choose_language(call: CallbackQuery, state: FSMContext):
    parsed = _parse_choice(call.data)
    if parsed is None:
        await call.answer(localize("errors.something_wrong"), show_alert=True)
        return
    code, payload = parsed
    user_id = call.from_user.id

    existing = await check_user_cached(user_id)
    had_language = bool(existing and existing.get("language"))

    # The language lives on the user row, so a brand-new user is registered (with the referral) first.
    role_data = await register_if_new(user_id, payload)
    if not await set_user_language(user_id, code):
        logger.warning("could not save language %s for user %s", code, user_id)
        await call.answer(localize("errors.something_wrong"), show_alert=True)
        return
    await invalidate_user_cache(user_id)

    with use_language(code):
        await call.answer(localize("language.changed", language=_LABELS[code]))
        await state.clear()
        if had_language and payload is None:
            # Changed from the profile. The reply keyboard keeps its old labels until a message replaces it, and
            # that message (the welcome line) must stay above the menu: remove the picker, send the welcome line,
            # then show the profile below it, now in the new language.
            await _delete_quietly(call.message)
            await send_bottom_nav(call.message)
            await show_profile(call, as_new=True)
            return
        # First choice: swap the picker for the normal start flow.
        await _delete_quietly(call.message)
        await open_main_menu(call.message, user_id, role_data)
