import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.database.methods.read import get_item_info, select_item_stock
from bot.handlers.admin._common import parse_quantity, MAX_STOCK, announce_arrival
from bot.handlers.admin.goods_management import (
    goods_management_callback_handler, delete_item_callback_handler, delete_str_item,
    item_stock_callback_handler, show_item_stock, stock_action_callback_handler,
    stock_back_to_card, apply_stock_change,
    stock_photo_callback_handler, stock_photo_upload, stock_photo_reprompt,
    stock_photo_remove_ask, stock_photo_remove,
)
from bot.database.methods.product_images import get_item_image_bytes, has_item_image, set_item_image
from bot.database.models import Permission
from bot.filters import HasPermissionFilter
from bot.handlers.admin import goods_management as gm
from bot.misc.images import MAX_IMAGE_BYTES
from bot.states import GoodsFSM, StockFSM


def _callbacks(mock_call_args):
    markup = mock_call_args[1]["reply_markup"]
    return [b.callback_data for row in markup.inline_keyboard for b in row]


@pytest.fixture
def stock_hooks():
    """Replace the restock fan-out and channel post; yields (notify, announce) mocks."""
    with patch('bot.handlers.admin.goods_management._notify_restock_safe', new_callable=AsyncMock) as notify, \
            patch('bot.handlers.admin.goods_management.announce_arrival', new_callable=AsyncMock) as announce:
        yield notify, announce


async def _open_card(make_message, fsm_context, name):
    await fsm_context.set_state(StockFSM.waiting_item_name)
    msg = make_message(text=name, user_id=1)
    await show_item_stock(msg, fsm_context)
    return msg


async def _choose(make_callback_query, fsm_context, mode):
    call = make_callback_query(data=f"stock_{mode}", user_id=1)
    await stock_action_callback_handler(call, fsm_context)
    return call


class TestGoodsMenu:

    async def test_menu_lists_every_action(self, make_callback_query, fsm_context):
        call = make_callback_query(data="goods_management", user_id=900800)
        await fsm_context.set_state(GoodsFSM.waiting_item_name_delete)

        await goods_management_callback_handler(call, fsm_context)

        assert _callbacks(call.message.edit_text.call_args) == [
            "add_item", "item_stock", "update_item", "manage_sale", "delete_item", "console",
        ]
        # Opening the menu drops any half-finished flow.
        assert await fsm_context.get_state() is None


class TestParseQuantity:

    @pytest.mark.parametrize("text,minimum,expected", [
        ("0", 0, 0),
        ("7", 0, 7),
        (" 15 ", 1, 15),
        (str(MAX_STOCK), 1, MAX_STOCK),
        ("0", 1, None),            # "add 0" is meaningless
        (str(MAX_STOCK + 1), 0, None),
        ("-3", 0, None),
        ("2.5", 0, None),
        ("abc", 0, None),
        ("", 0, None),
        (None, 0, None),
        ("٣", 0, None),            # non-ASCII digits are not accepted
    ])
    def test_parse(self, text, minimum, expected):
        assert parse_quantity(text, minimum=minimum) == expected


class TestDeletePosition:

    async def test_prompt_sets_the_state(self, make_callback_query, fsm_context):
        call = make_callback_query(data="delete_item", user_id=900801)
        await delete_item_callback_handler(call, fsm_context)

        assert await fsm_context.get_state() == GoodsFSM.waiting_item_name_delete

    async def test_existing_position_is_deleted(self, make_message, fsm_context, item_factory):
        await item_factory(name="Doomed", price=100, stock=2)

        await delete_str_item(make_message(text="Doomed", user_id=1), fsm_context)

        assert await get_item_info("Doomed") is None
        assert await fsm_context.get_state() is None

    async def test_unknown_position_deletes_nothing(self, make_message, fsm_context, item_factory):
        await item_factory(name="Innocent", price=100, stock=2)

        await delete_str_item(make_message(text="NoSuchPosition", user_id=1), fsm_context)

        assert await get_item_info("Innocent") is not None


class TestStockCard:

    async def test_prompt_sets_the_state(self, make_callback_query, fsm_context):
        call = make_callback_query(data="item_stock", user_id=900810)
        await item_stock_callback_handler(call, fsm_context)

        assert await fsm_context.get_state() == StockFSM.waiting_item_name

    async def test_card_shows_the_stock_and_the_three_actions(self, make_message, fsm_context,
                                                              item_factory):
        await item_factory(name="Kettle", price=250, stock=9)

        msg = await _open_card(make_message, fsm_context, "Kettle")

        text = msg.answer.call_args[0][0]
        assert "admin.goods.stock.card" in text and "'stock': 9" in text
        assert _callbacks(msg.answer.call_args) == [
            "stock_set", "stock_add", "stock_sub", "stock_photo", "goods_management",
        ]
        assert await fsm_context.get_state() == StockFSM.card
        assert (await fsm_context.get_data())["stock_item_name"] == "Kettle"

    async def test_unknown_product_keeps_the_prompt(self, make_message, fsm_context):
        msg = await _open_card(make_message, fsm_context, "Ghost")

        assert "position.not_found" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() == StockFSM.waiting_item_name

    @pytest.mark.parametrize("mode", ["set", "add", "sub"])
    async def test_action_asks_for_a_quantity(self, make_message, make_callback_query,
                                              fsm_context, item_factory, mode):
        await item_factory(name="Kettle", price=250, stock=9)
        await _open_card(make_message, fsm_context, "Kettle")

        call = await _choose(make_callback_query, fsm_context, mode)

        assert f"admin.goods.stock.prompt.{mode}" in call.message.edit_text.call_args[0][0]
        assert await fsm_context.get_state() == StockFSM.waiting_quantity
        assert (await fsm_context.get_data())["stock_mode"] == mode

    async def test_back_from_the_prompt_returns_to_the_card(self, make_message, make_callback_query,
                                                            fsm_context, item_factory):
        await item_factory(name="Kettle", price=250, stock=9)
        await _open_card(make_message, fsm_context, "Kettle")
        await _choose(make_callback_query, fsm_context, "add")

        call = make_callback_query(data="stock_card", user_id=1)
        await stock_back_to_card(call, fsm_context)

        assert await fsm_context.get_state() == StockFSM.card
        assert "admin.goods.stock.card" in call.message.edit_text.call_args[0][0]


class TestStockChange:

    async def _apply(self, make_message, make_callback_query, fsm_context, mode, text):
        await _choose(make_callback_query, fsm_context, mode)
        msg = make_message(text=text, user_id=42)
        await apply_stock_change(msg, fsm_context)
        return msg

    async def test_set_replaces_the_stock(self, make_message, make_callback_query, fsm_context,
                                          item_factory, stock_hooks):
        await item_factory(name="Kettle", price=250, stock=9)
        await _open_card(make_message, fsm_context, "Kettle")

        msg = await self._apply(make_message, make_callback_query, fsm_context, "set", "4")

        assert await select_item_stock("Kettle") == 4
        assert "'old': 9" in msg.answer.call_args[0][0] and "'new': 4" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() == StockFSM.card

    async def test_set_to_zero_marks_sold_out(self, make_message, make_callback_query, fsm_context,
                                              item_factory, stock_hooks):
        await item_factory(name="Kettle", price=250, stock=9)
        await _open_card(make_message, fsm_context, "Kettle")

        await self._apply(make_message, make_callback_query, fsm_context, "set", "0")

        assert await select_item_stock("Kettle") == 0

    async def test_add_increases_the_stock(self, make_message, make_callback_query, fsm_context,
                                           item_factory, stock_hooks):
        await item_factory(name="Kettle", price=250, stock=9)
        await _open_card(make_message, fsm_context, "Kettle")

        await self._apply(make_message, make_callback_query, fsm_context, "add", "5")

        assert await select_item_stock("Kettle") == 14

    async def test_sub_decreases_and_never_goes_negative(self, make_message, make_callback_query,
                                                         fsm_context, item_factory, stock_hooks):
        await item_factory(name="Kettle", price=250, stock=3)
        await _open_card(make_message, fsm_context, "Kettle")

        await self._apply(make_message, make_callback_query, fsm_context, "sub", "10")

        assert await select_item_stock("Kettle") == 0

    @pytest.mark.parametrize("mode,bad", [
        ("set", "-1"), ("set", "abc"), ("add", "0"), ("sub", "0"), ("add", "1.5"),
        ("set", str(MAX_STOCK + 1)),
    ])
    async def test_bad_quantity_changes_nothing(self, make_message, make_callback_query,
                                                fsm_context, item_factory, stock_hooks, mode, bad):
        await item_factory(name="Kettle", price=250, stock=9)
        await _open_card(make_message, fsm_context, "Kettle")

        msg = await self._apply(make_message, make_callback_query, fsm_context, mode, bad)

        assert await select_item_stock("Kettle") == 9
        assert "stock.invalid" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() == StockFSM.waiting_quantity

    async def test_restock_from_zero_notifies_subscribers_and_channel(
            self, make_message, make_callback_query, fsm_context, item_factory, stock_hooks, mock_bot):
        notify, announce = stock_hooks
        await item_factory(name="Kettle", price=250, stock=0)
        await _open_card(make_message, fsm_context, "Kettle")

        await self._apply(make_message, make_callback_query, fsm_context, "add", "6")

        notify.assert_awaited_once_with(mock_bot, "Kettle")
        announce.assert_awaited_once_with(mock_bot, "Kettle", 6)

    async def test_change_without_a_restock_stays_quiet(self, make_message, make_callback_query,
                                                        fsm_context, item_factory, stock_hooks):
        notify, announce = stock_hooks
        await item_factory(name="Kettle", price=250, stock=2)
        await _open_card(make_message, fsm_context, "Kettle")

        await self._apply(make_message, make_callback_query, fsm_context, "add", "6")
        await self._apply(make_message, make_callback_query, fsm_context, "set", "0")

        notify.assert_not_awaited()
        announce.assert_not_awaited()

    async def test_change_is_audited(self, make_message, make_callback_query, fsm_context,
                                     item_factory, stock_hooks):
        await item_factory(name="Kettle", price=250, stock=2)
        await _open_card(make_message, fsm_context, "Kettle")

        with patch('bot.handlers.admin.goods_management.log_audit', new_callable=AsyncMock) as audit:
            await self._apply(make_message, make_callback_query, fsm_context, "add", "1")

        assert audit.await_args[0][0] == "update_item_stock"
        assert audit.await_args[1]["user_id"] == 42
        assert "old=2, new=3" in audit.await_args[1]["details"]

    async def test_product_deleted_meanwhile_is_reported(self, make_message, make_callback_query,
                                                         fsm_context, item_factory, stock_hooks):
        await item_factory(name="Kettle", price=250, stock=2)
        await _open_card(make_message, fsm_context, "Kettle")
        await _choose(make_callback_query, fsm_context, "add")
        from bot.database.methods.delete import delete_item
        await delete_item("Kettle")

        msg = make_message(text="1", user_id=1)
        await apply_stock_change(msg, fsm_context)

        assert "position.not_found" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() is None


class TestAnnounceArrival:

    async def test_no_channel_means_no_post(self, mock_bot):
        with patch('bot.handlers.other._parse_channel_username', return_value=None):
            await announce_arrival(mock_bot, "Kettle", 3)

        mock_bot.send_message.assert_not_awaited()

    async def test_posts_to_the_channel(self, mock_bot):
        with patch('bot.handlers.other._parse_channel_username', return_value="shop"), \
                patch('bot.handlers.admin._common.EnvKeys') as env:
            env.CHANNEL_ID = None
            await announce_arrival(mock_bot, "Kettle <b>", 3)

        kwargs = mock_bot.send_message.call_args[1]
        assert kwargs["chat_id"] == "@shop"
        assert "Kettle &lt;b&gt;" in kwargs["text"]      # HTML in the name is escaped

    async def test_a_failing_channel_never_raises(self, mock_bot):
        mock_bot.send_message.side_effect = RuntimeError("bot was kicked")
        with patch('bot.handlers.other._parse_channel_username', return_value="shop"), \
                patch('bot.handlers.admin._common.EnvKeys') as env:
            env.CHANNEL_ID = None
            await announce_arrival(mock_bot, "Kettle", 3)


def _png(size=(4, 4), fmt="PNG") -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, (30, 120, 200)).save(buf, fmt)
    return buf.getvalue()


def _photo_message(make_message, payload: bytes, *, document=False, mime="image/png", size=None, user_id=42):
    msg = make_message(text=None, user_id=user_id)
    msg.photo = None
    msg.document = None
    media = MagicMock()
    media.file_size = size if size is not None else len(payload)
    if document:
        media.mime_type = mime
        msg.document = media
    else:
        msg.photo = [MagicMock(file_size=1), media]

    async def _download(m, destination=None, **kwargs):
        destination.write(payload)

    msg.bot.download = AsyncMock(side_effect=_download)
    return msg, media


@pytest.fixture
def audit_bg():
    with patch('bot.handlers.admin.goods_management.log_audit_bg') as audit:
        yield audit


class TestPhotoOnTheCard:

    async def test_card_without_a_picture_shows_status_and_no_remove_button(
            self, make_message, fsm_context, item_factory):
        await item_factory(name="Kettle", price=250, stock=9)

        msg = await _open_card(make_message, fsm_context, "Kettle")

        assert "photo.status.no" in msg.answer.call_args[0][0]
        assert "stock_photo" in _callbacks(msg.answer.call_args)
        assert "stock_photo_rm" not in _callbacks(msg.answer.call_args)

    async def test_card_with_a_picture_offers_change_and_remove(
            self, make_message, fsm_context, item_factory):
        await item_factory(name="Kettle", price=250, stock=9)
        await set_item_image("Kettle", _png())

        msg = await _open_card(make_message, fsm_context, "Kettle")

        assert "photo.status.yes" in msg.answer.call_args[0][0]
        assert _callbacks(msg.answer.call_args) == [
            "stock_set", "stock_add", "stock_sub", "stock_photo", "stock_photo_rm", "goods_management",
        ]

    async def test_change_button_asks_for_a_photo(self, make_message, make_callback_query,
                                                  fsm_context, item_factory):
        await item_factory(name="Kettle", price=250, stock=9)
        await _open_card(make_message, fsm_context, "Kettle")

        call = make_callback_query(data="stock_photo", user_id=1)
        await stock_photo_callback_handler(call, fsm_context)

        assert "photo.prompt.change" in call.message.edit_text.call_args[0][0]
        assert _callbacks(call.message.edit_text.call_args) == ["stock_card"]
        assert await fsm_context.get_state() == StockFSM.waiting_photo

    async def test_back_from_the_photo_prompt_returns_to_the_card(
            self, make_message, make_callback_query, fsm_context, item_factory):
        await item_factory(name="Kettle", price=250, stock=9)
        await _open_card(make_message, fsm_context, "Kettle")
        await stock_photo_callback_handler(make_callback_query(data="stock_photo", user_id=1), fsm_context)

        call = make_callback_query(data="stock_card", user_id=1)
        await stock_back_to_card(call, fsm_context)

        assert await fsm_context.get_state() == StockFSM.card


class TestChangePhoto:

    async def _prompt(self, make_message, make_callback_query, fsm_context, name="Kettle"):
        await _open_card(make_message, fsm_context, name)
        await stock_photo_callback_handler(make_callback_query(data="stock_photo", user_id=1), fsm_context)

    async def test_photo_is_stored_unchanged_and_the_card_returns(
            self, make_message, make_callback_query, fsm_context, item_factory, audit_bg):
        await item_factory(name="Kettle", price=250, stock=9)
        await self._prompt(make_message, make_callback_query, fsm_context)
        payload = _png()
        msg, media = _photo_message(make_message, payload)

        await stock_photo_upload(msg, fsm_context)

        assert await get_item_image_bytes("Kettle") == payload
        assert msg.bot.download.await_args[0][0] is media          # the largest size
        text = msg.answer.call_args[0][0]
        assert "photo.updated" in text and "photo.status.yes" in text
        assert "stock_photo_rm" in _callbacks(msg.answer.call_args)
        assert await fsm_context.get_state() == StockFSM.card

    async def test_an_image_document_replaces_the_old_picture(
            self, make_message, make_callback_query, fsm_context, item_factory, audit_bg):
        await item_factory(name="Kettle", price=250, stock=9)
        await set_item_image("Kettle", _png(size=(2, 2)))
        await self._prompt(make_message, make_callback_query, fsm_context)
        payload = _png(size=(8, 8), fmt="JPEG")
        msg, _ = _photo_message(make_message, payload, document=True, mime="image/jpeg")

        await stock_photo_upload(msg, fsm_context)

        assert await get_item_image_bytes("Kettle") == payload

    async def test_change_is_audited(self, make_message, make_callback_query, fsm_context,
                                     item_factory, audit_bg):
        await item_factory(name="Kettle", price=250, stock=9)
        await self._prompt(make_message, make_callback_query, fsm_context)
        msg, _ = _photo_message(make_message, _png(), user_id=42)

        await stock_photo_upload(msg, fsm_context)

        assert audit_bg.call_args[0][0] == "update_item_photo"
        assert audit_bg.call_args[1]["user_id"] == 42
        assert audit_bg.call_args[1]["resource_id"] == "Kettle"
        assert "action=set" in audit_bg.call_args[1]["details"]

    @pytest.mark.parametrize("payload,expected", [
        (b"definitely not an image", "photo.invalid"),
        (_png(fmt="GIF"), "photo.unsupported"),
    ])
    async def test_bad_file_changes_nothing_and_can_be_retried(
            self, make_message, make_callback_query, fsm_context, item_factory, audit_bg, payload, expected):
        await item_factory(name="Kettle", price=250, stock=9)
        old = _png(size=(2, 2))
        await set_item_image("Kettle", old)
        await self._prompt(make_message, make_callback_query, fsm_context)
        msg, _ = _photo_message(make_message, payload, document=True)

        await stock_photo_upload(msg, fsm_context)

        assert expected in msg.answer.call_args[0][0]
        assert await get_item_image_bytes("Kettle") == old
        assert await fsm_context.get_state() == StockFSM.waiting_photo
        audit_bg.assert_not_called()

        good = _png(size=(6, 6))
        retry, _ = _photo_message(make_message, good)
        await stock_photo_upload(retry, fsm_context)
        assert await get_item_image_bytes("Kettle") == good

    async def test_oversize_file_is_refused_without_downloading(
            self, make_message, make_callback_query, fsm_context, item_factory, audit_bg):
        await item_factory(name="Kettle", price=250, stock=9)
        await self._prompt(make_message, make_callback_query, fsm_context)
        msg, _ = _photo_message(make_message, _png(), document=True, size=MAX_IMAGE_BYTES + 1)

        await stock_photo_upload(msg, fsm_context)

        assert "photo.too_large" in msg.answer.call_args[0][0]
        msg.bot.download.assert_not_awaited()
        assert not await has_item_image("Kettle")

    async def test_text_reprompts(self, make_message, make_callback_query, fsm_context, item_factory):
        await item_factory(name="Kettle", price=250, stock=9)
        await self._prompt(make_message, make_callback_query, fsm_context)

        msg = make_message(text="a photo please", user_id=1)
        await stock_photo_reprompt(msg)

        assert "photo.reprompt" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() == StockFSM.waiting_photo

    async def test_product_deleted_meanwhile_is_reported(
            self, make_message, make_callback_query, fsm_context, item_factory, audit_bg):
        await item_factory(name="Kettle", price=250, stock=9)
        await self._prompt(make_message, make_callback_query, fsm_context)
        from bot.database.methods.delete import delete_item
        await delete_item("Kettle")
        msg, _ = _photo_message(make_message, _png())

        await stock_photo_upload(msg, fsm_context)

        assert "position.not_found" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() is None


class TestRemovePhoto:

    async def test_remove_asks_for_confirmation_first(self, make_message, make_callback_query,
                                                      fsm_context, item_factory):
        await item_factory(name="Kettle", price=250, stock=9)
        await set_item_image("Kettle", _png())
        await _open_card(make_message, fsm_context, "Kettle")

        call = make_callback_query(data="stock_photo_rm", user_id=1)
        await stock_photo_remove_ask(call, fsm_context)

        assert "photo.remove.confirm" in call.message.edit_text.call_args[0][0]
        assert _callbacks(call.message.edit_text.call_args) == ["stock_photo_rmy", "stock_card"]
        assert await has_item_image("Kettle")          # nothing removed yet

    async def test_confirming_removes_the_picture(self, make_message, make_callback_query,
                                                  fsm_context, item_factory, audit_bg):
        await item_factory(name="Kettle", price=250, stock=9)
        await set_item_image("Kettle", _png())
        await _open_card(make_message, fsm_context, "Kettle")

        call = make_callback_query(data="stock_photo_rmy", user_id=42)
        await stock_photo_remove(call, fsm_context)

        assert not await has_item_image("Kettle")
        text = call.message.edit_text.call_args[0][0]
        assert "photo.removed" in text and "photo.status.no" in text
        assert "stock_photo_rm" not in _callbacks(call.message.edit_text.call_args)
        assert await fsm_context.get_state() == StockFSM.card
        assert audit_bg.call_args[0][0] == "update_item_photo"
        assert "action=remove" in audit_bg.call_args[1]["details"]

    async def test_removing_a_missing_picture_is_harmless(self, make_message, make_callback_query,
                                                          fsm_context, item_factory, audit_bg):
        await item_factory(name="Kettle", price=250, stock=9)
        await _open_card(make_message, fsm_context, "Kettle")

        call = make_callback_query(data="stock_photo_rmy", user_id=42)
        await stock_photo_remove(call, fsm_context)

        assert "photo.none" in call.message.edit_text.call_args[0][0]
        audit_bg.assert_not_called()


class TestPhotoPermissions:

    def test_every_photo_handler_needs_catalog_manage(self):
        names = {"stock_photo_callback_handler", "stock_photo_upload", "stock_photo_reprompt",
                 "stock_photo_remove_ask", "stock_photo_remove"}
        handlers = [h for h in gm.router.callback_query.handlers + gm.router.message.handlers
                    if h.callback.__name__ in names]
        assert {h.callback.__name__ for h in handlers} == names
        for h in handlers:
            perms = [f.callback for f in h.filters if isinstance(f.callback, HasPermissionFilter)]
            assert perms and perms[0].permission == Permission.CATALOG_MANAGE, h.callback.__name__

    def test_callback_data_fits_telegram_limit(self):
        for cb in ("stock_photo", "stock_photo_rm", "stock_photo_rmy", "add_item_skip_photo"):
            assert len(cb.encode()) <= 64
