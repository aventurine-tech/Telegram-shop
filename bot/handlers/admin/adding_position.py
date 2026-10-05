from aiogram import Router, F
from aiogram.types import CallbackQuery, Message

from bot.database.models import Permission
from bot.database.methods import check_category_cached, get_item_info_cached, create_item
from bot.handlers.other import is_safe_item_name, caller_name
from bot.handlers.admin._common import _notify_restock_safe, announce_arrival, parse_price, parse_quantity
from bot.keyboards.inline import back
from bot.database.methods.audit import log_audit
from bot.filters import HasPermissionFilter
from bot.misc import EnvKeys
from bot.i18n import localize, esc
from bot.states import AddItemFSM

router = Router()


@router.callback_query(F.data == 'add_item', HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def add_item_callback_handler(call: CallbackQuery, state):
    """
    Ask administrator for a new position name.
    """
    await call.message.edit_text(localize('admin.goods.add.prompt.name'), reply_markup=back("goods_management"))
    await state.set_state(AddItemFSM.waiting_item_name)


@router.message(AddItemFSM.waiting_item_name, F.text)
async def check_item_name_for_add(message: Message, state):
    """
    If position already exists — inform the user; otherwise save name and ask for description.
    """
    item_name = (message.text or "").strip()
    if not is_safe_item_name(item_name):
        await message.answer(
            localize('admin.goods.add.name.invalid'),
            reply_markup=back('goods_management'),
        )
        return
    item = await get_item_info_cached(item_name)
    if item:
        await message.answer(
            localize('admin.goods.add.name.exists'),
            reply_markup=back('goods_management')
        )
        return

    await state.update_data(item_name=item_name)
    await message.answer(localize('admin.goods.add.prompt.description'), reply_markup=back('goods_management'))
    await state.set_state(AddItemFSM.waiting_item_description)


@router.message(AddItemFSM.waiting_item_description, F.text)
async def add_item_description(message: Message, state):
    """
    Save description and proceed to price input.
    """
    await state.update_data(item_description=(message.text or "").strip())
    await message.answer(localize('admin.goods.add.prompt.price', currency=EnvKeys.PAY_CURRENCY),
                         reply_markup=back('goods_management'))
    await state.set_state(AddItemFSM.waiting_item_price)


@router.message(AddItemFSM.waiting_item_price, F.text)
async def add_item_price(message: Message, state):
    """
    Validate price and ask for category.
    """
    price = parse_price(message.text)
    if price is None:
        await message.answer(localize('admin.goods.add.price.invalid'), reply_markup=back('goods_management'))
        return

    await state.update_data(item_price=price)
    await message.answer(localize('admin.goods.add.prompt.category'), reply_markup=back('goods_management'))
    await state.set_state(AddItemFSM.waiting_category)


@router.message(AddItemFSM.waiting_category, F.text)
async def check_category_for_add_item(message: Message, state):
    """
    Category must exist; then ask for the stock quantity.
    """
    category_name = (message.text or "").strip()
    category = await check_category_cached(category_name)
    if not category:
        await message.answer(
            localize('admin.goods.add.category.not_found'),
            reply_markup=back('goods_management')
        )
        return

    await state.update_data(item_category=category_name)
    await message.answer(localize('admin.goods.add.prompt.stock'), reply_markup=back('goods_management'))
    await state.set_state(AddItemFSM.waiting_stock)


@router.message(AddItemFSM.waiting_stock, F.text)
async def add_item_stock(message: Message, state):
    """
    Validate the stock quantity, create the product, announce it if it is in stock.
    """
    stock = parse_quantity(message.text)
    if stock is None:
        await message.answer(localize('admin.goods.stock.invalid'), reply_markup=back('goods_management'))
        return

    data = await state.get_data()
    item_name = data.get('item_name')

    await create_item(item_name, data.get('item_description'), data.get('item_price'),
                      data.get('item_category'), stock=stock)

    await message.answer(
        localize('admin.goods.add.result.created', name=esc(item_name), qty=stock),
        parse_mode='HTML', reply_markup=back('goods_management')
    )

    # Stock is committed — notify anyone waiting on this product and the shop channel.
    if stock > 0:
        await _notify_restock_safe(message.bot, item_name)
        await announce_arrival(message.bot, item_name, stock)

    admin_name = caller_name(message)
    await log_audit("create_item", user_id=message.from_user.id, resource_type="Item", resource_id=item_name,
                    details=f"admin={admin_name}, stock={stock}")

    await state.clear()
