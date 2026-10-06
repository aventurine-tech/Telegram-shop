"""Favorites: products a customer starred. A favorite is always the head product (the card of a weight option
stars its head), so lists show one entry per product."""
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from bot.database import Database
from bot.database.models.main import Favorites, Goods

PAGE_SIZE = 8


async def _head_id(s, item_name: str) -> int | None:
    row = (await s.execute(select(Goods.id, Goods.variant_of).where(Goods.name == item_name))).first()
    if row is None:
        return None
    return row.variant_of if row.variant_of is not None else row.id


async def is_favorite(user_id: int, item_name: str) -> bool:
    async with Database().session() as s:
        head = await _head_id(s, item_name)
        if head is None:
            return False
        return (await s.execute(
            select(Favorites.item_id).where(Favorites.user_id == user_id, Favorites.item_id == head)
        )).first() is not None


async def toggle_favorite(user_id: int, item_name: str) -> bool | None:
    """Star or un-star the product; returns the new state (True = now a favorite), None if the product is unknown."""
    async with Database().session() as s:
        head = await _head_id(s, item_name)
        if head is None:
            return None
        exists = (await s.execute(
            select(Favorites.item_id).where(Favorites.user_id == user_id, Favorites.item_id == head)
        )).first() is not None
        if exists:
            await s.execute(delete(Favorites).where(Favorites.user_id == user_id, Favorites.item_id == head))
            return False
        s.add(Favorites(user_id=user_id, item_id=head))
        try:
            await s.flush()
        except IntegrityError:            # a double tap: it is already there
            await s.rollback()
        return True


async def list_favorites(user_id: int, page: int = 0, page_size: int = PAGE_SIZE) -> tuple[list[dict], int]:
    """One page of the customer's favorites, newest first, as ``(rows, total)``; rows carry the translated names."""
    async with Database().session() as s:
        total = (await s.execute(
            select(func.count()).select_from(Favorites).where(Favorites.user_id == user_id))).scalar() or 0
        rows = (await s.execute(
            select(Goods.id, Goods.name, Goods.name_en, Goods.name_ru, Goods.name_ro)
            .join(Favorites, Favorites.item_id == Goods.id)
            .where(Favorites.user_id == user_id)
            .order_by(Favorites.created_at.desc(), Goods.id.desc())
            .limit(page_size).offset(page * page_size)
        )).all()
        return [dict(r._mapping) for r in rows], total


async def item_name_by_id(item_id: int) -> str | None:
    async with Database().session() as s:
        return (await s.execute(select(Goods.name).where(Goods.id == item_id))).scalar()
