from typing import Any
from sqlalchemy import case, func, literal, select, or_
from sqlalchemy import desc
from bot.database import Database
from bot.database.models import (
    Categories, Goods, User,
    ReferralEarnings, Operations
)
from bot.database.models.main import PromoCodes, Reviews, Orders, OrderStatus, PaymentStatus
from bot.misc.caching import get_cache_manager
from bot.misc.search_terms import split_terms, term_patterns

# Paginator COUNTs re-run on every page render; a short TTL absorbs that while
# catalog edits stay visible within a minute (targeted invalidation hooks handle the common cases sooner).
_COUNT_TTL = 60


async def _cached_count(cache_key: str, compute) -> int:
    cache = get_cache_manager()
    if cache:
        cached = await cache.get(cache_key)
        if cached is not None:
            return cached
    count = await compute()
    if cache:
        await cache.set(cache_key, count, ttl=_COUNT_TTL)
    return count


def _display_order(model, lang: str | None):
    """ORDER BY the name as the viewer sees it (translation, else canonical), then canonical."""
    from bot.i18n.main import current_language
    from bot.misc.localized import LANGS
    lang = lang or current_language()
    if lang not in LANGS:
        return (model.name.asc(),)
    col = getattr(model, f"name_{lang}")
    return (func.coalesce(func.nullif(func.trim(col), ''), model.name).asc(), model.name.asc())


async def query_categories(offset: int = 0, limit: int = 10, count_only: bool = False,
                           lang: str | None = None) -> Any:
    """Query categories with pagination. Returns canonical names, ordered as the viewer sees them."""
    if count_only:
        async def _count():
            async with Database().session() as s:
                return (await s.execute(
                    select(func.count(Categories.id)).where(Categories.parent_id.is_(None))
                )).scalar() or 0
        return await _cached_count("categories:count", _count)

    async with Database().session() as s:
        result = await s.execute(
            select(Categories.name)
            .where(Categories.parent_id.is_(None))
            .order_by(*_display_order(Categories, lang))
            .offset(offset)
            .limit(limit)
        )
        return [row[0] for row in result.all()]


async def query_top_categories_with_ids(limit: int = 7, lang: str | None = None) -> list[tuple[int, str]]:
    """``[(id, canonical name)]`` of the first top-level categories, ordered as the viewer sees them.

    Feeds the main-menu buttons (callback data carries the id, never a name).
    """
    async with Database().session() as s:
        result = await s.execute(
            select(Categories.id, Categories.name)
            .where(Categories.parent_id.is_(None))
            .order_by(*_display_order(Categories, lang))
            .limit(limit)
        )
        return [(row[0], row[1]) for row in result.all()]


async def query_subcategories(parent_name: str, offset: int = 0, limit: int = 10,
                              count_only: bool = False, lang: str | None = None) -> Any:
    """Subcategories of a category (canonical names, ordered as the viewer sees them).

    Not cached: the sets are tiny and an admin adding one expects it to show at once.
    """
    async with Database().session() as s:
        parent_id = (await s.execute(
            select(Categories.id).where(Categories.name == parent_name)
        )).scalar()
        if parent_id is None:
            return 0 if count_only else []
        base = Categories.parent_id == parent_id
        if count_only:
            return (await s.execute(select(func.count(Categories.id)).where(base))).scalar() or 0
        result = await s.execute(
            select(Categories.name).where(base)
            .order_by(*_display_order(Categories, lang)).offset(offset).limit(limit)
        )
        return [row[0] for row in result.all()]


async def query_items_in_category(category_name: str, offset: int = 0, limit: int = 10,
                                  count_only: bool = False, lang: str | None = None) -> Any:
    """Query items in category with pagination (canonical names, ordered as the viewer sees them)"""
    from bot.database.methods.read import check_category_cached
    cat = await check_category_cached(category_name)
    if not cat:
        return 0 if count_only else []
    cat_id = cat['id']

    query = select(Goods.name).where(Goods.category_id == cat_id, Goods.variant_of.is_(None))
    if count_only:
        async def _count():
            async with Database().session() as s:
                return (await s.execute(
                    select(func.count()).select_from(query.subquery())
                )).scalar() or 0
        return await _cached_count(f"category_items:{category_name}:count", _count)

    async with Database().session() as s:
        result = await s.execute(
            query.order_by(*_display_order(Goods, lang)).offset(offset).limit(limit)
        )
        return [row[0] for row in result.all()]


async def query_goods_search(query: str, offset: int = 0, limit: int = 10,
                             count_only: bool = False, lang: str | None = None) -> Any:
    """Search the catalog by the words describing a product, in any language, with pagination.

    Every word of the query must be found somewhere on the product: its name or description (any language), the
    label of one of its options ("50 mg"), or its category. ``cherry 50mg`` finds "Cherry" with a "50 mg" option.
    Returns a list of names, matching query_items_in_category's shape so the item card and the index-into-page-list
    convention work unchanged; best matches (words found in the name) first.
    """
    terms = split_terms(query)
    if not terms:
        return 0 if count_only else []

    name_columns = (Goods.name, Goods.name_en, Goods.name_ru, Goods.name_ro)
    text_columns = name_columns + (
        Goods.description, Goods.description_en, Goods.description_ru, Goods.description_ro, Goods.variant_label)
    category_columns = (Categories.name, Categories.name_en, Categories.name_ru, Categories.name_ro)

    def any_like(columns, term):
        return or_(*(c.ilike(p, escape='\\') for c in columns for p in term_patterns(term)))

    async with Database().session() as s:
        category_hit = lambda term: (  # noqa: E731 - a category or its parent matches
            select(Categories.id).where(any_like(category_columns, term)).union(
                select(Categories.id).where(Categories.parent_id.in_(
                    select(Categories.id).where(any_like(category_columns, term))))))
        # Weight options never show up on their own: a hit on an option surfaces its head.
        heads_for = lambda term: select(func.coalesce(Goods.variant_of, Goods.id)).where(  # noqa: E731
            or_(any_like(text_columns, term), Goods.category_id.in_(category_hit(term))))
        base = select(Goods.name).where(
            Goods.variant_of.is_(None), *(Goods.id.in_(heads_for(term)) for term in terms))
        if count_only:
            count_result = await s.execute(select(func.count()).select_from(base.subquery()))
            return count_result.scalar() or 0
        in_name = sum((case((any_like(name_columns, term), 1), else_=0) for term in terms), literal(0))
        result = await s.execute(
            base.order_by(in_name.desc(), *_display_order(Goods, lang)).offset(offset).limit(limit)
        )
        return [row[0] for row in result.all()]


async def query_user_orders(user_id: int, offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    """A user's orders (all statuses), newest first."""
    if count_only:
        async def _count():
            async with Database().session() as s:
                return (await s.execute(
                    select(func.count()).select_from(Orders).where(Orders.user_id == user_id)
                )).scalar() or 0
        return await _cached_count(f"count:orders:{user_id}", _count)

    async with Database().session() as s:
        result = await s.execute(
            select(Orders)
            .where(Orders.user_id == user_id)
            .order_by(desc(Orders.created_at), desc(Orders.id))
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all()


async def query_orders(status: str | None = None, offset: int = 0, limit: int = 10,
                       count_only: bool = False, awaiting_payment_check: bool = False) -> Any:
    """Admin order list, newest first.

    ``status`` filters by order status. ``awaiting_payment_check`` narrows to MIA orders
    whose customer says they paid and who are waiting for an admin to verify the transfer.
    Counts are not cached: an admin expects the badge to be live.
    """
    clauses = []
    if status:
        clauses.append(Orders.status == status)
    if awaiting_payment_check:
        clauses.append(Orders.payment_status == PaymentStatus.AWAITING_CONFIRMATION)
        clauses.append(Orders.status != OrderStatus.CANCELLED)

    async with Database().session() as s:
        if count_only:
            return (await s.execute(
                select(func.count()).select_from(Orders).where(*clauses)
            )).scalar() or 0
        result = await s.execute(
            select(Orders).where(*clauses)
            .order_by(desc(Orders.created_at), desc(Orders.id))
            .offset(offset).limit(limit)
        )
        return result.scalars().all()


async def query_all_users(offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    """Query all users with pagination"""
    if count_only:
        async def _count():
            async with Database().session() as s:
                return (await s.execute(select(func.count(User.telegram_id)))).scalar() or 0
        return await _cached_count("count:users", _count)

    async with Database().session() as s:
        result = await s.execute(
            select(User.telegram_id)
            .order_by(User.telegram_id.asc())
            .offset(offset)
            .limit(limit)
        )
        return [row[0] for row in result.all()]


async def query_user_referrals(user_id: int, offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    """Query user's referrals with earnings info"""
    if count_only:
        async def _count():
            async with Database().session() as s:
                return (await s.execute(
                    select(func.count(User.telegram_id)).where(User.referral_id == user_id)
                )).scalar() or 0
        return await _cached_count(f"count:refs:{user_id}", _count)

    async with Database().session() as s:
        earnings_subq = (
            select(
                ReferralEarnings.referral_id,
                func.coalesce(func.sum(ReferralEarnings.amount), 0).label('total_earned')
            )
            .where(ReferralEarnings.referrer_id == user_id)
            .group_by(ReferralEarnings.referral_id)
            .subquery()
        )

        stmt = (
            select(
                User.telegram_id,
                User.registration_date,
                func.coalesce(earnings_subq.c.total_earned, 0).label('total_earned')
            )
            .outerjoin(earnings_subq, User.telegram_id == earnings_subq.c.referral_id)
            .where(User.referral_id == user_id)
            .order_by(desc(func.coalesce(earnings_subq.c.total_earned, 0)), User.telegram_id.asc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await s.execute(stmt)).all()

        return [
            {
                'telegram_id': row.telegram_id,
                'registration_date': row.registration_date,
                'total_earned': row.total_earned
            }
            for row in rows
        ]


async def query_referral_earnings_from_user(referrer_id: int, referral_id: int, offset: int = 0, limit: int = 10,
                                            count_only: bool = False) -> Any:
    """Query earnings from specific referral"""
    if count_only:
        async def _count():
            async with Database().session() as s:
                return (await s.execute(
                    select(func.count(ReferralEarnings.id)).where(
                        ReferralEarnings.referrer_id == referrer_id,
                        ReferralEarnings.referral_id == referral_id,
                    )
                )).scalar() or 0
        return await _cached_count(f"count:earn:{referrer_id}:{referral_id}", _count)

    async with Database().session() as s:
        base = select(ReferralEarnings).where(
            ReferralEarnings.referrer_id == referrer_id,
            ReferralEarnings.referral_id == referral_id
        )
        result = await s.execute(
            base.order_by(desc(ReferralEarnings.created_at), desc(ReferralEarnings.id)).offset(offset).limit(limit)
        )
        return result.scalars().all()


async def query_all_referral_earnings(referrer_id: int, offset: int = 0, limit: int = 10,
                                      count_only: bool = False) -> Any:
    """Query all referral earnings for user"""
    if count_only:
        async def _count():
            async with Database().session() as s:
                return (await s.execute(
                    select(func.count(ReferralEarnings.id))
                    .where(ReferralEarnings.referrer_id == referrer_id)
                )).scalar() or 0
        return await _cached_count(f"count:earn:{referrer_id}", _count)

    async with Database().session() as s:
        base = select(ReferralEarnings).where(
            ReferralEarnings.referrer_id == referrer_id
        )
        result = await s.execute(
            base.order_by(desc(ReferralEarnings.created_at), desc(ReferralEarnings.id)).offset(offset).limit(limit)
        )
        return result.scalars().all()


async def query_promo_codes(offset: int = 0, limit: int = 10, count_only: bool = False) -> Any:
    """Query promo codes with pagination"""
    if count_only:
        async def _count():
            async with Database().session() as s:
                return (await s.execute(select(func.count(PromoCodes.id)))).scalar() or 0
        return await _cached_count("count:promos", _count)

    async with Database().session() as s:
        result = await s.execute(
            select(PromoCodes)
            .order_by(desc(PromoCodes.created_at), desc(PromoCodes.id))
            .offset(offset)
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            {
                'id': p.id, 'code': p.code, 'discount_type': p.discount_type,
                'discount_value': p.discount_value, 'max_uses': p.max_uses,
                'current_uses': p.current_uses, 'is_active': p.is_active,
                'expires_at': p.expires_at, 'created_at': p.created_at,
                'scope': p.scope, 'category_id': p.category_id, 'item_id': p.item_id,
                'dangling': (
                    (p.scope == 'category' and p.category_id is None)
                    or (p.scope == 'item' and p.item_id is None)
                ),
            }
            for p in rows
        ]



async def query_user_operations_history(user_id: int, offset: int = 0, limit: int = 10,
                                        count_only: bool = False) -> Any:
    """Query user's full operations history (topups, purchases, referral bonuses) as UNION ALL"""
    from sqlalchemy import union_all, literal

    if count_only:
        async def _count():
            async with Database().session() as s:
                return (await s.execute(
                    select(
                        select(func.count())
                        .select_from(Operations)
                        .where(Operations.user_id == user_id, Operations.operation_value > 0)
                        .scalar_subquery()
                        + select(func.count())
                        .select_from(Orders)
                        .where(Orders.user_id == user_id, Orders.balance_used > 0,
                               Orders.status != OrderStatus.CANCELLED)
                        .scalar_subquery()
                        + select(func.count())
                        .select_from(ReferralEarnings)
                        .where(ReferralEarnings.referrer_id == user_id)
                        .scalar_subquery()
                    )
                )).scalar() or 0
        return await _cached_count(f"count:ops:{user_id}", _count)

    async with Database().session() as s:
        # 1. Top-ups (operations with positive value)
        topups = (
            select(
                Operations.id,
                literal('topup').label('type'),
                Operations.operation_value.label('amount'),
                Operations.operation_time.label('date'),
            )
            .where(Operations.user_id == user_id, Operations.operation_value > 0)
        )
        # 2. Orders paid (fully or partly) from the balance
        purchases = (
            select(
                Orders.id,
                literal('purchase').label('type'),
                (-Orders.balance_used).label('amount'),
                Orders.created_at.label('date'),
            )
            .where(Orders.user_id == user_id, Orders.balance_used > 0,
                   Orders.status != OrderStatus.CANCELLED)
        )
        # 3. Referral earnings
        referrals = (
            select(
                ReferralEarnings.id,
                literal('referral').label('type'),
                ReferralEarnings.amount.label('amount'),
                ReferralEarnings.created_at.label('date'),
            )
            .where(ReferralEarnings.referrer_id == user_id)
        )

        combined = union_all(topups, purchases, referrals).subquery()

        result = await s.execute(
            select(combined).order_by(combined.c.date.desc(), combined.c.type, combined.c.id.desc()).offset(offset).limit(limit)
        )
        return [
            {
                'id': row.id,
                'type': row.type,
                'amount': row.amount,
                'date': row.date,
            }
            for row in result.all()
        ]


async def query_item_reviews(item_name: str, offset: int = 0, limit: int = 10,
                             count_only: bool = False) -> Any:
    """Query reviews for an item with pagination.

    The count also feeds the item card's review badge, which is rendered on
    every product view — hence the cache (dropped by invalidate_rating_cache).
    Weight options read their head's reviews.
    """
    from bot.database.methods.read import get_head_name
    item_name = await get_head_name(item_name)
    if count_only:
        async def _count():
            async with Database().session() as s:
                return (await s.execute(
                    select(func.count(Reviews.id))
                    .join(Goods, Goods.id == Reviews.item_id)
                    .where(Goods.name == item_name)
                )).scalar() or 0
        return await _cached_count(f"count:reviews:{item_name}", _count)

    async with Database().session() as s:
        base = (
            select(Reviews)
            .join(Goods, Goods.id == Reviews.item_id)
            .where(Goods.name == item_name)
        )
        result = await s.execute(
            base.order_by(desc(Reviews.created_at), desc(Reviews.id)).offset(offset).limit(limit)
        )
        return [
            {
                'id': r.id, 'user_id': r.user_id, 'rating': r.rating,
                'text': r.text, 'created_at': r.created_at,
            }
            for r in result.scalars().all()
        ]
