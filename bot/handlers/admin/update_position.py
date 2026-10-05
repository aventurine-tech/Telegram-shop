from aiogram import Router, F
from aiogram.types import CallbackQuery, Message

from bot.database.models import Permission
from bot.database.methods import get_item_info_cached, update_item, get_category_name_by_id
from bot.database.methods.read import category_accepts_items, resolve_category_name, resolve_item_name
from bot.handlers.other import is_safe_item_name, caller_name
from bot.handlers.admin._common import parse_price

from bot.keyboards.inline import back, simple_buttons
from bot.database.methods.audit import log_audit
from bot.filters import HasPermissionFilter
from bot.misc import EnvKeys
from bot.i18n import localize, esc
from bot.states import UpdateItemFSM

router = Router()

# Stable update_item error codes -> localization keys (update_item returns codes, not messages).
_UPDATE_ITEM_ERRORS = {
    "position_invalid": "admin.goods.update.position.invalid",
    "position_exists": "admin.goods.update.position.exists",
    "db_error": "errors.something_wrong",
}


async def _show_update_item_error(send, error_code) -> None:
    """Send the localized message for an update_item failure.

    ``send`` is the bound sender to use (call.message.edit_text or message.answer).
    """
    key = _UPDATE_ITEM_ERRORS.get(error_code, "errors.something_wrong")
    await send(localize(key), reply_markup=back('goods_management'))


@router.callback_query(F.data == 'update_item', HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def update_item_callback_handler(call: CallbackQuery, state):
    """Starts the product update flow."""
    await call.message.edit_text(localize('admin.goods.update.prompt.name'), reply_markup=back("goods_management"))
    await state.set_state(UpdateItemFSM.waiting_item_name_for_update)


@router.message(UpdateItemFSM.waiting_item_name_for_update, F.text)
async def check_item_name_for_update(message: Message, state):
    """Validate item and ask for a new name."""
    item_name = await resolve_item_name(message.text)
    item = await get_item_info_cached(item_name) if item_name else None
    if not item:
        await message.answer(
            localize('admin.goods.update.not_exists'),
            reply_markup=back('goods_management')
        )
        return

    category_name = await get_category_name_by_id(item['category_id'])
    await state.update_data(item_old_name=item_name, item_category=category_name)
    await message.answer(localize('admin.goods.update.prompt.new_name'), reply_markup=back('goods_management'))
    await state.set_state(UpdateItemFSM.waiting_item_new_name)


@router.message(UpdateItemFSM.waiting_item_new_name, F.text)
async def update_item_name(message: Message, state):
    """Ask for item description."""
    new_name = (message.text or "").strip()
    if not is_safe_item_name(new_name):
        await message.answer(
            localize('admin.goods.add.name.invalid'),
            reply_markup=back('goods_management'),
        )
        return

    await state.update_data(item_new_name=new_name)
    await message.answer(localize('admin.goods.update.prompt.description'), reply_markup=back('goods_management'))
    await state.set_state(UpdateItemFSM.waiting_item_description)


@router.message(UpdateItemFSM.waiting_item_description, F.text)
async def update_item_description(message: Message, state):
    """Ask for new price."""
    await state.update_data(item_description=message.text.strip())
    await message.answer(localize('admin.goods.add.prompt.price', currency=EnvKeys.PAY_CURRENCY),
                         reply_markup=back('goods_management'))
    await state.set_state(UpdateItemFSM.waiting_item_price)


@router.message(UpdateItemFSM.waiting_item_price, F.text)
async def update_item_price(message: Message, state):
    """Validate price and ask for the category (the current one can be kept)."""
    price = parse_price(message.text)
    if price is None:
        await message.answer(localize('admin.goods.add.price.invalid'), reply_markup=back('goods_management'))
        return

    await state.update_data(item_price=price)
    data = await state.get_data()
    await message.answer(
        localize('admin.goods.update.prompt.category', category=esc(data.get('item_category'))),
        reply_markup=simple_buttons([
            (localize('admin.goods.update.keep_category'), 'update_keep_category'),
            (localize('btn.back'), 'goods_management'),
        ], per_row=1),
    )
    await state.set_state(UpdateItemFSM.waiting_item_category)


async def _apply_update(send, user, state) -> None:
    """Write the collected details and report. ``send`` is the bound sender (edit_text / answer)."""
    data = await state.get_data()
    item_old_name = data.get('item_old_name')
    item_new_name = data.get('item_new_name')

    ok, err = await update_item(
        item_old_name, item_new_name, data.get('item_description'), data.get('item_price'),
        data.get('item_category'),
    )
    if not ok:
        await _show_update_item_error(send, err)
        await state.clear()
        return

    await send(localize('admin.goods.update.success'), reply_markup=back('goods_management'))
    admin_name = caller_name(user)
    await log_audit("update_item", user_id=user.from_user.id, resource_type="Item", resource_id=item_new_name,
                    details=f"admin={admin_name}, old_name={item_old_name}")
    await state.clear()


@router.callback_query(F.data == 'update_keep_category', UpdateItemFSM.waiting_item_category,
                       HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def update_item_keep_category(call: CallbackQuery, state):
    """Keep the product's current category and save."""
    await _apply_update(call.message.edit_text, call, state)


@router.message(UpdateItemFSM.waiting_item_category, F.text)
async def update_item_category(message: Message, state):
    """The new category must exist; then save."""
    category_name = await resolve_category_name(message.text)
    if not category_name:
        await message.answer(
            localize('admin.goods.update.category.not_found'),
            reply_markup=back('goods_management')
        )
        return
    if not await category_accepts_items(category_name):
        await message.answer(
            localize('admin.goods.update.category.has_subcategories'),
            reply_markup=back('goods_management')
        )
        return

    await state.update_data(item_category=category_name)
    await _apply_update(message.answer, message, state)
