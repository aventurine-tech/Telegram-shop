import io
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.database.methods.read import get_item_info, select_item_stock
from bot.handlers.admin.adding_position import (
    add_item_callback_handler, check_item_name_for_add, add_item_description,
    add_item_price, check_category_for_add_item, add_item_stock,
    add_item_photo, add_item_skip_photo, add_item_photo_reprompt,
    add_item_name_translation, add_item_description_translation, add_item_skip_translation,
)
from bot.database.methods.product_images import get_item_image_bytes
from bot.misc.images import MAX_IMAGE_BYTES
from bot.states import AddItemFSM


def _skip_call():
    call = AsyncMock()
    call.data = "add_item_skip_tr"
    call.from_user.id = 1
    return call


async def _walk_to_stock_prompt(make_message, fsm_context, *,
                                name="NewItem", price="100", category="AddCat"):
    """Drive the FSM from the name prompt up to the stock quantity prompt (translations skipped)."""
    await check_item_name_for_add(make_message(text=name, user_id=1), fsm_context)
    for _ in range(2):
        await add_item_skip_translation(_skip_call(), fsm_context)
    await add_item_description(make_message(text="A description", user_id=1), fsm_context)
    for _ in range(2):
        await add_item_skip_translation(_skip_call(), fsm_context)
    await add_item_price(make_message(text=price, user_id=1), fsm_context)
    await check_category_for_add_item(make_message(text=category, user_id=1), fsm_context)


class TestAddItemStart:

    async def test_start_sets_the_name_state(self, make_callback_query, fsm_context):
        call = make_callback_query(data="add_item", user_id=900600)
        await add_item_callback_handler(call, fsm_context)

        assert await fsm_context.get_state() == AddItemFSM.waiting_item_name
        call.message.edit_text.assert_called_once()


class TestItemNameStep:

    async def test_valid_name_advances_to_description(self, make_message, fsm_context):
        await check_item_name_for_add(make_message(text="Fresh Item", user_id=1), fsm_context)

        # The name is stored; the other two languages are asked before the description.
        assert await fsm_context.get_state() == AddItemFSM.waiting_item_name_translation
        assert list((await fsm_context.get_data())["item_names"].values()) == ["Fresh Item"]

    async def test_existing_name_is_refused(self, make_message, fsm_context, item_factory):
        await item_factory(name="AlreadyHere", price=10, category="C", stock=1)

        await fsm_context.set_state(AddItemFSM.waiting_item_name)
        await check_item_name_for_add(make_message(text="AlreadyHere", user_id=1), fsm_context)

        assert await fsm_context.get_state() == AddItemFSM.waiting_item_name

    @pytest.mark.parametrize("bad_name", [
        "",
        "   ",
        "A" * 101,          # over the 100-char cap
        "bad\x00name",      # control characters
    ])
    async def test_unsafe_name_is_refused(self, make_message, fsm_context, bad_name):
        await fsm_context.set_state(AddItemFSM.waiting_item_name)
        await check_item_name_for_add(make_message(text=bad_name, user_id=1), fsm_context)

        assert await fsm_context.get_state() == AddItemFSM.waiting_item_name
        assert "item_name" not in await fsm_context.get_data()


class TestPriceStep:

    @pytest.mark.parametrize("text,expected", [
        ("100", 100),
        ("1", 1),                  # the minimum accepted price
        ("99999999", 99_999_999),  # Numeric(12, 2) leaves 10 integer digits
    ])
    async def test_valid_price_advances_to_category(self, make_message, fsm_context,
                                                    text, expected):
        await add_item_price(make_message(text=text, user_id=1), fsm_context)

        assert await fsm_context.get_state() == AddItemFSM.waiting_category
        assert (await fsm_context.get_data())["item_price"] == expected

    @pytest.mark.parametrize("bad_price", [
        "abc", "", "-10", "0",
        "99.99",       # prices are whole units only
        "100000000",   # one over the cap the DB column can hold
        "１００",       # non-ASCII digits are not accepted
    ])
    async def test_invalid_price_keeps_the_state(self, make_message, fsm_context, bad_price):
        await fsm_context.set_state(AddItemFSM.waiting_item_price)
        await add_item_price(make_message(text=bad_price, user_id=1), fsm_context)

        assert await fsm_context.get_state() == AddItemFSM.waiting_item_price
        assert "item_price" not in await fsm_context.get_data()


class TestCategoryStep:

    async def test_existing_category_advances_to_stock(self, make_message, fsm_context,
                                                       category_factory):
        await category_factory("RealCat")

        await check_category_for_add_item(make_message(text="RealCat", user_id=1), fsm_context)

        assert await fsm_context.get_state() == AddItemFSM.waiting_stock
        assert (await fsm_context.get_data())["item_category"] == "RealCat"

    async def test_unknown_category_keeps_the_state(self, make_message, fsm_context):
        await fsm_context.set_state(AddItemFSM.waiting_category)
        await check_category_for_add_item(make_message(text="Ghost", user_id=1), fsm_context)

        assert await fsm_context.get_state() == AddItemFSM.waiting_category
        assert "item_category" not in await fsm_context.get_data()


def _png(size=(4, 4), fmt="PNG") -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, fmt)
    return buf.getvalue()


def _download_returning(payload: bytes):
    """A fake ``bot.download`` that writes ``payload`` into the destination buffer."""
    async def _download(media, destination=None, **kwargs):
        destination.write(payload)
    return AsyncMock(side_effect=_download)


def _photo_message(make_message, payload: bytes, *, document=False, mime="image/png", size=None, user_id=1):
    msg = make_message(text=None, user_id=user_id)
    msg.photo = None
    msg.document = None
    media = MagicMock()
    media.file_size = size if size is not None else len(payload)
    if document:
        media.mime_type = mime
        msg.document = media
    else:
        msg.photo = [MagicMock(file_size=1), media]      # smallest first, largest last
    msg.bot.download = _download_returning(payload)
    return msg, media


async def _walk_to_photo_prompt(make_message, fsm_context, category_factory, *, name="Lamp", stock="12"):
    await category_factory("AddCat")
    await _walk_to_stock_prompt(make_message, fsm_context, name=name)
    await add_item_stock(make_message(text=stock, user_id=1), fsm_context)


@pytest.fixture
def hooks():
    with patch('bot.handlers.admin.adding_position._notify_restock_safe', new_callable=AsyncMock) as notify, \
            patch('bot.handlers.admin.adding_position.announce_arrival', new_callable=AsyncMock) as announce:
        yield notify, announce


class TestStockStep:

    @pytest.mark.parametrize("bad_qty", [
        "abc", "", "-1", "2.5", "1000001", "１０",
    ])
    async def test_invalid_quantity_keeps_the_state(self, make_message, fsm_context,
                                                    category_factory, bad_qty):
        await category_factory("AddCat")
        await _walk_to_stock_prompt(make_message, fsm_context, name="NotYet")

        await add_item_stock(make_message(text=bad_qty, user_id=1), fsm_context)

        assert await fsm_context.get_state() == AddItemFSM.waiting_stock
        assert await get_item_info("NotYet") is None

    async def test_valid_quantity_asks_for_the_photo_and_creates_nothing_yet(
            self, make_message, fsm_context, category_factory):
        await category_factory("AddCat")
        await _walk_to_stock_prompt(make_message, fsm_context, name="Pending")

        msg = make_message(text="5", user_id=1)
        await add_item_stock(msg, fsm_context)

        assert await fsm_context.get_state() == AddItemFSM.waiting_photo
        assert (await fsm_context.get_data())["item_stock"] == 5
        assert "prompt.photo" in msg.answer.call_args[0][0]
        markup = msg.answer.call_args[1]["reply_markup"]
        assert [b.callback_data for r in markup.inline_keyboard for b in r] == [
            "add_item_skip_photo", "goods_management"]
        assert await get_item_info("Pending") is None


class TestPhotoStep:

    async def test_photo_creates_the_product_with_the_picture(
            self, make_message, fsm_context, category_factory, hooks):
        await _walk_to_photo_prompt(make_message, fsm_context, category_factory)
        payload = _png()
        msg, media = _photo_message(make_message, payload)

        await add_item_photo(msg, fsm_context)

        item = await get_item_info("Lamp")
        assert item["price"] == Decimal("100")
        assert item["description"] == "A description"
        assert await select_item_stock("Lamp") == 12
        assert await get_item_image_bytes("Lamp") == payload      # stored unchanged
        assert msg.bot.download.await_args[0][0] is media          # the largest size was used
        assert await fsm_context.get_state() is None

    async def test_image_document_is_accepted_and_kept_unchanged(
            self, make_message, fsm_context, category_factory, hooks):
        await _walk_to_photo_prompt(make_message, fsm_context, category_factory, name="DocLamp")
        payload = _png(fmt="WEBP")
        msg, _ = _photo_message(make_message, payload, document=True, mime="image/webp")

        await add_item_photo(msg, fsm_context)

        assert await get_item_image_bytes("DocLamp") == payload
        assert await get_item_info("DocLamp") is not None

    async def test_skip_creates_the_product_without_a_picture(
            self, make_message, make_callback_query, fsm_context, category_factory, hooks):
        await _walk_to_photo_prompt(make_message, fsm_context, category_factory, name="Plain")

        call = make_callback_query(data="add_item_skip_photo", user_id=1)
        await add_item_skip_photo(call, fsm_context)

        assert await get_item_info("Plain") is not None
        assert await select_item_stock("Plain") == 12
        assert await get_item_image_bytes("Plain") is None
        call.message.answer.assert_called_once()
        assert await fsm_context.get_state() is None

    @pytest.mark.parametrize("payload,expected", [
        (b"not an image at all", "photo.invalid"),
        (b"", "photo.invalid"),
        (_png(fmt="GIF"), "photo.unsupported"),
    ])
    async def test_bad_file_is_refused_and_the_admin_can_retry(
            self, make_message, fsm_context, category_factory, hooks, payload, expected):
        await _walk_to_photo_prompt(make_message, fsm_context, category_factory, name="Retry")
        msg, _ = _photo_message(make_message, payload, document=True, mime="image/png")

        await add_item_photo(msg, fsm_context)

        assert expected in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() == AddItemFSM.waiting_photo
        assert await get_item_info("Retry") is None

        good = _png()
        retry, _ = _photo_message(make_message, good)
        await add_item_photo(retry, fsm_context)
        assert await get_item_image_bytes("Retry") == good

    async def test_oversize_file_is_refused_without_downloading(
            self, make_message, fsm_context, category_factory, hooks):
        await _walk_to_photo_prompt(make_message, fsm_context, category_factory, name="Huge")
        msg, _ = _photo_message(make_message, _png(), document=True, size=MAX_IMAGE_BYTES + 1)

        await add_item_photo(msg, fsm_context)

        assert "photo.too_large" in msg.answer.call_args[0][0]
        msg.bot.download.assert_not_awaited()
        assert await fsm_context.get_state() == AddItemFSM.waiting_photo
        assert await get_item_info("Huge") is None

    async def test_failed_download_is_reported_and_retryable(
            self, make_message, fsm_context, category_factory, hooks):
        await _walk_to_photo_prompt(make_message, fsm_context, category_factory, name="Flaky")
        msg, _ = _photo_message(make_message, _png())
        msg.bot.download = AsyncMock(side_effect=RuntimeError("telegram is down"))

        await add_item_photo(msg, fsm_context)

        assert "photo.download_failed" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() == AddItemFSM.waiting_photo

    async def test_text_at_the_photo_step_reprompts(self, make_message, fsm_context, category_factory):
        await _walk_to_photo_prompt(make_message, fsm_context, category_factory, name="Chatty")

        msg = make_message(text="here you go", user_id=1)
        await add_item_photo_reprompt(msg)

        assert "photo.reprompt" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() == AddItemFSM.waiting_photo
        assert await get_item_info("Chatty") is None

    async def test_picture_is_not_stored_when_creation_fails(
            self, make_message, fsm_context, category_factory, hooks):
        await _walk_to_photo_prompt(make_message, fsm_context, category_factory, name="Doomed")
        msg, _ = _photo_message(make_message, _png())

        with patch('bot.handlers.admin.adding_position.create_item', new_callable=AsyncMock), \
                patch('bot.handlers.admin.adding_position.set_item_image', new_callable=AsyncMock) as store:
            await add_item_photo(msg, fsm_context)

        store.assert_not_awaited()
        assert await get_item_info("Doomed") is None
        assert await get_item_image_bytes("Doomed") is None

    async def test_zero_stock_is_allowed_and_not_announced(
            self, make_message, make_callback_query, fsm_context, category_factory, hooks):
        notify, announce = hooks
        await _walk_to_photo_prompt(make_message, fsm_context, category_factory,
                                    name="PreOrder", stock="0")

        await add_item_skip_photo(make_callback_query(data="add_item_skip_photo", user_id=1), fsm_context)

        assert await select_item_stock("PreOrder") == 0
        notify.assert_not_awaited()
        announce.assert_not_awaited()

    async def test_in_stock_product_wakes_subscribers_and_channel(
            self, make_message, fsm_context, category_factory, hooks, mock_bot):
        notify, announce = hooks
        await _walk_to_photo_prompt(make_message, fsm_context, category_factory,
                                    name="AwaitedItem", stock="3")

        msg, _ = _photo_message(make_message, _png())
        await add_item_photo(msg, fsm_context)

        notify.assert_awaited_once_with(mock_bot, "AwaitedItem")
        announce.assert_awaited_once_with(mock_bot, "AwaitedItem", 3)

    async def test_creation_is_audited(self, make_message, fsm_context, category_factory, hooks):
        await _walk_to_photo_prompt(make_message, fsm_context, category_factory,
                                    name="Audited", stock="1")

        msg, _ = _photo_message(make_message, _png(), user_id=77)
        with patch('bot.handlers.admin.adding_position.log_audit', new_callable=AsyncMock) as audit:
            await add_item_photo(msg, fsm_context)

        assert audit.await_args[0][0] == "create_item"
        assert audit.await_args[1]["user_id"] == 77
        assert audit.await_args[1]["resource_id"] == "Audited"
        assert "photo=yes" in audit.await_args[1]["details"]
