"""Web admin panel: product picture upload / removal on the product form."""
import io
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from starlette.datastructures import UploadFile

from bot.database.main import Database
from bot.database.methods.product_images import get_item_image_bytes, has_item_image, set_item_image
from bot.database.models.main import Goods
from bot.misc.images import MAX_IMAGE_BYTES
from bot.web.admin import GoodsAdmin, GoodsForm

pytestmark = pytest.mark.usefixtures("english")


def _png(size=(4, 4), fmt="PNG") -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 160, 90)).save(buf, fmt)
    return buf.getvalue()


def _upload(content: bytes, name="pic.png") -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=name)


class TestPictureForm:

    def test_form_has_the_upload_and_remove_controls(self):
        form = GoodsForm()
        assert "picture" in form._fields and "remove_picture" in form._fields
        assert GoodsAdmin.form_base_class is GoodsForm

    def test_list_has_a_picture_column(self):
        assert "picture" in GoodsAdmin.column_list

    async def test_list_cell_shows_yes_or_dash(self):
        view = GoodsAdmin()
        has, shown = await view.get_list_value(MagicMock(picture=True), "picture")
        none, hidden = await view.get_list_value(MagicMock(picture=False), "picture")
        assert (has, shown) == (True, "yes")
        assert (none, hidden) == (False, "—")


class TestPictureUpload:

    def _request(self):
        request = MagicMock()
        request.client.host = "127.0.0.1"
        return request

    async def _goods(self, name):
        async with Database().session() as s:
            return (await s.execute(select(Goods).where(Goods.name == name))).scalars().first()

    async def _save(self, name, data, *, is_created=False, request=None):
        """Replay SQLAdmin: on_model_change, (the row exists after the commit), after_model_change."""
        request = request or self._request()
        view = GoodsAdmin()
        model = await self._goods(name) if not is_created else Goods(name=name)
        await view.on_model_change(data, model, is_created, request)
        if is_created:
            model = await self._goods(name)         # the commit has created the row by now
        with patch('bot.web.admin.log_audit') as audit, \
                patch('bot.web.admin.safe_create_task', side_effect=lambda c: c.close()):
            audit.side_effect = _noop
            await view.after_model_change(data, model, is_created, request)
        return audit

    async def test_edit_with_an_upload_stores_the_picture_unchanged(self, item_factory):
        await item_factory(name="WebItem", price=10, stock=1)
        payload = _png()
        data = {"stock": 1, "picture": _upload(payload), "remove_picture": False}

        audit = await self._save("WebItem", data)

        assert await get_item_image_bytes("WebItem") == payload
        assert "picture" not in data and "remove_picture" not in data    # never reach the model
        assert any(c.args[0] == "sqladmin_update_item_photo" for c in audit.call_args_list)

    async def test_create_stores_the_picture_after_the_row_exists(self, item_factory):
        request = self._request()
        view = GoodsAdmin()
        payload = _png(fmt="WEBP")
        data = {"name_en": "BrandNew", "name_ru": "BrandNew", "description_en": "d", "description_ru": "d", "picture": _upload(payload), "remove_picture": False}
        new_model = Goods(name="BrandNew")

        await view.on_model_change(data, new_model, True, request)
        # Nothing is written while the product has no row yet.
        assert await get_item_image_bytes("BrandNew") is None
        await item_factory(name="BrandNew", price=10, stock=1)      # SQLAdmin's commit
        with patch('bot.web.admin.log_audit') as audit, patch('bot.web.admin.safe_create_task',
                                                              side_effect=lambda c: c.close()):
            audit.side_effect = _noop
            await view.after_model_change(data, await self._goods("BrandNew"), True, request)

        assert await get_item_image_bytes("BrandNew") == payload

    async def test_edit_without_an_upload_keeps_the_current_picture(self, item_factory):
        await item_factory(name="WebKeep", price=10, stock=1)
        original = _png()
        await set_item_image("WebKeep", original)

        await self._save("WebKeep", {"stock": 2, "picture": _upload(b""), "remove_picture": False})

        assert await get_item_image_bytes("WebKeep") == original

    async def test_edit_replaces_the_picture(self, item_factory):
        await item_factory(name="WebSwap", price=10, stock=1)
        await set_item_image("WebSwap", _png(size=(2, 2)))
        new = _png(size=(9, 9), fmt="JPEG")

        await self._save("WebSwap", {"picture": _upload(new), "remove_picture": False})

        assert await get_item_image_bytes("WebSwap") == new

    async def test_remove_checkbox_deletes_the_picture(self, item_factory):
        await item_factory(name="WebDrop", price=10, stock=1)
        await set_item_image("WebDrop", _png())

        audit = await self._save("WebDrop", {"picture": _upload(b""), "remove_picture": True})

        assert not await has_item_image("WebDrop")
        details = [c.kwargs["details"] for c in audit.call_args_list
                   if c.args[0] == "sqladmin_update_item_photo"]
        assert details and "action=remove" in details[0]

    async def test_remove_with_nothing_stored_is_a_quiet_noop(self, item_factory):
        await item_factory(name="WebNone", price=10, stock=1)

        audit = await self._save("WebNone", {"picture": _upload(b""), "remove_picture": True})

        assert not any(c.args[0] == "sqladmin_update_item_photo" for c in audit.call_args_list)

    @pytest.mark.parametrize("content,fragment", [
        (b"this is not an image", "could not be read"),
        (_png(fmt="GIF"), "JPEG, PNG and WEBP"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, "could not be read"),
        (b"x" * (MAX_IMAGE_BYTES + 1), "too large"),
    ])
    async def test_invalid_upload_is_rejected_before_saving(self, item_factory, content, fragment):
        await item_factory(name="WebBad", price=10, stock=1)
        original = _png()
        await set_item_image("WebBad", original)
        data = {"picture": _upload(content), "remove_picture": False}

        with pytest.raises(ValueError, match=fragment):
            await GoodsAdmin().on_model_change(data, await self._goods("WebBad"), False, self._request())

        assert await get_item_image_bytes("WebBad") == original       # untouched

    async def test_upload_and_remove_together_is_refused(self, item_factory):
        await item_factory(name="WebBoth", price=10, stock=1)
        data = {"picture": _upload(_png()), "remove_picture": True}

        with pytest.raises(ValueError, match="not both"):
            await GoodsAdmin().on_model_change(data, await self._goods("WebBoth"), False, self._request())

    async def test_stock_edit_still_notifies_on_restock_with_a_picture(self, mock_bot, item_factory,
                                                                        user_factory):
        from bot.database.methods.create import subscribe_to_stock
        from bot.web.admin import set_notifier_bot
        await user_factory(telegram_id=991001)
        await item_factory(name="WebRestock", price=10, stock=0)
        await subscribe_to_stock(991001, "WebRestock")

        set_notifier_bot(mock_bot)
        try:
            view = GoodsAdmin()
            model = await self._goods("WebRestock")
            data = {"stock": 4, "picture": _upload(_png()), "remove_picture": False}
            scheduled = []
            request = self._request()
            await view.on_model_change(data, model, False, request)
            model.stock = 4
            with patch('bot.web.admin.log_audit') as audit, \
                    patch('bot.web.admin.safe_create_task', side_effect=scheduled.append):
                audit.side_effect = _noop
                await view.after_model_change(data, model, False, request)
            for coro in scheduled:
                await coro
        finally:
            set_notifier_bot(None)

        mock_bot.send_message.assert_awaited_once()
        assert await has_item_image("WebRestock")


async def _noop(*args, **kwargs):
    return None


class TestPanelEndToEnd:
    """Drive the real SQLAdmin create / edit endpoints with a multipart form."""

    @pytest.fixture
    async def client(self, category_factory):
        import httpx
        from bot.web.admin import AdminAuth, create_admin_app

        await category_factory("WebCat")
        app = create_admin_app()
        with patch.object(AdminAuth, "authenticate", return_value=True):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://testserver") as c:
                yield c

    async def _category_id(self):
        from bot.database.models.main import Categories
        async with Database().session() as s:
            return (await s.execute(select(Categories.id).where(Categories.name == "WebCat"))).scalar()

    async def test_create_with_a_picture_then_edit_and_remove(self, client):
        cat = await self._category_id()
        payload = _png()
        form = {"name_en": "E2E Item", "name_ru": "E2E Item", "price": "10", "stock": "3", "category": str(cat),
                "description_en": "d", "description_ru": "d"}

        resp = await client.post("/admin/goods/create", data=form,
                                 files={"picture": ("a.png", payload, "image/png")})
        assert resp.status_code in (200, 302), resp.text[:500]
        assert await get_item_image_bytes("E2E Item") == payload

        async with Database().session() as s:
            gid = (await s.execute(select(Goods.id).where(Goods.name == "E2E Item"))).scalar()

        # Edit without a file keeps the picture.
        resp = await client.post(f"/admin/goods/edit/{gid}", data={**form, "stock": "4"},
                                 files={"picture": ("", b"", "application/octet-stream")})
        assert resp.status_code in (200, 302), resp.text[:500]
        assert await get_item_image_bytes("E2E Item") == payload

        # An invalid file is rejected with the error shown on the form.
        resp = await client.post(f"/admin/goods/edit/{gid}", data=form,
                                 files={"picture": ("a.png", b"junk", "image/png")})
        assert resp.status_code == 400
        assert "could not be read" in resp.text
        assert await get_item_image_bytes("E2E Item") == payload

        # The remove checkbox deletes it.
        resp = await client.post(f"/admin/goods/edit/{gid}", data={**form, "remove_picture": "y"},
                                 files={"picture": ("", b"", "application/octet-stream")})
        assert resp.status_code in (200, 302), resp.text[:500]
        assert not await has_item_image("E2E Item")

    async def test_list_page_marks_products_with_a_picture(self, client, item_factory):
        await item_factory(name="ListWith", price=10, stock=1)
        await item_factory(name="ListWithout", price=10, stock=1)
        await set_item_image("ListWith", _png())

        resp = await client.get("/admin/goods/list")

        assert resp.status_code == 200
        assert "Picture" in resp.text and "ListWith" in resp.text
        # one product has a picture ("yes"), the other shows the dash
        assert resp.text.count(">yes<") + resp.text.count("yes\n") >= 1
