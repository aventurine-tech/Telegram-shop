import contextlib

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.enums.chat_type import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError

import asyncio
import datetime
from html import escape as _esc

from bot.database.methods import (
    select_max_role_id, create_user, check_role_cached, check_user,
    select_user_items, check_user_cached
)
from bot.database.methods.read import get_cart_count, invalidate_user_cache
from bot.database.methods.lazy_queries import query_top_categories_with_ids
from bot.database.methods.translations import category_labels
from bot.handlers.other import check_sub_channel, _parse_channel_username
from bot.keyboards import main_menu, back, profile_keyboard, check_sub
from bot.keyboards.inline import MENU_CATEGORY_LIMIT
from bot.keyboards.reply import bottom_nav_keyboard
from bot.middleware.clean_chat import carrier_tracker, outside_screen
from bot.handlers.user._screen import edit_screen
from bot.misc import EnvKeys
from bot.misc.metrics import get_metrics
from bot.i18n import localize
from bot.logger_mesh import logger

router = Router()


async def _ensure_user(user_id: int) -> dict | None:
    """Return the user's row, registering them first if it is missing.

    A stale keyboard (or a wiped database) can hand a callback from someone
    with no row at all; every screen that reads user fields needs the row to
    exist rather than blowing up on None.
    """
    user = await check_user_cached(user_id)
    if user:
        return user

    await create_user(
        telegram_id=user_id,
        registration_date=datetime.datetime.now(datetime.timezone.utc),
        referral_id=None,
        role=1,
    )
    await invalidate_user_cache(user_id)
    return await check_user_cached(user_id)


def _channel_chat_id(channel_username: str) -> int | str:
    """Resolve the chat id to query for the subscription check.

    CHANNEL_ID wins when set (private channels have no username to address), but
    a non-numeric value in the env must not take the handler down with it.
    """
    raw = EnvKeys.CHANNEL_ID
    if raw:
        try:
            return int(raw)
        except (TypeError, ValueError):
            logger.warning("CHANNEL_ID=%r is not a valid chat id; falling back to @%s", raw, channel_username)
    return f"@{channel_username}"


async def _delete_quietly(message: Message) -> None:
    """Delete a message, tolerating the cases Telegram refuses.

    A message older than 48h, or one in a chat where the bot lost delete rights,
    raises — and that must not abort a handler that already did its real work.
    """
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.debug(f"Failed to delete message: {e}")


async def _is_subscribed(bot, channel_username: str, user_id: int) -> bool | None:
    """Whether the user is in the required channel.

    Returns None when the check could not be performed (private channel, bad
    link, bot not an admin) so callers can treat it as "don't block".
    """
    try:
        chat_member = await bot.get_chat_member(
            chat_id=_channel_chat_id(channel_username), user_id=user_id
        )
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.warning(f"Channel subscription check failed for user {user_id}: {e}")
        return None
    return await check_sub_channel(chat_member)


async def register_if_new(user_id: int, payload: str | None = None) -> int:
    """Register the user when they have no row yet; returns their permission bitmask.

    `payload` is the /start argument: a referrer's id, honoured only for a new user who is not
    referring themselves and whose referrer exists.
    """
    role_data = await check_role_cached(user_id)
    if role_data != 0:
        return role_data

    owner_max_role = await select_max_role_id()
    user_role = owner_max_role if user_id == EnvKeys.OWNER_ID else 1

    referral_id = None
    if payload:
        payload = payload.strip()
        if payload.isdigit() and payload != str(user_id):
            candidate = int(payload)
            if await check_user(candidate) is not None:
                referral_id = candidate

    # registration_date is DateTime
    await create_user(
        telegram_id=int(user_id),
        registration_date=datetime.datetime.now(datetime.timezone.utc),
        referral_id=referral_id,
        role=user_role
    )

    await invalidate_user_cache(user_id)
    from bot.middleware.security import invalidate_auth_caches
    invalidate_auth_caches(user_id)

    metrics = get_metrics()
    if metrics:
        metrics.track_event("registration", user_id)

    # Re-read (now cached) so the menu reflects the freshly assigned role.
    return await check_role_cached(user_id)


async def menu_categories() -> list[tuple[int, str]]:
    """``[(id, label)]`` for the main-menu category buttons, in the viewer's language and order.

    One extra row is fetched so the keyboard can tell there are more than it shows.
    """
    cats = await query_top_categories_with_ids(limit=MENU_CATEGORY_LIMIT + 1)
    labels = await category_labels([name for _id, name in cats])
    return [(cat_id, labels.get(name, name)) for cat_id, name in cats]


async def open_main_menu(message: Message, user_id: int, role_data: int) -> None:
    """Answer in `message`'s chat with the main menu, or the subscribe prompt when the channel check fails."""
    channel_username = _parse_channel_username()

    # Optional subscription check. A failed check (None) does not block entry.
    if channel_username:
        subscribed = await _is_subscribed(message.bot, channel_username, user_id)
        if subscribed is False:
            await message.answer(localize("subscribe.prompt"), reply_markup=check_sub(channel_username))
            return

    # The bottom keyboard rides on its own message (one reply_markup per message), ahead of the inline menu.
    await send_bottom_nav(message)
    markup = main_menu(role=role_data, channel=channel_username, helper=EnvKeys.HELPER_ID,
                       categories=await menu_categories())
    await message.answer(localize("menu.title"), reply_markup=markup)


# Telegram needs a message to hold the reply keyboard (it rejects text that is empty after trimming, and drops the
# keyboard when that message is deleted), so the keyboard rides on a short welcome line that stays at the top of the
# chat. A newer one replaces it, e.g. after a language change.


async def send_bottom_nav(message: Message) -> None:
    """(Re)send the persistent Catalog / Cart / Profile keyboard in the current language.

    The keyboard rides on the welcome line ("Welcome to UMBRA"), which is kept out of the clean-chat screen tracking (so it
    never replaces the screen the user is looking at). A newer carrier replaces the previous one: the old
    message is deleted only after the new keyboard is in place."""
    try:
        with outside_screen():
            sent = await message.answer(localize("menu.welcome"), reply_markup=bottom_nav_keyboard())
    except TelegramAPIError as e:
        # The menu matters more than the keyboard: never let a keyboard failure block /start.
        logger.warning("could not send the bottom keyboard: %s", e)
        return
    new_id = getattr(sent, "message_id", None)
    chat_id = message.chat.id
    previous = carrier_tracker.get(chat_id)
    if isinstance(new_id, int):
        carrier_tracker.set(chat_id, new_id)
        if previous and previous != new_id:
            with contextlib.suppress(Exception):  # cosmetic: a stale carrier is harmless
                await message.bot.delete_message(chat_id=chat_id, message_id=previous)


def start_payload(text: str | None) -> str | None:
    """The argument of ``/start <payload>`` (None when absent)."""
    parts = (text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else None


@router.message(F.text.startswith('/start'))
async def start(message: Message, state: FSMContext):
    """
    Handle /start:
    - Ensure user exists (register if new)
    - (Optional) Check channel subscription
    - Show the main menu
    (A user who has not picked a language yet is intercepted earlier by the language picker.)
    """
    if message.chat.type != ChatType.PRIVATE:
        return

    user_id = message.from_user.id
    await state.clear()

    role_data = await register_if_new(user_id, start_payload(message.text))
    await open_main_menu(message, user_id, role_data)
    await _delete_quietly(message)
    await state.clear()


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Return user to the main menu.
    """
    user_id = call.from_user.id
    await _ensure_user(user_id)

    role = await check_role_cached(user_id) or 0

    channel_username = _parse_channel_username()

    markup = main_menu(role=role, channel=channel_username, helper=EnvKeys.HELPER_ID,
                       categories=await menu_categories())
    await call.message.edit_text(localize("menu.title"), reply_markup=markup)
    await state.clear()


@router.callback_query(F.data == "rules")
async def rules_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Show rules text if provided in ENV.
    """
    rules_data = EnvKeys.RULES
    if rules_data:
        await call.message.edit_text(rules_data, reply_markup=back("back_to_menu"))
    else:
        await call.answer(localize("rules.not_set"))
    await state.clear()


def _details_lines(user_info: dict) -> str:
    """The customer's saved name, phone, city and address, one line each (only those that are set)."""
    out = []
    for key, column in (("profile.name", "contact_name"), ("profile.phone", "phone"),
                        ("profile.city", "city"), ("profile.address", "address")):
        value = (user_info.get(column) or "").strip()
        if value:
            out.append(localize(key, value=_esc(value)))
    return ("\n" + "\n".join(out)) if out else ""


async def show_profile(call: CallbackQuery | Message, *, as_new: bool = False) -> None:
    """Render the profile screen into the callback's message (or as a new message for a Message).

    ``as_new`` sends it as a fresh message instead (the caller has removed the old screen)."""
    # For both a CallbackQuery and a Message, `from_user` is the person (`call.message.from_user` would be the bot).
    user_id = call.from_user.id
    tg_user = call.from_user
    user_info = await _ensure_user(user_id)
    if not user_info:
        if isinstance(call, Message):
            await call.answer(localize("errors.something_wrong"))
        else:
            await call.answer(localize("errors.something_wrong"), show_alert=True)
        return

    balance = user_info.get('balance')
    orders, cart_count = await asyncio.gather(
        select_user_items(user_id),
        get_cart_count(user_id),
    )
    referral = EnvKeys.REFERRAL_PERCENT

    markup = profile_keyboard(referral, orders, cart_count=cart_count)
    text = (
        f"{localize('profile.caption', name=_esc(tg_user.first_name or ''), id=user_id)}\n"
        f"{localize('profile.id', id=user_id)}\n"
        f"{localize('profile.balance', amount=balance, currency=EnvKeys.PAY_CURRENCY)}\n"
        f"{localize('profile.orders_count', count=orders)}"
        f"{_details_lines(user_info)}"
    )
    try:
        if as_new and not isinstance(call, Message):
            await call.message.answer(text, reply_markup=markup, parse_mode='HTML')
        else:
            await edit_screen(call, text, reply_markup=markup, parse_mode='HTML')
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


@router.callback_query(F.data == "profile")
async def profile_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Send profile info (balance, orders count, id, etc.).
    """
    await show_profile(call)
    await state.clear()


@router.callback_query(F.data == "sub_channel_done")
async def check_sub_to_channel(call: CallbackQuery, state: FSMContext):
    """
    Re-check channel subscription after user clicks "Check".
    """
    user_id = call.from_user.id
    channel_username = _parse_channel_username()
    helper = EnvKeys.HELPER_ID

    if channel_username:
        # None (check unavailable) is treated as subscribed, matching /start: a misconfigured channel must not lock everyone out of the bot.
        if await _is_subscribed(call.bot, channel_username, user_id) is not False:
            await _ensure_user(user_id)
            role = await check_role_cached(user_id) or 0
            markup = main_menu(role, channel_username, helper, categories=await menu_categories())
            await call.message.edit_text(localize("menu.title"), reply_markup=markup)
            await state.clear()
            return

    await call.answer(localize("errors.not_subscribed"))
