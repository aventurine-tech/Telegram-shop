from sqlalchemy import func, select, delete as sa_delete

from bot.database.methods.read import invalidate_item_cache, invalidate_category_cache
from bot.database.methods.cache_utils import safe_create_task
from bot.database.models import Database, Goods, Categories, Role, User
from bot.database.models.main import PromoCodes, CartItems, Reviews, StockSubscriptions, ProductImages
from bot.database.methods.audit import log_audit


async def delete_item(item_name: str) -> None:
    """Delete a product. Order lines that reference it keep their name/price snapshot."""
    category_name = None
    option_names: list[str] = []
    async with Database().session() as s:
        result = await s.execute(select(Goods).where(Goods.name == item_name))
        item = result.scalars().first()
        if item:
            category_name = (await s.execute(
                select(Categories.name).where(Categories.id == item.category_id)
            )).scalar()
            # A head takes its weight options with it.
            options = (await s.execute(select(Goods.id, Goods.name).where(Goods.variant_of == item.id))).all()
            option_names = [n for _, n in options]
            for oid, _ in options:
                await s.execute(sa_delete(ProductImages).where(ProductImages.item_id == oid))
                await s.execute(sa_delete(CartItems).where(CartItems.item_id == oid))
                await s.execute(sa_delete(StockSubscriptions).where(StockSubscriptions.item_id == oid))
                await s.execute(sa_delete(Goods).where(Goods.id == oid))
            await s.execute(sa_delete(ProductImages).where(ProductImages.item_id == item.id))
            await s.delete(item)

    safe_create_task(invalidate_item_cache(item_name))
    for n in option_names:
        safe_create_task(invalidate_item_cache(n))
    if category_name:
        # The category's cached item count changed.
        safe_create_task(invalidate_category_cache(category_name))


async def delete_category(category_name: str) -> str:
    """Delete a category and all products/stock inside it (CASCADE handles items).

    A category that still has subcategories is refused (``"has_subcategories"``) rather than
    silently taking them with it. Returns ``"ok"`` or ``"not_found"`` otherwise.
    """
    async with Database().session() as s:
        result = await s.execute(select(Categories).where(Categories.name == category_name))
        cat = result.scalars().first()
        if not cat:
            return "not_found"
        if (await s.execute(select(func.count(Categories.id)).where(Categories.parent_id == cat.id))).scalar():
            return "has_subcategories"
        items_result = await s.execute(select(Goods.name).where(Goods.category_id == cat.id))
        items = items_result.all()
        item_names = [i[0] for i in items]
        if item_names:
            await log_audit(
                "cascade_delete",
                resource_type="Category",
                resource_id=category_name,
                details=f"deleted items: {item_names}",
                session=s,
            )
        await s.execute(sa_delete(ProductImages).where(
            ProductImages.item_id.in_(select(Goods.id).where(Goods.category_id == cat.id))
        ))
        await s.delete(cat)

    safe_create_task(invalidate_category_cache(category_name))
    # The category delete cascades to its goods; their per-item caches (item_info / stock) would otherwise serve deleted products until TTL, so invalidate each one
    for name in item_names:
        safe_create_task(invalidate_item_cache(name))
    return "ok"


async def delete_role(role_id: int) -> tuple[bool, str | None]:
    """Delete a role. Fails if users are assigned, it's default, or it's a built-in role."""
    async with Database().session() as s:
        result = await s.execute(select(Role).where(Role.id == role_id))
        role = result.scalars().first()
        if not role:
            return False, "Role not found"
        if role.default:
            return False, "Cannot delete the default role"
        if role.name in ('USER', 'ADMIN', 'OWNER'):
            return False, "Cannot delete built-in roles"
        user_count = (await s.execute(
            select(func.count(User.telegram_id)).where(User.role_id == role_id)
        )).scalar() or 0
        if user_count > 0:
            return False, f"Role has {user_count} users assigned"
        await s.delete(role)
        return True, None


async def delete_promo_code(promo_id: int) -> bool:
    """Delete a promo code by ID."""
    async with Database().session() as s:
        result = await s.execute(select(PromoCodes).where(PromoCodes.id == promo_id))
        promo = result.scalars().first()
        if promo:
            await s.delete(promo)
            return True
        return False


async def remove_from_cart(cart_item_id: int, user_id: int = None) -> bool:
    """Remove a single item from cart by CartItems ID."""
    async with Database().session() as s:
        clause = CartItems.id == cart_item_id
        if user_id is not None:
            clause = clause & (CartItems.user_id == user_id)
        result = await s.execute(sa_delete(CartItems).where(clause))
        return result.rowcount > 0


async def clear_cart(user_id: int) -> int:
    """Clear all cart items for a user. Returns count deleted."""
    async with Database().session() as s:
        result = await s.execute(sa_delete(CartItems).where(CartItems.user_id == user_id))
        return result.rowcount


async def unsubscribe_from_stock(user_id: int, item_name: str) -> bool:
    """Drop a user's restock subscription for an item."""
    async with Database().session() as s:
        item_id = (await s.execute(select(Goods.id).where(Goods.name == item_name))).scalar()
        if not item_id:
            return False
        result = await s.execute(
            sa_delete(StockSubscriptions).where(
                StockSubscriptions.user_id == user_id,
                StockSubscriptions.item_id == item_id,
            )
        )
        return result.rowcount > 0


async def pop_stock_subscribers(item_name: str) -> list[int]:
    """Claim and remove every restock subscription for an item.

    Locks the rows before deleting them so two concurrent restocks cannot both
    notify the same user: the loser waits on the locks, then finds nothing.
    """
    async with Database().session() as s:
        item_id = (await s.execute(select(Goods.id).where(Goods.name == item_name))).scalar()
        if not item_id:
            return []

        rows = (await s.execute(
            select(StockSubscriptions.id, StockSubscriptions.user_id)
            .where(StockSubscriptions.item_id == item_id)
            .with_for_update()
        )).all()
        if not rows:
            return []

        await s.execute(
            sa_delete(StockSubscriptions).where(
                StockSubscriptions.id.in_([r.id for r in rows])
            )
        )
        return [r.user_id for r in rows]


async def delete_review(review_id: int) -> bool:
    """Delete a review by ID."""
    async with Database().session() as s:
        result = await s.execute(sa_delete(Reviews).where(Reviews.id == review_id))
        return result.rowcount > 0
