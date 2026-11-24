"""What Telegram asks every shop bot to have (D-25): /help, /settings and /support, the terms of sale and the
privacy policy, and a way for a customer to see and delete what the shop holds about them.

/help, /settings and /support are screens like the other ☰ commands. /terms and /privacy are different: they are
sent as a separate message with a Close button and leave any flow in progress alone, because the checkout summary
points at them and reading them must not cancel the order being placed.
"""
from aiogram import F, Router
from aiogram.enums.chat_type import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.methods.erasure import erase_client
from bot.database.methods.mailings import set_mailing_optout
from bot.database.methods.read import check_user, invalidate_user_cache, select_user_items
from bot.handlers.user._screen import edit_screen
from bot.handlers.user.main import _delete_quietly
from bot.i18n import localize
from bot.i18n.main import LANGUAGES, esc
from bot.logger_mesh import logger
from bot.middleware.clean_chat import outside_screen
from bot.misc import EnvKeys
from bot.misc.bot_commands import COMMANDS

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)


# --- texts -----------------------------------------------------------------------------------------------------------

def _on(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def adults_only() -> bool:
    return _on(EnvKeys.ADULTS_ONLY)


def business_only() -> bool:
    """Trade customers only (D-26). It includes the 18+ rule, so it wins over ADULTS_ONLY."""
    return _on(EnvKeys.BUSINESS_ONLY)


def _who_can_order_clause() -> str:
    if business_only():
        return localize("legal.terms.business")
    return localize("legal.terms.adults") if adults_only() else ""


def _seller() -> str:
    return esc(EnvKeys.SELLER_INFO.strip()) if EnvKeys.SELLER_INFO.strip() else localize("legal.seller_default")


def terms_text() -> str:
    return localize("legal.terms", seller=_seller(), currency=esc(EnvKeys.PAY_CURRENCY),
                    minutes=EnvKeys.MIA_PAY_TIMEOUT_MIN,
                    adults=_who_can_order_clause())


def privacy_text() -> str:
    return localize("legal.privacy", seller=_seller())


def agreement_line() -> str:
    """The last line of the checkout summary: pressing Confirm is the customer's agreement."""
    if business_only():
        return localize("checkout.summary.agree_business")
    return localize("checkout.summary.agree_adults" if adults_only() else "checkout.summary.agree")


def help_text() -> str:
    commands = "\n".join(localize("help.command_line", command=name, description=localize(key))
                         for name, key in COMMANDS)
    return localize("help.text", commands=commands)


def support_contact() -> str:
    """Who answers customers: the support account when one is set, otherwise the owner."""
    return str(EnvKeys.HELPER_ID).strip() or str(EnvKeys.OWNER_ID)


# --- keyboards -------------------------------------------------------------------------------------------------------

def _buttons(*rows: tuple[str, str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for text_key, callback in rows:
        kb.button(text=localize(text_key), callback_data=callback)
    kb.adjust(1)
    return kb.as_markup()


def privacy_keyboard() -> InlineKeyboardMarkup:
    return _buttons(("btn.my_data", "my_data"), ("btn.my_data_erase", "my_data_erase"), ("btn.close", "close"))


def settings_keyboard(mailings_on: bool) -> InlineKeyboardMarkup:
    return _buttons(
        ("btn.language", "profile_language"),
        ("settings.mailings_on" if mailings_on else "settings.mailings_off", "settings_mailings"),
        ("btn.privacy", "legal_privacy_open"),
        ("btn.back", "back_to_menu"),
    )


def support_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=localize("btn.support.write"), url=f"tg://user?id={support_contact()}")
    kb.button(text=localize("btn.back"), callback_data="back_to_menu")
    kb.adjust(1)
    return kb.as_markup()


# --- screens: /help, /settings, /support -----------------------------------------------------------------------------

async def _open(message: Message, state: FSMContext) -> None:
    """Like the other ☰ commands: drop any flow in progress and the typed command (clean chat)."""
    await state.clear()
    try:
        await _delete_quietly(message)
    except Exception:           # cosmetic
        pass


@router.message(Command("help"))
async def help_command(message: Message, state: FSMContext):
    await _open(message, state)
    await edit_screen(message, help_text(), reply_markup=_buttons(("btn.back", "back_to_menu")))


@router.message(Command("support", "paysupport"))
async def support_command(message: Message, state: FSMContext):
    await _open(message, state)
    await edit_screen(message, localize("support.text"), reply_markup=support_keyboard())


async def _settings_view(user_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    user = await check_user(user_id)
    if not user:
        return None
    language = dict(LANGUAGES).get(user.get("language") or EnvKeys.BOT_LOCALE, "—")
    text = f"{localize('settings.title')}\n\n{localize('settings.language', language=language)}"
    return text, settings_keyboard(mailings_on=not bool(user.get("mailing_optout")))


@router.message(Command("settings"))
async def settings_command(message: Message, state: FSMContext):
    await _open(message, state)
    view = await _settings_view(message.from_user.id)
    if view is None:
        await message.answer(localize("errors.something_wrong"))
        return
    await edit_screen(message, view[0], reply_markup=view[1])


@router.callback_query(F.data == "settings_mailings")
async def settings_mailings_handler(call: CallbackQuery):
    """Settings → Shop news: on / off, redrawn in place."""
    user = await check_user(call.from_user.id)
    if not user:
        await call.answer(localize("errors.something_wrong"), show_alert=True)
        return
    now_off = not bool(user.get("mailing_optout"))
    if await set_mailing_optout(call.from_user.id, now_off):
        await invalidate_user_cache(call.from_user.id)
    await call.answer(localize("mailing.optout.done" if now_off else "mailing.optin.done"))
    view = await _settings_view(call.from_user.id)
    if view:
        try:
            await call.message.edit_text(view[0], reply_markup=view[1])
        except TelegramBadRequest:      # nothing changed on screen
            pass


# --- documents: /terms, /privacy (a separate message, the flow in progress goes on) -----------------------------------

async def _send_document(message: Message, text: str, markup: InlineKeyboardMarkup) -> None:
    with outside_screen():              # not a screen: it must not replace the checkout the customer is in
        await message.answer(text, reply_markup=markup, disable_web_page_preview=True)


@router.message(Command("terms"))
async def terms_command(message: Message):
    await _delete_quietly(message)
    await _send_document(message, terms_text(), _buttons(("btn.close", "close")))


@router.message(Command("privacy"))
async def privacy_command(message: Message):
    await _delete_quietly(message)
    await _send_document(message, privacy_text(), privacy_keyboard())


@router.callback_query(F.data == "legal_privacy_open")
async def privacy_open_handler(call: CallbackQuery):
    """Settings → Privacy and my data: the policy as its own message, the settings screen stays."""
    await call.answer()
    await _send_document(call.message, privacy_text(), privacy_keyboard())


@router.callback_query(F.data == "legal_privacy")
async def privacy_back_handler(call: CallbackQuery):
    await call.message.edit_text(privacy_text(), reply_markup=privacy_keyboard(), disable_web_page_preview=True)


# --- my data: see it, delete it --------------------------------------------------------------------------------------

async def my_data_text(user_id: int) -> str | None:
    """Everything the profile holds about the person, in their words (a copy of their data on request)."""
    user = await check_user(user_id)
    if not user:
        return None
    registered = user.get("registration_date")
    values = [
        ("id", str(user_id)),
        ("first_name", user.get("first_name")),
        ("last_name", user.get("last_name")),
        ("username", f"@{user['username']}" if user.get("username") else None),
        ("language", dict(LANGUAGES).get(user.get("language") or "", None)),
        ("contact_name", user.get("contact_name")),
        ("phone", user.get("phone")),
        ("city", user.get("city")),
        ("address", user.get("address")),
        ("orders", str(await select_user_items(user_id))),
        ("mailings", localize("my_data.off" if user.get("mailing_optout") else "my_data.on")),
        ("registered", registered.strftime("%Y-%m-%d") if hasattr(registered, "strftime") else None),
    ]
    lines = [localize("my_data.title"), ""]
    lines += [localize("my_data.line", label=localize(f"my_data.label.{key}"), value=esc(str(value)))
              for key, value in values if value not in (None, "")]
    lines += ["", localize("my_data.orders_hint")]
    return "\n".join(lines)


@router.callback_query(F.data == "my_data")
async def my_data_handler(call: CallbackQuery):
    text = await my_data_text(call.from_user.id)
    if text is None:
        await call.answer(localize("errors.something_wrong"), show_alert=True)
        return
    await call.message.edit_text(
        text, reply_markup=_buttons(("btn.my_data_erase", "my_data_erase"), ("btn.back", "legal_privacy")))


@router.callback_query(F.data == "my_data_erase")
async def my_data_erase_ask_handler(call: CallbackQuery):
    await call.message.edit_text(
        localize("my_data.erase.ask"),
        reply_markup=_buttons(("btn.my_data_erase_yes", "my_data_erase_yes"), ("btn.back", "legal_privacy")))


@router.callback_query(F.data == "my_data_erase_yes")
async def my_data_erase_handler(call: CallbackQuery, state: FSMContext):
    """The customer's own request to delete their data: done at once, with the same rules as the panel's Erase."""
    user_id = call.from_user.id
    ok, code, _counts = await erase_client(user_id, by=f"customer:{user_id}")
    if ok:
        await state.clear()             # a checkout in progress held the details that were just deleted
        await call.message.edit_text(localize("my_data.erase.done"), reply_markup=_buttons(("btn.close", "close")))
        return
    logger.info("customer %s asked to delete their data: refused (%s)", user_id, code)
    key = "my_data.erase.active_orders" if code == "has_active_orders" else "my_data.erase.failed"
    await call.message.edit_text(localize(key), reply_markup=_buttons(("btn.back", "legal_privacy")))
