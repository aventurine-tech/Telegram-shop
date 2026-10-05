"""Product pictures: validation and storage. The bytes are kept exactly as uploaded."""
import asyncio
import io

import pytest
from PIL import Image
from sqlalchemy import select, func

from bot.database.main import Database
from bot.database.methods.delete import delete_item, delete_category
from bot.database.methods.product_images import (
    set_item_image, remove_item_image, get_item_image_ref, get_item_image_bytes,
    store_image_file_id, items_with_images,
)
from bot.database.methods.read import get_item_info
from bot.database.models.main import ProductImages
from bot.misc.images import ImageError, validate_image, MAX_IMAGE_BYTES


def _img(fmt="PNG", size=(40, 30), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


class TestValidate:

    @pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
    def test_accepts_common_formats(self, fmt):
        assert validate_image(_img(fmt)) == fmt

    @pytest.mark.parametrize("data,code", [
        (b"", "invalid_image"),
        (b"not an image at all", "invalid_image"),
        (_img("PNG")[:40], "invalid_image"),                 # truncated
        (_img("GIF"), "unsupported_format"),
        (_img("BMP"), "unsupported_format"),
        (b"\x00" * (MAX_IMAGE_BYTES + 1), "too_large"),
    ])
    def test_rejects(self, data, code):
        with pytest.raises(ImageError) as exc:
            validate_image(data)
        assert exc.value.code == code

    def test_rejects_huge_pixel_count(self, monkeypatch):
        monkeypatch.setattr("bot.misc.images.MAX_IMAGE_PIXELS", 100)
        with pytest.raises(ImageError) as exc:
            validate_image(_img("PNG", size=(20, 20)))
        assert exc.value.code == "too_large"


class TestStorage:

    async def test_set_keeps_bytes_unchanged(self, item_factory):
        await item_factory(name="Pic")
        data = _img("JPEG")
        assert await set_item_image("Pic", data) == (True, "success")
        assert await get_item_image_bytes("Pic") == data
        assert await get_item_image_ref("Pic") == {"file_id": None}

    async def test_no_picture(self, item_factory):
        await item_factory(name="Plain")
        assert await get_item_image_ref("Plain") is None
        assert await get_item_image_bytes("Plain") is None

    async def test_unknown_item_and_bad_image(self, item_factory):
        await item_factory(name="Bad")
        assert await set_item_image("Nope", _img()) == (False, "item_not_found")
        assert await set_item_image("Bad", b"junk") == (False, "invalid_image")
        assert await get_item_image_ref("Bad") is None

    async def test_replace_clears_the_stale_file_id(self, item_factory):
        await item_factory(name="Swap")
        await set_item_image("Swap", _img(color=(1, 2, 3)))
        await store_image_file_id("Swap", "tg-file-1")
        await asyncio.sleep(0)
        assert (await get_item_image_ref("Swap"))["file_id"] == "tg-file-1"

        newer = _img(color=(9, 9, 9))
        await set_item_image("Swap", newer)
        await asyncio.sleep(0)

        assert (await get_item_image_ref("Swap"))["file_id"] is None
        assert await get_item_image_bytes("Swap") == newer
        async with Database().session() as s:
            assert (await s.execute(select(func.count()).select_from(ProductImages))).scalar() == 1

    async def test_remove(self, item_factory):
        await item_factory(name="Gone")
        await set_item_image("Gone", _img())
        assert await remove_item_image("Gone") is True
        assert await remove_item_image("Gone") is False
        assert await get_item_image_ref("Gone") is None

    async def test_file_id_is_cleared_on_request(self, item_factory):
        await item_factory(name="Stale")
        await set_item_image("Stale", _img())
        await store_image_file_id("Stale", "x")
        await store_image_file_id("Stale", None)
        await asyncio.sleep(0)
        assert (await get_item_image_ref("Stale"))["file_id"] is None

    async def test_bytes_never_leak_into_item_info(self, item_factory):
        await item_factory(name="Lean")
        await set_item_image("Lean", _img())
        info = await get_item_info("Lean")
        assert "data" not in info and "image" not in info
        assert not any(isinstance(v, bytes) for v in info.values())

    async def test_items_with_images(self, item_factory):
        await item_factory(name="HasPic")
        await item_factory(name="NoPic", category="Other")
        await set_item_image("HasPic", _img())
        assert await items_with_images() == {"HasPic"}

    async def test_deleting_the_product_deletes_its_picture(self, item_factory):
        await item_factory(name="Doomed")
        await set_item_image("Doomed", _img())
        await delete_item("Doomed")
        async with Database().session() as s:
            assert (await s.execute(select(func.count()).select_from(ProductImages))).scalar() == 0

    async def test_deleting_the_category_deletes_pictures(self, item_factory):
        await item_factory(name="InCat", category="Doomed Cat")
        await set_item_image("InCat", _img())
        await delete_category("Doomed Cat")
        async with Database().session() as s:
            assert (await s.execute(select(func.count()).select_from(ProductImages))).scalar() == 0

    async def test_cache_is_invalidated_on_change(self, item_factory, fake_cache):
        await item_factory(name="Cached")
        await set_item_image("Cached", _img())
        await asyncio.sleep(0)
        assert await get_item_image_ref("Cached") == {"file_id": None}
        assert "item_image:Cached" in fake_cache.store

        await store_image_file_id("Cached", "fid")
        await asyncio.sleep(0)
        assert "item_image:Cached" not in fake_cache.store
        assert await get_item_image_ref("Cached") == {"file_id": "fid"}
