from decimal import Decimal
from functools import partial

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.database.models import Permission
from bot.database.models.main import PaymentStatus
from bot.database.methods.audit import log_audit
from bot.database.methods.lazy_queries import query_orders
from bot.database.methods.orders import (
    get_order, set_order_status, cancel_order_transaction, confirm_mia_payment, reject_mia_payment,
)
from bot.filters import HasPermissionFilter
from bot.handlers.admin._common import _notify_restock_safe
from bot.handlers.other import caller_name
from bot.i18n import localize
from bot.keyboards.inline import back, lazy_paginated_keyboard
from bot.keyboards.orders_admin import (
    ORDER_LISTS, STATUS_CODES, ctx_suffix, parse_ctx, orders_menu_keyboard, order_card_keyboard,
    cancel_confirm_keyboard,
)
from bot.misc import EnvKeys, LazyPaginator
from bot.misc.services.order_view import format_order, notify_customer
from bot.states import OrdersAdminFSM

router = Router()

_PERM = Permission.ORDERS_MANAGE
_PAGE_SIZE = 10

# Failure codes from the order layer -> localization keys.
_ERRORS = {
    "order_not_found": "admin.orders.err.not_found",
    "not_mia": "admin.orders.err.not_mia",
    "not_awaiting_payment": "admin.orders.err.not_awaiting_payment",
    "invalid_transition": "admin.orders.err.invalid_transition",
    "invalid_status": "admin.orders.err.invalid_transition",
    "payment_not_confirmed": "admin.orders.err.payment_not_confirmed",
    "not_cancellable": "admin.orders.err.not_cancellable",
}

# The customer notice sent for each status the admin can set.
_STATUS_NOTICE = {"confirmed": "confirmed", "shipped": "shipped", "completed": "completed"}


async def _render(call: CallbackQuery, text: str, markup) -> None:
    """Edit the message in place; a staff alert with a screenshot is a photo, which has no text to edit."""
    try:
        await call.message.edit_text(text, parse_mode='HTML', reply_markup=markup)
    except TelegramBadRequest as e:
        if 'not modified' in str(e).lower():
            return
        await call.message.answer(text, parse_mode='HTML', reply_markup=markup)


def _error_text(code: str) -> str:
    return localize(_ERRORS.get(code, "errors.something_wrong"))


async def _show_order(call: CallbackQuery, order_id: int, key: str = "", page: int = 0, note: str = "") -> None:
    """Draw the order card with the actions for its state (``note`` goes above it)."""
    order = await get_order(order_id)
    if not order:
        await call.answer(localize("admin.orders.err.not_found"), show_alert=True)
        return
    text = format_order(order, admin=True)
    if note:
        text = f"{note}\n\n{text}"
    await _render(call, text, order_card_keyboard(order, key, page))


def _order_button(order) -> str:
    """One line of an order list."""
    mark = "🔔 " if order.payment_status == PaymentStatus.AWAITING_CONFIRMATION else ""
    return f"{mark}#{order.id} · {order.total} {EnvKeys.PAY_CURRENCY} · {order.customer_name}"[:60]


async def _show_list(call: CallbackQuery, key: str, page: int) -> None:
    paginator = LazyPaginator(partial(query_orders, **ORDER_LISTS[key]), per_page=_PAGE_SIZE)
    if await paginator.get_total_count() == 0:
        await _render(call, localize("admin.orders.list.empty"), back("orders_mgmt"))
        return
    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=_order_button,
        item_callback=lambda o: f"ord:{o.id}{ctx_suffix(key, page)}",
        page=page,
        back_cb="orders_mgmt",
        nav_cb_prefix=f"ords_{key}_",
    )
    await _render(call, localize(f"admin.orders.list.{key}.title"), markup)


@router.callback_query(F.data == 'orders_mgmt', HasPermissionFilter(permission=_PERM))
async def orders_menu_handler(call: CallbackQuery, state: FSMContext):
    """Orders console: lists by status, the transfers waiting for a check, find by number."""
    new_count = await query_orders(status="new", count_only=True)
    check_count = await query_orders(awaiting_payment_check=True, count_only=True)
    await _render(call, localize("admin.orders.menu.title"), orders_menu_keyboard(new_count, check_count))
    await state.clear()


@router.callback_query(F.data.startswith('ords_'), HasPermissionFilter(permission=_PERM))
async def orders_list_handler(call: CallbackQuery):
    """One page of an order list. Callback data format: ords_{key}_{page}"""
    try:
        _prefix, key, page_str = call.data.split('_')
        page = int(page_str)
    except ValueError:
        await call.answer(localize("errors.pagination_invalid"))
        return
    if key not in ORDER_LISTS:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    await _show_list(call, key, page)


def _parse_order_id(call: CallbackQuery) -> tuple[int, list[str]] | None:
    """Split ``name:{id}:...`` into the order id and the remaining parts."""
    parts = call.data.split(':')
    try:
        return int(parts[1]), parts[2:]
    except (ValueError, IndexError):
        return None


@router.callback_query(F.data.startswith('ord:'), HasPermissionFilter(permission=_PERM))
async def order_card_handler(call: CallbackQuery, state: FSMContext):
    """Open an order card. Callback data format: ord:{id}[:{list}:{page}]"""
    parsed = _parse_order_id(call)
    if not parsed:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    order_id, rest = parsed
    await _show_order(call, order_id, *parse_ctx(rest))
    await state.clear()


@router.callback_query(F.data == 'ord_find', HasPermissionFilter(permission=_PERM))
async def order_find_handler(call: CallbackQuery, state: FSMContext):
    """Ask for an order number."""
    await _render(call, localize("admin.orders.find.prompt"), back("orders_mgmt"))
    await state.set_state(OrdersAdminFSM.waiting_order_id)


@router.message(OrdersAdminFSM.waiting_order_id, F.text, HasPermissionFilter(permission=_PERM))
async def order_find_process(message: Message, state: FSMContext):
    """Show the order with the entered number."""
    text = (message.text or "").strip().lstrip('#')
    if not (text.isascii() and text.isdigit()) or len(text) > 9:
        await message.answer(localize("errors.id_should_be_number"), reply_markup=back("orders_mgmt"))
        return
    order = await get_order(int(text))
    if not order:
        await message.answer(localize("admin.orders.err.not_found"), reply_markup=back("orders_mgmt"))
        return
    await message.answer(format_order(order, admin=True), parse_mode='HTML',
                         reply_markup=order_card_keyboard(order))
    await state.clear()


@router.callback_query(F.data.startswith('ord_proof:'), HasPermissionFilter(permission=_PERM))
async def order_proof_handler(call: CallbackQuery):
    """Send the customer's payment screenshot."""
    parsed = _parse_order_id(call)
    order = await get_order(parsed[0]) if parsed else None
    if not order:
        await call.answer(localize("admin.orders.err.not_found"), show_alert=True)
        return
    if not order.get("payment_proof"):
        await call.answer(localize("admin.orders.err.no_proof"), show_alert=True)
        return
    try:
        await call.message.bot.send_photo(
            call.message.chat.id, order["payment_proof"],
            caption=localize("admin.orders.proof.caption", id=order["id"]), parse_mode='HTML',
        )
        await call.answer()
    except TelegramBadRequest:
        await call.answer(localize("admin.orders.err.proof_unavailable"), show_alert=True)


@router.callback_query(F.data.startswith('ord_mia_ok:'), HasPermissionFilter(permission=_PERM))
async def mia_confirm_handler(call: CallbackQuery):
    """The admin found the MIA transfer: mark it paid and accept the order."""
    parsed = _parse_order_id(call)
    if not parsed:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    order_id, rest = parsed
    ok, code, order = await confirm_mia_payment(order_id, admin_id=call.from_user.id)
    if not ok:
        await call.answer(_error_text(code), show_alert=True)
        return
    await notify_customer(call.message.bot, order, "payment_confirmed")
    await _show_order(call, order_id, *parse_ctx(rest), note=localize("admin.orders.done.payment_confirmed"))


@router.callback_query(F.data.startswith('ord_mia_no:'), HasPermissionFilter(permission=_PERM))
async def mia_reject_handler(call: CallbackQuery):
    """The transfer was not found: send the order back to "awaiting payment"."""
    parsed = _parse_order_id(call)
    if not parsed:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    order_id, rest = parsed
    ok, code, order = await reject_mia_payment(order_id, admin_id=call.from_user.id)
    if not ok:
        await call.answer(_error_text(code), show_alert=True)
        return
    await notify_customer(call.message.bot, order, "payment_rejected")
    await _show_order(call, order_id, *parse_ctx(rest), note=localize("admin.orders.done.payment_rejected"))


@router.callback_query(F.data.startswith('ord_st:'), HasPermissionFilter(permission=_PERM))
async def order_status_handler(call: CallbackQuery):
    """Move an order forward. Callback data format: ord_st:{id}:{cnf|shp|cmp}[:{list}:{page}]"""
    parsed = _parse_order_id(call)
    if not parsed or not parsed[1] or parsed[1][0] not in STATUS_CODES:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    order_id, rest = parsed
    new_status = STATUS_CODES[rest[0]]
    ok, code, order = await set_order_status(order_id, new_status, admin_id=call.from_user.id)
    if not ok:
        await call.answer(_error_text(code), show_alert=True)
        return
    await notify_customer(call.message.bot, order, _STATUS_NOTICE[new_status])
    await _show_order(call, order_id, *parse_ctx(rest[1:]),
                      note=localize(f"admin.orders.done.{new_status}"))


@router.callback_query(F.data.startswith('ord_cx:'), HasPermissionFilter(permission=_PERM))
async def order_cancel_ask_handler(call: CallbackQuery):
    """Ask before cancelling; warn when money already received has to be returned by hand."""
    parsed = _parse_order_id(call)
    order = await get_order(parsed[0]) if parsed else None
    if not order:
        await call.answer(localize("admin.orders.err.not_found"), show_alert=True)
        return
    key, page = parse_ctx(parsed[1])
    text = localize("admin.orders.cancel.confirm", id=order["id"])
    due = Decimal(str(order["total"])) - Decimal(str(order["balance_used"]))
    if due > 0 and order["payment_status"] in (PaymentStatus.PAID, PaymentStatus.AWAITING_CONFIRMATION):
        text += "\n\n" + localize("admin.orders.cancel.refund_warning", amount=due, currency=EnvKeys.PAY_CURRENCY)
    await _render(call, text, cancel_confirm_keyboard(order["id"], key, page))


@router.callback_query(F.data.startswith('ord_cxy:'), HasPermissionFilter(permission=_PERM))
async def order_cancel_handler(call: CallbackQuery):
    """Cancel the order: stock goes back on the shelf, the balance part returns to the customer."""
    parsed = _parse_order_id(call)
    if not parsed:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    order_id, rest = parsed
    ok, code, order = await cancel_order_transaction(order_id, reason=f"admin:{call.from_user.id}")
    if not ok:
        await call.answer(_error_text(code), show_alert=True)
        return

    admin_name = caller_name(call)
    await log_audit("admin_cancel_order", user_id=call.from_user.id, resource_type="Order",
                    resource_id=str(order_id), details=f"admin={admin_name}, payment={order['payment_status']}")

    await notify_customer(call.message.bot, order, "cancelled")
    for name in order.get("restocked", []):
        await _notify_restock_safe(call.message.bot, name)

    note = localize("admin.orders.done.cancelled")
    if order["payment_status"] == PaymentStatus.REFUNDED:
        due = Decimal(str(order["total"])) - Decimal(str(order["balance_used"]))
        note += "\n" + localize("admin.orders.cancel.refund_manual", amount=due, currency=EnvKeys.PAY_CURRENCY)
    await _show_order(call, order_id, *parse_ctx(rest), note=note)
