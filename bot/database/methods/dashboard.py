"""Numbers for the panel's home page: orders, revenue, new clients, top products and what needs attention."""
import datetime
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select

from bot.database import Database
from bot.database.models.main import Goods, OrderItems, Orders, OrderStatus, PaymentStatus, User
from bot.misc.localized import pick
from bot.misc.shop_time import shop_tz, to_shop

PERIODS = (7, 30, 90)
DEFAULT_DAYS = 30
LOW_STOCK = 3
TOP_LIMIT = 5
ATTENTION_LIMIT = 8

_ZERO = Decimal("0.00")


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def parse_days(raw) -> int:
    """The period asked for in ``?days=``; anything but 7, 30 or 90 means the default."""
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_DAYS
    return days if days in PERIODS else DEFAULT_DAYS


def _period(days: int, now: datetime.datetime | None = None) -> tuple[list[datetime.date], datetime.datetime]:
    """The calendar days of the period in the shop's timezone (oldest first) and the UTC moment it starts."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    today = to_shop(now).date()
    dates = [today - datetime.timedelta(days=n) for n in range(days - 1, -1, -1)]
    start = datetime.datetime.combine(dates[0], datetime.time.min, tzinfo=shop_tz())
    return dates, start.astimezone(datetime.timezone.utc)


async def dashboard_data(days: int = DEFAULT_DAYS, now: datetime.datetime | None = None) -> dict:
    """Everything the home page shows for the last ``days`` calendar days (today included, shop timezone).

    Revenue counts completed orders only, delivery included. Cancelled orders are left out of the product ranking
    because their stock went back on the shelf.
    """
    days = parse_days(days)
    dates, start = _period(days, now)
    per_day = {d: {"date": d, "orders": 0, "revenue": _ZERO, "clients": 0} for d in dates}
    statuses: dict[str, int] = defaultdict(int)
    async with Database().session() as s:
        orders = (await s.execute(
            select(Orders.id, Orders.status, Orders.total, Orders.created_at).where(Orders.created_at >= start)
        )).all()
        registered = (await s.execute(
            select(User.registration_date).where(User.registration_date >= start)
        )).scalars().all()
        lines = (await s.execute(
            select(OrderItems.item_id, OrderItems.item_name, OrderItems.name_en, OrderItems.name_ru,
                   OrderItems.name_ro, OrderItems.quantity, OrderItems.line_total, Orders.status)
            .join(Orders, Orders.id == OrderItems.order_id)
            .where(Orders.created_at >= start, Orders.status != OrderStatus.CANCELLED)
        )).all()
        new_orders = (await s.execute(
            select(func.count(Orders.id)).where(Orders.status == OrderStatus.NEW)
        )).scalar_one()
        to_check = (await s.execute(
            select(func.count(Orders.id)).where(
                Orders.payment_status == PaymentStatus.AWAITING_CONFIRMATION,
                Orders.status.in_(OrderStatus.ACTIVE))
        )).scalar_one()
        # A head product that only groups options carries no stock of its own: its options are listed instead.
        heads = select(Goods.variant_of).where(Goods.variant_of.is_not(None))
        thin = (await s.execute(
            select(Goods).where(Goods.stock <= LOW_STOCK, Goods.id.not_in(heads))
            .order_by(Goods.stock, Goods.id).limit(ATTENTION_LIMIT)
        )).scalars().all()

    revenue = _ZERO
    completed = cancelled = 0
    for o in orders:
        day = to_shop(o.created_at).date()
        statuses[o.status] += 1
        if o.status == OrderStatus.CANCELLED:
            cancelled += 1
        row = per_day.get(day)
        if row is None:
            continue
        row["orders"] += 1
        if o.status == OrderStatus.COMPLETED:
            completed += 1
            total = _money(o.total)
            row["revenue"] += total
            revenue += total
    for moment in registered:
        row = per_day.get(to_shop(moment).date())
        if row is not None:
            row["clients"] += 1

    products: dict[object, dict] = {}
    for ln in lines:
        key = ln.item_id if ln.item_id is not None else ("name", ln.item_name)
        name = pick({"name": ln.item_name, "name_en": ln.name_en, "name_ru": ln.name_ru, "name_ro": ln.name_ro}, "name")
        entry = products.setdefault(key, {"name": name, "qty": 0, "sum": _ZERO})
        entry["qty"] += ln.quantity
        entry["sum"] += _money(ln.line_total)
    top = sorted(products.values(), key=lambda p: (-p["qty"], -p["sum"], p["name"]))[:TOP_LIMIT]

    # An option is its own row, already named "<product> · <label>".
    low_stock = [{"id": g.id, "name": pick(g, "name"), "stock": g.stock} for g in thin]

    count = len(orders)
    peak = max([r["revenue"] for r in per_day.values()] + [_ZERO])
    rows = list(per_day.values())
    for r in rows:
        r["share"] = int(r["revenue"] / peak * 100) if peak > 0 else 0
    return {
        "days": days, "periods": PERIODS,
        "orders": count, "completed": completed, "cancelled": cancelled,
        "revenue": revenue, "average": (revenue / completed).quantize(Decimal("0.01")) if completed else _ZERO,
        "cancelled_share": int(round(cancelled * 100 / count)) if count else 0,
        "new_clients": len(registered),
        "per_day": list(reversed(rows)),
        "top_products": top,
        "statuses": [(st, statuses[st]) for st in OrderStatus.ALL if statuses.get(st)],
        "attention": {"new_orders": new_orders, "to_check": to_check, "low_stock": low_stock},
    }
