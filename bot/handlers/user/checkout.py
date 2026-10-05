from decimal import Decimal, InvalidOperation

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery, Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)
from aiogram.fsm.context import FSMContext

from bot.database.methods.audit import log_audit_bg
from bot.database.methods.orders import (
    create_order_transaction, get_order, mark_mia_paid,
    available_fulfillments, available_payment_methods,
)
from bot.database.methods.read import check_user
from bot.database.methods.shipping import active_methods, delivery_fee, get_active_method
from bot.database.models.main import Fulfillment, PaymentMethod, PaymentStatus, OrderStatus
from bot.handlers.user.cart import _cart_view_data, _show_cart
from bot.keyboards.inline import (
    checkout_fulfillment_keyboard, checkout_shipping_keyboard, checkout_name_keyboard, checkout_cancel_keyboard, checkout_comment_keyboard,
    checkout_payment_keyboard, checkout_confirm_keyboard, mia_keyboard, simple_buttons, back,
)
from bot.logger_mesh import logger
from bot.misc import (
    EnvKeys, validate_customer_name, validate_phone, clean_text, ADDRESS_MAX_LEN, COMMENT_MAX_LEN,
)
from bot.misc.metrics import get_metrics
from bot.misc.services.order_view import format_order, method_label, delivery_lines, notify_new_order, notify_mia_claim, fmt_dt
from bot.i18n import localize, esc
from bot.misc.localized import pick
from bot.database.methods.translations import item_labels
from bot.states import CheckoutFSM

router = Router()


async def _show(msg: Message, text: str, markup=None, edit: bool = True) -> None:
    """Render a checkout screen: edit the bot's message after a button press, send a new one after typed input."""
    if edit:
        await msg.edit_text(text, reply_markup=markup)
    else:
        await msg.answer(text, reply_markup=markup)


def _money(raw) -> Decimal:
    return Decimal(str(raw)).quantize(Decimal("0.01"))


def _order_id(data: str) -> int | None:
    try:
        return int(data.split(":")[1])
    except (ValueError, IndexError):
        return None


def mia_instructions(order: dict) -> str:
    """Where and how much to pay for an MIA order, with the reference the shop will look for."""
    cur = EnvKeys.PAY_CURRENCY
    due = _money(order["total"]) - _money(order["balance_used"])
    lines = [localize("mia.title", id=order["id"]), "", localize("mia.amount", amount=due, currency=cur)]
    if EnvKeys.MIA_RECIPIENT:
        lines.append(localize("mia.recipient", recipient=esc(EnvKeys.MIA_RECIPIENT)))
    if EnvKeys.MIA_PHONE:
        lines.append(localize("mia.phone", phone=esc(EnvKeys.MIA_PHONE)))
    if EnvKeys.MIA_IBAN:
        lines.append(localize("mia.iban", iban=esc(EnvKeys.MIA_IBAN)))
    lines.append(localize("mia.reference", id=order["id"]))
    if order.get("pay_by"):
        lines.append("")
        lines.append(localize("mia.pay_by", dt=fmt_dt(order["pay_by"])))
    lines.append(localize("mia.after"))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Steps. Each takes the message to render on and whether to edit it (button press) or answer (typed input).
# --------------------------------------------------------------------------- #

async def _expired(msg: Message, state: FSMContext, edit: bool = True) -> None:
    """The FSM data is gone or the cart was emptied: send the customer back to the cart."""
    await state.clear()
    await _show(msg, localize("checkout.session_expired"), back("cart"), edit)


async def _ask_fulfillment(msg: Message, state: FSMContext, edit: bool = True) -> None:
    kinds = available_fulfillments()
    await state.set_state(CheckoutFSM.choosing_fulfillment)
    await _show(msg, localize("checkout.fulfillment_prompt"), checkout_fulfillment_keyboard(kinds), edit)


async def _ask_name(msg: Message, state: FSMContext, first_name: str | None, edit: bool = True) -> None:
    await state.set_state(CheckoutFSM.waiting_name)
    await _show(
        msg, localize("checkout.name_prompt"),
        checkout_name_keyboard((first_name or "").strip()[:60] or None), edit,
    )


async def _ask_phone(msg: Message, state: FSMContext) -> None:
    """Always a new message: the contact-share button is a reply keyboard, which an edit cannot carry."""
    await state.set_state(CheckoutFSM.waiting_phone)
    share = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=localize("btn.checkout.share_phone"), request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )
    await msg.answer(localize("checkout.phone_prompt"), reply_markup=share)


async def _ask_address(msg: Message, state: FSMContext, edit: bool = False) -> None:
    await state.set_state(CheckoutFSM.waiting_address)
    text = localize("checkout.address_prompt")
    if EnvKeys.DELIVERY_INFO:
        text += "\n\n" + localize("checkout.delivery_info", info=esc(EnvKeys.DELIVERY_INFO))
    await _show(msg, text, checkout_cancel_keyboard(), edit)


async def _after_address(msg: Message, state: FSMContext, user_id: int, edit: bool = False) -> None:
    """Delivery: let the customer pick one of the shop's shipping methods (a single one is taken as is)."""
    methods = await active_methods()
    if not methods:
        await _ask_comment(msg, state, edit)
        return
    if len(methods) == 1:
        await _apply_shipping(state, user_id, methods[0])
        await _ask_comment(msg, state, edit)
        return
    _items, _info, _lines, goods_total = await _cart_view_data(user_id)
    await state.set_state(CheckoutFSM.choosing_shipping)
    await _show(msg, localize("checkout.shipping_prompt"),
                checkout_shipping_keyboard(methods, goods_total, EnvKeys.PAY_CURRENCY), edit)


async def _apply_shipping(state: FSMContext, user_id: int, method: dict) -> None:
    """Remember the chosen method and fold its price into the total the rest of the checkout works with."""
    _items, _info, _lines, goods_total = await _cart_view_data(user_id)
    fee = delivery_fee(method, goods_total)
    await state.update_data(co_ship=method["id"], co_total=str(goods_total + fee))


async def _ask_comment(msg: Message, state: FSMContext, edit: bool = False) -> None:
    await state.set_state(CheckoutFSM.waiting_comment)
    await _show(msg, localize("checkout.comment_prompt"), checkout_comment_keyboard(), edit)


async def _balance_of(user_id: int) -> Decimal:
    user = await check_user(user_id)
    return _money(user["balance"]) if user and user.get("balance") else Decimal("0.00")


async def _ask_payment(msg: Message, state: FSMContext, user_id: int, edit: bool = True) -> None:
    data = await state.get_data()
    try:
        total = _money(data["co_total"])
    except (KeyError, InvalidOperation):
        await _expired(msg, state, edit)
        return

    balance = await _balance_of(user_id)
    use_balance = bool(data.get("co_use_balance")) and balance > 0
    covered = use_balance and balance >= total
    methods = [] if covered else available_payment_methods()

    cur = EnvKeys.PAY_CURRENCY
    lines = [localize("checkout.payment_prompt", total=total, currency=cur)]
    if use_balance:
        applied = min(balance, total)
        lines.append(localize("checkout.payment_balance_applied", amount=applied, currency=cur))
        if not covered:
            lines.append(localize("checkout.payment_due", amount=total - applied, currency=cur))
    if not covered and not methods:
        lines.append(localize("checkout.payment_none"))

    await state.set_state(CheckoutFSM.choosing_payment)
    markup = checkout_payment_keyboard(
        methods, data.get("co_ful"), balance=balance, use_balance=use_balance, covered=covered,
    )
    await _show(msg, "\n".join(lines), markup, edit)


async def _ask_summary(msg: Message, state: FSMContext, user_id: int, edit: bool = True) -> None:
    """Final review. Recomputes the total from the live cart, so what is confirmed is what is charged."""
    data = await state.get_data()
    items, _info, line_data, total = await _cart_view_data(user_id)
    if not items or not line_data or not all(data.get(k) for k in ("co_ful", "co_name", "co_phone")):
        await _expired(msg, state, edit)
        return

    # Delivery with shipping methods: the chosen method's price joins the total (recomputed from the live cart).
    shipping = None
    fee = Decimal("0.00")
    if data["co_ful"] == Fulfillment.DELIVERY and await active_methods():
        shipping = await get_active_method(int(data["co_ship"])) if data.get("co_ship") else None
        if shipping is None:                      # none chosen yet, or the chosen one was switched off meanwhile
            await _after_address(msg, state, user_id, edit)
            return
        fee = delivery_fee(shipping, total)
    total = total + fee

    balance = await _balance_of(user_id)
    applied = min(balance, total) if data.get("co_use_balance") and balance > 0 else Decimal("0.00")
    due = total - applied
    method = data.get("co_method")
    if due > 0 and method not in available_payment_methods():
        await _ask_payment(msg, state, user_id, edit)
        return

    cur = EnvKeys.PAY_CURRENCY
    fake_order = {"payment_method": method if due > 0 else PaymentMethod.BALANCE, "fulfillment": data["co_ful"]}
    lines = [localize("checkout.summary.title"), ""]
    for item in items:
        ld = line_data.get(item["id"])
        if ld is None:
            continue
        lines.append(localize(
            "order.line.item", name=esc(pick(item, "name")), qty=item["quantity"],
            total=ld["line_total"], currency=cur,
        ))
    lines.append("")
    lines.extend(delivery_lines({"shipping_name": shipping["name"] if shipping else None, "delivery_fee": fee}, cur))
    lines.append(localize("order.line.total", total=total, currency=cur))
    if applied > 0:
        lines.append(localize("order.line.balance_used", amount=applied, currency=cur))
        lines.append(localize("order.line.due", amount=due, currency=cur))
    lines.append(localize("checkout.summary.payment", method=method_label(fake_order)))
    lines.append(localize("order.line.fulfillment", fulfillment=localize(f"order.fulfillment.{data['co_ful']}")))
    lines.append(localize("order.line.contact", name=esc(data["co_name"]), phone=esc(data["co_phone"])))
    if data.get("co_address"):
        lines.append(localize("order.line.address", address=esc(data["co_address"])))
    if data.get("co_comment"):
        lines.append(localize("order.line.comment", comment=esc(data["co_comment"])))
    if data["co_ful"] == Fulfillment.PICKUP and EnvKeys.PICKUP_ADDRESS:
        lines.append(localize("checkout.pickup_info", address=esc(EnvKeys.PICKUP_ADDRESS)))

    await state.update_data(co_total=str(total))
    await state.set_state(CheckoutFSM.confirming)
    await _show(msg, "\n".join(lines), checkout_confirm_keyboard(), edit)


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #

@router.callback_query(F.data == "cart_checkout")
async def cart_checkout_handler(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    items, _info, line_data, total = await _cart_view_data(user_id)
    if not items or not line_data:
        await call.answer(localize("cart.empty"), show_alert=True)
        await _show_cart(call)
        return
    if not available_fulfillments() or not available_payment_methods():
        await call.answer(localize("checkout.unavailable"), show_alert=True)
        return

    await call.answer()
    await state.clear()
    await state.update_data(co_total=str(total), co_use_balance=False)

    kinds = available_fulfillments()
    if len(kinds) == 1:
        await state.update_data(co_ful=kinds[0])
        await _ask_name(call.message, state, call.from_user.first_name)
        return
    await _ask_fulfillment(call.message, state)


@router.callback_query(F.data == "co_cancel")
async def checkout_cancel_handler(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await _show_cart(call)


# --------------------------------------------------------------------------- #
# Fulfilment -> name -> phone -> address -> comment
# --------------------------------------------------------------------------- #

@router.callback_query(F.data.startswith("co_ful:"), CheckoutFSM.choosing_fulfillment)
async def fulfillment_chosen_handler(call: CallbackQuery, state: FSMContext):
    kind = call.data.split(":", 1)[1]
    if kind not in available_fulfillments():
        await call.answer(localize("checkout.fail.invalid_fulfillment"), show_alert=True)
        return
    await call.answer()
    await state.update_data(co_ful=kind)
    await _ask_name(call.message, state, call.from_user.first_name)


async def _name_given(msg: Message, state: FSMContext, name: str, edit: bool) -> None:
    await state.update_data(co_name=name)
    if edit:
        # Lock in the answer: the keyboard under the prompt goes away.
        await msg.edit_text(localize("checkout.name_saved", name=esc(name)))
    await _ask_phone(msg, state)


@router.callback_query(F.data == "co_name_tg", CheckoutFSM.waiting_name)
async def name_from_telegram_handler(call: CallbackQuery, state: FSMContext):
    try:
        name = validate_customer_name(call.from_user.first_name)
    except ValueError:
        await call.answer(localize("checkout.name_invalid"), show_alert=True)
        return
    await call.answer()
    await _name_given(call.message, state, name, edit=True)


@router.message(CheckoutFSM.waiting_name, F.text)
async def name_text_handler(message: Message, state: FSMContext):
    try:
        name = validate_customer_name(message.text)
    except ValueError:
        await message.answer(localize("checkout.name_invalid"), reply_markup=checkout_cancel_keyboard())
        return
    await _name_given(message, state, name, edit=False)


async def _phone_given(message: Message, state: FSMContext, phone: str) -> None:
    await state.update_data(co_phone=phone)
    # Also takes the contact-share keyboard off the screen.
    await message.answer(localize("checkout.phone_saved", phone=esc(phone)), reply_markup=ReplyKeyboardRemove())
    if (await state.get_data()).get("co_ful") == Fulfillment.DELIVERY:
        await _ask_address(message, state)
    else:
        await _ask_comment(message, state)


@router.message(CheckoutFSM.waiting_phone, F.contact)
async def phone_contact_handler(message: Message, state: FSMContext):
    raw = message.contact.phone_number or ""
    if raw and not raw.startswith("+") and raw.isdigit():
        raw = "+" + raw
    try:
        phone = validate_phone(raw)
    except ValueError:
        await message.answer(localize("checkout.phone_invalid"))
        return
    await _phone_given(message, state, phone)


@router.message(CheckoutFSM.waiting_phone, F.text)
async def phone_text_handler(message: Message, state: FSMContext):
    try:
        phone = validate_phone(message.text)
    except ValueError:
        await message.answer(localize("checkout.phone_invalid"))
        return
    await _phone_given(message, state, phone)


@router.message(CheckoutFSM.waiting_address, F.text)
async def address_handler(message: Message, state: FSMContext):
    try:
        address = clean_text(message.text, ADDRESS_MAX_LEN)
    except ValueError:
        await message.answer(
            localize("checkout.address_invalid", max=ADDRESS_MAX_LEN), reply_markup=checkout_cancel_keyboard(),
        )
        return
    await state.update_data(co_address=address)
    await _after_address(message, state, message.from_user.id)


@router.callback_query(F.data.startswith("co_ship:"), CheckoutFSM.choosing_shipping)
async def shipping_chosen_handler(call: CallbackQuery, state: FSMContext):
    try:
        method = await get_active_method(int(call.data.split(":", 1)[1]))
    except ValueError:
        method = None
    if method is None:
        await call.answer(localize("checkout.fail.invalid_shipping"), show_alert=True)
        await _after_address(call.message, state, call.from_user.id, edit=True)
        return
    await call.answer()
    await _apply_shipping(state, call.from_user.id, method)
    await _ask_comment(call.message, state, edit=True)


async def _comment_done(msg: Message, state: FSMContext, user_id: int, edit: bool) -> None:
    await state.update_data(co_method=None)
    await _ask_payment(msg, state, user_id, edit)


@router.message(CheckoutFSM.waiting_comment, F.text)
async def comment_handler(message: Message, state: FSMContext):
    try:
        comment = clean_text(message.text, COMMENT_MAX_LEN)
    except ValueError:
        await message.answer(
            localize("checkout.comment_invalid", max=COMMENT_MAX_LEN), reply_markup=checkout_comment_keyboard(),
        )
        return
    await state.update_data(co_comment=comment)
    await _comment_done(message, state, message.from_user.id, edit=False)


@router.callback_query(F.data == "co_skip_comment", CheckoutFSM.waiting_comment)
async def skip_comment_handler(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(co_comment=None)
    await _comment_done(call.message, state, call.from_user.id, edit=True)


# --------------------------------------------------------------------------- #
# Payment method, summary, placing the order
# --------------------------------------------------------------------------- #

@router.callback_query(F.data == "co_balance", CheckoutFSM.choosing_payment)
async def toggle_balance_handler(call: CallbackQuery, state: FSMContext):
    if await _balance_of(call.from_user.id) <= 0:
        await call.answer(localize("checkout.no_balance"), show_alert=True)
        return
    await call.answer()
    data = await state.get_data()
    await state.update_data(co_use_balance=not data.get("co_use_balance"))
    await _ask_payment(call.message, state, call.from_user.id)


@router.callback_query(F.data.startswith("co_pay:"), CheckoutFSM.choosing_payment)
async def payment_chosen_handler(call: CallbackQuery, state: FSMContext):
    method = call.data.split(":", 1)[1]
    data = await state.get_data()

    if method == "balance":
        # Only valid when the balance really covers the total; otherwise a stale button.
        try:
            total = _money(data["co_total"])
        except (KeyError, InvalidOperation):
            await call.answer(localize("checkout.session_expired"), show_alert=True)
            return
        if not data.get("co_use_balance") or await _balance_of(call.from_user.id) < total:
            await call.answer(localize("checkout.fail.invalid_payment_method"), show_alert=True)
            await _ask_payment(call.message, state, call.from_user.id)
            return
        method = None
    elif method not in available_payment_methods():
        await call.answer(localize("checkout.fail.invalid_payment_method"), show_alert=True)
        return

    await call.answer()
    await state.update_data(co_method=method)
    await _ask_summary(call.message, state, call.from_user.id)


@router.callback_query(F.data == "co_to_payment", CheckoutFSM.confirming)
async def back_to_payment_handler(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await _ask_payment(call.message, state, call.from_user.id)


async def _fail_text(code: str, data: dict | None) -> str:
    if code == "out_of_stock":
        data = data or {}
        raw = data.get("item_name", "")
        shown = (await item_labels([raw])).get(raw, raw) if raw else raw   # in the buyer's language
        return localize("checkout.fail.out_of_stock", name=esc(shown), available=data.get("available", 0))
    known = {
        "cart_empty": "cart.empty",
        "cart_items_unavailable": "cart.items_unavailable",
        "price_changed": "cart.price_changed",
        "invalid_payment_method": "checkout.fail.invalid_payment_method",
        "invalid_fulfillment": "checkout.fail.invalid_fulfillment",
        "address_required": "checkout.fail.address_required",
        "shipping_required": "checkout.fail.shipping_required",
        "invalid_shipping": "checkout.fail.invalid_shipping",
        "user_not_found": "checkout.fail.user_not_found",
    }
    return localize(known.get(code, "errors.something_wrong"))


@router.callback_query(F.data == "co_confirm", CheckoutFSM.confirming)
async def confirm_order_handler(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    data = await state.get_data()
    if not all(data.get(k) for k in ("co_ful", "co_name", "co_phone", "co_total")):
        await call.answer(localize("checkout.session_expired"), show_alert=True)
        await _expired(call.message, state)
        return

    await call.answer(localize("checkout.processing"))
    # A fully balance-covered order needs no method; the transaction ignores it then.
    method = data.get("co_method") or PaymentMethod.COD

    success, code, order = await create_order_transaction(
        user_id,
        fulfillment=data["co_ful"],
        customer_name=data["co_name"],
        phone=data["co_phone"],
        address=data.get("co_address"),
        comment=data.get("co_comment"),
        payment_method=method,
        use_balance=bool(data.get("co_use_balance")),
        expected_total=_money(data["co_total"]),
        shipping_method_id=data.get("co_ship"),
    )

    if not success:
        await state.clear()
        await call.message.edit_text(
            localize("checkout.fail", reason=await _fail_text(code, order)), reply_markup=back("cart"),
        )
        return

    await state.clear()

    metrics = get_metrics()
    if metrics:
        metrics.track_conversion("purchase_funnel", "order_placed", user_id)
    log_audit_bg(
        "order_created", user_id=user_id, resource_type="Order", resource_id=str(order["id"]),
        details=f"total={order['total']}, method={order['payment_method']}",
    )
    try:
        await notify_new_order(call.bot, order)
    except Exception as e:  # the order is placed; a failed staff alert must not undo the customer's confirmation
        logger.error(f"New-order alert for order {order['id']} failed: {e}")

    if order["payment_method"] == PaymentMethod.MIA:
        await call.message.edit_text(mia_instructions(order), reply_markup=mia_keyboard(order["id"]))
        return

    text = localize("checkout.placed", id=order["id"]) + "\n\n" + format_order(order)
    if order["fulfillment"] == Fulfillment.PICKUP and EnvKeys.PICKUP_ADDRESS:
        text += "\n" + localize("checkout.pickup_info", address=esc(EnvKeys.PICKUP_ADDRESS))
    text += "\n\n" + localize("checkout.placed_footer")
    await call.message.edit_text(text, reply_markup=simple_buttons([
        (localize("btn.order.open"), f"my_order:{order['id']}"),
        (localize("btn.to_menu"), "back_to_menu"),
    ]))


@router.callback_query(F.data.startswith("co_"))
async def stale_checkout_button_handler(call: CallbackQuery):
    """A checkout button pressed after its FSM state is gone (restart, cart emptied, double tap)."""
    await call.answer(localize("checkout.session_expired"), show_alert=True)


# --------------------------------------------------------------------------- #
# MIA: payment details and the "I've paid" claim
# --------------------------------------------------------------------------- #

def _awaiting_mia_payment(order: dict | None) -> bool:
    return bool(
        order
        and order["payment_method"] == PaymentMethod.MIA
        and order["status"] == OrderStatus.NEW
        and order["payment_status"] == PaymentStatus.AWAITING_PAYMENT
    )


@router.callback_query(F.data.startswith("mia_info:"))
async def mia_info_handler(call: CallbackQuery):
    """Show the payment instructions again. Format: mia_info:{order_id}"""
    order_id = _order_id(call.data)
    order = await get_order(order_id, user_id=call.from_user.id) if order_id is not None else None
    if not _awaiting_mia_payment(order):
        await call.answer(localize("mia.not_awaiting"), show_alert=True)
        return
    await call.answer()
    await call.message.edit_text(mia_instructions(order), reply_markup=mia_keyboard(order["id"]))


@router.callback_query(F.data.startswith("mia_paid:"))
async def mia_paid_handler(call: CallbackQuery, state: FSMContext):
    """"I've paid": ask for an optional screenshot. Format: mia_paid:{order_id}"""
    order_id = _order_id(call.data)
    order = await get_order(order_id, user_id=call.from_user.id) if order_id is not None else None
    if not _awaiting_mia_payment(order):
        await call.answer(localize("mia.not_awaiting"), show_alert=True)
        return
    await call.answer()
    await state.clear()
    await state.set_state(CheckoutFSM.waiting_proof)
    await state.update_data(proof_order_id=order["id"])
    await call.message.edit_text(
        localize("mia.proof_prompt"),
        reply_markup=simple_buttons([
            (localize("btn.mia.skip_proof"), f"mia_skip:{order['id']}"),
            (localize("btn.back"), f"mia_info:{order['id']}"),
        ]),
    )


async def _claim_payment(bot, user_id: int, order_id: int, proof_file_id: str | None) -> str:
    """Record the customer's claim and alert staff. Returns the localized reply."""
    ok, code, order = await mark_mia_paid(order_id, user_id, proof_file_id)
    if not ok:
        return localize("mia.not_awaiting" if code in ("not_awaiting_payment", "not_mia", "order_not_found")
                        else "errors.something_wrong")
    try:
        await notify_mia_claim(bot, order)
    except Exception as e:
        logger.error(f"MIA claim alert for order {order_id} failed: {e}")
    return localize("mia.claim_sent", id=order_id)


def _after_claim_keyboard(order_id: int):
    return simple_buttons([
        (localize("btn.order.open"), f"my_order:{order_id}"),
        (localize("btn.my_orders"), "my_orders"),
    ])


@router.callback_query(F.data.startswith("mia_skip:"))
async def mia_skip_proof_handler(call: CallbackQuery, state: FSMContext):
    """Claim the payment without a screenshot. Format: mia_skip:{order_id}"""
    order_id = _order_id(call.data)
    if order_id is None:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    await call.answer()
    await state.clear()
    text = await _claim_payment(call.bot, call.from_user.id, order_id, None)
    await call.message.edit_text(text, reply_markup=_after_claim_keyboard(order_id))


@router.message(CheckoutFSM.waiting_proof, F.photo)
async def mia_proof_photo_handler(message: Message, state: FSMContext):
    order_id = (await state.get_data()).get("proof_order_id")
    await state.clear()
    if order_id is None:
        await message.answer(localize("checkout.session_expired"), reply_markup=back("my_orders"))
        return
    text = await _claim_payment(message.bot, message.from_user.id, order_id, message.photo[-1].file_id)
    await message.answer(text, reply_markup=_after_claim_keyboard(order_id))


@router.message(CheckoutFSM.waiting_proof)
async def mia_proof_other_handler(message: Message, state: FSMContext):
    order_id = (await state.get_data()).get("proof_order_id")
    if order_id is None:
        await state.clear()
        await message.answer(localize("checkout.session_expired"), reply_markup=back("my_orders"))
        return
    await message.answer(
        localize("mia.proof_only_photo"),
        reply_markup=simple_buttons([(localize("btn.mia.skip_proof"), f"mia_skip:{order_id}")]),
    )
