from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.handlers.other import caller_name
from bot.handlers.admin._common import (
    _notify_restock_safe, announce_arrival, parse_quantity,
    IMAGE_MESSAGE, download_message_image, image_error_text,
)
from bot.i18n import localize, esc
from bot.database.models import Permission
from bot.database.methods import get_item_info, delete_item
from bot.database.methods.product_images import has_item_image, remove_item_image, set_item_image
from bot.database.methods.update import set_item_stock, adjust_item_stock
from bot.keyboards.inline import back, simple_buttons
from bot.database.methods.audit import log_audit, log_audit_bg
from bot.filters import HasPermissionFilter
from bot.misc import EnvKeys
from bot.misc.images import ImageError, validate_image
from bot.states import GoodsFSM, StockFSM

router = Router()

# What the admin may do on the stock screen -> the minimum accepted quantity.
# "set" accepts 0 (sold out); "add"/"sub" need at least one unit.
_STOCK_MODES = {'set': 0, 'add': 1, 'sub': 1}


@router.callback_query(F.data == 'goods_management', HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def goods_management_callback_handler(call: CallbackQuery, state):
    """
    Opens the products management menu.
    """
    actions = [
        (localize("admin.goods.add_position"), "add_item"),
        (localize("admin.goods.stock_manage"), "item_stock"),
        (localize("admin.goods.update_position"), "update_item"),
        (localize("admin.goods.sale_manage"), "manage_sale"),
        (localize("admin.goods.delete_position"), "delete_item"),
        (localize("btn.back"), "console"),
    ]
    markup = simple_buttons(actions, per_row=1)
    await call.message.edit_text(localize('admin.goods.menu.title'), reply_markup=markup)
    await state.clear()


@router.callback_query(F.data == 'delete_item', HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def delete_item_callback_handler(call: CallbackQuery, state):
    """
    Requests a product name to delete.
    """
    await call.message.edit_text(localize('admin.goods.delete.prompt.name'), reply_markup=back("goods_management"))
    await state.set_state(GoodsFSM.waiting_item_name_delete)


@router.message(GoodsFSM.waiting_item_name_delete, F.text)
async def delete_str_item(message: Message, state):
    """
    Deletes a product by the provided name. Past orders keep their own copy of the name and price.
    """
    item_name = message.text
    item = await get_item_info(item_name)
    if not item:
        await message.answer(
            localize('admin.goods.delete.position.not_found'),
            reply_markup=back('goods_management')
        )
    else:
        await delete_item(item_name)
        await message.answer(
            localize('admin.goods.delete.position.success'),
            reply_markup=back('goods_management')
        )
        admin_name = caller_name(message)
        await log_audit("delete_item", user_id=message.from_user.id, resource_type="Item", resource_id=item_name,
                        details=f"admin={admin_name}")
    await state.clear()


def _stock_card(item: dict, has_photo: bool = False) -> str:
    """Product name, price, units on hand and whether it has a picture."""
    card = localize(
        'admin.goods.stock.card',
        name=esc(item['name']), price=item['price'], currency=EnvKeys.PAY_CURRENCY, stock=item['stock'],
    )
    return f"{card}\n{localize('admin.goods.photo.status.yes' if has_photo else 'admin.goods.photo.status.no')}"


def _stock_card_markup(has_photo: bool = False):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=localize('admin.goods.stock.btn.set'), callback_data='stock_set'),
        InlineKeyboardButton(text=localize('admin.goods.stock.btn.add'), callback_data='stock_add'),
        InlineKeyboardButton(text=localize('admin.goods.stock.btn.sub'), callback_data='stock_sub'),
    )
    kb.row(InlineKeyboardButton(text=localize('admin.goods.photo.btn.change'), callback_data='stock_photo'))
    if has_photo:
        kb.row(InlineKeyboardButton(text=localize('admin.goods.photo.btn.remove'), callback_data='stock_photo_rm'))
    kb.row(InlineKeyboardButton(text=localize('btn.back'), callback_data='goods_management'))
    return kb.as_markup()


async def _render_card(item: dict) -> tuple[str, object]:
    """Card text and keyboard for a product, with its current picture status."""
    has_photo = await has_item_image(item['name'])
    return _stock_card(item, has_photo), _stock_card_markup(has_photo)


@router.callback_query(F.data == 'item_stock', HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def item_stock_callback_handler(call: CallbackQuery, state):
    """
    Requests a product name to open its stock screen.
    """
    await call.message.edit_text(localize('admin.goods.prompt.enter_item_name'), reply_markup=back("goods_management"))
    await state.set_state(StockFSM.waiting_item_name)


@router.message(StockFSM.waiting_item_name, F.text, HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def show_item_stock(message: Message, state: FSMContext):
    """
    Shows the product's stock with the set / add / remove buttons.
    """
    item_name = message.text.strip()
    item = await get_item_info(item_name)
    if not item:
        await message.answer(localize('admin.goods.position.not_found'), reply_markup=back('goods_management'))
        return

    await state.update_data(stock_item_name=item['name'])
    await state.set_state(StockFSM.card)
    text, markup = await _render_card(item)
    await message.answer(text, parse_mode='HTML', reply_markup=markup)


@router.callback_query(F.data.in_({'stock_set', 'stock_add', 'stock_sub'}), StockFSM.card,
                       HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def stock_action_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Remembers which stock action was chosen and asks for the quantity.
    """
    mode = call.data.split('_')[1]
    await state.update_data(stock_mode=mode)
    await state.set_state(StockFSM.waiting_quantity)
    await call.message.edit_text(
        localize(f'admin.goods.stock.prompt.{mode}'),
        reply_markup=back('stock_card'),
    )


@router.callback_query(F.data == 'stock_card', StateFilter(StockFSM.waiting_quantity, StockFSM.waiting_photo),
                       HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def stock_back_to_card(call: CallbackQuery, state: FSMContext):
    """
    Cancels the quantity prompt and returns to the product's stock screen.
    """
    data = await state.get_data()
    item = await get_item_info(data.get('stock_item_name') or '')
    if not item:
        await call.message.edit_text(localize('admin.goods.position.not_found'), reply_markup=back('goods_management'))
        await state.clear()
        return
    await state.set_state(StockFSM.card)
    text, markup = await _render_card(item)
    await call.message.edit_text(text, parse_mode='HTML', reply_markup=markup)


@router.message(StockFSM.waiting_quantity, F.text, HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def apply_stock_change(message: Message, state: FSMContext):
    """
    Applies the chosen action: set an absolute stock, add units or remove units.
    A restock (0 -> more than 0) wakes up customers subscribed to the product.
    """
    data = await state.get_data()
    item_name = data.get('stock_item_name')
    mode = data.get('stock_mode')
    if mode not in _STOCK_MODES or not item_name:
        await message.answer(localize('errors.invalid_data'), reply_markup=back('goods_management'))
        await state.clear()
        return

    qty = parse_quantity(message.text, minimum=_STOCK_MODES[mode])
    if qty is None:
        await message.answer(localize('admin.goods.stock.invalid'), reply_markup=back('stock_card'))
        return

    if mode == 'set':
        found, old, new = await set_item_stock(item_name, qty)
    else:
        found, old, new = await adjust_item_stock(item_name, qty if mode == 'add' else -qty)
    if not found:
        await message.answer(localize('admin.goods.position.not_found'), reply_markup=back('goods_management'))
        await state.clear()
        return

    item = await get_item_info(item_name)
    await state.set_state(StockFSM.card)
    text, markup = await _render_card(item)
    await message.answer(
        f"{localize('admin.goods.stock.updated', old=old, new=new)}\n\n{text}",
        parse_mode='HTML', reply_markup=markup,
    )

    admin_name = caller_name(message)
    await log_audit("update_item_stock", user_id=message.from_user.id, resource_type="Item", resource_id=item_name,
                    details=f"admin={admin_name}, mode={mode}, old={old}, new={new}")

    if old == 0 < new:
        await _notify_restock_safe(message.bot, item_name)
        await announce_arrival(message.bot, item_name, new)


async def _card_item(state: FSMContext) -> dict | None:
    """The product whose card is open (None if it is gone)."""
    data = await state.get_data()
    return await get_item_info(data.get('stock_item_name') or '')


@router.callback_query(F.data == 'stock_photo', StockFSM.card,
                       HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def stock_photo_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Asks for a new picture (a photo or an image file) for the open product.
    """
    await state.set_state(StockFSM.waiting_photo)
    await call.message.edit_text(localize('admin.goods.photo.prompt.change'), reply_markup=back('stock_card'))


@router.message(StockFSM.waiting_photo, IMAGE_MESSAGE, HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def stock_photo_upload(message: Message, state: FSMContext):
    """
    Validates and stores the uploaded picture. A bad file is refused and the admin may send another one.
    """
    data = await state.get_data()
    item_name = data.get('stock_item_name')
    if not item_name:
        await message.answer(localize('errors.invalid_data'), reply_markup=back('goods_management'))
        await state.clear()
        return

    try:
        image = await download_message_image(message)
        if image is None:
            raise ImageError("invalid_image")
        validate_image(image)
    except ImageError as e:
        await message.answer(image_error_text(e.code), reply_markup=back('stock_card'))
        return

    ok, code = await set_item_image(item_name, image)
    if not ok:
        await message.answer(image_error_text(code), reply_markup=back('stock_card'))
        if code == 'item_not_found':
            await state.clear()
        return

    item = await get_item_info(item_name)
    await state.set_state(StockFSM.card)
    text, markup = await _render_card(item)
    await message.answer(f"{localize('admin.goods.photo.updated')}\n\n{text}",
                         parse_mode='HTML', reply_markup=markup)

    log_audit_bg("update_item_photo", user_id=message.from_user.id, resource_type="Item", resource_id=item_name,
                 details=f"admin={caller_name(message)}, action=set, bytes={len(image)}")


@router.message(StockFSM.waiting_photo, HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def stock_photo_reprompt(message: Message):
    """
    Anything but a photo / image file at the picture prompt: ask again.
    """
    await message.answer(localize('admin.goods.photo.reprompt'), reply_markup=back('stock_card'))


@router.callback_query(F.data == 'stock_photo_rm', StockFSM.card,
                       HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def stock_photo_remove_ask(call: CallbackQuery, state: FSMContext):
    """
    Yes / no before removing the picture.
    """
    item = await _card_item(state)
    if not item:
        await call.message.edit_text(localize('admin.goods.position.not_found'), reply_markup=back('goods_management'))
        await state.clear()
        return
    kb = InlineKeyboardBuilder()
    kb.button(text=localize('admin.goods.photo.remove.yes'), callback_data='stock_photo_rmy')
    kb.button(text=localize('admin.goods.photo.remove.no'), callback_data='stock_card')
    kb.adjust(2)
    await call.message.edit_text(localize('admin.goods.photo.remove.confirm', name=esc(item['name'])),
                                 parse_mode='HTML', reply_markup=kb.as_markup())


@router.callback_query(F.data == 'stock_photo_rmy', StockFSM.card,
                       HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def stock_photo_remove(call: CallbackQuery, state: FSMContext):
    """
    Removes the product's picture and returns to the card.
    """
    data = await state.get_data()
    item_name = data.get('stock_item_name') or ''
    removed = await remove_item_image(item_name)
    item = await get_item_info(item_name)
    if not item:
        await call.message.edit_text(localize('admin.goods.position.not_found'), reply_markup=back('goods_management'))
        await state.clear()
        return

    text, markup = await _render_card(item)
    note = localize('admin.goods.photo.removed' if removed else 'admin.goods.photo.none')
    await call.message.edit_text(f"{note}\n\n{text}", parse_mode='HTML', reply_markup=markup)
    if removed:
        log_audit_bg("update_item_photo", user_id=call.from_user.id, resource_type="Item", resource_id=item_name,
                     details=f"admin={caller_name(call)}, action=remove")
