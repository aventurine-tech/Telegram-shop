"""Order lifecycle for physical goods.

Stock is *reserved* when an order is placed and *released* when it is cancelled, so
two customers can never both buy the last unit. Money never moves through the bot
except the optional store balance: MIA transfers are verified by an admin and cash
is collected on delivery/pickup.

Every function here is one transaction and returns ``(ok, code, data)``. ``code`` is a
stable key the handlers map to a localized message; ``data`` is the payload on success.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, exists, delete as sa_delete
from sqlalchemy.exc import IntegrityError, OperationalError, DBAPIError

from bot.database import Database
from bot.database.methods.audit import log_audit
from bot.database.methods.cache_utils import safe_create_task
from bot.database.methods.pricing import effective_price, apply_promo_discount
from bot.database.methods.shipping import delivery_fee
from bot.database.methods.read import (
    invalidate_user_cache, invalidate_stats_cache, invalidate_item_cache,
    promo_rule_error,
)
from bot.database.models import User, Goods, Role
from bot.database.models.main import (
    CartItems, PromoCodes, PromoCodeUsages, ReferralEarnings,
    Orders, OrderItems, OrderStatus, PaymentMethod, PaymentStatus, Fulfillment, Permission, ShippingMethods,
)
from bot.misc import EnvKeys

logger = logging.getLogger(__name__)

_RETRIES = 3


class _Abort(Exception):
    """Abort the current transaction with a user-facing failure code."""

    def __init__(self, code: str, data: dict | None = None):
        self.code = code
        self.data = data
        super().__init__(code)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; they are UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def payment_method_enabled(method: str) -> bool:
    if method == PaymentMethod.MIA:
        return EnvKeys.mia_enabled()
    if method == PaymentMethod.COD:
        return EnvKeys.COD_ENABLED == "1"
    return False


def fulfillment_enabled(kind: str) -> bool:
    if kind == Fulfillment.DELIVERY:
        return EnvKeys.DELIVERY_ENABLED == "1"
    if kind == Fulfillment.PICKUP:
        return EnvKeys.PICKUP_ENABLED == "1"
    return False


def available_payment_methods() -> list[str]:
    return [m for m in PaymentMethod.CHOICES if payment_method_enabled(m)]


def available_fulfillments() -> list[str]:
    return [f for f in Fulfillment.CHOICES if fulfillment_enabled(f)]


def order_to_dict(order: Orders, items: list[OrderItems] | None = None) -> dict:
    """Plain, cache/FSM-safe snapshot of an order (money as Decimal)."""
    d = {
        "id": order.id,
        "user_id": order.user_id,
        "status": order.status,
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "fulfillment": order.fulfillment,
        "customer_name": order.customer_name,
        "phone": order.phone,
        "address": order.address,
        "comment": order.comment,
        "total": order.total,
        "balance_used": order.balance_used,
        "due": order.total - order.balance_used,
        "shipping_name": order.shipping_name,
        "shipping_name_en": order.shipping_name_en,
        "shipping_name_ru": order.shipping_name_ru,
        "shipping_name_ro": order.shipping_name_ro,
        "delivery_fee": order.delivery_fee,
        "tracking_note": order.tracking_note,
        "payment_proof": order.payment_proof,
        "pay_by": order.pay_by,
        "created_at": order.created_at,
    }
    if items is not None:
        d["items"] = [
            {
                "item_id": i.item_id,
                "item_name": i.item_name,
                "name": i.item_name,          # canonical key `pick(line, "name")` falls back to
                "name_en": i.name_en,
                "name_ru": i.name_ru,
                "name_ro": i.name_ro,
                "quantity": i.quantity,
                "unit_price": i.unit_price,
                "line_total": i.line_total,
            }
            for i in items
        ]
    return d


async def _load_items(s, order_id: int) -> list[OrderItems]:
    return list((await s.execute(
        select(OrderItems).where(OrderItems.order_id == order_id).order_by(OrderItems.id)
    )).scalars().all())


def _invalidate_after(user_id: int | None, item_names) -> None:
    if user_id is not None:
        safe_create_task(invalidate_user_cache(user_id))
    safe_create_task(invalidate_stats_cache())
    for name in set(item_names):
        safe_create_task(invalidate_item_cache(name))


# --------------------------------------------------------------------------- #
# Placing an order
# --------------------------------------------------------------------------- #

async def create_order_transaction(
        user_id: int,
        *,
        fulfillment: str,
        customer_name: str,
        phone: str,
        address: str | None,
        comment: str | None,
        payment_method: str,
        use_balance: bool = False,
        expected_total: Decimal | None = None,
        shipping_method_id: int | None = None,
) -> tuple[bool, str, dict | None]:
    """Turn the user's cart into an order, reserving stock.

    Promo codes come from ``cart_items.promo_code`` and are validated here; a code is a
    single redemption so it discounts the single most expensive line it applies to (the
    cart view renders the same rule, so the totals agree and ``expected_total`` catches drift).

    ``expected_total`` is the total the customer confirmed. If a price or sale moved in
    between, the order is refused with ``price_changed`` rather than silently charged.

    For a delivery, when the shop has active shipping methods one of them must be chosen
    (``shipping_method_id``); its price (free above its threshold) is added to the total and
    kept on the order as ``delivery_fee``. Without active methods delivery is free.

    ``use_balance`` spends as much store balance as covers the total. If that covers all of
    it, nothing is due and the order is recorded with ``payment_method='balance'``.

    Failure codes: user_not_found, cart_empty, cart_items_unavailable, out_of_stock
    (data: ``item_name``, ``available``), price_changed, invalid_payment_method,
    invalid_fulfillment, address_required, shipping_required, invalid_shipping, transaction_error.
    """
    if payment_method not in PaymentMethod.CHOICES:
        return False, "invalid_payment_method", None
    if fulfillment not in Fulfillment.CHOICES or not fulfillment_enabled(fulfillment):
        return False, "invalid_fulfillment", None
    if fulfillment == Fulfillment.DELIVERY and not (address or "").strip():
        return False, "address_required", None

    for attempt in range(_RETRIES):
        try:
            async with Database().session() as s:
                user = (await s.execute(
                    select(User).where(User.telegram_id == user_id).with_for_update()
                )).scalars().one_or_none()
                if not user:
                    raise _Abort("user_not_found")

                cart_items = (await s.execute(
                    select(CartItems).where(CartItems.user_id == user_id).order_by(CartItems.id)
                )).scalars().all()
                if not cart_items:
                    raise _Abort("cart_empty")

                # Lock all distinct goods in id order so overlapping carts can't deadlock.
                item_ids = list({ci.item_id for ci in cart_items})
                goods_by_id = {
                    g.id: g for g in (await s.execute(
                        select(Goods).where(Goods.id.in_(item_ids)).order_by(Goods.id).with_for_update()
                    )).scalars().all()
                }

                purchases = []
                stale_cart_rows = []
                promos_by_code: dict[str, PromoCodes | None] = {}
                promo_used: dict[int, bool] = {}

                for ci in cart_items:
                    goods = goods_by_id.get(ci.item_id)
                    if goods is None:
                        stale_cart_rows.append(ci.id)
                        continue

                    qty = ci.quantity
                    if goods.stock < qty:
                        raise _Abort("out_of_stock", {
                            "item_name": goods.name, "available": goods.stock,
                        })

                    price, _on_sale, _original = effective_price(goods)
                    line_price = (price * qty).quantize(Decimal("0.01"))

                    promo = None
                    if ci.promo_code:
                        code = ci.promo_code.upper()
                        if code not in promos_by_code:
                            promos_by_code[code] = (await s.execute(
                                select(PromoCodes).where(PromoCodes.code == code).with_for_update()
                            )).scalars().first()
                        candidate = promos_by_code[code]
                        if candidate is not None:
                            if candidate.id not in promo_used:
                                promo_used[candidate.id] = bool((await s.execute(
                                    select(exists().where(
                                        PromoCodeUsages.promo_id == candidate.id,
                                        PromoCodeUsages.user_id == user_id,
                                    ))
                                )).scalar())
                            if not await promo_rule_error(
                                    s, candidate, user_id, goods=goods, used=promo_used[candidate.id],
                            ):
                                promo = candidate

                    purchases.append({
                        'cart_id': ci.id, 'goods': goods, 'qty': qty,
                        'unit_price': price, 'line_price': line_price, 'promo': promo,
                    })

                promos_to_record: dict[int, PromoCodes] = {}
                for promo in {p['promo'].id: p['promo'] for p in purchases if p['promo'] is not None}.values():
                    eligible = [p for p in purchases if p['promo'] is not None and p['promo'].id == promo.id]
                    best = max(eligible, key=lambda p: (p['line_price'], -p['cart_id']))
                    for p in eligible:
                        if p is not best:
                            p['promo'] = None
                    best['line_price'] = apply_promo_discount(
                        best['unit_price'], promo.discount_type, promo.discount_value, best['qty']
                    )
                    promos_to_record[promo.id] = promo

                if stale_cart_rows:
                    await s.execute(sa_delete(CartItems).where(CartItems.id.in_(stale_cart_rows)))
                if not purchases:
                    # Persist the clean-up above before reporting failure (an abort rolls back).
                    await s.commit()
                    raise _Abort("cart_items_unavailable")

                goods_total = sum((p['line_price'] for p in purchases), Decimal(0))
                shipping = None
                fee = Decimal("0.00")
                if fulfillment == Fulfillment.DELIVERY:
                    offered = (await s.execute(
                        select(ShippingMethods).where(ShippingMethods.is_active.is_(True)))).scalars().all()
                    if offered:
                        if shipping_method_id is None:
                            raise _Abort("shipping_required")
                        shipping = next((m for m in offered if m.id == shipping_method_id), None)
                        if shipping is None:
                            raise _Abort("invalid_shipping")
                        fee = delivery_fee(shipping, goods_total)
                total = goods_total + fee
                if expected_total is not None and total != expected_total:
                    raise _Abort("price_changed")

                balance_used = Decimal("0.00")
                if use_balance and user.balance > 0:
                    balance_used = min(_money(user.balance), total)
                due = total - balance_used

                method = payment_method
                # A balance-covered order needs no usable method; anything still due does.
                if due > 0 and not payment_method_enabled(method):
                    raise _Abort("invalid_payment_method")
                if due == 0:
                    method = PaymentMethod.BALANCE
                    payment_status = PaymentStatus.PAID
                    pay_by = None
                elif method == PaymentMethod.MIA:
                    payment_status = PaymentStatus.AWAITING_PAYMENT
                    pay_by = _now() + timedelta(minutes=EnvKeys.MIA_PAY_TIMEOUT_MIN)
                else:
                    payment_status = PaymentStatus.UNPAID
                    pay_by = None

                if balance_used > 0:
                    user.balance -= balance_used

                order = Orders(
                    user_id=user_id,
                    status=OrderStatus.NEW,
                    payment_method=method,
                    payment_status=payment_status,
                    fulfillment=fulfillment,
                    customer_name=customer_name.strip()[:100],
                    phone=phone.strip()[:32],
                    address=(address or "").strip() or None,
                    comment=(comment or "").strip() or None,
                    shipping_name=shipping.name if shipping else None,
                    shipping_name_en=shipping.name_en if shipping else None,
                    shipping_name_ru=shipping.name_ru if shipping else None,
                    shipping_name_ro=shipping.name_ro if shipping else None,
                    delivery_fee=fee,
                    total=total,
                    balance_used=balance_used,
                    pay_by=pay_by,
                    created_at=_now(),
                )
                s.add(order)
                await s.flush()

                # The client's profile keeps the contact details of their latest order.
                user.phone = order.phone
                user.contact_name = order.customer_name
                if fulfillment == Fulfillment.DELIVERY and order.address:
                    # "city, address" built from the saved profile is not a new address: keep the two parts apart.
                    saved = ", ".join(p for p in ((user.city or "").strip(), (user.address or "").strip()) if p)
                    if order.address != saved:
                        user.address = order.address

                for p in purchases:
                    p['goods'].stock -= p['qty']
                    s.add(OrderItems(
                        order_id=order.id,
                        item_id=p['goods'].id,
                        item_name=p['goods'].name,
                        name_en=p['goods'].name_en,
                        name_ru=p['goods'].name_ru,
                        name_ro=p['goods'].name_ro,
                        quantity=p['qty'],
                        unit_price=p['unit_price'],
                        line_total=p['line_price'],
                    ))

                for promo in promos_to_record.values():
                    promo.current_uses += 1
                    s.add(PromoCodeUsages(promo_id=promo.id, user_id=user_id))

                await s.execute(sa_delete(CartItems).where(CartItems.user_id == user_id))
                await s.flush()

                items = await _load_items(s, order.id)
                result = order_to_dict(order, items)
                result["new_balance"] = user.balance
                names = [p['goods'].name for p in purchases]

        except _Abort as e:
            return False, e.code, e.data

        except (OperationalError, DBAPIError) as e:
            msg = str(e).lower()
            if ("deadlock" in msg or "could not serialize" in msg) and attempt < _RETRIES - 1:
                continue
            await log_audit("order_create_failed", level="WARNING", user_id=user_id, details=str(e))
            return False, "transaction_error", None

        except Exception as e:
            await log_audit("order_create_failed", level="WARNING", user_id=user_id, details=str(e))
            return False, "transaction_error", None

        _invalidate_after(user_id, names)
        return True, "success", result

    return False, "transaction_error", None


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #

async def get_order(order_id: int, user_id: int | None = None) -> dict | None:
    """One order with its lines, or None.

    With ``user_id`` the order must belong to that customer, so a customer can only read
    their own. Admin views pass ``None`` after a permission check.
    """
    async with Database().session() as s:
        clauses = [Orders.id == int(order_id)]
        if user_id is not None:
            clauses.append(Orders.user_id == user_id)
        order = (await s.execute(select(Orders).where(*clauses))).scalars().first()
        if not order:
            return None
        return order_to_dict(order, await _load_items(s, order.id))


TRACKING_NOTE_MAX = 300
_NOTE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


async def set_tracking_note(order_id: int, note: str | None) -> tuple[bool, str, dict | None]:
    """Save (or clear) the staff note the customer sees with a shipped order.

    Returns ``(True, "success", order)`` with ``order["note_changed"]`` telling whether it differs from before, or
    ``(False, "order_not_found" | "order_closed" | "note_too_long", None)``. A cancelled order takes no note.
    """
    text = _NOTE_CONTROL.sub("", note or "").strip() or None
    if text and len(text) > TRACKING_NOTE_MAX:
        return False, "note_too_long", None
    async with Database().session() as s:
        order = (await s.execute(select(Orders).where(Orders.id == int(order_id)).with_for_update())
                 ).scalars().first()
        if not order:
            return False, "order_not_found", None
        if order.status == OrderStatus.CANCELLED:
            return False, "order_closed", None
        changed = order.tracking_note != text
        order.tracking_note = text
        result = order_to_dict(order, await _load_items(s, order.id))
    result["note_changed"] = changed
    return True, "success", result


async def get_order_notify_ids() -> list[int]:
    """Telegram ids of everyone allowed to manage orders (they get new-order alerts)."""
    async with Database().session() as s:
        roles = (await s.execute(select(Role.id, Role.permissions))).all()
        role_ids = [r.id for r in roles if Permission.granted(r.permissions or 0, Permission.ORDERS_MANAGE)]
        if not role_ids:
            return []
        rows = await s.execute(
            select(User.telegram_id).where(User.role_id.in_(role_ids), User.is_blocked.is_not(True))
        )
        return [r[0] for r in rows.all()]


# --------------------------------------------------------------------------- #
# Cancelling
# --------------------------------------------------------------------------- #

async def _cancel_in_session(s, order: Orders, *, reason: str) -> dict:
    """Release stock, refund the balance part and mark the order cancelled.

    Caller holds the order row and has checked the transition is legal. Returns
    ``{"restocked": [item names whose stock went from 0 to >0]}`` for notifications.
    """
    lines = await _load_items(s, order.id)

    # Lock the user first (same order as order creation: user, then goods).
    user = None
    if order.user_id is not None:
        user = (await s.execute(
            select(User).where(User.telegram_id == order.user_id).with_for_update()
        )).scalars().one_or_none()

    restocked = []
    ids = sorted({l.item_id for l in lines if l.item_id is not None})
    goods_by_id = {}
    if ids:
        goods_by_id = {
            g.id: g for g in (await s.execute(
                select(Goods).where(Goods.id.in_(ids)).order_by(Goods.id).with_for_update()
            )).scalars().all()
        }
    for line in lines:
        g = goods_by_id.get(line.item_id)
        if g is None:
            continue  # product deleted since: nothing to restock
        if g.stock == 0 and line.quantity > 0:
            restocked.append(g.name)
        g.stock += line.quantity

    if user is not None and order.balance_used > 0:
        user.balance += order.balance_used

    # Cash/MIA already collected can't be returned by the bot: flag it for the admin.
    if order.payment_status in (PaymentStatus.PAID, PaymentStatus.AWAITING_CONFIRMATION) \
            and (order.total - order.balance_used) > 0:
        order.payment_status = PaymentStatus.REFUNDED
    elif order.payment_status in (PaymentStatus.AWAITING_PAYMENT, PaymentStatus.UNPAID):
        order.payment_status = PaymentStatus.UNPAID

    order.status = OrderStatus.CANCELLED
    order.pay_by = None
    await log_audit(
        "order_cancelled", user_id=order.user_id, resource_type="Order",
        resource_id=str(order.id), details=reason, session=s,
    )
    return {"restocked": restocked, "item_names": [l.item_name for l in lines]}


async def cancel_order_transaction(
        order_id: int, *, by_customer_id: int | None = None, reason: str = "admin",
) -> tuple[bool, str, dict | None]:
    """Cancel an order and give its stock (and balance share) back.

    A customer (``by_customer_id``) may only cancel their own order and only while the
    shop has not accepted it and no money is with the shop yet. An admin may cancel any
    active order. Codes: order_not_found, not_cancellable, forbidden, transaction_error.
    """
    try:
        async with Database().session() as s:
            order = (await s.execute(
                select(Orders).where(Orders.id == int(order_id)).with_for_update()
            )).scalars().one_or_none()
            if not order or (by_customer_id is not None and order.user_id != by_customer_id):
                raise _Abort("order_not_found")
            if order.status not in OrderStatus.ACTIVE:
                raise _Abort("not_cancellable")
            if by_customer_id is not None and not (
                    order.status == OrderStatus.NEW
                    and order.payment_status in (PaymentStatus.UNPAID, PaymentStatus.AWAITING_PAYMENT)
            ):
                raise _Abort("not_cancellable")

            info = await _cancel_in_session(s, order, reason=reason)
            result = order_to_dict(order, await _load_items(s, order.id))
            result.update(info)
    except _Abort as e:
        return False, e.code, None
    except Exception as e:
        await log_audit("order_cancel_failed", level="WARNING", resource_type="Order",
                        resource_id=str(order_id), details=str(e))
        return False, "transaction_error", None

    _invalidate_after(result["user_id"], result["item_names"])
    return True, "success", result


async def expire_unpaid_orders(now: datetime | None = None) -> list[dict]:
    """Cancel MIA orders nobody paid for in time; returns the cancelled orders (for notices)."""
    now = now or _now()
    async with Database().session() as s:
        ids = [r[0] for r in (await s.execute(
            select(Orders.id).where(
                Orders.status == OrderStatus.NEW,
                Orders.payment_status == PaymentStatus.AWAITING_PAYMENT,
                Orders.pay_by.is_not(None),
                Orders.pay_by < now,
            ).order_by(Orders.id)
        )).all()]

    cancelled = []
    for oid in ids:
        ok, _code, data = await cancel_order_transaction(oid, reason="mia_payment_timeout")
        if ok:
            cancelled.append(data)
    return cancelled


async def _claim_sweep(ids_stmt, stamp: str, recheck, now: datetime) -> list[dict]:
    """Stamp each candidate order once and return the ones this call stamped (a concurrent sweep gets none of them)."""
    async with Database().session() as s:
        ids = [r[0] for r in (await s.execute(ids_stmt)).all()]
    claimed = []
    for oid in ids:
        async with Database().session() as s:
            order = (await s.execute(select(Orders).where(Orders.id == oid).with_for_update())
                     ).scalars().one_or_none()
            if order is None or getattr(order, stamp) is not None or not recheck(order):
                continue
            setattr(order, stamp, now)
            claimed.append(order_to_dict(order, await _load_items(s, order.id)))
    return claimed


async def claim_payment_reminders(now: datetime | None = None) -> list[dict]:
    """Unpaid MIA orders that are close to their deadline and have not been reminded yet (each is returned once).

    Orders whose whole payment window is shorter than ``MIA_REMIND_BEFORE_MIN`` are never reminded.
    """
    window = int(EnvKeys.MIA_REMIND_BEFORE_MIN)
    if window <= 0:
        return []
    now = now or _now()
    soon = now + timedelta(minutes=window)
    waiting = (Orders.status == OrderStatus.NEW, Orders.payment_status == PaymentStatus.AWAITING_PAYMENT,
               Orders.pay_by.is_not(None), Orders.pay_by > now, Orders.pay_by <= soon,
               Orders.created_at <= now - timedelta(minutes=window), Orders.reminder_sent_at.is_(None))

    def still(o: Orders) -> bool:
        return (o.status == OrderStatus.NEW and o.payment_status == PaymentStatus.AWAITING_PAYMENT
                and o.pay_by is not None and _aware(o.pay_by) > now)

    orders = await _claim_sweep(select(Orders.id).where(*waiting).order_by(Orders.id), "reminder_sent_at", still, now)
    for o in orders:
        o["minutes_left"] = max(int((_aware(o["pay_by"]) - now).total_seconds() // 60), 1)
    return orders


async def claim_stale_orders(now: datetime | None = None) -> list[tuple[str, dict]]:
    """Orders staff have left alone for too long, each returned once as ``(kind, order)``.

    ``payment_check``: the customer said they paid by MIA and nobody verified it (``STALE_PAYMENT_ALERT_MIN``);
    ``unhandled``: a cash order nobody confirmed yet (``STALE_ORDER_ALERT_MIN``). A limit of 0 turns that kind off.
    """
    now = now or _now()
    found: list[tuple[str, dict]] = []
    minutes = int(EnvKeys.STALE_PAYMENT_ALERT_MIN)
    if minutes > 0:
        old = now - timedelta(minutes=minutes)
        stmt = select(Orders.id).where(
            Orders.status == OrderStatus.NEW, Orders.payment_status == PaymentStatus.AWAITING_CONFIRMATION,
            Orders.updated_at < old, Orders.staff_alerted_at.is_(None)).order_by(Orders.id)
        found += [("payment_check", o) for o in await _claim_sweep(
            stmt, "staff_alerted_at",
            lambda o: o.status == OrderStatus.NEW and o.payment_status == PaymentStatus.AWAITING_CONFIRMATION, now)]
    minutes = int(EnvKeys.STALE_ORDER_ALERT_MIN)
    if minutes > 0:
        old = now - timedelta(minutes=minutes)
        stmt = select(Orders.id).where(
            Orders.status == OrderStatus.NEW, Orders.payment_status == PaymentStatus.UNPAID,
            Orders.created_at < old, Orders.staff_alerted_at.is_(None)).order_by(Orders.id)
        found += [("unhandled", o) for o in await _claim_sweep(
            stmt, "staff_alerted_at",
            lambda o: o.status == OrderStatus.NEW and o.payment_status == PaymentStatus.UNPAID, now)]
    return found


# --------------------------------------------------------------------------- #
# MIA payment
# --------------------------------------------------------------------------- #

async def mark_mia_paid(order_id: int, user_id: int, proof_file_id: str | None = None
                        ) -> tuple[bool, str, dict | None]:
    """Customer says they sent the MIA transfer; queue it for an admin to verify.

    Codes: order_not_found, not_mia, not_awaiting_payment, transaction_error.
    """
    try:
        async with Database().session() as s:
            order = (await s.execute(
                select(Orders).where(Orders.id == int(order_id), Orders.user_id == user_id).with_for_update()
            )).scalars().one_or_none()
            if not order:
                raise _Abort("order_not_found")
            if order.payment_method != PaymentMethod.MIA:
                raise _Abort("not_mia")
            if order.status != OrderStatus.NEW or order.payment_status not in (
                    PaymentStatus.AWAITING_PAYMENT, PaymentStatus.AWAITING_CONFIRMATION):
                raise _Abort("not_awaiting_payment")
            order.payment_status = PaymentStatus.AWAITING_CONFIRMATION
            if proof_file_id:
                order.payment_proof = proof_file_id[:256]
            # Verification is on the shop now, don't let the unpaid timer cancel the order.
            order.pay_by = None
            result = order_to_dict(order, await _load_items(s, order.id))
    except _Abort as e:
        return False, e.code, None
    except Exception as e:
        await log_audit("mia_mark_paid_failed", level="WARNING", user_id=user_id,
                        resource_type="Order", resource_id=str(order_id), details=str(e))
        return False, "transaction_error", None
    return True, "success", result


async def confirm_mia_payment(order_id: int, admin_id: int | None = None) -> tuple[bool, str, dict | None]:
    """Admin verified the transfer: mark paid and accept the order.

    Codes: order_not_found, not_mia, not_awaiting_payment, transaction_error.
    """
    try:
        async with Database().session() as s:
            order = (await s.execute(
                select(Orders).where(Orders.id == int(order_id)).with_for_update()
            )).scalars().one_or_none()
            if not order:
                raise _Abort("order_not_found")
            if order.payment_method != PaymentMethod.MIA:
                raise _Abort("not_mia")
            if order.status != OrderStatus.NEW or order.payment_status not in (
                    PaymentStatus.AWAITING_PAYMENT, PaymentStatus.AWAITING_CONFIRMATION):
                raise _Abort("not_awaiting_payment")
            order.payment_status = PaymentStatus.PAID
            order.status = OrderStatus.CONFIRMED
            order.pay_by = None
            await log_audit("mia_payment_confirmed", user_id=admin_id, resource_type="Order",
                            resource_id=str(order.id), details=f"due={order.total - order.balance_used}",
                            session=s)
            result = order_to_dict(order, await _load_items(s, order.id))
    except _Abort as e:
        return False, e.code, None
    except Exception as e:
        await log_audit("mia_confirm_failed", level="WARNING", user_id=admin_id,
                        resource_type="Order", resource_id=str(order_id), details=str(e))
        return False, "transaction_error", None
    safe_create_task(invalidate_stats_cache())
    return True, "success", result


async def reject_mia_payment(order_id: int, admin_id: int | None = None) -> tuple[bool, str, dict | None]:
    """Admin could not find the transfer: send the order back to "awaiting payment".

    The customer gets a fresh window to pay and can resend a proof.
    """
    try:
        async with Database().session() as s:
            order = (await s.execute(
                select(Orders).where(Orders.id == int(order_id)).with_for_update()
            )).scalars().one_or_none()
            if not order:
                raise _Abort("order_not_found")
            if order.payment_method != PaymentMethod.MIA:
                raise _Abort("not_mia")
            if order.status != OrderStatus.NEW or order.payment_status != PaymentStatus.AWAITING_CONFIRMATION:
                raise _Abort("not_awaiting_payment")
            order.payment_status = PaymentStatus.AWAITING_PAYMENT
            order.payment_proof = None
            order.pay_by = _now() + timedelta(minutes=EnvKeys.MIA_PAY_TIMEOUT_MIN)
            await log_audit("mia_payment_rejected", user_id=admin_id, resource_type="Order",
                            resource_id=str(order.id), session=s)
            result = order_to_dict(order, await _load_items(s, order.id))
    except _Abort as e:
        return False, e.code, None
    except Exception as e:
        await log_audit("mia_reject_failed", level="WARNING", user_id=admin_id,
                        resource_type="Order", resource_id=str(order_id), details=str(e))
        return False, "transaction_error", None
    return True, "success", result


# --------------------------------------------------------------------------- #
# Status changes
# --------------------------------------------------------------------------- #

async def _credit_referral_in_session(s, order: Orders) -> int | None:
    """Pay the referrer their cut of the cash the customer actually paid for the goods (the delivery fee earns
    nothing). Returns referrer id."""
    percent = min(max(int(EnvKeys.REFERRAL_PERCENT), 0), 99)
    if percent <= 0 or order.user_id is None:
        return None
    paid = order.total - order.delivery_fee - order.balance_used
    if paid <= 0:
        return None
    customer = (await s.execute(
        select(User).where(User.telegram_id == order.user_id)
    )).scalars().one_or_none()
    if not customer or not customer.referral_id or customer.referral_id == order.user_id:
        return None
    bonus = ((Decimal(percent) / Decimal(100)) * paid).quantize(Decimal("0.01"))
    if bonus <= 0:
        return None
    referrer = (await s.execute(
        select(User).where(User.telegram_id == customer.referral_id).with_for_update()
    )).scalars().one_or_none()
    if not referrer:
        return None
    referrer.balance += bonus
    s.add(ReferralEarnings(
        referrer_id=referrer.telegram_id, referral_id=order.user_id,
        amount=bonus, original_amount=paid,
    ))
    await log_audit(
        "referral_bonus", user_id=referrer.telegram_id, resource_type="Order",
        resource_id=str(order.id), details=f"paid={paid}, bonus={bonus}", session=s,
    )
    return referrer.telegram_id


async def set_order_status(order_id: int, new_status: str, admin_id: int | None = None
                           ) -> tuple[bool, str, dict | None]:
    """Move an order along new → confirmed → shipped → completed.

    Cancelling goes through :func:`cancel_order_transaction`. Completing a cash-on-delivery
    order records the cash as collected; completing an MIA order requires the payment to be
    verified first. Completing pays the referral commission, once.

    Codes: order_not_found, invalid_status, invalid_transition, payment_not_confirmed,
    transaction_error.
    """
    if new_status == OrderStatus.CANCELLED:
        return await cancel_order_transaction(order_id, reason=f"admin:{admin_id}")
    if new_status not in OrderStatus.ALL:
        return False, "invalid_status", None

    referrer_id = None
    try:
        async with Database().session() as s:
            order = (await s.execute(
                select(Orders).where(Orders.id == int(order_id)).with_for_update()
            )).scalars().one_or_none()
            if not order:
                raise _Abort("order_not_found")
            if new_status not in OrderStatus.NEXT.get(order.status, ()):
                raise _Abort("invalid_transition")

            # An MIA order must be verified before the shop accepts it or hands goods over.
            if order.payment_method == PaymentMethod.MIA and order.payment_status != PaymentStatus.PAID:
                raise _Abort("payment_not_confirmed")

            if new_status == OrderStatus.COMPLETED:
                if order.payment_status == PaymentStatus.UNPAID:
                    order.payment_status = PaymentStatus.PAID  # cash collected
                referrer_id = await _credit_referral_in_session(s, order)

            order.status = new_status
            await log_audit("order_status", user_id=admin_id, resource_type="Order",
                            resource_id=str(order.id), details=new_status, session=s)
            result = order_to_dict(order, await _load_items(s, order.id))
    except _Abort as e:
        return False, e.code, None
    except Exception as e:
        await log_audit("order_status_failed", level="WARNING", user_id=admin_id,
                        resource_type="Order", resource_id=str(order_id), details=str(e))
        return False, "transaction_error", None

    safe_create_task(invalidate_stats_cache())
    if referrer_id:
        safe_create_task(invalidate_user_cache(referrer_id))
    return True, "success", result
