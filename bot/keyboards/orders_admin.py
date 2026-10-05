"""Keyboards of the orders console (admin side)."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.models.main import OrderStatus, PaymentMethod, PaymentStatus
from bot.i18n import localize

# Order list key (kept short for callback_data) -> filters passed to ``query_orders``.
ORDER_LISTS: dict[str, dict] = {
    "new": {"status": OrderStatus.NEW},
    "chk": {"awaiting_payment_check": True},
    "cnf": {"status": OrderStatus.CONFIRMED},
    "shp": {"status": OrderStatus.SHIPPED},
    "cmp": {"status": OrderStatus.COMPLETED},
    "can": {"status": OrderStatus.CANCELLED},
}

# Short callback code -> the status the button moves the order to.
STATUS_CODES: dict[str, str] = {
    "cnf": OrderStatus.CONFIRMED,
    "shp": OrderStatus.SHIPPED,
    "cmp": OrderStatus.COMPLETED,
}


def ctx_suffix(key: str = "", page: int = 0) -> str:
    """Where the admin came from (list key + page), appended to order callbacks so Back returns there."""
    return f":{key}:{page}" if key in ORDER_LISTS else ""


def parse_ctx(parts: list[str]) -> tuple[str, int]:
    """Read the ``[key, page]`` tail of an order callback; ('', 0) when absent or malformed."""
    if len(parts) >= 2 and parts[0] in ORDER_LISTS and parts[1].isdigit():
        return parts[0], int(parts[1])
    return "", 0


def back_target(key: str, page: int) -> str:
    return f"ords_{key}_{page}" if key in ORDER_LISTS else "orders_mgmt"


def payment_verified(order: dict) -> bool:
    """MIA orders may only move on once the transfer is verified; other methods have no such gate."""
    return order["payment_method"] != PaymentMethod.MIA or order["payment_status"] == PaymentStatus.PAID


def orders_menu_keyboard(new_count: int = 0, check_count: int = 0) -> InlineKeyboardMarkup:
    """Orders console: the lists, with a count on the ones that need attention."""
    def label(key: str, count: int = 0) -> str:
        text = localize(f"admin.orders.list.{key}")
        return f"{text} ({count})" if count else text

    kb = InlineKeyboardBuilder()
    kb.button(text=label("new", new_count), callback_data="ords_new_0")
    kb.button(text=label("chk", check_count), callback_data="ords_chk_0")
    for key in ("cnf", "shp", "cmp", "can"):
        kb.button(text=label(key), callback_data=f"ords_{key}_0")
    kb.button(text=localize("admin.orders.find"), callback_data="ord_find")
    kb.button(text=localize("btn.back"), callback_data="console")
    kb.adjust(1)
    return kb.as_markup()


def order_card_keyboard(order: dict, key: str = "", page: int = 0,
                        back_cb: str | None = None) -> InlineKeyboardMarkup:
    """Actions that make sense for the order's current state.

    Back goes to the list the admin came from (``key``/``page``), or to ``back_cb`` when the
    order was opened from somewhere else (a user's profile).
    """
    oid = order["id"]
    ctx = ctx_suffix(key, page)
    status = order["status"]
    kb = InlineKeyboardBuilder()

    if status == OrderStatus.NEW and order["payment_method"] == PaymentMethod.MIA:
        if order["payment_status"] == PaymentStatus.AWAITING_CONFIRMATION:
            kb.row(
                InlineKeyboardButton(text=localize("btn.order.mia_ok"), callback_data=f"ord_mia_ok:{oid}{ctx}"),
                InlineKeyboardButton(text=localize("btn.order.mia_no"), callback_data=f"ord_mia_no:{oid}{ctx}"),
            )
        elif order["payment_status"] == PaymentStatus.AWAITING_PAYMENT:
            # The admin can see the money before the customer taps "I've paid".
            kb.row(InlineKeyboardButton(text=localize("btn.order.mia_ok"), callback_data=f"ord_mia_ok:{oid}{ctx}"))

    if order.get("payment_proof"):
        kb.row(InlineKeyboardButton(text=localize("admin.orders.btn.proof"), callback_data=f"ord_proof:{oid}"))

    if payment_verified(order):
        if status == OrderStatus.NEW:
            kb.row(InlineKeyboardButton(text=localize("admin.orders.btn.confirm"),
                                        callback_data=f"ord_st:{oid}:cnf{ctx}"))
        if status == OrderStatus.CONFIRMED:
            kb.row(InlineKeyboardButton(text=localize("admin.orders.btn.ship"),
                                        callback_data=f"ord_st:{oid}:shp{ctx}"))
        if status in (OrderStatus.CONFIRMED, OrderStatus.SHIPPED):
            kb.row(InlineKeyboardButton(text=localize("admin.orders.btn.complete"),
                                        callback_data=f"ord_st:{oid}:cmp{ctx}"))

    if status in OrderStatus.ACTIVE:
        kb.row(InlineKeyboardButton(text=localize("admin.orders.btn.cancel"), callback_data=f"ord_cx:{oid}{ctx}"))

    if order.get("user_id"):
        kb.row(InlineKeyboardButton(text=localize("admin.orders.btn.contact"),
                                    url=f"tg://user?id={order['user_id']}"))
    kb.row(InlineKeyboardButton(text=localize("btn.back"), callback_data=back_cb or back_target(key, page)))
    return kb.as_markup()


def cancel_confirm_keyboard(order_id: int, key: str = "", page: int = 0) -> InlineKeyboardMarkup:
    """Yes / no before cancelling (cancelling restocks and refunds the balance part)."""
    ctx = ctx_suffix(key, page)
    kb = InlineKeyboardBuilder()
    kb.button(text=localize("admin.orders.cancel.yes"), callback_data=f"ord_cxy:{order_id}{ctx}")
    kb.button(text=localize("admin.orders.cancel.no"), callback_data=f"ord:{order_id}{ctx}")
    kb.adjust(2)
    return kb.as_markup()
