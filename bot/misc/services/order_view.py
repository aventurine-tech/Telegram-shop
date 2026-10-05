"""Rendering and notifying for orders — shared by the customer and admin handlers."""
import logging
from decimal import Decimal

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.database.methods.orders import get_order_notify_ids
from bot.database.methods.read import get_user_languages
from bot.database.models.main import Fulfillment, PaymentMethod, PaymentStatus
from bot.i18n import localize, esc, use_language
from bot.misc import EnvKeys
from bot.misc.localized import pick

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


def delivery_lines(order: dict, cur: str) -> list[str]:
    """The delivery price line of an order that used a shipping method (nothing for pickup / unpriced delivery)."""
    name = order.get("shipping_name")
    if not name:
        return []
    fee = Decimal(str(order.get("delivery_fee") or 0))
    if fee > 0:
        return [localize("order.line.delivery", name=esc(name), fee=fee, currency=cur)]
    return [localize("order.line.delivery_free", name=esc(name))]


def format_order(order: dict, *, admin: bool = False) -> str:
    """The order card. ``order`` is the dict from ``orders.get_order`` / the transaction result."""
    cur = EnvKeys.PAY_CURRENCY
    lines = [
        localize("order.title", id=order["id"], status=localize(f"order.status.{order['status']}")),
        "",
    ]
    for it in order.get("items", []):
        lines.append(localize(
            "order.line.item", name=esc(pick(it, "name")), qty=it["quantity"],
            total=Decimal(str(it["line_total"])), currency=cur,
        ))
    lines.append("")
    lines.extend(delivery_lines(order, cur))
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


async def _send_to_staff(bot: Bot, build, photo: str | None = None) -> int:
    """Send to every staff chat; ``build()`` returns (text, markup) and runs once per language.

    Each admin gets the alert in their own language; the optional orders group chat has no profile
    and gets the bot default.
    """
    ids = await get_order_notify_ids()
    languages = await get_user_languages(ids)
    built: dict[str | None, tuple[str, InlineKeyboardMarkup]] = {}
    sent = 0
    for chat_id in _admin_targets(ids):
        lang = languages.get(chat_id)
        if lang not in built:
            with use_language(lang):
                built[lang] = build()
        text, markup = built[lang]
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
    def build():
        return (localize("notify.admin.new_order") + "\n\n" + format_order(order, admin=True),
                admin_order_keyboard(order))

    return await _send_to_staff(bot, build)


async def notify_mia_claim(bot: Bot, order: dict) -> int:
    """The customer says they paid by MIA: ask staff to verify (with the screenshot if any)."""
    cur = EnvKeys.PAY_CURRENCY
    due = Decimal(str(order["total"])) - Decimal(str(order["balance_used"]))

    def build():
        text = localize("notify.admin.mia_claim", amount=due, currency=cur, id=order["id"]) \
            + "\n\n" + format_order(order, admin=True)
        return text, admin_order_keyboard(order)

    return await _send_to_staff(bot, build, photo=order.get("payment_proof"))


async def notify_customer(bot: Bot, order: dict, kind: str) -> bool:
    """Tell the customer something changed, in their own language. ``kind`` is one of: confirmed, shipped,
    completed, cancelled, payment_confirmed, payment_rejected, mia_expired."""
    if not order.get("user_id"):
        return False
    try:
        lang = (await get_user_languages([order["user_id"]])).get(order["user_id"])
        with use_language(lang):
            text = localize(f"notify.customer.{kind}", id=order["id"])
            markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=localize("btn.order.open"), callback_data=f"my_order:{order['id']}"),
            ]])
        await bot.send_message(order["user_id"], text, reply_markup=markup)
        return True
    except Exception as e:
        logger.warning("customer notice %s for order %s failed: %s", kind, order.get("id"), e)
        return False
