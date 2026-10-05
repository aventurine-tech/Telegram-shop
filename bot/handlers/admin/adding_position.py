from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.models import Permission
from bot.database.methods import get_item_info, create_item
from bot.database.methods.read import category_accepts_items, resolve_category_name, resolve_item_name
from bot.database.methods.product_images import set_item_image
from bot.handlers.other import is_safe_item_name
from bot.handlers.admin._common import (
    _notify_restock_safe, announce_arrival, parse_price, parse_quantity,
    IMAGE_MESSAGE, download_message_image, image_error_text,
    admin_language, main_language, wizard_languages, language_label, check_translation, translation_limit,
)
from bot.keyboards.inline import back
from bot.keyboards.translations import skip_keyboard
from bot.database.methods.audit import log_audit
from bot.filters import HasPermissionFilter
from bot.misc import EnvKeys
from bot.misc.images import ImageError, validate_image
from bot.misc.localized import MAX_DESCRIPTION_LEN, derive_canonical
from bot.i18n import localize, esc
from bot.states import AddItemFSM

router = Router()


@router.callback_query(F.data == 'add_item', HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def add_item_callback_handler(call: CallbackQuery, state):
    """
    Ask administrator for a new position name, first in the admin's own language.
    """
    admin_lang = wizard_languages(await admin_language(call.from_user.id))[0]
    await call.message.edit_text(localize('admin.goods.add.prompt.name', language=language_label(admin_lang)),
                                 reply_markup=back("goods_management"))
    await state.set_state(AddItemFSM.waiting_item_name)


@router.message(AddItemFSM.waiting_item_name, F.text)
async def check_item_name_for_add(message: Message, state):
    """
    The name in the admin's own language (required). If a product with that name (canonical or any
    translation) already exists — inform the user; otherwise ask for the other languages (each skippable).
    """
    item_name = (message.text or "").strip()
    if not is_safe_item_name(item_name):
        await message.answer(
            localize('admin.goods.add.name.invalid'),
            reply_markup=back('goods_management'),
        )
        return
    if await resolve_item_name(item_name):
        await message.answer(
            localize('admin.goods.add.name.exists'),
            reply_markup=back('goods_management')
        )
        return

    languages = wizard_languages(await admin_language(message.from_user.id))
    await state.update_data(item_name_lang=languages[0], item_names={languages[0]: item_name},
                            item_name_queue=languages[1:])
    await _next_name_translation(message, state)


async def _next_name_translation(target: Message, state):
    """Asks for the product name in the next language, or moves on to the description."""
    data = await state.get_data()
    queue = list(data.get('item_name_queue') or [])
    if not queue:
        admin_lang = wizard_languages(data.get('item_name_lang'))[0]
        await target.answer(localize('admin.goods.add.prompt.description', language=language_label(admin_lang)),
                            reply_markup=back('goods_management'))
        await state.set_state(AddItemFSM.waiting_item_description)
        return
    await target.answer(
        localize('admin.goods.add.prompt.name_translation', language=language_label(queue[0])),
        reply_markup=skip_keyboard('add_item_skip_tr', 'goods_management'),
    )
    await state.set_state(AddItemFSM.waiting_item_name_translation)


async def _next_description_translation(target: Message, state):
    """Asks for the product description in the next language, or moves on to the price."""
    data = await state.get_data()
    queue = list(data.get('item_desc_queue') or [])
    if not queue:
        await target.answer(localize('admin.goods.add.prompt.price', currency=EnvKeys.PAY_CURRENCY),
                            reply_markup=back('goods_management'))
        await state.set_state(AddItemFSM.waiting_item_price)
        return
    await target.answer(
        localize('admin.goods.add.prompt.description_translation', language=language_label(queue[0])),
        reply_markup=skip_keyboard('add_item_skip_tr', 'goods_management'),
    )
    await state.set_state(AddItemFSM.waiting_item_description_translation)


@router.message(AddItemFSM.waiting_item_name_translation, F.text,
                HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def add_item_name_translation(message: Message, state):
    """
    Take the product name in the current language (validated) and move on.
    """
    data = await state.get_data()
    queue = list(data.get('item_name_queue') or [])
    if not queue:
        await _next_name_translation(message, state)
        return
    value, error = check_translation('name', message.text)
    if error:
        await message.answer(localize(error, max=translation_limit('name')),
                             reply_markup=skip_keyboard('add_item_skip_tr', 'goods_management'))
        return
    if await resolve_item_name(value):
        await message.answer(localize('admin.goods.add.name.exists'),
                             reply_markup=skip_keyboard('add_item_skip_tr', 'goods_management'))
        return
    names = dict(data.get('item_names') or {})
    names[queue[0]] = value
    await state.update_data(item_names=names, item_name_queue=queue[1:])
    await _next_name_translation(message, state)


@router.message(AddItemFSM.waiting_item_description_translation, F.text,
                HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def add_item_description_translation(message: Message, state):
    """
    Take the product description in the current language (validated) and move on.
    """
    data = await state.get_data()
    queue = list(data.get('item_desc_queue') or [])
    if not queue:
        await _next_description_translation(message, state)
        return
    value, error = check_translation('description', message.text)
    if error:
        await message.answer(localize(error, max=translation_limit('description')),
                             reply_markup=skip_keyboard('add_item_skip_tr', 'goods_management'))
        return
    descriptions = dict(data.get('item_descriptions') or {})
    descriptions[queue[0]] = value
    await state.update_data(item_descriptions=descriptions, item_desc_queue=queue[1:])
    await _next_description_translation(message, state)


@router.callback_query(F.data == 'add_item_skip_tr',
                       StateFilter(AddItemFSM.waiting_item_name_translation,
                                   AddItemFSM.waiting_item_description_translation),
                       HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def add_item_skip_translation(call: CallbackQuery, state):
    """
    Leave the current language empty (it falls back to the main-language text).
    """
    await call.answer()
    data = await state.get_data()
    if await state.get_state() == AddItemFSM.waiting_item_name_translation:
        await state.update_data(item_name_queue=list(data.get('item_name_queue') or [])[1:])
        await _next_name_translation(call.message, state)
    else:
        await state.update_data(item_desc_queue=list(data.get('item_desc_queue') or [])[1:])
        await _next_description_translation(call.message, state)


@router.message(AddItemFSM.waiting_item_description, F.text)
async def add_item_description(message: Message, state):
    """
    Save the description in the admin's own language (required) and ask for the other languages.
    """
    description = (message.text or "").strip()
    if not description:
        await message.answer(localize('admin.translations.invalid'), reply_markup=back('goods_management'))
        return
    if len(description) > MAX_DESCRIPTION_LEN:
        await message.answer(localize('admin.translations.too_long', max=MAX_DESCRIPTION_LEN),
                             reply_markup=back('goods_management'))
        return
    languages = wizard_languages(await admin_language(message.from_user.id))
    await state.update_data(item_desc_lang=languages[0], item_descriptions={languages[0]: description},
                            item_desc_queue=languages[1:])
    await _next_description_translation(message, state)


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
    category_name = await resolve_category_name(message.text)
    if not category_name:
        await message.answer(
            localize('admin.goods.add.category.not_found'),
            reply_markup=back('goods_management')
        )
        return
    if not await category_accepts_items(category_name):
        await message.answer(
            localize('admin.goods.add.category.has_subcategories'),
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
    names = dict(data.get('item_names') or {})
    descriptions = dict(data.get('item_descriptions') or {})
    # Canonical (lookup-key) text: the main-language (BOT_LOCALE) text if entered, else the admin's own
    # language, else the first filled. Every entered language is stored as ``name_<lang>`` /
    # ``description_<lang>``, so ``name_<main>`` is set only when the canonical IS the main-language text
    # and stays NULL otherwise.
    item_name = derive_canonical(names, main_language(), data.get('item_name_lang'))
    item_description = derive_canonical(descriptions, main_language(), data.get('item_desc_lang')) or ''
    stock = data.get('item_stock') or 0
    translated = set(names) | set(descriptions)

    await create_item(item_name, item_description, data.get('item_price'),
                      data.get('item_category'), stock=stock,
                      names=names or None, descriptions=descriptions or None)

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
                    details=f"admin={admin_name}, stock={stock}, photo={'yes' if photo_ok else 'no'}, "
                            f"translations={','.join(sorted(translated)) or '-'}")

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
