from decimal import Decimal

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from bot.database.methods.create import add_to_cart, CART_MAX_QTY_PER_ITEM
from bot.database.methods.read import get_cart_items, validate_promos_for_cart, select_item_stock
from bot.database.methods.update import set_cart_item_quantity, clear_cart_item_promo
from bot.database.methods.delete import remove_from_cart, clear_cart
from bot.keyboards.inline import back, cart_keyboard
from bot.database.methods.pricing import apply_promo_discount
from bot.misc import EnvKeys
from bot.i18n import localize, esc
from bot.misc.localized import pick
from bot.database.methods.translations import item_labels
from bot.handlers.user._screen import edit_screen

router = Router()


async def _cart_view_data(user_id: int) -> tuple[list[dict], dict[str, dict], dict[int, dict], Decimal]:
    """Load everything a cart render or total needs in three queries total.

    Returns (items, info_map, line_data, total); line_data maps cart line id to
    {'line_total', 'discounted', 'eligible', 'on_sale', 'original'} using the
    same clamped math *and the same one-promo-one-line rule* as
    create_order_transaction, so the displayed total matches what is charged.
    ``eligible`` marks a line whose promo is valid but was spent on another line.
    Lines whose item no longer exists are absent from line_data.
    """
    items = await get_cart_items(user_id)
    if not items:
        return [], {}, {}, Decimal(0)

    from bot.database.methods.read import get_items_info
    from bot.database.methods import effective_price
    info_map = await get_items_info([item['item_name'] for item in items])
    promo_results = await validate_promos_for_cart(user_id, items, info_map)

    line_data: dict[int, dict] = {}
    # promo id -> cart line ids it validly applies to
    promo_lines: dict[int, list[int]] = {}

    for item in items:
        info = info_map.get(item['item_name'])
        if not info:
            continue
        qty = item['quantity']
        base_price, on_sale, original = effective_price(info)

        promo = None
        res = promo_results.get(item['id'])
        if res is not None and res[0]:
            promo = res[2]
            promo_lines.setdefault(promo['id'], []).append(item['id'])

        line_data[item['id']] = {
            'line_total': (base_price * qty).quantize(Decimal("0.01")),
            'discounted': None,
            'eligible': promo is not None,
            'on_sale': on_sale,
            'original': original,
            'promo': promo,
            'qty': qty,
            'unit_price': base_price,
        }

    for line_ids in promo_lines.values():
        best_id = max(line_ids, key=lambda lid: (line_data[lid]['line_total'], -lid))
        ld = line_data[best_id]
        ld['discounted'] = apply_promo_discount(
            ld['unit_price'], ld['promo']['discount_type'], ld['promo']['discount_value'], ld['qty'],
        )
        ld['line_total'] = ld['discounted']

    total = sum((ld['line_total'] for ld in line_data.values()), Decimal(0))
    return items, info_map, line_data, total


async def _show_cart(call: CallbackQuery | Message):
    """Shared logic: render cart view (edits the pressed message, or answers a new one for a Message)."""
    user_id = call.from_user.id
    items, info_map, line_data, real_total = await _cart_view_data(user_id)

    if not items:
        await edit_screen(
            call,
            localize("cart.title") + "\n\n" + localize("cart.empty"),
            reply_markup=back("profile"),
        )
        return

    lines = [localize("cart.title"), ""]

    for item in items:
        qty = item['quantity']
        name = esc(pick(item, 'name'))
        code = esc(item.get('promo_code'))
        ld = line_data.get(item['id'])
        if ld is None:
            lines.append(localize(
                "cart.item", name=name, qty=qty,
                price='?', currency=EnvKeys.PAY_CURRENCY,
            ))
            continue

        # Sale price is the base; a promo code (if any) stacks on top of it.
        line_total, original = ld['line_total'], ld['original']

        if ld['discounted'] is not None:
            lines.append(localize(
                "cart.item_promo", name=name, qty=qty,
                original=(original * qty).quantize(Decimal("0.01")), price=line_total,
                currency=EnvKeys.PAY_CURRENCY, code=code,
            ))
        elif ld['eligible']:
            # Valid code, but its single redemption went to another line.
            lines.append(localize(
                "cart.item_promo_elsewhere", name=name, qty=qty,
                price=line_total, currency=EnvKeys.PAY_CURRENCY,
                code=code,
            ))
        elif item.get('promo_code'):
            lines.append(localize(
                "cart.item_promo_invalid", name=name, qty=qty,
                price=line_total, currency=EnvKeys.PAY_CURRENCY,
                code=code,
            ))
        elif ld['on_sale']:
            lines.append(localize(
                "cart.item_sale", name=name, qty=qty,
                original=(original * qty).quantize(Decimal("0.01")), price=line_total,
                currency=EnvKeys.PAY_CURRENCY,
            ))
        else:
            lines.append(localize(
                "cart.item", name=name, qty=qty,
                price=line_total, currency=EnvKeys.PAY_CURRENCY,
            ))

        info = info_map.get(item['item_name'])
        if info is not None and info['stock'] < qty:
            lines.append(localize("cart.low_stock", available=info['stock']))

    lines.append(localize("cart.total", total=real_total, currency=EnvKeys.PAY_CURRENCY))

    try:
        await edit_screen(
            call,
            "\n".join(lines),
            reply_markup=cart_keyboard(items),
            parse_mode="HTML",
        )
    except TelegramBadRequest as e:
        # Stepping quantity up then back down re-renders an identical message.
        if "message is not modified" not in str(e):
            raise


async def _display_name(item_name: str) -> str:
    """The product's name in the viewer's language (canonical if untranslated)."""
    return (await item_labels([item_name])).get(item_name, item_name)


async def _add_selected_item(call: CallbackQuery, state: FSMContext) -> bool:
    """Put the item on screen into the cart, never beyond what is in stock.

    Answers the callback itself on failure; on success the caller answers.
    """
    data = await state.get_data()
    item_name = data.get('csrf_item')
    if not item_name:
        await call.answer(localize("cart.item_not_found"), show_alert=True)
        return False

    stock = await select_item_stock(item_name)
    if stock <= 0:
        await call.answer(localize("cart.item_out_of_stock", name=await _display_name(item_name)), show_alert=True)
        return False

    in_cart = next(
        (i['quantity'] for i in await get_cart_items(call.from_user.id) if i['item_name'] == item_name), 0
    )
    if in_cart + 1 > stock:
        await call.answer(localize("cart.stock_limit", available=stock), show_alert=True)
        return False

    success, msg = await add_to_cart(call.from_user.id, item_name, promo_code=data.get('applied_promo'))
    if not success:
        error_map = {
            "cart_full": localize("cart.full"),
            "item_not_found": localize("cart.item_not_found"),
            "cart_qty_max": localize("cart.qty_max", max=CART_MAX_QTY_PER_ITEM),
            "cart_conflict": localize("errors.something_wrong"),
            "invalid_quantity": localize("errors.something_wrong"),
        }
        await call.answer(error_map.get(msg, msg), show_alert=True)
    return success


@router.callback_query(F.data == "add_to_cart")
async def add_to_cart_handler(call: CallbackQuery, state: FSMContext):
    if await _add_selected_item(call, state):
        item_name = (await state.get_data()).get('csrf_item')
        await call.answer(localize("cart.added", name=await _display_name(item_name)))


@router.callback_query(F.data == "buy_item")
async def buy_item_handler(call: CallbackQuery, state: FSMContext):
    """"Order now": add the item and jump straight to the cart."""
    if await _add_selected_item(call, state):
        await call.answer()
        await _show_cart(call)


@router.callback_query(F.data.startswith("cart_qty:"))
async def cart_qty_handler(call: CallbackQuery, state: FSMContext):
    """Step a cart line's quantity up or down. Format: cart_qty:{id}:{delta}"""
    try:
        parts = call.data.split(":")
        cart_item_id = int(parts[1])
        delta = int(parts[2])
    except (ValueError, IndexError):
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return

    if delta > 0:
        line = next((i for i in await get_cart_items(call.from_user.id) if i['id'] == cart_item_id), None)
        if line is not None:
            stock = await select_item_stock(line['item_name'])
            if line['quantity'] + delta > stock:
                await call.answer(localize("cart.stock_limit", available=stock), show_alert=True)
                await _show_cart(call)
                return

    ok, code, _new_qty = await set_cart_item_quantity(cart_item_id, call.from_user.id, delta)
    if not ok:
        error_map = {
            "item_not_found": localize("cart.item_not_found"),
            "cart_qty_max": localize("cart.qty_max", max=CART_MAX_QTY_PER_ITEM),
        }
        await call.answer(error_map.get(code, code), show_alert=True)
    elif code == "removed":
        await call.answer(localize("cart.removed"))
    else:
        await call.answer()

    await _show_cart(call)


@router.callback_query(F.data == "cart")
async def view_cart_handler(call: CallbackQuery, state: FSMContext):
    await _show_cart(call)


@router.callback_query(F.data.startswith("cart_remove:"))
async def remove_cart_item_handler(call: CallbackQuery, state: FSMContext):
    try:
        cart_item_id = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    removed = await remove_from_cart(cart_item_id, user_id=call.from_user.id)
    if removed:
        await call.answer(localize("cart.removed"))
    else:
        await call.answer(localize("cart.item_not_found"), show_alert=True)
    await _show_cart(call)


@router.callback_query(F.data.startswith("cart_unpromo:"))
async def cart_remove_promo_handler(call: CallbackQuery, state: FSMContext):
    """Drop the promo code from one cart line. Format: cart_unpromo:{id}"""
    try:
        cart_item_id = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return

    if await clear_cart_item_promo(cart_item_id, call.from_user.id):
        await call.answer(localize("promo.removed"))
    else:
        await call.answer(localize("cart.item_not_found"), show_alert=True)
    await _show_cart(call)


@router.callback_query(F.data == "cart_clear")
async def clear_cart_handler(call: CallbackQuery, state: FSMContext):
    await clear_cart(call.from_user.id)
    await call.answer(localize("cart.cleared"))
    await _show_cart(call)
