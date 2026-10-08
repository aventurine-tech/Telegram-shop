"""Mailing preferences: the unsubscribe button under every mailing, and the toggle in the profile."""
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.database.methods.mailings import set_mailing_optout
from bot.database.methods.read import check_user, invalidate_user_cache
from bot.handlers.user.main import show_profile
from bot.i18n import localize

router = Router()


def _button(text_key: str, callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=localize(text_key), callback_data=callback)]])


async def _apply(user_id: int, optout: bool) -> bool:
    ok = await set_mailing_optout(user_id, optout)
    if ok:
        await invalidate_user_cache(user_id)
    return ok


async def _swap_button(call: CallbackQuery, text_key: str, callback: str) -> None:
    try:
        await call.message.edit_reply_markup(reply_markup=_button(text_key, callback))
    except TelegramBadRequest:          # the message is too old to edit, or unchanged: the toast already answered
        pass


@router.callback_query(F.data == "mailing_optout")
async def mailing_optout_handler(call: CallbackQuery):
    """The button under a mailing: stop sending me these."""
    if not await _apply(call.from_user.id, True):
        await call.answer(localize("errors.something_wrong"), show_alert=True)
        return
    await call.answer(localize("mailing.optout.done"), show_alert=True)
    await _swap_button(call, "btn.mailing.resubscribe", "mailing_optin")


@router.callback_query(F.data == "mailing_optin")
async def mailing_optin_handler(call: CallbackQuery):
    """…and the way back."""
    if not await _apply(call.from_user.id, False):
        await call.answer(localize("errors.something_wrong"), show_alert=True)
        return
    await call.answer(localize("mailing.optin.done"), show_alert=True)
    await _swap_button(call, "btn.mailing.unsubscribe", "mailing_optout")


@router.callback_query(F.data == "mailing_toggle")
async def mailing_toggle_handler(call: CallbackQuery):
    """Profile → Mailings: on / off."""
    user = await check_user(call.from_user.id)
    if not user:
        await call.answer(localize("errors.something_wrong"), show_alert=True)
        return
    now_off = not bool(user.get("mailing_optout"))
    await _apply(call.from_user.id, now_off)
    await call.answer(localize("mailing.optout.done" if now_off else "mailing.optin.done"))
    await show_profile(call)
