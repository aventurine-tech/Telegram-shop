"""Customers see category/product names and descriptions in their own language.

Display only: callbacks, FSM keys, cache keys and lookups stay on the canonical (main-language) text.
"""
import datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from bot.database.methods.create import create_category, create_item, add_to_cart
from bot.database.methods.create import subscribe_to_stock
from bot.database.methods.orders import create_order_transaction
from bot.database.methods.read import get_cart_items
from bot.handlers.user import shop_and_goods as shop
from bot.handlers.user.cart import view_cart_handler, add_to_cart_handler
from bot.handlers.user.checkout import _fail_text
from bot.handlers.user.shop_and_goods import (
    shop_callback_handler, items_list_callback_handler, item_info_callback_handler,
    receive_search_query_handler, search_item_info_handler, _render_item_page,
)
from bot.database.models.main import Fulfillment, PaymentMethod
from bot.i18n import use_language
from bot.keyboards.inline import cart_keyboard
from bot.misc.services.order_view import format_order, notify_new_order
from bot.misc.services.restock_notifier import notify_restock


def _buttons(markup) -> list:
    return [b for row in markup.inline_keyboard for b in row]


def _texts(markup) -> list[str]:
    return [b.text for b in _buttons(markup)]


@pytest.fixture
async def catalog():
    """Mobilă/Scaun are translated; Plain has no translation at all."""
    await create_category("Mobilă", names={"en": "Furniture", "ru": "Мебель"})
    await create_category("Plain")
    await create_item("Scaun", "Scaun de lemn", 100, "Mobilă", stock=5,
                      names={"en": "Chair", "ru": "Стул"},
                      descriptions={"en": "A wooden chair", "ru": "Деревянный стул"})
    await create_item("Masă", "Masă mare", 200, "Mobilă", stock=5, names={"en": "Table"})


class TestCategoryAndItemLists:

    async def test_categories_in_viewer_language_with_canonical_callbacks(
            self, make_callback_query, fsm_context, catalog):
        for lang, expected in (("en", "Furniture"), ("ru", "Мебель"), ("ro", "Mobilă")):
            call = make_callback_query(data="shop")
            with use_language(lang):
                await shop_callback_handler(call, fsm_context)
            markup = call.message.edit_text.call_args[1]["reply_markup"]
            assert expected in _texts(markup)
            assert "Plain" in _texts(markup)                      # untranslated -> canonical
        data = await fsm_context.get_data()
        assert set(data["category_page_items"]) == {"Mobilă", "Plain"}   # FSM keys stay canonical
        cbs = [b.callback_data for b in _buttons(markup) if (b.callback_data or "").startswith("cat:")]
        assert len(cbs) == 2

    async def test_open_category_from_translated_button_and_list_items(
            self, make_callback_query, fsm_context, catalog):
        with use_language("en"):
            await shop_callback_handler(make_callback_query(data="shop"), fsm_context)
            idx = (await fsm_context.get_data())["category_page_items"].index("Mobilă")
            call = make_callback_query(data=f"cat:{idx}:0")
            await items_list_callback_handler(call, fsm_context)
        markup = call.message.edit_text.call_args[1]["reply_markup"]
        assert sorted(t for t in _texts(markup) if t in ("Chair", "Table")) == ["Chair", "Table"]
        data = await fsm_context.get_data()
        assert data["current_category"] == "Mobilă"
        assert set(data["goods_page_items"]) == {"Scaun", "Masă"}

    async def test_item_buttons_fall_back_per_item_and_open_the_right_item(
            self, make_callback_query, fsm_context, catalog):
        with use_language("ru"):
            await shop_callback_handler(make_callback_query(data="shop"), fsm_context)
            idx = (await fsm_context.get_data())["category_page_items"].index("Mobilă")
            call = make_callback_query(data=f"cat:{idx}:0")
            await items_list_callback_handler(call, fsm_context)
            texts = _texts(call.message.edit_text.call_args[1]["reply_markup"])
            assert "Стул" in texts and "Masă" in texts            # Masă has no ru name

            goods = (await fsm_context.get_data())["goods_page_items"]
            call = make_callback_query(data=f"itm:{goods.index('Scaun')}:0")
            await item_info_callback_handler(call, fsm_context)
        assert (await fsm_context.get_data())["csrf_item"] == "Scaun"
        assert "Стул" in call.message.edit_text.call_args[0][0]

    async def test_list_order_follows_display_name(self, make_callback_query, fsm_context):
        await create_category("Mobilă", names={"en": "Zebra"})
        await create_category("Zzz", names={"en": "Apple"})
        call = make_callback_query(data="shop")
        with use_language("en"):
            await shop_callback_handler(call, fsm_context)
        assert _texts(call.message.edit_text.call_args[1]["reply_markup"])[:2] == ["Apple", "Zebra"]


class TestSearch:

    async def test_search_by_translated_word_shows_viewer_language(
            self, make_message, make_callback_query, fsm_context, catalog):
        msg = make_message(text="chair")
        with use_language("ru"):
            await receive_search_query_handler(msg, fsm_context)
        markup = msg.answer.call_args[1]["reply_markup"]
        assert "Стул" in _texts(markup)                           # found via the English word
        assert (await fsm_context.get_data())["search_page_items"] == ["Scaun"]

        call = make_callback_query(data="sitm:0:0")
        with use_language("ru"):
            await search_item_info_handler(call, fsm_context)
        assert (await fsm_context.get_data())["csrf_item"] == "Scaun"


class TestItemCard:

    @pytest.mark.parametrize("lang,name,desc", [
        ("en", "Chair", "A wooden chair"),
        ("ru", "Стул", "Деревянный стул"),
        ("ro", "Scaun", "Scaun de lemn"),
    ])
    async def test_card_title_and_description_per_language(
            self, make_callback_query, fsm_context, catalog, lang, name, desc):
        call = make_callback_query(data="x")
        await fsm_context.update_data(csrf_item="Scaun")
        with use_language(lang):
            await _render_item_page(call, fsm_context, "Scaun", "gp_0", user_id=100001)
        text = call.message.edit_text.call_args[0][0]
        assert f"'name': '{name}'" in text and f"'description': '{desc}'" in text
        assert (await fsm_context.get_data())["csrf_item"] == "Scaun"

    async def test_card_falls_back_to_canonical_description(self, make_callback_query, fsm_context, catalog):
        call = make_callback_query(data="x")
        with use_language("ru"):
            await _render_item_page(call, fsm_context, "Masă", "gp_0", user_id=100001)
        text = call.message.edit_text.call_args[0][0]
        assert "'name': 'Masă'" in text and "'description': 'Masă mare'" in text

    async def test_long_translated_description_is_trimmed_to_caption(self, fsm_context, make_callback_query,
                                                                     monkeypatch):
        await create_category("C")
        await create_item("Item", "short", 10, "C", stock=1, descriptions={"en": "word " * 600})
        monkeypatch.setattr(shop, "get_item_image_ref", AsyncMock(return_value={"file_id": "f"}))
        sent = AsyncMock(return_value=True)
        monkeypatch.setattr(shop, "_send_card_photo", sent)
        call = make_callback_query(data="x")
        with use_language("en"):
            await _render_item_page(call, fsm_context, "Item", "gp_0", user_id=100001)
        caption = sent.call_args[0][3]
        assert len(caption) <= 1024 and "…" in caption and "word" in caption


class TestReviewPromptsAndToasts:

    async def test_cart_toast_uses_display_name(self, make_callback_query, fsm_context, user_factory, catalog):
        await user_factory(telegram_id=830001)
        await fsm_context.update_data(csrf_item="Scaun")
        call = make_callback_query(data="add_to_cart", user_id=830001)
        with use_language("ru"):
            await add_to_cart_handler(call, fsm_context)
        assert "'name': 'Стул'" in call.answer.call_args[0][0]
        assert [i["item_name"] for i in await get_cart_items(830001)] == ["Scaun"]

    async def test_out_of_stock_toast_and_review_title(self, make_callback_query, fsm_context, user_factory):
        await create_category("C")
        await create_item("Gone", "d", 10, "C", stock=0, names={"en": "Vanished"})
        await user_factory(telegram_id=830002)
        await fsm_context.update_data(csrf_item="Gone")
        call = make_callback_query(data="add_to_cart", user_id=830002)
        with use_language("en"):
            await add_to_cart_handler(call, fsm_context)
        assert "'name': 'Vanished'" in call.answer.call_args[0][0]
        with use_language("en"):
            assert await shop._display_name("Gone") == "Vanished"
        assert await shop._display_name("Unknown") == "Unknown"


class TestCartAndCheckout:

    async def test_cart_view_and_keyboard_per_language(self, make_callback_query, fsm_context,
                                                       user_factory, catalog):
        await user_factory(telegram_id=830010, balance=1000)
        await add_to_cart(830010, "Scaun", quantity=2)
        await add_to_cart(830010, "Masă")
        for lang, chair, table in (("en", "Chair", "Table"), ("ru", "Стул", "Masă"), ("ro", "Scaun", "Masă")):
            call = make_callback_query(data="cart", user_id=830010)
            with use_language(lang):
                await view_cart_handler(call, fsm_context)
            text = call.message.edit_text.call_args[0][0]
            assert f"'name': '{chair}'" in text and f"'name': '{table}'" in text
            texts = _texts(call.message.edit_text.call_args[1]["reply_markup"])
            assert f"{chair} ×2" in texts
            assert any(t.startswith("❌") and chair in t for t in texts)      # the remove button

    async def test_cart_keyboard_falls_back_without_translation(self):
        lines = [{"id": 1, "item_name": "Scaun", "name": "Scaun", "name_en": None, "quantity": 1}]
        with use_language("en"):
            assert "Scaun ×1" in _texts(cart_keyboard(lines))

    async def test_out_of_stock_failure_names_the_product_in_viewer_language(self, catalog):
        with use_language("ru"):
            text = await _fail_text("out_of_stock", {"item_name": "Scaun", "available": 1})
        assert "'name': 'Стул'" in text
        with use_language("ro"):
            assert "'name': 'Scaun'" in await _fail_text("out_of_stock", {"item_name": "Scaun"})
        assert "'name': ''" in await _fail_text("out_of_stock", None)


class TestOrderCard:

    ORDER = {
        "id": 7, "status": "new", "payment_status": "unpaid", "payment_method": "cod",
        "fulfillment": "pickup", "total": 100, "balance_used": 0, "user_id": 1,
        "customer_name": "Ana", "phone": "+373", "address": None, "comment": None,
        "created_at": datetime.datetime(2026, 1, 1),
        "items": [{"item_name": "Scaun", "name": "Scaun", "name_en": "Chair", "name_ru": "Стул",
                   "name_ro": None, "quantity": 1, "line_total": Decimal("100")}],
    }

    @pytest.mark.parametrize("lang,shown", [("en", "Chair"), ("ru", "Стул"), ("ro", "Scaun")])
    def test_format_order_per_language(self, lang, shown):
        with use_language(lang):
            assert f"'name': '{shown}'" in format_order(self.ORDER)

    async def test_real_order_snapshot_renders_in_each_language(self, user_factory, catalog):
        await user_factory(telegram_id=830020, balance=1000)
        await add_to_cart(830020, "Scaun")
        ok, code, order = await create_order_transaction(
            830020, fulfillment=Fulfillment.PICKUP, payment_method=PaymentMethod.COD,
            customer_name="Ana", phone="+373", address=None, comment=None,
        )
        assert ok, code
        with use_language("ru"):
            assert "'name': 'Стул'" in format_order(order)
        with use_language("en"):
            assert "'name': 'Chair'" in format_order(order)

    async def test_staff_alert_in_staff_members_language(self, mock_bot, user_factory):
        await user_factory(telegram_id=830030, role_id=3, language="en")
        await user_factory(telegram_id=830031, role_id=3, language="ru")
        with use_language("ro"):
            await notify_new_order(mock_bot, self.ORDER)
        by_chat = {c.args[0]: c.args[1] for c in mock_bot.send_message.await_args_list}
        assert "'name': 'Chair'" in by_chat[830030]
        assert "'name': 'Стул'" in by_chat[830031]


class TestRestockNotice:

    async def test_names_per_language_group(self, mock_bot, user_factory, catalog):
        for uid, lang in ((830040, "en"), (830041, "ru"), (830042, "ro"), (830043, "ru")):
            await user_factory(telegram_id=uid, language=lang)
            await subscribe_to_stock(uid, "Scaun")
        assert await notify_restock(mock_bot, "Scaun") == 4
        by_chat = {c.kwargs["chat_id"]: c.kwargs["text"] for c in mock_bot.send_message.await_args_list}
        assert "Chair</b>" in by_chat[830040]
        assert "Стул</b>" in by_chat[830041] and "Стул</b>" in by_chat[830043]
        assert "Scaun</b>" in by_chat[830042]
