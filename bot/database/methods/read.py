import datetime
from decimal import Decimal
from functools import wraps
from types import SimpleNamespace
from typing import Optional, Dict, TypeVar, Callable, Any, Coroutine

from sqlalchemy import func, exists, select, or_, inspect as sa_inspect
from sqlalchemy.orm import aliased

from bot.database.models import Database, User, Goods, Categories, Role, \
    Operations, ReferralEarnings, Permission
from bot.database.models.main import (
    PromoCodes, PromoCodeUsages, CartItems, Reviews, StockSubscriptions,
    Orders, OrderItems, OrderStatus,
)
from bot.misc.caching import get_cache_manager, single_flight

F = TypeVar('F', bound=Callable[..., Coroutine[Any, Any, Any]])


def async_cached(ttl: int = 300, key_prefix: str = "", cache_empty: bool = True) -> Callable[[F], F]:
    """Decorator for async functions with caching.

    Misses are single-flighted (see single_flight): concurrent callers of the
    same key wait for one computation instead of all hitting the DB when a hot
    key expires.
    """

    def decorator(async_func: F) -> F:
        @wraps(async_func)
        async def async_wrapper(*args, **kwargs):
            key_parts = [str(arg) for arg in args]
            # Keyword arguments belong in the key too:
            # without them f(1) and f(x=1) would share the entry f: and serve each other's results.
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = f"{key_prefix or async_func.__name__}:{':'.join(key_parts)}"

            cache = get_cache_manager()
            if not cache:
                return await async_func(*args, **kwargs)

            return await single_flight(
                cache, cache_key, lambda: async_func(*args, **kwargs), ttl,
                should_cache=(
                    None if cache_empty
                    else (lambda result: result is not None and bool(result))
                ),
            )

        return async_wrapper

    return decorator


def _day_window(date_str: str) -> tuple[datetime.datetime, datetime.datetime]:
    d = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    start = datetime.datetime.combine(d, datetime.time.min, tzinfo=datetime.timezone.utc)
    end = start + datetime.timedelta(days=1)
    return start, end


def _obj_to_dict(obj, model=None) -> dict:
    """Convert an ORM object to a dict of its column values."""
    mapper = sa_inspect(model if model is not None else type(obj))
    return {attr.key: getattr(obj, attr.key) for attr in mapper.column_attrs}


async def _fetch_one_dict(model, *whereclauses) -> dict | None:
    """Fetch a single 'model' row matching the where-clauses as a dict, or None."""
    async with Database().session() as s:
        obj = (await s.execute(select(model).where(*whereclauses))).scalars().first()
        return _obj_to_dict(obj, model) if obj else None


# --- Async implementations ---

async def check_user(telegram_id: int | str) -> Optional[dict]:
    """Return user by Telegram ID or None if not found."""
    return await _fetch_one_dict(User, User.telegram_id == telegram_id)


async def get_user_languages(telegram_ids) -> dict[int, str | None]:
    """{telegram_id: language or None} for the given users, in one query (for per-recipient messages)."""
    ids = list(dict.fromkeys(telegram_ids))
    if not ids:
        return {}
    async with Database().session() as s:
        rows = await s.execute(select(User.telegram_id, User.language).where(User.telegram_id.in_(ids)))
        return {r[0]: r[1] for r in rows.all()}


async def check_role(telegram_id: int) -> int:
    """Return permission bitmask for user (0 if none)."""
    async with Database().session() as s:
        result = await s.execute(
            select(Role.permissions).join(User, User.role_id == Role.id).where(User.telegram_id == telegram_id)
        )
        return result.scalar() or 0


async def get_role_id_by_name(role_name: str) -> Optional[int]:
    """Return role id by name or None."""
    async with Database().session() as s:
        return (await s.execute(select(Role.id).where(Role.name == role_name))).scalar()


async def check_role_name_by_id(role_id: int) -> str:
    """Return role name by id (raises if not found)."""
    async with Database().session() as s:
        result = await s.execute(select(Role.name).where(Role.id == role_id))
        return result.scalar_one()


async def select_max_role_id() -> Optional[int]:
    """Return role_id with the highest numeric permissions value (OWNER=127)."""
    async with Database().session() as s:
        result = await s.execute(select(Role.id).order_by(Role.permissions.desc()).limit(1))
        row = result.first()
        return row[0] if row else None


async def get_all_roles() -> list[dict]:
    """Return all roles as list of dicts ordered by permissions asc."""
    async with Database().session() as s:
        result = await s.execute(select(Role).order_by(Role.permissions.asc()))
        roles = result.scalars().all()
        return [{'id': r.id, 'name': r.name, 'permissions': r.permissions, 'default': r.default} for r in roles]


async def get_role_by_id(role_id: int) -> dict | None:
    """Return single role as dict or None."""
    async with Database().session() as s:
        result = await s.execute(select(Role).where(Role.id == role_id))
        r = result.scalars().first()
        return {'id': r.id, 'name': r.name, 'permissions': r.permissions, 'default': r.default} if r else None


async def get_roles_with_max_perms(max_perms: int) -> list[dict]:
    """Return roles whose permissions are a subset of max_perms (bitwise)."""
    async with Database().session() as s:
        result = await s.execute(select(Role).order_by(Role.permissions.asc()))
        roles = result.scalars().all()
        return [
            {'id': r.id, 'name': r.name, 'permissions': r.permissions, 'default': r.default}
            for r in roles
            if (r.permissions & ~max_perms) == 0
        ]


async def count_users_with_role(role_id: int) -> int:
    """Return count of users assigned to a given role."""
    async with Database().session() as s:
        return (await s.execute(
            select(func.count(User.telegram_id)).where(User.role_id == role_id)
        )).scalar() or 0


async def get_roles_with_user_counts() -> list[dict]:
    """Return all non-default roles that have at least 1 user, with user count."""
    async with Database().session() as s:
        result = await s.execute(
            select(Role.name, Role.permissions, func.count(User.telegram_id))
            .join(User, User.role_id == Role.id)
            .where(Role.default == False)  # noqa: E712
            .group_by(Role.id, Role.name, Role.permissions)
            .having(func.count(User.telegram_id) > 0)
            .order_by(Role.permissions.asc())
        )
        return [
            {'name': name, 'permissions': perms, 'user_count': count}
            for name, perms, count in result.all()
        ]


async def select_today_users(date: str) -> int:
    """Return count of users registered on given date (YYYY-MM-DD)."""
    start_of_day, end_of_day = _day_window(date)
    async with Database().session() as s:
        return (await s.execute(
            select(func.count()).select_from(User).where(
                User.registration_date >= start_of_day,
                User.registration_date < end_of_day
            )
        )).scalar() or 0


async def get_user_count() -> int:
    """Return total users count."""
    async with Database().session() as s:
        return (await s.execute(select(func.count()).select_from(User))).scalar() or 0


async def select_admins() -> int:
    """Return count of users whose role has any admin permission (beyond USE)."""
    async with Database().session() as s:
        return (await s.execute(
            select(func.count(User.telegram_id))
            .join(Role, User.role_id == Role.id)
            .where(Role.permissions.op('&')(~Permission.USE) != 0)
        )).scalar() or 0


async def get_all_users() -> list[tuple[int]]:
    """Return list of all user telegram_ids (as tuples)."""
    async with Database().session() as s:
        result = await s.execute(select(User.telegram_id))
        return result.all()


async def get_item_info(item_name: str) -> dict | None:
    """Return item (position) row as dict by name, or None."""
    return await _fetch_one_dict(Goods, Goods.name == item_name)


async def get_items_info(item_names: list[str]) -> dict[str, dict]:
    """Return {name: item_row_dict} for the given names in a single query."""
    names = [n for n in dict.fromkeys(item_names)]  # dedupe, preserve order
    if not names:
        return {}
    async with Database().session() as s:
        result = await s.execute(select(Goods).where(Goods.name.in_(names)))
        return {g.name: _obj_to_dict(g, Goods) for g in result.scalars().all()}


async def get_head_name(item_name: str) -> str:
    """The head product's name for a weight option (reviews and ratings live on the head); a head or
    standalone product — or an unknown name — comes back unchanged."""
    async with Database().session() as s:
        head = aliased(Goods)
        name = (await s.execute(
            select(head.name).join(Goods, Goods.variant_of == head.id).where(Goods.name == item_name)
        )).scalar()
    return name or item_name


async def get_item_family(item_name: str) -> dict | None:
    """A product with its weight options, from the name of the head *or* of any option.

    ``{"head": row, "options": [row, ...], "current": row}`` — options in creation order, rows as
    for get_item_info. ``options`` is empty for a standalone product. None if the name is unknown."""
    async with Database().session() as s:
        cur = (await s.execute(select(Goods).where(Goods.name == item_name))).scalars().first()
        if cur is None:
            return None
        head = cur
        if cur.variant_of is not None:
            head = (await s.execute(select(Goods).where(Goods.id == cur.variant_of))).scalars().one()
        opts = (await s.execute(
            select(Goods).where(Goods.variant_of == head.id).order_by(Goods.id)
        )).scalars().all()
        return {"head": _obj_to_dict(head, Goods),
                "options": [_obj_to_dict(o, Goods) for o in opts],
                "current": _obj_to_dict(cur, Goods)}


async def get_option_by_id(goods_id: int) -> dict | None:
    """A weight option's row by id; None for a head, a standalone product or an unknown id."""
    return await _fetch_one_dict(Goods, Goods.id == goods_id, Goods.variant_of.is_not(None))


async def resolve_item_name(text: str) -> str | None:
    """Canonical product name for something an admin typed: the canonical name itself, else a
    translated name in any language (case-insensitive). None if nothing matches."""
    return await _resolve_name(Goods, text)


async def resolve_category_name(text: str) -> str | None:
    """Canonical category name for something an admin typed (canonical or any translation)."""
    return await _resolve_name(Categories, text)


async def _resolve_name(model, text: str) -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    async with Database().session() as s:
        exact = (await s.execute(select(model.name).where(model.name == text))).scalar()
        if exact:
            return exact
        # Case-insensitive match over the translations. Folded in Python rather than SQL `lower()`,
        # which is ASCII-only on SQLite; this runs only on an admin's typed lookup over a small table.
        wanted = text.casefold()
        rows = await s.execute(
            select(model.name, model.name_en, model.name_ru, model.name_ro).order_by(model.id)
        )
        for canonical, *translations in rows.all():
            if any(v and v.strip().casefold() == wanted for v in (canonical, *translations)):
                return canonical
    return None


async def get_category_by_id(category_id: int) -> dict | None:
    """Category row (all columns, incl. translations and parent_id) by id, or None."""
    return await _fetch_one_dict(Categories, Categories.id == int(category_id))


async def category_children_count(category_id: int) -> int:
    """How many subcategories a category has."""
    async with Database().session() as s:
        return (await s.execute(
            select(func.count(Categories.id)).where(Categories.parent_id == category_id)
        )).scalar() or 0


async def category_items_count(category_id: int) -> int:
    """How many products sit directly in a category."""
    async with Database().session() as s:
        return (await s.execute(
            select(func.count(Goods.id)).where(Goods.category_id == category_id)
        )).scalar() or 0


async def category_accepts_items(category_name: str) -> bool:
    """A product may only go into an existing category that has no subcategories."""
    async with Database().session() as s:
        cat_id = (await s.execute(select(Categories.id).where(Categories.name == category_name))).scalar()
        if cat_id is None:
            return False
        return not (await s.execute(
            select(exists().where(Categories.parent_id == cat_id))
        )).scalar()


async def parent_assignment_error(s, parent: Categories, own_id: int | None = None) -> str | None:
    """Why ``parent`` cannot be the parent of a category, or None when it can (shared by the bot and the web panel).

    ``own_id`` is the category being (re)parented (None for a new one). Codes: self_parent,
    parent_not_top_level (two levels at most), has_children (a category with subcategories cannot
    become a subcategory), parent_has_items (a parent holds subcategories, not products).
    """
    if own_id is not None and parent.id == own_id:
        return "self_parent"
    if parent.parent_id is not None:
        return "parent_not_top_level"
    if own_id is not None and (await s.execute(
            select(exists().where(Categories.parent_id == own_id)))).scalar():
        return "has_children"
    if (await s.execute(select(exists().where(Goods.category_id == parent.id)))).scalar():
        return "parent_has_items"
    return None


async def check_category(category_name: str) -> dict | None:
    """Return category as dict by name, or None."""
    return await _fetch_one_dict(Categories, Categories.name == category_name)


async def get_category_name_by_id(category_id: int) -> str | None:
    """Return a category's name by its id, or None."""
    async with Database().session() as s:
        return (await s.execute(
            select(Categories.name).where(Categories.id == category_id)
        )).scalar()


async def get_item_name_by_id(item_id: int) -> str | None:
    """Return a product's name by its id, or None.

    Handy for callers that only hold an item id (e.g. a callback payload).
    """
    async with Database().session() as s:
        return (await s.execute(
            select(Goods.name).where(Goods.id == item_id)
        )).scalar()


async def select_item_stock(item_name: str) -> int:
    """Return units on hand for an item (by item name); 0 when the item is unknown."""
    async with Database().session() as s:
        return (await s.execute(
            select(Goods.stock).where(Goods.name == item_name)
        )).scalar() or 0


async def select_user_items(buyer_id: int | str) -> int:
    """Return count of orders the user has placed (cancelled ones excluded)."""
    async with Database().session() as s:
        return (await s.execute(
            select(func.count()).select_from(Orders).where(
                Orders.user_id == buyer_id, Orders.status != OrderStatus.CANCELLED,
            )
        )).scalar() or 0


async def select_count_items() -> int:
    """Return total units in stock across all products."""
    async with Database().session() as s:
        return (await s.execute(select(func.coalesce(func.sum(Goods.stock), 0)))).scalar() or 0


async def select_count_goods() -> int:
    """Return total count of goods (positions)."""
    async with Database().session() as s:
        return (await s.execute(select(func.count()).select_from(Goods))).scalar() or 0


async def select_count_categories() -> int:
    """Return total count of categories."""
    async with Database().session() as s:
        return (await s.execute(select(func.count()).select_from(Categories))).scalar() or 0


async def select_count_bought_items() -> int:
    """Return total units sold (cancelled orders excluded)."""
    async with Database().session() as s:
        return (await s.execute(
            select(func.coalesce(func.sum(OrderItems.quantity), 0))
            .join(Orders, Orders.id == OrderItems.order_id)
            .where(Orders.status != OrderStatus.CANCELLED)
        )).scalar() or 0


async def select_unique_buyers() -> int:
    """Return count of unique users who placed at least one (non-cancelled) order."""
    async with Database().session() as s:
        return (await s.execute(
            select(func.count(func.distinct(Orders.user_id))).where(Orders.status != OrderStatus.CANCELLED)
        )).scalar() or 0


async def select_avg_order() -> Decimal:
    """Return the average order total (cancelled orders excluded)."""
    async with Database().session() as s:
        return (await s.execute(
            select(func.avg(Orders.total)).where(Orders.status != OrderStatus.CANCELLED)
        )).scalar() or Decimal(0)


async def select_today_orders_count(date: str) -> int:
    """Return number of orders placed on the given date (cancelled excluded)."""
    start_of_day, end_of_day = _day_window(date)
    async with Database().session() as s:
        return (await s.execute(
            select(func.count()).select_from(Orders).where(
                Orders.status != OrderStatus.CANCELLED,
                Orders.created_at >= start_of_day,
                Orders.created_at < end_of_day,
            )
        )).scalar() or 0


async def select_blocked_users_count() -> int:
    """Return count of blocked users."""
    async with Database().session() as s:
        return (await s.execute(
            select(func.count()).select_from(User).where(User.is_blocked == True)  # noqa: E712
        )).scalar() or 0


async def get_blocked_user_ids() -> list[int]:
    """Return list of telegram_ids of all blocked users."""
    async with Database().session() as s:
        result = await s.execute(
            select(User.telegram_id).where(User.is_blocked == True)  # noqa: E712
        )
        return [row[0] for row in result.all()]


async def select_today_orders(date: str) -> Decimal:
    """Return total of orders placed on the given date (YYYY-MM-DD), cancelled excluded."""
    start_of_day, end_of_day = _day_window(date)
    async with Database().session() as s:
        res = (await s.execute(
            select(func.sum(Orders.total)).where(
                Orders.status != OrderStatus.CANCELLED,
                Orders.created_at >= start_of_day,
                Orders.created_at < end_of_day,
            )
        )).scalar()
        return res or Decimal(0)


async def select_all_orders() -> Decimal:
    """Return total of all orders ever placed (cancelled excluded)."""
    async with Database().session() as s:
        return (await s.execute(
            select(func.sum(Orders.total)).where(Orders.status != OrderStatus.CANCELLED)
        )).scalar() or Decimal(0)


async def select_today_operations(date: str) -> Decimal:
    """Return total operations value for given date (YYYY-MM-DD)."""
    start_of_day, end_of_day = _day_window(date)
    async with Database().session() as s:
        res = (await s.execute(
            select(func.sum(Operations.operation_value)).where(
                Operations.operation_time >= start_of_day,
                Operations.operation_time < end_of_day
            )
        )).scalar()
        return res or Decimal(0)


async def select_all_operations() -> Decimal:
    """Return total operations value for all time."""
    async with Database().session() as s:
        return (await s.execute(select(func.sum(Operations.operation_value)))).scalar() or Decimal(0)


async def select_users_balance() -> Decimal:
    """Return sum of all users' balances (0 when there are none)."""
    async with Database().session() as s:
        return (await s.execute(
            select(func.coalesce(func.sum(User.balance), 0))
        )).scalar() or Decimal(0)


async def select_user_operations_total(user_id: int | str) -> Decimal:
    """Total of a user's operations, summed server-side (avoids pulling every row)."""
    async with Database().session() as s:
        return (await s.execute(
            select(func.coalesce(func.sum(Operations.operation_value), 0))
            .where(Operations.user_id == user_id)
        )).scalar() or Decimal(0)


async def check_user_referrals(user_id: int) -> int:
    """Return count of referrals of the user."""
    async with Database().session() as s:
        return (await s.execute(
            select(func.count()).select_from(User).where(User.referral_id == user_id)
        )).scalar() or 0


async def get_user_referral(user_id: int) -> Optional[int]:
    """Return referral_id of the user or None."""
    async with Database().session() as s:
        result = await s.execute(select(User.referral_id).where(User.telegram_id == user_id))
        row = result.first()
        return row[0] if row else None


async def get_user_profile_aggregates(user_id: int, role_id: int | None) -> dict:
    """Everything the admin user-profile screen needs, in one query."""
    async with Database().session() as s:
        row = (await s.execute(
            select(
                select(func.coalesce(func.sum(Operations.operation_value), 0))
                .where(Operations.user_id == user_id)
                .scalar_subquery().label("operations_total"),

                select(func.count()).select_from(Orders)
                .where(Orders.user_id == user_id, Orders.status != OrderStatus.CANCELLED)
                .scalar_subquery().label("items_count"),

                select(func.count()).select_from(User)
                .where(User.referral_id == user_id)
                .scalar_subquery().label("referrals"),

                select(func.count(ReferralEarnings.id))
                .where(ReferralEarnings.referrer_id == user_id)
                .scalar_subquery().label("earnings_count"),

                select(func.coalesce(func.sum(ReferralEarnings.amount), 0))
                .where(ReferralEarnings.referrer_id == user_id)
                .scalar_subquery().label("earnings_amount"),

                select(func.coalesce(func.sum(ReferralEarnings.original_amount), 0))
                .where(ReferralEarnings.referrer_id == user_id)
                .scalar_subquery().label("earnings_original"),

                select(func.count(func.distinct(ReferralEarnings.referral_id)))
                .where(ReferralEarnings.referrer_id == user_id)
                .scalar_subquery().label("active_referrals"),

                select(User.is_blocked).where(User.telegram_id == user_id)
                .scalar_subquery().label("is_blocked"),

                select(Role.name).where(Role.id == role_id)
                .scalar_subquery().label("role_name"),
            )
        )).one()

    return {
        "operations_total": row.operations_total or Decimal(0),
        "items_count": row.items_count or 0,
        "referrals": row.referrals or 0,
        "role_name": row.role_name,
        "blocked": bool(row.is_blocked),
        "earnings": {
            "total_earnings_count": row.earnings_count or 0,
            "total_amount": row.earnings_amount or Decimal(0),
            "total_original_amount": row.earnings_original or Decimal(0),
            "active_referrals_count": row.active_referrals or 0,
        },
    }


async def get_referral_earnings_stats(referrer_id: int) -> Dict:
    """Get statistics on user referral charges."""
    async with Database().session() as s:
        result = await s.execute(
            select(
                func.count(ReferralEarnings.id).label('total_earnings_count'),
                func.sum(ReferralEarnings.amount).label('total_amount'),
                func.sum(ReferralEarnings.original_amount).label('total_original_amount'),
                func.count(func.distinct(ReferralEarnings.referral_id)).label('active_referrals_count')
            ).where(ReferralEarnings.referrer_id == referrer_id)
        )
        stats = result.first()

        return {
            'total_earnings_count': stats.total_earnings_count or 0,
            'total_amount': stats.total_amount or Decimal(0),
            'total_original_amount': stats.total_original_amount or Decimal(0),
            'active_referrals_count': stats.active_referrals_count or 0
        }


async def get_one_referral_earning(earning_id: int, referrer_id: int | None = None) -> dict | None:
    """Get one referral earning as a dict, or None.

    When ``referrer_id`` is given the row must belong to that referrer, so a user
    can only read their own earnings. Admin views pass ``referrer_id=None`` after
    an explicit permission check.
    """
    clauses = [ReferralEarnings.id == earning_id]
    if referrer_id is not None:
        clauses.append(ReferralEarnings.referrer_id == referrer_id)
    return await _fetch_one_dict(ReferralEarnings, *clauses)


# --- Cached versions ---

@async_cached(ttl=600, key_prefix="user")
async def check_user_cached(telegram_id: int | str):
    """Cached version of check_user"""
    return await check_user(telegram_id)


async def check_role_cached(telegram_id: int) -> int:
    """Cached permission bitmask for a user.

    Delegates to the shared role cache in the auth middleware (in-process tier
    first, then Redis, then the DB). role 0 (unknown user) is intentionally not cached.
    """
    from bot.middleware.security import get_role_cached
    return await get_role_cached(telegram_id)


@async_cached(ttl=1800, key_prefix="category")
async def check_category_cached(category_name: str):
    """Cached Category Check"""
    return await check_category(category_name)


@async_cached(ttl=900, key_prefix="item_info")
async def get_item_info_cached(item_name: str):
    """Cached product information"""
    return await get_item_info(item_name)


@async_cached(ttl=300, key_prefix="item_values")
async def select_item_stock_cached(item_name: str):
    """Cached units on hand"""
    return await select_item_stock(item_name)


@async_cached(ttl=60, key_prefix="user_count")
async def get_user_count_cached():
    """Cached number of users"""
    return await get_user_count()


@async_cached(ttl=60, key_prefix="admin_count")
async def select_admins_cached():
    """Cached number of admins"""
    return await select_admins()


# Cache invalidation functions
async def invalidate_user_cache(user_id: int):
    """Invalidate a user's cached row, role and paginator counts.

    Batched into one round-trip: this runs on every purchase, payment, checkout
    and balance change. Only keys the app actually writes are listed.
    New per-user caches must be added below.
    """
    cache = get_cache_manager()
    if cache:
        await cache.delete_many((
            f"user:{user_id}",
            f"auth:role:{user_id}",
            f"count:orders:{user_id}",
            f"count:ops:{user_id}",
        ))

    # The auth middleware keeps its own in-process role cache; drop that entry
    # too so a role change takes effect before its TTL.
    from bot.middleware.security import get_auth_middleware
    mw = get_auth_middleware()
    if mw is not None:
        mw.admin_cache.pop(user_id, None)


async def invalidate_item_cache(item_name: str, category_name: str = None):
    """Invalidate every cache entry keyed by a product's name.
    """
    cache = get_cache_manager()
    if cache:
        keys = [
            f"item_info:{item_name}",
            f"item_values:{item_name}",
            f"item_image:{item_name}",
            f"avg_rating:{item_name}",
            f"count:reviews:{item_name}",
        ]
        if category_name:
            keys.append(f"category:{category_name}")
            keys.append(f"category_items:{category_name}:count")
        await cache.delete_many(keys)


async def invalidate_category_cache(category_name: str):
    """Invalidate category cache.

    ``category_items:<name>:count`` is the only key in that namespace
    (lazy_queries._cached_count), so it is deleted by name.
    """
    cache = get_cache_manager()
    if cache:
        await cache.delete_many((
            f"category:{category_name}",
            "categories:count",
            f"category_items:{category_name}:count",
        ))


async def invalidate_stats_cache():
    """Invalidate the statistics caches with targeted deletes (no Redis SCAN).

    This runs on nearly every write (purchases, balance changes, catalog
    edits), so it must not use invalidate_pattern — a SCAN per write. Keys
    match how they are built: async_cached appends a colon to zero-arg
    functions (user_count:/admin_count:), stats:daily is keyed by the
    dashboard's local date (UTC included for the midnight window). The hourly
    scheduler sweep janitors any stale dated keys.
    """
    cache = get_cache_manager()
    if cache:
        today_local = datetime.date.today().isoformat()
        today_utc = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        await cache.delete_many({
            f"stats:daily:{today_local}",
            f"stats:daily:{today_utc}", "user_count:", "admin_count:",
        })


# --- Promo codes ---

async def get_promo_code(code: str) -> dict | None:
    """Return promo code by code string, or None."""
    return await _fetch_one_dict(PromoCodes, PromoCodes.code == code.upper())


async def promo_rule_error(s, promo, user_id, *, goods=None, require_balance=False,
                           used: bool | None = None) -> str | None:
    """Shared promo-code business rules; returns a canonical error code or None if valid.

    Canonical codes: not_found, inactive, wrong_type, expired, max_uses, already_used, wrong_item, wrong_category
    each caller maps them to its own user-facing keys. wrong_item/wrong_category
    also cover a promo whose bound item/category has since been deleted.

    - ``promo``: the already-fetched PromoCodes row (or None).
    - ``goods``: the Goods row the promo applies to, for item/category binding (ignored when ``require_balance`` is True).
    - ``require_balance``: True for balance-type redemption, False for discount promos.
    - ``used``: pre-computed "already used by this user" flag; when None (the
      default) it is looked up here. Batch callers pass it to avoid one
      EXISTS query per promo.
    ``s`` is the caller's open session (so the per-user usage check joins the same transaction / row locks).
    """
    if not promo:
        return "not_found"
    if not promo.is_active:
        return "inactive"
    # discount promos must NOT be balance-type; balance redemption requires it.
    if require_balance != (promo.discount_type == "balance"):
        return "wrong_type"

    expires_at = promo.expires_at
    if expires_at is not None:
        # SQLite returns naive datetimes for DateTime(timezone=True); treat naive as
        # UTC so the comparison is valid on every backend (mirrors coerce_sale_until).
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)
        if expires_at < datetime.datetime.now(datetime.timezone.utc):
            return "expired"

    if 0 < promo.max_uses <= promo.current_uses:
        return "max_uses"

    if used is None:
        used = (await s.execute(
            select(exists().where(
                PromoCodeUsages.promo_id == promo.id,
                PromoCodeUsages.user_id == user_id,
            ))
        )).scalar()
    if used:
        return "already_used"

    if not require_balance:
        if promo.scope == "item" and promo.item_id is None:
            return "wrong_item"
        if promo.scope == "category" and promo.category_id is None:
            return "wrong_category"
        if promo.item_id and (goods is None or promo.item_id != goods.id):
            return "wrong_item"
        if promo.category_id:
            if goods is None:
                return "wrong_category"
            if promo.category_id != goods.category_id:
                # A promo bound to a parent category also covers the products of its subcategories.
                parent_id = (await s.execute(
                    select(Categories.parent_id).where(Categories.id == goods.category_id)
                )).scalar()
                if parent_id != promo.category_id:
                    return "wrong_category"

    return None


# Canonical promo error code -> user-facing key for the read-side validator.
_VALIDATE_PROMO_ERRORS = {
    "not_found": "promo.not_found",
    "inactive": "promo.inactive",
    "wrong_type": "promo.not_balance_type",
    "expired": "promo.expired",
    "max_uses": "promo.max_uses_reached",
    "already_used": "promo.already_used",
    "wrong_item": "promo.wrong_item",
    "wrong_category": "promo.wrong_category",
}


async def validate_promo_for_item(
        code: str, item_name: str, user_id: int
) -> tuple[bool, str, dict]:
    """
    Validate a promo code for a specific item and user.
    Returns (valid, error_key, promo_dict).
    """
    async with Database().session() as s:
        promo = (await s.execute(
            select(PromoCodes).where(PromoCodes.code == code.upper())
        )).scalars().first()
        goods = (await s.execute(
            select(Goods).where(Goods.name == item_name)
        )).scalars().first()

        err = await promo_rule_error(s, promo, user_id, goods=goods, require_balance=False)
        if err:
            return False, _VALIDATE_PROMO_ERRORS[err], {}

        return True, "", _obj_to_dict(promo, PromoCodes)


async def validate_promos_for_cart(
        user_id: int, lines: list[dict], info_map: dict[str, dict]
) -> dict[int, tuple[bool, str, dict]]:
    """Batch counterpart of validate_promo_for_item for a whole cart.

    Same verdicts, but one session and one query per table (promos, usages)
    for all lines instead of two queries per line; goods binding is checked
    against the already-loaded ``info_map`` (from get_items_info) instead of
    re-fetching each Goods row.

    Returns {cart line id: (valid, error_key, promo_dict)} for lines that
    carry a promo_code.
    """
    coded = [ln for ln in lines if ln.get('promo_code')]
    if not coded:
        return {}

    codes = {ln['promo_code'].upper() for ln in coded}
    async with Database().session() as s:
        promos = (await s.execute(
            select(PromoCodes).where(PromoCodes.code.in_(codes))
        )).scalars().all()
        promo_by_code = {p.code: p for p in promos}

        used_ids: set[int] = set()
        if promos:
            used_ids = set((await s.execute(
                select(PromoCodeUsages.promo_id).where(
                    PromoCodeUsages.user_id == user_id,
                    PromoCodeUsages.promo_id.in_([p.id for p in promos]),
                )
            )).scalars().all())

        out: dict[int, tuple[bool, str, dict]] = {}
        for ln in coded:
            promo = promo_by_code.get(ln['promo_code'].upper())
            info = info_map.get(ln['item_name'])
            goods = (
                SimpleNamespace(id=info['id'], category_id=info['category_id'])
                if info else None
            )
            err = await promo_rule_error(
                s, promo, user_id, goods=goods, require_balance=False,
                used=(promo.id in used_ids) if promo else False,
            )
            if err:
                out[ln['id']] = (False, _VALIDATE_PROMO_ERRORS[err], {})
            else:
                out[ln['id']] = (True, "", _obj_to_dict(promo, PromoCodes))
        return out


# --- Cart ---

async def get_cart_items(user_id: int) -> list[dict]:
    """Return all cart items for user; each dict includes the current item_name for display."""
    async with Database().session() as s:
        result = await s.execute(
            select(CartItems, Goods.name.label('item_name'),
                   Goods.name_en, Goods.name_ru, Goods.name_ro)
            .join(Goods, Goods.id == CartItems.item_id)
            .where(CartItems.user_id == user_id)
            .order_by(CartItems.added_at.desc())
        )
        items = []
        for ci, item_name, name_en, name_ru, name_ro in result.all():
            d = _obj_to_dict(ci, CartItems)
            d['item_name'] = item_name
            d['name'] = item_name          # canonical key `pick(line, 'name')` falls back to
            # translations ride along so the cart can show names in the viewer's language
            d.update(name_en=name_en, name_ru=name_ru, name_ro=name_ro)
            items.append(d)
        return items


async def get_cart_count(user_id: int) -> int:
    """Return the total number of units in a user's cart.

    Units, not lines: this feeds the cart badge and the checkout confirmation,
    and both must agree with the number of items the receipt lists.
    """
    async with Database().session() as s:
        return int((await s.execute(
            select(func.coalesce(func.sum(CartItems.quantity), 0)).where(CartItems.user_id == user_id)
        )).scalar() or 0)


# --- Stock subscriptions ---

async def is_subscribed_to_stock(user_id: int, item_name: str) -> bool:
    """Whether the user is waiting for this item to be restocked.
    """
    async with Database().session() as s:
        return bool((await s.execute(
            select(exists().where(
                StockSubscriptions.user_id == user_id,
                StockSubscriptions.item_id == Goods.id,
                Goods.name == item_name,
            ))
        )).scalar())


# --- Reviews ---

@async_cached(ttl=600, key_prefix="avg_rating")
async def get_item_avg_rating(item_name: str) -> float | None:
    """Return average rating for an item, or None if no reviews (options share their head's)."""
    item_name = await get_head_name(item_name)
    async with Database().session() as s:
        result = (await s.execute(
            select(func.avg(Reviews.rating))
            .join(Goods, Goods.id == Reviews.item_id)
            .where(Goods.name == item_name)
        )).scalar()
        return round(float(result), 1) if result else None


async def has_purchased_item(user_id: int, item_name: str) -> bool:
    """Check if the user has received an item (a *completed* order contains it, or — for a head
    product — any of its weight options)."""
    async with Database().session() as s:
        head = aliased(Goods)
        family = select(Goods.name).outerjoin(head, Goods.variant_of == head.id).where(
            or_(Goods.name == item_name, head.name == item_name))
        return (await s.execute(
            select(exists().where(
                OrderItems.order_id == Orders.id,
                Orders.user_id == user_id,
                Orders.status == OrderStatus.COMPLETED,
                OrderItems.item_name.in_(family),
            ))
        )).scalar()


async def get_user_review(user_id: int, item_name: str) -> dict | None:
    """Return user's review for an item, or None."""
    item_name = await get_head_name(item_name)
    async with Database().session() as s:
        obj = (await s.execute(
            select(Reviews)
            .join(Goods, Goods.id == Reviews.item_id)
            .where(Reviews.user_id == user_id, Goods.name == item_name)
        )).scalars().first()
        return _obj_to_dict(obj, Reviews) if obj else None


async def invalidate_rating_cache(item_name: str):
    """Invalidate the review caches for an item (average and count)."""
    item_name = await get_head_name(item_name)
    cache = get_cache_manager()
    if cache:
        await cache.delete_many((
            f"avg_rating:{item_name}",
            f"count:reviews:{item_name}",
        ))
