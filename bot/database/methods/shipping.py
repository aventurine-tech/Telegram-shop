"""Shipping methods: what the customer can choose when they want delivery, and what it costs."""
from decimal import Decimal

from sqlalchemy import select

from bot.database import Database
from bot.database.models.main import ShippingMethods

_ZERO = Decimal("0.00")


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def method_to_dict(m: ShippingMethods) -> dict:
    return {
        "id": m.id, "name": m.name, "name_en": m.name_en, "name_ru": m.name_ru, "name_ro": m.name_ro,
        "price": _money(m.price), "free_from": None if m.free_from is None else _money(m.free_from),
        "is_active": bool(m.is_active), "position": m.position,
    }


def delivery_fee(method: dict | ShippingMethods, goods_total) -> Decimal:
    """The price of this method for an order whose goods come to ``goods_total`` (free above the threshold)."""
    get = method.get if isinstance(method, dict) else (lambda k: getattr(method, k))
    free_from = get("free_from")
    if free_from is not None and _money(goods_total) >= _money(free_from):
        return _ZERO
    return _money(get("price"))


async def active_methods() -> list[dict]:
    """Methods offered at checkout, in the order the shop set (position, then id)."""
    async with Database().session() as s:
        rows = (await s.execute(
            select(ShippingMethods).where(ShippingMethods.is_active.is_(True))
            .order_by(ShippingMethods.position, ShippingMethods.id)
        )).scalars().all()
        return [method_to_dict(m) for m in rows]


async def get_active_method(method_id: int) -> dict | None:
    async with Database().session() as s:
        m = (await s.execute(select(ShippingMethods).where(
            ShippingMethods.id == method_id, ShippingMethods.is_active.is_(True)))).scalars().first()
        return method_to_dict(m) if m else None
