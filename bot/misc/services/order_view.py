"""Rendering and notifying for orders — shared by the customer and admin handlers."""
import logging
from decimal import Decimal

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.database.methods.orders import get_order_notify_ids
from bot.database.models.main import Fulfillment, PaymentMethod, PaymentStatus
from bot.i18n import localize, esc
from bot.misc import EnvKeys

logger = logging.getLogger(__name__)


def method_label(order: dict) -> str:
    """Human label for how the order is paid ("Cash on delivery" vs "Cash on pickup")."""
    method = order["payment_method"]
    if method == PaymentMethod.COD:
        key = "order.method.cod_pickup" if order["fulfillment"] == Fulfillment.PICKUP else "order.method.cod_delivery"
    else:
        key = f"order.method.{method}"
    return localize(key)


def fmt_dt(value) -> str:
    try:
        return value.strftime("%Y-%m-%d %H:%M")
    except AttributeError:
        return str(value or "")


def format_order(order: dict, *, admin: bool = False) -> str:
    """The order card. ``order`` is the dict from ``orders.get_order`` / the transaction result."""
    cur = EnvKeys.PAY_CURRENCY
    lines = [
        localize("order.title", id=order["id"], status=localize(f"order.status.{order['status']}")),
        "",
    ]
    for it in order.get("items", []):
        lines.append(localize(
            "order.line.item", name=esc(it["item_name"]), qty=it["quantity"],
            total=Decimal(str(it["line_total"])), currency=cur,
        ))
    lines.append("")
    lines.append(localize("order.line.total", total=Decimal(str(order["total"])), currency=cur))
    balance_used = Decimal(str(order["balance_used"]))
    if balance_used > 0:
        lines.append(localize("order.line.balance_used", amount=balance_used, currency=cur))
        lines.append(localize("order.line.due", amount=Decimal(str(order["total"])) - balance_used, currency=cur))
    lines.append(localize(
        "order.line.payment", method=method_label(order),
        status=localize(f"order.paystatus.{order['payment_status']}"),
    ))
    lines.append(localize("order.line.fulfillment", fulfillment=localize(f"order.fulfillment.{order['fulfillment']}")))
    lines.append(localize("order.line.contact", name=esc(order["customer_name"]), phone=esc(order["phone"])))
    if order.get("address"):
        lines.append(localize("order.line.address", address=esc(order["address"])))
    if order.get("comment"):
        lines.append(localize("order.line.comment", comment=esc(order["comment"])))
    lines.append(localize("order.line.created", dt=fmt_dt(order.get("created_at"))))
    if admin and order.get("user_id"):
        lines.append(localize("order.line.customer_id", id=order["user_id"]))
    return "\n".join(lines)


def _admin_targets(ids: list[int]) -> list[int | str]:
    targets: list[int | str] = list(ids)
    if EnvKeys.ORDERS_CHAT_ID:
        chat = EnvKeys.ORDERS_CHAT_ID.strip()
        targets.append(int(chat) if chat.lstrip("-").isdigit() else chat)
    return targets


async def _send_to_staff(bot: Bot, text: str, markup: InlineKeyboardMarkup, photo: str | None = None) -> int:
    sent = 0
    for chat_id in _admin_targets(await get_order_notify_ids()):
        try:
            if photo:
                # A caption is capped at 1024 chars; the order card fits, the proof goes first.
                await bot.send_photo(chat_id, photo, caption=text[:1024], reply_markup=markup)
            else:
                await bot.send_message(chat_id, text, reply_markup=markup)
            sent += 1
        except Exception as e:  # blocked bot, deleted chat, ...: never break the customer's checkout
            logger.warning("order alert to %s failed: %s", chat_id, e)
    return sent


def admin_order_keyboard(order: dict) -> InlineKeyboardMarkup:
    """Open button, plus verify buttons while an MIA transfer waits for a human."""
    rows = []
    if order["payment_status"] == PaymentStatus.AWAITING_CONFIRMATION:
        rows.append([
            InlineKeyboardButton(text=localize("btn.order.mia_ok"), callback_data=f"ord_mia_ok:{order['id']}"),
            InlineKeyboardButton(text=localize("btn.order.mia_no"), callback_data=f"ord_mia_no:{order['id']}"),
        ])
    rows.append([InlineKeyboardButton(text=localize("btn.order.open"), callback_data=f"ord:{order['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def notify_new_order(bot: Bot, order: dict) -> int:
    """Alert staff about a freshly placed order. Returns how many chats got it."""
    text = localize("notify.admin.new_order") + "\n\n" + format_order(order, admin=True)
    return await _send_to_staff(bot, text, admin_order_keyboard(order))


async def notify_mia_claim(bot: Bot, order: dict) -> int:
    """The customer says they paid by MIA: ask staff to verify (with the screenshot if any)."""
    cur = EnvKeys.PAY_CURRENCY
    due = Decimal(str(order["total"])) - Decimal(str(order["balance_used"]))
    text = localize("notify.admin.mia_claim", amount=due, currency=cur, id=order["id"]) \
        + "\n\n" + format_order(order, admin=True)
    return await _send_to_staff(bot, text, admin_order_keyboard(order), photo=order.get("payment_proof"))


async def notify_customer(bot: Bot, order: dict, kind: str) -> bool:
    """Tell the customer something changed. ``kind`` is one of: confirmed, shipped, completed,
    cancelled, payment_confirmed, payment_rejected, mia_expired."""
    if not order.get("user_id"):
        return False
    try:
        await bot.send_message(
            order["user_id"],
            localize(f"notify.customer.{kind}", id=order["id"]),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=localize("btn.order.open"), callback_data=f"my_order:{order['id']}"),
            ]]),
        )
        return True
    except Exception as e:
        logger.warning("customer notice %s for order %s failed: %s", kind, order.get("id"), e)
        return False
