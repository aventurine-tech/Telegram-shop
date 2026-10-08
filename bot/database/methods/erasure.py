"""Erase a customer's personal data on request, keeping the records the shop needs (orders, money, ratings)."""
from sqlalchemy import delete as sa_delete, select, update

from bot.database import Database
from bot.database.methods.audit import log_audit
from bot.database.methods.cache_utils import safe_create_task
from bot.database.methods.read import invalidate_user_cache
from bot.database.models import User
from bot.database.models.main import (
    CartItems, Favorites, Orders, OrderStatus, Reviews, StockSubscriptions,
)
from bot.misc import EnvKeys

ERASED_NAME = "(erased)"
ERASED_PHONE = "-"


async def erase_client(telegram_id: int, *, by: str | None = None) -> tuple[bool, str, dict | None]:
    """Remove who the person is from their profile and past orders, in one transaction.

    Cleared: name, @username, phone, address, city, staff notes; on every order the name, phone, address, comment,
    customer note and payment screenshot; cart, favorites, restock subscriptions and review texts.
    Kept, because the shop's books depend on them: the order rows (amounts, items, dates), the balance, referral links
    and star ratings — none of them identify the person without the Telegram id.

    Codes: ``user_not_found``, ``is_owner`` (the owner account is never erased) and ``has_active_orders`` (finish or
    cancel those first, someone still has to deliver them).
    """
    telegram_id = int(telegram_id)
    if telegram_id == int(EnvKeys.OWNER_ID):
        return False, "is_owner", None
    async with Database().session() as s:
        user = (await s.execute(select(User).where(User.telegram_id == telegram_id).with_for_update())
                ).scalars().one_or_none()
        if user is None:
            return False, "user_not_found", None
        active = (await s.execute(
            select(Orders.id).where(Orders.user_id == telegram_id, Orders.status.in_(OrderStatus.ACTIVE)).limit(1)
        )).first()
        if active:
            return False, "has_active_orders", None

        for column in ("first_name", "last_name", "username", "phone", "address", "contact_name", "city", "notes"):
            setattr(user, column, None)

        orders = (await s.execute(
            update(Orders).where(Orders.user_id == telegram_id).values(
                customer_name=ERASED_NAME, phone=ERASED_PHONE, address=None, comment=None,
                tracking_note=None, payment_proof=None))).rowcount
        reviews = (await s.execute(
            update(Reviews).where(Reviews.user_id == telegram_id, Reviews.text.is_not(None)).values(text=None)
        )).rowcount
        for model in (CartItems, Favorites, StockSubscriptions):
            await s.execute(sa_delete(model).where(model.user_id == telegram_id))

        counts = {"orders": orders or 0, "reviews": reviews or 0}
        await log_audit("client_erased", resource_type="User", resource_id=str(telegram_id), level="WARNING",
                        details=f"by={by or '-'}, orders={counts['orders']}, reviews={counts['reviews']}", session=s)

    safe_create_task(invalidate_user_cache(telegram_id))
    return True, "success", counts
