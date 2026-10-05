from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, exists, func as sa_func
from sqlalchemy.exc import IntegrityError

from bot.database.models import User, Goods, Categories, Role
from bot.database.models.main import PromoCodes, CartItems, Reviews, StockSubscriptions, promo_scope_for
from bot.database import Database
from bot.database.methods.cache_utils import safe_create_task
from bot.database.methods.read import invalidate_stats_cache, invalidate_item_cache, invalidate_category_cache

# Cart limits: distinct positions per cart, and units of any one position.
CART_MAX_ITEMS = 10
CART_MAX_QTY_PER_ITEM = 99


async def create_user(telegram_id: int, registration_date: datetime, referral_id: int | None, role: int = 1) -> None:
    """Create user if missing; commit."""
    async with Database().session() as s:
        result = await s.execute(select(exists().where(User.telegram_id == telegram_id)))
        if result.scalar():
            return
        s.add(
            User(
                telegram_id=telegram_id,
                role_id=role,
                registration_date=registration_date,
                referral_id=referral_id,
            )
        )
        try:
            await s.flush()
        except IntegrityError:
            # Lost the race — the user now exists, which is the desired outcome.
            await s.rollback()


async def create_item(item_name: str, item_description: str, item_price: int, category_name: str,
                      stock: int = 0, names: dict[str, str] | None = None,
                      descriptions: dict[str, str] | None = None) -> None:
    """Insert item (goods) with its initial stock; commit. Resolves category_name to category_id.

    ``names`` / ``descriptions`` optionally carry display translations ``{lang: text}``."""
    from bot.misc.localized import LANGS, clean_name, clean_description
    translated = {
        **{f"name_{l}": clean_name(v) for l, v in (names or {}).items() if l in LANGS},
        **{f"description_{l}": clean_description(v) for l, v in (descriptions or {}).items() if l in LANGS},
    }
    async with Database().session() as s:
        result = await s.execute(select(exists().where(Goods.name == item_name)))
        if result.scalar():
            return
        cat = (await s.execute(select(Categories.id).where(Categories.name == category_name))).scalar()
        if not cat:
            return
        # A category with subcategories holds no products of its own.
        if (await s.execute(select(exists().where(Categories.parent_id == cat)))).scalar():
            return
        s.add(
            Goods(
                name=item_name,
                description=item_description,
                price=item_price,
                category_id=cat,
                stock=max(int(stock), 0),
                **translated,
            )
        )

    safe_create_task(invalidate_stats_cache())
    # The category's cached item count changed.
    safe_create_task(invalidate_category_cache(category_name))


async def create_category(category_name: str, names: dict[str, str] | None = None) -> None:
    """Insert category; commit. ``names`` optionally carries display translations ``{lang: text}``."""
    from bot.misc.localized import LANGS, clean_name
    async with Database().session() as s:
        result = await s.execute(select(exists().where(Categories.name == category_name)))
        if result.scalar():
            return
        s.add(Categories(
            name=category_name,
            **{f"name_{l}": clean_name(v) for l, v in (names or {}).items() if l in LANGS},
        ))

    safe_create_task(invalidate_stats_cache())
    # Drops the cached categories:count
    safe_create_task(invalidate_category_cache(category_name))


async def create_subcategory(category_name: str, parent_name: str,
                             names: dict[str, str] | None = None) -> tuple[bool, str]:
    """Create a category under a top-level parent. Returns ``(ok, code)``.

    Codes: success, exists, parent_not_found, parent_not_top_level, parent_has_items.
    """
    from bot.misc.localized import LANGS, clean_name
    async with Database().session() as s:
        if (await s.execute(select(exists().where(Categories.name == category_name)))).scalar():
            return False, "exists"
        parent = (await s.execute(
            select(Categories).where(Categories.name == parent_name).with_for_update()
        )).scalars().one_or_none()
        if parent is None:
            return False, "parent_not_found"
        if parent.parent_id is not None:
            return False, "parent_not_top_level"          # two levels at most
        if (await s.execute(select(exists().where(Goods.category_id == parent.id)))).scalar():
            return False, "parent_has_items"              # a parent holds subcategories, not products
        s.add(Categories(
            name=category_name, parent_id=parent.id,
            **{f"name_{l}": clean_name(v) for l, v in (names or {}).items() if l in LANGS},
        ))

    safe_create_task(invalidate_stats_cache())
    safe_create_task(invalidate_category_cache(parent_name))
    safe_create_task(invalidate_category_cache(category_name))
    return True, "success"


async def create_role(name: str, permissions: int) -> int | None:
    """Create a new role. Returns the new role ID, or None if name conflict."""
    async with Database().session() as s:
        result = await s.execute(select(exists().where(Role.name == name)))
        if result.scalar():
            return None
        role = Role(name=name, permissions=permissions)
        s.add(role)
        await s.flush()
        return role.id


async def create_promo_code(
        code: str,
        discount_type: str,
        discount_value,
        max_uses: int = 0,
        expires_at=None,
        category_id: int = None,
        item_id: int = None,
) -> int | None:
    """Create a promo code. Returns ID or None if code already exists.

    Raises ValueError if bound to both a category and an item.
    """
    from decimal import Decimal

    if category_id is not None and item_id is not None:
        raise ValueError("a promo code cannot be bound to both a category and an item")

    async with Database().session() as s:
        result = await s.execute(select(exists().where(PromoCodes.code == code.upper())))
        if result.scalar():
            return None
        promo = PromoCodes(
            code=code.upper(),
            discount_type=discount_type,
            discount_value=Decimal(str(discount_value)),
            scope=promo_scope_for(category_id, item_id),
            max_uses=max_uses,
            expires_at=expires_at,
            category_id=category_id,
            item_id=item_id,
        )
        s.add(promo)
        await s.flush()
        return promo.id


async def _add_to_cart_once(user_id: int, item_name: str, promo_code: str, quantity: int) -> tuple[bool, str]:
    """One attempt at add_to_cart. See add_to_cart for semantics."""
    async with Database().session() as s:
        # Resolve to the goods id (also serves as the existence check).
        item_id = (await s.execute(
            select(Goods.id).where(Goods.name == item_name)
        )).scalar()
        if not item_id:
            return False, "item_not_found"

        existing = (await s.execute(
            select(CartItems)
            .where(CartItems.user_id == user_id, CartItems.item_id == item_id)
            .with_for_update()
        )).scalars().first()

        if existing:
            if existing.quantity + quantity > CART_MAX_QTY_PER_ITEM:
                return False, "cart_qty_max"
            existing.quantity += quantity
            if promo_code:
                # Latest applied promo wins for the whole line.
                existing.promo_code = promo_code
            return True, "success"

        # Only a new line can fill the cart up
        count = (await s.execute(
            select(sa_func.count(CartItems.id)).where(CartItems.user_id == user_id)
        )).scalar() or 0
        if count >= CART_MAX_ITEMS:
            return False, "cart_full"

        s.add(CartItems(user_id=user_id, item_id=item_id, promo_code=promo_code, quantity=quantity))
        return True, "success"


async def add_to_cart(user_id: int, item_name: str, promo_code: str = None, quantity: int = 1) -> tuple[bool, str]:
    """Add `quantity` units of an item to the user's cart.

    One row per (user, item): adding something already in the cart increments the existing line rather than inserting a duplicate.

    Returns (success, message).
    """
    if quantity < 1:
        return False, "invalid_quantity"

    try:
        return await _add_to_cart_once(user_id, item_name, promo_code, quantity)
    except IntegrityError:
        # Lost the uq_cart_item_per_user race against a concurrent add. Retry once: this attempt finds the row the winner inserted and increments it.
        try:
            return await _add_to_cart_once(user_id, item_name, promo_code, quantity)
        except IntegrityError:
            return False, "cart_conflict"


async def subscribe_to_stock(user_id: int, item_name: str) -> tuple[bool, str]:
    """Subscribe a user to the restock notification for an item.

    Idempotent: subscribing twice is a success, not an error.
    Returns (success, code).
    """
    try:
        async with Database().session() as s:
            item_id = (await s.execute(select(Goods.id).where(Goods.name == item_name))).scalar()
            if not item_id:
                return False, "item_not_found"

            already = (await s.execute(
                select(exists().where(
                    StockSubscriptions.user_id == user_id,
                    StockSubscriptions.item_id == item_id,
                ))
            )).scalar()
            if already:
                return True, "already_subscribed"

            s.add(StockSubscriptions(user_id=user_id, item_id=item_id))
    except IntegrityError:
        # Lost the uq_stock_sub_per_user_item race — the subscription now exists, which is what the caller wanted anyway.
        return True, "already_subscribed"

    return True, "subscribed"


async def create_review(user_id: int, item_name: str, rating: int, text: str = None) -> int | None:
    """Create a review. Returns ID, or None if the item is unknown, already
    reviewed, or the rating is outside 1-5.
    """
    if not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5:
        return None
    if not item_name:
        return None

    async with Database().session() as s:
        item_id = (await s.execute(
            select(Goods.id).where(Goods.name == item_name)
        )).scalar()
        if not item_id:
            return None
        existing = (await s.execute(
            select(exists().where(
                Reviews.user_id == user_id,
                Reviews.item_id == item_id,
            ))
        )).scalar()
        if existing:
            return None
        review = Reviews(user_id=user_id, item_id=item_id, rating=rating, text=text)
        s.add(review)
        await s.flush()
        return review.id
