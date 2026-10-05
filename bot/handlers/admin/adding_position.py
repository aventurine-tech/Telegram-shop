from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.models import Permission
from bot.database.methods import check_category_cached, get_item_info, get_item_info_cached, create_item
from bot.database.methods.product_images import set_item_image
from bot.handlers.other import is_safe_item_name
from bot.handlers.admin._common import (
    _notify_restock_safe, announce_arrival, parse_price, parse_quantity,
    IMAGE_MESSAGE, download_message_image, image_error_text,
)
from bot.keyboards.inline import back
from bot.database.methods.audit import log_audit
from bot.filters import HasPermissionFilter
from bot.misc import EnvKeys
from bot.misc.images import ImageError, validate_image
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


def _photo_prompt_markup():
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=localize('admin.goods.photo.btn.skip'), callback_data='add_item_skip_photo'))
    kb.row(InlineKeyboardButton(text=localize('btn.back'), callback_data='goods_management'))
    return kb.as_markup()


@router.message(AddItemFSM.waiting_stock, F.text)
async def add_item_stock(message: Message, state):
    """
    Validate the stock quantity and ask for the optional picture; the product is created after that step.
    """
    stock = parse_quantity(message.text)
    if stock is None:
        await message.answer(localize('admin.goods.stock.invalid'), reply_markup=back('goods_management'))
        return

    await state.update_data(item_stock=stock)
    await message.answer(localize('admin.goods.add.prompt.photo'), reply_markup=_photo_prompt_markup())
    await state.set_state(AddItemFSM.waiting_photo)


async def _create_product(message: Message, user, state, image: bytes | None = None) -> None:
    """
    Create the product from the collected answers, store its picture (if any), announce it if it is in stock.
    ``message`` is where replies go, ``user`` is the admin who acted.
    """
    data = await state.get_data()
    item_name = data.get('item_name')
    stock = data.get('item_stock') or 0

    await create_item(item_name, data.get('item_description'), data.get('item_price'),
                      data.get('item_category'), stock=stock)

    created = await get_item_info(item_name)    # uncached: the name step may have cached a miss
    photo_ok = None
    if image is not None and created:
        # Only a product that really exists gets a picture.
        photo_ok, code = await set_item_image(item_name, image)
        if not photo_ok:
            await message.answer(image_error_text(code), reply_markup=back('goods_management'))

    await message.answer(
        localize('admin.goods.add.result.created', name=esc(item_name), qty=stock),
        parse_mode='HTML', reply_markup=back('goods_management')
    )

    # Stock is committed — notify anyone waiting on this product and the shop channel.
    if stock > 0:
        await _notify_restock_safe(message.bot, item_name)
        await announce_arrival(message.bot, item_name, stock)

    admin_name = user.first_name or str(user.id)
    await log_audit("create_item", user_id=user.id, resource_type="Item", resource_id=item_name,
                    details=f"admin={admin_name}, stock={stock}, photo={'yes' if photo_ok else 'no'}")

    await state.clear()


@router.message(AddItemFSM.waiting_photo, IMAGE_MESSAGE)
async def add_item_photo(message: Message, state):
    """
    Take the product picture (photo or image file). A bad file is refused and the admin may retry or skip.
    """
    try:
        image = await download_message_image(message)
        if image is None:
            raise ImageError("invalid_image")
        validate_image(image)
    except ImageError as e:
        await message.answer(image_error_text(e.code), reply_markup=_photo_prompt_markup())
        return

    await _create_product(message, message.from_user, state, image)


@router.callback_query(F.data == 'add_item_skip_photo', AddItemFSM.waiting_photo,
                       HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def add_item_skip_photo(call: CallbackQuery, state):
    """
    Create the product without a picture.
    """
    await call.answer()
    await _create_product(call.message, call.from_user, state)


@router.message(AddItemFSM.waiting_photo)
async def add_item_photo_reprompt(message: Message):
    """
    Anything but a photo / image file at the photo step: ask again.
    """
    await message.answer(localize('admin.goods.photo.reprompt'), reply_markup=_photo_prompt_markup())
