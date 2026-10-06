"""Profile → My details: the name for delivery, phone, city and address the customer keeps in the bot.

Each detail is edited by typing it (one prompt per field, with a Clear button); checkout offers the saved values."""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.database.methods.profiles import DETAIL_FIELDS, save_details
from bot.database.methods.read import check_user, invalidate_user_cache
from bot.handlers.user._screen import edit_screen
from bot.i18n import esc, localize
from bot.keyboards.inline import details_edit_keyboard, my_details_keyboard
from bot.misc import ADDRESS_MAX_LEN, clean_text, validate_customer_name, validate_phone
from bot.states import ProfileFSM

router = Router()

CITY_MAX_LEN = 100
# short callback name -> user column
FIELDS = {"name": "contact_name", "phone": "phone", "city": "city", "address": "address"}


def details_text(profile: dict | None) -> str:
    profile = profile or {}
    lines = [localize("details.title"), "", localize("details.hint"), ""]
    for short, column in FIELDS.items():
        value = (profile.get(column) or "").strip()
        lines.append(localize("details.row", label=localize(f"details.label_{short}"),
                              value=esc(value) if value else localize("details.empty")))
    return "\n".join(lines)


async def show_my_details(target, user_id: int) -> None:
    profile = await check_user(user_id)
    await edit_screen(target, details_text(profile), reply_markup=my_details_keyboard(profile or {}),
                      parse_mode="HTML")


@router.callback_query(F.data == "my_details")
async def my_details_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show_my_details(call, call.from_user.id)


@router.callback_query(F.data.startswith("mydet_edit:"))
async def edit_detail_handler(call: CallbackQuery, state: FSMContext):
    short = call.data.split(":", 1)[1]
    if short not in FIELDS:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    profile = await check_user(call.from_user.id) or {}
    await call.answer()
    await state.set_state(ProfileFSM.editing)
    await state.update_data(pd_field=short)
    current = (profile.get(FIELDS[short]) or "").strip()
    text = localize(f"details.ask_{short}")
    if current:
        text += "\n\n" + localize("details.current", value=esc(current))
    await edit_screen(call, text, reply_markup=details_edit_keyboard(short, bool(current)), parse_mode="HTML")


def _clean(short: str, raw: str) -> str:
    if short == "name":
        return validate_customer_name(raw)
    if short == "phone":
        return validate_phone(raw)
    if short == "city":
        return clean_text(raw, CITY_MAX_LEN)
    return clean_text(raw, ADDRESS_MAX_LEN)


@router.message(ProfileFSM.editing, F.text)
async def detail_text_handler(message: Message, state: FSMContext):
    short = (await state.get_data()).get("pd_field")
    if short not in FIELDS:
        await state.clear()
        await message.answer(localize("errors.something_wrong"))
        return
    try:
        value = _clean(short, message.text)
    except ValueError:
        invalid = {"name": "checkout.name_invalid", "phone": "checkout.phone_invalid",
                   "city": "details.city_invalid", "address": "checkout.address_invalid"}[short]
        await message.answer(localize(invalid, max=ADDRESS_MAX_LEN if short == "address" else CITY_MAX_LEN),
                             reply_markup=details_edit_keyboard(short, False))
        return
    await save_details(message.from_user.id, **{FIELDS[short]: value})
    await invalidate_user_cache(message.from_user.id)
    await state.clear()
    profile = await check_user(message.from_user.id)
    await message.answer(localize("details.saved") + "\n\n" + details_text(profile),
                         reply_markup=my_details_keyboard(profile or {}), parse_mode="HTML")


@router.callback_query(F.data.startswith("mydet_clear:"))
async def clear_detail_handler(call: CallbackQuery, state: FSMContext):
    short = call.data.split(":", 1)[1]
    if short not in FIELDS:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    await save_details(call.from_user.id, **{FIELDS[short]: None})
    await invalidate_user_cache(call.from_user.id)
    await state.clear()
    await call.answer(localize("details.cleared"))
    await show_my_details(call, call.from_user.id)


assert set(FIELDS.values()) <= set(DETAIL_FIELDS)
