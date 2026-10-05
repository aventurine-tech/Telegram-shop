"""Product pictures: set / remove / read, and the cached `file_id` shortcut."""
from datetime import datetime, timezone

from sqlalchemy import select, delete as sa_delete, update as sa_update

from bot.database import Database
from bot.database.methods.cache_utils import safe_create_task
from bot.database.methods.read import async_cached, invalidate_item_cache
from bot.database.models import Goods
from bot.database.models.main import ProductImages
from bot.misc.images import ImageError, validate_image


async def set_item_image(item_name: str, data: bytes) -> tuple[bool, str]:
    """Attach (or replace) a product's picture. The bytes are validated and kept unchanged.

    Returns ``(ok, code)``; codes: ``success``, ``item_not_found``, ``too_large``,
    ``invalid_image``, ``unsupported_format``.
    """
    try:
        validate_image(data)
    except ImageError as e:
        return False, e.code

    async with Database().session() as s:
        item_id = (await s.execute(select(Goods.id).where(Goods.name == item_name))).scalar()
        if not item_id:
            return False, "item_not_found"
        row = (await s.execute(
            select(ProductImages).where(ProductImages.item_id == item_id).with_for_update()
        )).scalars().one_or_none()
        if row is None:
            s.add(ProductImages(item_id=item_id, data=data, file_id=None))
        else:
            row.data = data
            row.file_id = None          # the old reference points at the old picture
            row.updated_at = datetime.now(timezone.utc)

    safe_create_task(invalidate_item_cache(item_name))
    return True, "success"


async def remove_item_image(item_name: str) -> bool:
    """Drop a product's picture. True if there was one."""
    async with Database().session() as s:
        item_id = (await s.execute(select(Goods.id).where(Goods.name == item_name))).scalar()
        if not item_id:
            return False
        removed = (await s.execute(
            sa_delete(ProductImages).where(ProductImages.item_id == item_id)
        )).rowcount

    safe_create_task(invalidate_item_cache(item_name))
    return bool(removed)


@async_cached(ttl=900, key_prefix="item_image")
async def get_item_image_ref(item_name: str) -> dict | None:
    """``{"file_id": str | None}`` if the product has a picture, else None. No bytes (cache-safe)."""
    async with Database().session() as s:
        row = (await s.execute(
            select(ProductImages.file_id)
            .join(Goods, Goods.id == ProductImages.item_id)
            .where(Goods.name == item_name)
        )).first()
    return None if row is None else {"file_id": row[0]}


async def get_item_image_bytes(item_name: str) -> bytes | None:
    """The stored picture, for sending when Telegram has no usable `file_id` yet."""
    async with Database().session() as s:
        return (await s.execute(
            select(ProductImages.data)
            .join(Goods, Goods.id == ProductImages.item_id)
            .where(Goods.name == item_name)
        )).scalar()


async def store_image_file_id(item_name: str, file_id: str | None) -> None:
    """Remember the Telegram `file_id` a picture earned (or clear a stale one)."""
    async with Database().session() as s:
        item_id = (await s.execute(select(Goods.id).where(Goods.name == item_name))).scalar()
        if not item_id:
            return
        await s.execute(
            sa_update(ProductImages).where(ProductImages.item_id == item_id)
            .values(file_id=file_id[:256] if file_id else None)
        )

    safe_create_task(invalidate_item_cache(item_name))


async def items_with_images() -> set[str]:
    """Names of products that have a picture (for the web panel list)."""
    async with Database().session() as s:
        rows = await s.execute(
            select(Goods.name).join(ProductImages, ProductImages.item_id == Goods.id)
        )
        return {r[0] for r in rows.all()}


async def has_item_image(item_name: str) -> bool:
    """Uncached "does this product have a picture" check (admin screens must never show a stale answer)."""
    async with Database().session() as s:
        return (await s.execute(
            select(ProductImages.item_id)
            .join(Goods, Goods.id == ProductImages.item_id)
            .where(Goods.name == item_name)
        )).first() is not None
