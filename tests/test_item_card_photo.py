"""Item card with a product picture: photo + caption, file_id reuse, fallbacks, edit_screen."""
import asyncio
import io
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile
from PIL import Image

from bot.database.methods.product_images import (
    set_item_image, get_item_image_ref, store_image_file_id, remove_item_image,
)
from bot.handlers.user._screen import edit_screen
from bot.handlers.user.shop_and_goods import (
    _render_item_page, item_info_callback_handler, back_to_item_handler,
    navigate_goods, CAPTION_LIMIT,
)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 10, 10)).save(buf, "PNG")
    return buf.getvalue()


def _bad_request(text="Bad Request: wrong file identifier/HTTP URL specified"):
    return TelegramBadRequest(method=MagicMock(), message=text)


def _photo_message(call, file_id="NEWFID"):
    """Make the callback's message a real-looking photo message and its sent copy return a file_id."""
    call.message.photo = [MagicMock(file_id="old")]
    sent = MagicMock()
    sent.photo = [MagicMock(file_id="small"), MagicMock(file_id=file_id)]
    call.message.answer_photo = AsyncMock(return_value=sent)
    call.message.edit_caption = AsyncMock()
    call.message.delete = AsyncMock()
    call.message.answer = AsyncMock()
    return call


def _text_message(call, file_id="NEWFID"):
    call.message.photo = None
    sent = MagicMock()
    sent.photo = [MagicMock(file_id=file_id)]
    call.message.answer_photo = AsyncMock(return_value=sent)
    call.message.edit_caption = AsyncMock()
    call.message.delete = AsyncMock()
    return call


class TestItemCardPhoto:
    async def test_photo_sent_with_caption_and_keyboard(self, make_callback_query, fsm_context, item_factory):
        await item_factory(name="PicItem", price=100, stock=5)
        assert (await set_item_image("PicItem", _png()))[0]
        call = _text_message(make_callback_query(data="x", user_id=700001))

        await _render_item_page(call, fsm_context, "PicItem", "gp_0", user_id=700001)

        call.message.answer_photo.assert_awaited_once()
        args, kwargs = call.message.answer_photo.call_args
        assert isinstance(args[0], BufferedInputFile)
        assert "PicItem" in kwargs["caption"]
        assert kwargs["reply_markup"] is not None
        call.message.edit_text.assert_not_called()
        call.message.delete.assert_awaited_once()           # old text message replaced

    async def test_file_id_stored_then_reused(self, make_callback_query, fsm_context, item_factory):
        await item_factory(name="PicItem2", price=100, stock=5)
        await set_item_image("PicItem2", _png())
        call = _text_message(make_callback_query(data="x", user_id=700002), file_id="FID-1")
        await _render_item_page(call, fsm_context, "PicItem2", "gp_0", user_id=700002)
        await asyncio.sleep(0)                  # let the scheduled cache invalidation run
        assert (await get_item_image_ref("PicItem2"))["file_id"] == "FID-1"

        call2 = _text_message(make_callback_query(data="x", user_id=700002))
        await _render_item_page(call2, fsm_context, "PicItem2", "gp_0", user_id=700002)
        assert call2.message.answer_photo.call_args[0][0] == "FID-1"

    async def test_stale_file_id_falls_back_to_bytes_and_refreshes(
            self, make_callback_query, fsm_context, item_factory):
        await item_factory(name="PicItem3", price=100, stock=5)
        await set_item_image("PicItem3", _png())
        await store_image_file_id("PicItem3", "STALE")
        call = _text_message(make_callback_query(data="x", user_id=700003), file_id="FRESH")
        sent = call.message.answer_photo.return_value
        call.message.answer_photo = AsyncMock(side_effect=[_bad_request(), sent])

        await _render_item_page(call, fsm_context, "PicItem3", "gp_0", user_id=700003)

        first, second = call.message.answer_photo.call_args_list
        assert first[0][0] == "STALE"
        assert isinstance(second[0][0], BufferedInputFile)
        await asyncio.sleep(0)
        assert (await get_item_image_ref("PicItem3"))["file_id"] == "FRESH"

    async def test_no_picture_keeps_text_card(self, make_callback_query, fsm_context, item_factory):
        await item_factory(name="PlainItem", price=100, stock=5)
        call = _text_message(make_callback_query(data="x", user_id=700004))

        await _render_item_page(call, fsm_context, "PlainItem", "gp_0", user_id=700004)

        call.message.edit_text.assert_awaited_once()
        call.message.answer_photo.assert_not_called()

    async def test_no_picture_from_photo_message_deletes_and_sends_text(
            self, make_callback_query, fsm_context, item_factory):
        await item_factory(name="PlainItem2", price=100, stock=5)
        call = _photo_message(make_callback_query(data="x", user_id=700005))

        await _render_item_page(call, fsm_context, "PlainItem2", "gp_0", user_id=700005)

        call.message.delete.assert_awaited_once()
        call.message.answer.assert_awaited_once()
        call.message.edit_text.assert_not_called()

    async def test_missing_bytes_fall_back_to_text(self, make_callback_query, fsm_context, item_factory):
        await item_factory(name="PicItem4", price=100, stock=5)
        await set_item_image("PicItem4", _png())
        call = _text_message(make_callback_query(data="x", user_id=700006))
        from unittest.mock import patch
        with patch("bot.handlers.user.shop_and_goods.get_item_image_bytes", AsyncMock(return_value=None)):
            await _render_item_page(call, fsm_context, "PicItem4", "gp_0", user_id=700006)
        call.message.answer_photo.assert_not_called()
        call.message.edit_text.assert_awaited_once()

    async def test_rerender_on_photo_edits_caption(self, make_callback_query, fsm_context, item_factory):
        await item_factory(name="PicItem5", price=100, stock=5)
        await set_item_image("PicItem5", _png())
        call = _photo_message(make_callback_query(data="fav_toggle", user_id=700007))

        await _render_item_page(call, fsm_context, "PicItem5", "gp_0", user_id=700007)

        call.message.edit_caption.assert_awaited_once()
        assert "PicItem5" in call.message.edit_caption.call_args[1]["caption"]
        call.message.answer_photo.assert_not_called()
        call.message.delete.assert_not_called()

    async def test_caption_not_modified_is_ignored(self, make_callback_query, fsm_context, item_factory):
        await item_factory(name="PicItem6", price=100, stock=5)
        await set_item_image("PicItem6", _png())
        call = _photo_message(make_callback_query(data="x", user_id=700008))
        call.message.edit_caption = AsyncMock(side_effect=_bad_request("Bad Request: message is not modified"))

        await _render_item_page(call, fsm_context, "PicItem6", "gp_0", user_id=700008)   # no raise

    async def test_switching_item_from_photo_sends_new_photo(
            self, make_callback_query, fsm_context, item_factory):
        await item_factory(name="PicA", price=100, stock=5)
        await item_factory(name="PicB", price=100, stock=5)
        await set_item_image("PicB", _png())
        await fsm_context.update_data(csrf_item="PicA", goods_page_items=["PicB"], goods_page_num=0)
        call = _photo_message(make_callback_query(data="itm:0:0", user_id=700009))

        await item_info_callback_handler(call, fsm_context)

        call.message.edit_caption.assert_not_called()
        call.message.answer_photo.assert_awaited_once()
        call.message.delete.assert_awaited_once()

    async def test_back_from_photo_card_deletes_and_sends_list_as_text(
            self, make_callback_query, fsm_context, category_factory, item_factory):
        await item_factory(name="PicItem7", price=100, stock=5, category="TestCategory")
        await fsm_context.update_data(current_category="TestCategory", categories_last_viewed_page=0)
        call = _photo_message(make_callback_query(data="gp_0", user_id=700010))

        await navigate_goods(call, fsm_context)

        call.message.delete.assert_awaited_once()
        call.message.answer.assert_awaited_once()
        call.message.edit_text.assert_not_called()

    async def test_long_description_trimmed_to_caption_limit(
            self, make_callback_query, fsm_context, item_factory):
        await item_factory(name="LongPic", price=100, stock=5, description="<b>" + "word " * 600)
        await set_item_image("LongPic", _png())
        call = _text_message(make_callback_query(data="x", user_id=700011))

        await _render_item_page(call, fsm_context, "LongPic", "gp_0", user_id=700011)

        caption = call.message.answer_photo.call_args[1]["caption"]
        assert len(caption) <= CAPTION_LIMIT
        assert "…" in caption
        assert "shop.item.price" in caption and "shop.item.in_stock" in caption

    async def test_removed_picture_uses_text_card(self, make_callback_query, fsm_context, item_factory):
        await item_factory(name="PicItem8", price=100, stock=5)
        await set_item_image("PicItem8", _png())
        await remove_item_image("PicItem8")
        call = _text_message(make_callback_query(data="x", user_id=700012))
        await _render_item_page(call, fsm_context, "PicItem8", "gp_0", user_id=700012)
        call.message.edit_text.assert_awaited_once()


class TestEditScreen:
    async def test_text_message_is_edited(self, make_callback_query):
        call = make_callback_query()
        call.message.photo = None
        await edit_screen(call, "hi", reply_markup="kb", parse_mode="HTML")
        call.message.edit_text.assert_awaited_once_with("hi", reply_markup="kb", parse_mode="HTML")

    async def test_mock_photo_attribute_is_not_a_photo(self, make_callback_query):
        call = make_callback_query()          # .photo is an AsyncMock attribute, not a list
        await edit_screen(call, "hi")
        call.message.edit_text.assert_awaited_once()
        call.message.delete.assert_not_called()

    async def test_photo_message_is_replaced(self, make_callback_query):
        call = make_callback_query()
        call.message.photo = [MagicMock()]
        call.message.delete = AsyncMock()
        call.message.answer = AsyncMock()
        await edit_screen(call, "hi", reply_markup="kb")
        call.message.delete.assert_awaited_once()
        call.message.answer.assert_awaited_once_with("hi", reply_markup="kb")
        call.message.edit_text.assert_not_called()

    async def test_delete_error_is_ignored(self, make_callback_query):
        call = make_callback_query()
        call.message.photo = [MagicMock()]
        call.message.delete = AsyncMock(side_effect=_bad_request("message can't be deleted"))
        call.message.answer = AsyncMock()
        await edit_screen(call, "hi")
        call.message.answer.assert_awaited_once()
