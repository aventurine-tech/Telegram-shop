import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch, AsyncMock, MagicMock

from bot.database.main import Database
from bot.database.methods.create import add_to_cart, subscribe_to_stock
from bot.database.methods.lazy_queries import query_goods_search
from bot.database.methods.read import (
    get_cart_items, get_cart_count, is_subscribed_to_stock,
)
from bot.database.models.main import PromoCodes
from bot.handlers.user.cart import (
    cart_qty_handler, view_cart_handler, add_to_cart_handler,
    _show_cart,
)
from bot.handlers.user.shop_and_goods import (
    router, shop_callback_handler, navigate_categories, navigate_goods,
    items_list_callback_handler, item_info_callback_handler,
    search_item_info_handler, shop_search_handler, receive_search_query_handler,
    subscribe_stock_handler, unsubscribe_stock_handler,
    back_to_item_handler,
    my_orders_handler, my_order_handler, my_order_cancel_ask_handler, my_order_cancel_handler,
    _render_item_page,
)
from bot.states import ShopStates


class TestCartHandlers:
    async def test_stepper_increments_and_rerenders(self, make_callback_query, fsm_context,
                                                    user_factory, item_factory):

        await user_factory(telegram_id=620001, balance=1000)
        await item_factory(name="StepItem", price=100, stock=5)
        await add_to_cart(620001, "StepItem")
        cid = (await get_cart_items(620001))[0]["id"]

        call = make_callback_query(data=f"cart_qty:{cid}:1", user_id=620001)
        await cart_qty_handler(call, fsm_context)

        assert await get_cart_count(620001) == 2
        call.message.edit_text.assert_called()          # cart re-rendered
        text = call.message.edit_text.call_args[0][0]
        assert "'qty': 2" in text                             # quantity shown to the user

    async def test_stepper_down_to_zero_removes_line(self, make_callback_query, fsm_context,
                                                     user_factory, item_factory):

        await user_factory(telegram_id=620002, balance=1000)
        await item_factory(name="DropItem", price=100, stock=5)
        await add_to_cart(620002, "DropItem")
        cid = (await get_cart_items(620002))[0]["id"]

        call = make_callback_query(data=f"cart_qty:{cid}:-1", user_id=620002)
        await cart_qty_handler(call, fsm_context)

        assert await get_cart_items(620002) == []
        # Re-rendered as an empty cart: no stepper buttons left.
        markup = call.message.edit_text.call_args[1]["reply_markup"]
        cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert not any(c and c.startswith("cart_qty:") for c in cbs)

    async def test_cart_total_multiplies_by_quantity(self, make_callback_query, fsm_context,
                                                     user_factory, item_factory):

        await user_factory(telegram_id=620003, balance=1000)
        await item_factory(name="TotalItem", price=25, stock=5)
        await add_to_cart(620003, "TotalItem", quantity=4)

        call = make_callback_query(data="cart", user_id=620003)
        await view_cart_handler(call, fsm_context)

        text = call.message.edit_text.call_args[0][0]
        assert "100" in text          # 25 * 4, not 25
        assert "'qty': 4" in text

    async def test_cart_warns_when_a_line_promo_stopped_applying(self, make_callback_query,
                                                                 fsm_context, user_factory,
                                                                 item_factory):

        await user_factory(telegram_id=620010, balance=1000)
        await item_factory(name="WarnItem", price=100, stock=5)
        async with Database().session() as s:
            s.add(PromoCodes(
                code="WARNEXP", discount_type="percent", discount_value=Decimal("10"),
                scope="global", is_active=True,
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ))
        await add_to_cart(620010, "WarnItem", promo_code="WARNEXP")

        call = make_callback_query(data="cart", user_id=620010)
        await view_cart_handler(call, fsm_context)

        text = call.message.edit_text.call_args[0][0]
        assert "cart.item_promo_invalid" in text            # the line is flagged, not silently full-price
        assert "WARNEXP" in text        # and it names the promo to remove
        assert "100" in text            # charged at full price, no fake discount

    async def test_stepper_rejects_other_users_line(self, make_callback_query, fsm_context,
                                                    user_factory, item_factory):

        await user_factory(telegram_id=620004, balance=1000)
        await user_factory(telegram_id=620005, balance=1000)
        await item_factory(name="MineItem", price=10, stock=5)
        await add_to_cart(620004, "MineItem", quantity=2)
        cid = (await get_cart_items(620004))[0]["id"]

        call = make_callback_query(data=f"cart_qty:{cid}:1", user_id=620005)
        await cart_qty_handler(call, fsm_context)

        assert await get_cart_count(620004) == 2    # untouched
        call.answer.assert_called()


class TestBackButtonSurvivesSubFlows:
    """The card's Back button is gp_/sp_, and both pagers are state-filtered.

    Anything that drops the browsing state leaves that button silently dead.
    """

    async def test_notify_keeps_the_browsing_state(self, make_callback_query, fsm_context,
                                                   user_factory, item_factory):

        await user_factory(telegram_id=650001)
        await item_factory(name="BellItem", price=10, stock=0)
        await fsm_context.update_data(csrf_item="BellItem", item_back_data="sp_0")
        await fsm_context.set_state(ShopStates.viewing_search_results)

        call = make_callback_query(data="sub_stock", user_id=650001)
        await subscribe_stock_handler(call, fsm_context)

        assert await fsm_context.get_state() == ShopStates.viewing_search_results

class TestCartStockLimits:
    """A cart can never hold more than the shop has on the shelf."""

    async def test_add_to_cart_refuses_out_of_stock_item(self, make_callback_query, fsm_context,
                                                         user_factory, item_factory):

        await user_factory(telegram_id=640001)
        await item_factory(name="GoneItem", price=10, stock=0)
        await fsm_context.update_data(csrf_item="GoneItem")

        call = make_callback_query(data="add_to_cart", user_id=640001)
        await add_to_cart_handler(call, fsm_context)

        assert await get_cart_count(640001) == 0
        assert call.answer.call_args[1].get("show_alert") is True
        assert "cart.item_out_of_stock" in call.answer.call_args[0][0]

    async def test_add_to_cart_stops_at_stock(self, make_callback_query, fsm_context,
                                              user_factory, item_factory):

        await user_factory(telegram_id=640002)
        await item_factory(name="TwoLeft", price=10, stock=2)
        await fsm_context.update_data(csrf_item="TwoLeft")

        for _ in range(3):
            await add_to_cart_handler(make_callback_query(data="add_to_cart", user_id=640002), fsm_context)

        assert await get_cart_count(640002) == 2

    async def test_stepper_cannot_exceed_stock(self, make_callback_query, fsm_context,
                                               user_factory, item_factory):

        await user_factory(telegram_id=640003)
        await item_factory(name="OneLeft", price=10, stock=1)
        await add_to_cart(640003, "OneLeft")
        cid = (await get_cart_items(640003))[0]["id"]

        call = make_callback_query(data=f"cart_qty:{cid}:1", user_id=640003)
        await cart_qty_handler(call, fsm_context)

        assert await get_cart_count(640003) == 1
        assert "cart.stock_limit" in call.answer.call_args[0][0]

    async def test_cart_warns_about_a_line_above_stock(self, make_callback_query, fsm_context,
                                                       user_factory, item_factory):
        """Stock can drop after the item went into the cart (someone else ordered it)."""

        await user_factory(telegram_id=640004)
        await item_factory(name="Shrinking", price=10, stock=5)
        await add_to_cart(640004, "Shrinking", quantity=3)
        from sqlalchemy import update as sa_update
        from bot.database.models.main import Goods
        async with Database().session() as s:
            await s.execute(sa_update(Goods).where(Goods.name == "Shrinking").values(stock=1))

        call = make_callback_query(data="cart", user_id=640004)
        await view_cart_handler(call, fsm_context)

        assert "cart.low_stock" in call.message.edit_text.call_args[0][0]


class TestRestockButtonFlow:

    async def test_subscribe_from_item_card(self, make_callback_query, fsm_context,
                                            user_factory, item_factory):

        await user_factory(telegram_id=630001)
        await item_factory(name="EmptyItem", price=10, stock=0)   # out of stock
        await fsm_context.update_data(csrf_item="EmptyItem")

        call = make_callback_query(data="sub_stock", user_id=630001)
        await subscribe_stock_handler(call, fsm_context)

        assert await is_subscribed_to_stock(630001, "EmptyItem") is True

    async def test_unsubscribe_from_item_card(self, make_callback_query, fsm_context,
                                              user_factory, item_factory):

        await user_factory(telegram_id=630002)
        await item_factory(name="EmptyItem2", price=10, stock=0)
        await subscribe_to_stock(630002, "EmptyItem2")
        await fsm_context.update_data(csrf_item="EmptyItem2")

        call = make_callback_query(data="unsub_stock", user_id=630002)
        await unsubscribe_stock_handler(call, fsm_context)

        assert await is_subscribed_to_stock(630002, "EmptyItem2") is False

    async def test_subscribe_without_item_in_state(self, make_callback_query, fsm_context,
                                                   user_factory):

        await user_factory(telegram_id=630003)
        call = make_callback_query(data="sub_stock", user_id=630003)
        await subscribe_stock_handler(call, fsm_context)

        call.answer.assert_called_once()
        assert call.answer.call_args[1].get("show_alert") is True


class TestCatalogSearch:

    async def test_prompt_sets_state(self, make_callback_query, fsm_context):

        call = make_callback_query(data="shop_search", user_id=610001)
        await shop_search_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()
        assert await fsm_context.get_state() == ShopStates.waiting_search_query

    async def test_query_renders_results(self, make_message, fsm_context, item_factory):

        await item_factory(name="Netflix Account", price=100, stock=5)
        await item_factory(name="Spotify Account", price=50, stock=5)
        await item_factory(name="Unrelated", price=10, stock=5)

        message = make_message(text="Account", user_id=610002)
        await receive_search_query_handler(message, fsm_context)

        message.answer.assert_called_once()
        data = await fsm_context.get_data()
        assert sorted(data["search_page_items"]) == ["Netflix Account", "Spotify Account"]
        assert data["search_query"] == "Account"
        assert await fsm_context.get_state() == ShopStates.viewing_search_results

    async def test_description_only_match_is_found(self, make_message, fsm_context, item_factory):
        """Proves the OR arm against description, not just name."""

        await item_factory(name="Opaque Name", price=10,
                           description="a premium gamepass inside", stock=5)

        message = make_message(text="gamepass", user_id=610003)
        await receive_search_query_handler(message, fsm_context)

        data = await fsm_context.get_data()
        assert data["search_page_items"] == ["Opaque Name"]

    async def test_search_is_case_insensitive(self, make_message, fsm_context, item_factory):

        await item_factory(name="UPPERCASE Item", price=10, stock=5)

        message = make_message(text="uppercase", user_id=610004)
        await receive_search_query_handler(message, fsm_context)

        data = await fsm_context.get_data()
        assert data["search_page_items"] == ["UPPERCASE Item"]

    async def test_empty_result(self, make_message, fsm_context, item_factory):

        await item_factory(name="Something", price=10, stock=5)

        message = make_message(text="nothingmatchesthis", user_id=610005)
        await receive_search_query_handler(message, fsm_context)

        text = message.answer.call_args[0][0]
        assert "shop.search.empty" in text
        assert (await fsm_context.get_data()).get("search_page_items") is None

    async def test_too_short_query_stays_in_state(self, make_message, fsm_context):

        await fsm_context.set_state(ShopStates.waiting_search_query)
        message = make_message(text="a", user_id=610006)
        await receive_search_query_handler(message, fsm_context)

        text = message.answer.call_args[0][0]
        assert "shop.search.too_short" in text
        # Still waiting, so the user can just retype.
        assert await fsm_context.get_state() == ShopStates.waiting_search_query

    async def test_open_item_from_search_sets_back_to_results(self, make_callback_query,
                                                              fsm_context, item_factory):
        """Back from a search-opened card must return to the results, not categories."""

        await item_factory(name="FoundItem", price=100, stock=5)
        await fsm_context.update_data(search_query="found")

        call = make_callback_query(data="sitm:0:0", user_id=610007)
        await search_item_info_handler(call, fsm_context)

        data = await fsm_context.get_data()
        assert data["csrf_item"] == "FoundItem"
        assert data["item_back_data"] == "sp_0"

    async def test_open_item_bad_index(self, make_callback_query, fsm_context):

        await fsm_context.update_data(search_query="nothingmatches")
        call = make_callback_query(data="sitm:5:0", user_id=610008)
        await search_item_info_handler(call, fsm_context)

        call.answer.assert_called_once()
        assert call.answer.call_args[1].get("show_alert") is True


class TestSearchQueryEscaping:
    """LIKE wildcards typed by a user must be literals, not patterns."""

    async def test_underscore_is_literal(self, item_factory):

        await item_factory(name="a_b", price=10, stock=5)
        await item_factory(name="axb", price=10, stock=5)

        assert await query_goods_search("a_b") == ["a_b"]

    async def test_percent_is_literal(self, item_factory):

        await item_factory(name="100% cashback", price=10, stock=5)
        await item_factory(name="plain item", price=10, stock=5)

        assert await query_goods_search("100%") == ["100% cashback"]

    async def test_blank_query_returns_nothing(self, item_factory):

        await item_factory(name="Anything", price=10, stock=5)

        assert await query_goods_search("   ") == []
        assert await query_goods_search("   ", count_only=True) == 0

    async def test_count_only_matches_results(self, item_factory):

        for i in range(3):
            await item_factory(name=f"Bundle {i}", price=10, stock=5)

        assert await query_goods_search("Bundle", count_only=True) == 3
        assert len(await query_goods_search("Bundle")) == 3


class TestShopCategories:

    async def test_shop_shows_categories(self, make_callback_query, fsm_context, category_factory):

        await category_factory("Electronics")
        await category_factory("Clothing")

        call = make_callback_query(data="shop", user_id=600001)

        with patch('bot.handlers.user.shop_and_goods.lazy_paginated_keyboard', new_callable=AsyncMock) as mock_kb:
            mock_kb.return_value = MagicMock()
            await shop_callback_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()
        text = call.message.edit_text.call_args[0][0]
        assert "shop" in text.lower() or "categories" in text.lower() or "shop.categories" in text
        state = await fsm_context.get_state()
        assert state == ShopStates.viewing_categories

    async def test_navigate_categories_page(self, make_callback_query, fsm_context, category_factory):

        for i in range(15):
            await category_factory(f"Cat_{i}")

        call = make_callback_query(data="categories-page_1", user_id=600002)

        with patch('bot.handlers.user.shop_and_goods.lazy_paginated_keyboard', new_callable=AsyncMock) as mock_kb:
            mock_kb.return_value = MagicMock()
            await navigate_categories(call, fsm_context)

        call.message.edit_text.assert_called_once()


class TestItemsList:

    async def test_items_list_valid_category(self, make_callback_query, fsm_context, item_factory):

        await item_factory(name="Widget", price=100, category="Widgets", stock=5)

        call = make_callback_query(data="cat:0:0", user_id=600010)
        await fsm_context.update_data(category_page_items=["Widgets"])

        with patch('bot.handlers.user.shop_and_goods.lazy_paginated_keyboard', new_callable=AsyncMock) as mock_kb:
            mock_kb.return_value = MagicMock()
            await items_list_callback_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()
        assert call.message.edit_text.call_args is not None
        data = await fsm_context.get_data()
        assert data['current_category'] == 'Widgets'

    async def test_items_list_invalid_index(self, make_callback_query, fsm_context):

        call = make_callback_query(data="cat:5:0", user_id=600011)
        await fsm_context.update_data(category_page_items=["OnlyCat"])

        await items_list_callback_handler(call, fsm_context)

        call.answer.assert_called_once()


class TestItemInfo:

    async def test_item_info_display(self, make_callback_query, fsm_context, item_factory):

        await item_factory(name="InfoItem", price=250, category="TestCat", stock=5)

        call = make_callback_query(data="itm:0:0", user_id=600020)
        await fsm_context.update_data(
            goods_page_items=["InfoItem"],
            current_category="TestCat",
        )

        await item_info_callback_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()

    async def test_item_info_invalid_index(self, make_callback_query, fsm_context):

        call = make_callback_query(data="itm:10:0", user_id=600021)
        await fsm_context.update_data(goods_page_items=["SomeItem"])

        await item_info_callback_handler(call, fsm_context)

        call.answer.assert_called_once()

    async def test_item_info_resolves_from_state_without_requery(self, make_callback_query,
                                                                  fsm_context, item_factory):

        await item_factory(name="StateItem", price=100, category="StateCat", stock=5)

        call = make_callback_query(data="itm:0:0", user_id=600025)
        await fsm_context.update_data(
            goods_page_items=["StateItem"],
            goods_page_num=0,
            current_category="StateCat",
        )

        # The page list saved by the last render must be enough — the list
        # query is not re-run for the drill-down.
        with patch('bot.handlers.user.shop_and_goods.query_items_in_category',
                   new_callable=AsyncMock) as mock_q:
            await item_info_callback_handler(call, fsm_context)

        mock_q.assert_not_called()
        call.message.edit_text.assert_called_once()

    async def test_item_info_state_page_mismatch_falls_back(self, make_callback_query,
                                                            fsm_context, item_factory):

        await item_factory(name="FallbackItem", price=100, category="FallbackCat", stock=5)

        # Keyboard says page 0 but state stored page 3 — must fall back to the DB path.
        call = make_callback_query(data="itm:0:0", user_id=600026)
        await fsm_context.update_data(
            goods_page_items=["WrongItem"],
            goods_page_num=3,
            current_category="FallbackCat",
        )

        await item_info_callback_handler(call, fsm_context)

        call.message.edit_text.assert_called_once()
        data = await fsm_context.get_data()
        assert data['csrf_item'] == 'FallbackItem'

    async def test_item_info_not_found_in_db(self, make_callback_query, fsm_context):

        call = make_callback_query(data="itm:0:0", user_id=600022)
        await fsm_context.update_data(
            goods_page_items=["NonExistent"],
            current_category="TestCat",
        )

        await item_info_callback_handler(call, fsm_context)

        call.answer.assert_called_once()

    async def test_item_info_shows_units_in_stock(self, make_callback_query, fsm_context, item_factory):

        await item_factory(name="StockedItem", price=50, category="StockCat", stock=7)

        call = make_callback_query(data="itm:0:0", user_id=600023)
        await fsm_context.update_data(goods_page_items=["StockedItem"], current_category="StockCat")

        await item_info_callback_handler(call, fsm_context)

        text = call.message.edit_text.call_args[0][0]
        assert "shop.item.in_stock" in text and "'count': 7" in text
        cbs = [b.callback_data for row in call.message.edit_text.call_args[1]["reply_markup"].inline_keyboard
               for b in row]
        assert "add_to_cart" in cbs and "fav_toggle" in cbs and "buy_item" not in cbs

    async def test_out_of_stock_item_offers_restock_alert_instead_of_ordering(
            self, make_callback_query, fsm_context, item_factory):

        await item_factory(name="SoldOutItem", price=50, category="SoldCat", stock=0)

        call = make_callback_query(data="itm:0:0", user_id=600024)
        await fsm_context.update_data(goods_page_items=["SoldOutItem"], current_category="SoldCat")

        await item_info_callback_handler(call, fsm_context)

        assert "shop.item.out_of_stock" in call.message.edit_text.call_args[0][0]
        cbs = [b.callback_data for row in call.message.edit_text.call_args[1]["reply_markup"].inline_keyboard
               for b in row]
        assert "buy_item" not in cbs and "add_to_cart" not in cbs
        assert "sub_stock" in cbs



async def _place_order(user_id: int, item_name: str, qty: int = 1, method: str = "cod"):
    """Put `qty` of an item in the cart and order it; returns the order dict."""
    from bot.database.methods.orders import create_order_transaction
    await add_to_cart(user_id, item_name, quantity=qty)
    ok, code, order = await create_order_transaction(
        user_id, fulfillment="pickup", customer_name="Ana", phone="+37369123456",
        address=None, comment=None, payment_method=method,
    )
    assert ok, code
    return order


class TestMyOrders:

    async def test_orders_list_empty(self, make_callback_query, fsm_context, user_factory):

        await user_factory(telegram_id=600030)
        call = make_callback_query(data="my_orders", user_id=600030)

        await my_orders_handler(call, fsm_context)

        text = call.message.edit_text.call_args[0][0]
        assert "orders.empty" in text

    async def test_orders_list_shows_own_orders(self, make_callback_query, fsm_context,
                                                user_factory, item_factory):

        await user_factory(telegram_id=600032)
        await item_factory(name="Mug", price=40, stock=5)
        order = await _place_order(600032, "Mug", qty=2)

        call = make_callback_query(data="my_orders", user_id=600032)
        await my_orders_handler(call, fsm_context)

        markup = call.message.edit_text.call_args[1]["reply_markup"]
        cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert f"my_order:{order['id']}:0" in cbs

    async def test_order_detail_renders_the_card(self, make_callback_query, fsm_context,
                                                 user_factory, item_factory):

        await user_factory(telegram_id=600033)
        await item_factory(name="Lamp", price=40, stock=5)
        order = await _place_order(600033, "Lamp")

        call = make_callback_query(data=f"my_order:{order['id']}", user_id=600033)
        await my_order_handler(call, fsm_context)

        text = call.message.edit_text.call_args[0][0]
        assert "Lamp" in text
        cbs = [b.callback_data for row in call.message.edit_text.call_args[1]["reply_markup"].inline_keyboard
               for b in row]
        assert f"my_order_cancel:{order['id']}" in cbs       # a fresh COD order can still be cancelled

    async def test_order_detail_of_someone_else_is_not_found(self, make_callback_query, fsm_context,
                                                             user_factory, item_factory):

        await user_factory(telegram_id=600034)
        await user_factory(telegram_id=600035)
        await item_factory(name="Chair", price=40, stock=5)
        order = await _place_order(600034, "Chair")

        call = make_callback_query(data=f"my_order:{order['id']}", user_id=600035)
        await my_order_handler(call, fsm_context)

        call.message.edit_text.assert_not_called()
        assert "orders.not_found" in call.answer.call_args[0][0]

    async def test_order_detail_bad_payload(self, make_callback_query, fsm_context):

        call = make_callback_query(data="my_order:abc", user_id=600036)
        await my_order_handler(call, fsm_context)

        call.message.edit_text.assert_not_called()
        call.answer.assert_called_once()

    async def test_mia_order_awaiting_payment_offers_payment_buttons(
            self, make_callback_query, fsm_context, user_factory, item_factory):

        await user_factory(telegram_id=600037)
        await item_factory(name="Desk", price=40, stock=5)
        order = await _place_order(600037, "Desk", method="mia")

        call = make_callback_query(data=f"my_order:{order['id']}", user_id=600037)
        await my_order_handler(call, fsm_context)

        cbs = [b.callback_data for row in call.message.edit_text.call_args[1]["reply_markup"].inline_keyboard
               for b in row]
        assert f"mia_paid:{order['id']}" in cbs and f"mia_info:{order['id']}" in cbs

    async def test_cancel_asks_first_then_restocks(self, make_callback_query, fsm_context,
                                                   user_factory, item_factory):
        from bot.database.methods.read import select_item_stock

        await user_factory(telegram_id=600038)
        await item_factory(name="Vase", price=40, stock=1)
        order = await _place_order(600038, "Vase")
        assert await select_item_stock("Vase") == 0

        ask = make_callback_query(data=f"my_order_cancel:{order['id']}", user_id=600038)
        await my_order_cancel_ask_handler(ask, fsm_context)
        assert "orders.cancel_confirm" in ask.message.edit_text.call_args[0][0]
        assert await select_item_stock("Vase") == 0          # asking changes nothing

        yes = make_callback_query(data=f"my_order_cancel_yes:{order['id']}:0", user_id=600038)
        with patch('bot.handlers.user.shop_and_goods.notify_restock', new_callable=AsyncMock) as notify:
            await my_order_cancel_handler(yes, fsm_context)

        assert await select_item_stock("Vase") == 1
        assert "orders.cancelled" in yes.answer.call_args[0][0]
        notify.assert_called_once_with(yes.bot, "Vase")      # 0 -> 1 wakes the restock subscribers

    async def test_cancel_refused_once_the_shop_accepted_the_order(
            self, make_callback_query, fsm_context, user_factory, item_factory):
        from bot.database.methods.orders import set_order_status

        await user_factory(telegram_id=600039)
        await item_factory(name="Plate", price=40, stock=3)
        order = await _place_order(600039, "Plate")
        assert (await set_order_status(order["id"], "confirmed"))[0]

        yes = make_callback_query(data=f"my_order_cancel_yes:{order['id']}", user_id=600039)
        await my_order_cancel_handler(yes, fsm_context)

        assert "orders.not_cancellable" in yes.answer.call_args[0][0]

    async def test_cannot_cancel_someone_elses_order(self, make_callback_query, fsm_context,
                                                     user_factory, item_factory):
        from bot.database.methods.read import select_item_stock

        await user_factory(telegram_id=600040)
        await user_factory(telegram_id=600041)
        await item_factory(name="Bowl", price=40, stock=3)
        order = await _place_order(600040, "Bowl")

        yes = make_callback_query(data=f"my_order_cancel_yes:{order['id']}", user_id=600041)
        await my_order_cancel_handler(yes, fsm_context)

        assert await select_item_stock("Bowl") == 2
        assert "orders.not_found" in yes.answer.call_args[0][0]


class TestHtmlEscapingInRenderedText:
    HOSTILE = '<b>Widget</b> & "co" <script>'

    async def test_item_card_escapes_name_and_description(
        self, make_callback_query, fsm_context, item_factory
    ):

        await item_factory(
            name=self.HOSTILE, price=100, description=self.HOSTILE,
            stock=5,
        )

        call = make_callback_query(data="itm:0:0", user_id=610901)
        await _render_item_page(call, fsm_context, self.HOSTILE, "gp_0", user_id=610901)

        text = call.message.edit_text.call_args[0][0]
        assert "&lt;b&gt;Widget&lt;/b&gt;" in text
        assert "&amp;" in text
        # No raw angle bracket survives outside the template's own markup.
        assert "<script>" not in text

    async def test_cart_escapes_item_name(self, make_callback_query, user_factory, item_factory):

        await user_factory(telegram_id=610902, balance=1000)
        await item_factory(name=self.HOSTILE, price=100, stock=5)
        ok, _ = await add_to_cart(610902, self.HOSTILE)
        assert ok

        call = make_callback_query(data="cart", user_id=610902)
        await _show_cart(call)

        text = call.message.edit_text.call_args[0][0]
        assert "&lt;b&gt;Widget&lt;/b&gt;" in text
        assert "<script>" not in text

    async def test_esc_helper_handles_none(self):
        from bot.i18n import esc

        assert esc(None) == ""
        assert esc(5) == "5"
        assert esc("a < b & c") == "a &lt; b &amp; c"


class TestBackFromItemCardAfterPurchase:
    """The receipt's Back button leads to the item card, whose own Back is
    gp_/sp_ — and those pagers are state-filtered. Anything on that path that
    drops the browsing state leaves the card's Back button dead."""

    async def test_back_to_item_after_buying_keeps_the_browsing_state(
        self, make_callback_query, fsm_context, user_factory, item_factory
    ):

        await user_factory(telegram_id=660001, balance=1000)
        await item_factory(name="BoughtThenBack", price=100, stock=5)

        # Browsing a category, with the item card open.
        await fsm_context.update_data(csrf_item="BoughtThenBack", item_back_data="gp_0",
                                      current_category="TestCategory")
        await fsm_context.set_state(ShopStates.viewing_goods)

        buy = make_callback_query(data="add_to_cart", user_id=660001)
        await add_to_cart_handler(buy, fsm_context)

        # Receipt -> Back returns to the item card.
        back = make_callback_query(data="back_to_item", user_id=660001)
        await back_to_item_handler(back, fsm_context)

        # The card's Back is gp_0; navigate_goods is filtered on this state, so
        # losing it here is what made the button do nothing.
        assert await fsm_context.get_state() == ShopStates.viewing_goods

    async def test_back_to_item_from_search_keeps_the_search_state(
        self, make_callback_query, fsm_context, user_factory, item_factory
    ):

        await user_factory(telegram_id=660002, balance=1000)
        await item_factory(name="SearchThenBack", price=100, stock=5)

        await fsm_context.update_data(csrf_item="SearchThenBack", item_back_data="sp_0",
                                      search_query="Search")
        await fsm_context.set_state(ShopStates.viewing_search_results)

        buy = make_callback_query(data="add_to_cart", user_id=660002)
        await add_to_cart_handler(buy, fsm_context)

        back = make_callback_query(data="back_to_item", user_id=660002)
        await back_to_item_handler(back, fsm_context)

        assert await fsm_context.get_state() == ShopStates.viewing_search_results

    @staticmethod
    def _registered_filters(callback):
        """The filters aiogram will run for a handler, as registered."""

        for h in router.callback_query.handlers:
            if h.callback is callback:
                return h.filters or ()
        raise AssertionError(f"{callback.__name__} is not registered on the router")

    async def _passes_registered_filters(self, callback, call, fsm_context):
        """Whether aiogram's own filters would let this callback through.

        Calling the handler directly would bypass them, which is exactly the
        thing that was broken — the payload matched, the state did not.
        """
        raw_state = await fsm_context.get_state()
        # aiogram stores raw_state as a string; the fake context keeps the object.
        raw_state = getattr(raw_state, "state", raw_state)

        for f in self._registered_filters(callback):
            verdict = f.magic.resolve(call) if f.magic is not None \
                else f.callback(call, raw_state=raw_state)
            if not verdict:
                return False
        return True

    async def test_the_back_button_actually_pages_after_a_purchase(
        self, make_callback_query, fsm_context, user_factory, item_factory
    ):
        """End-to-end on the reported flow: browse a category, buy, return from
        the receipt, then press the card's Back — aiogram must route it, and it
        must render the goods list rather than silently doing nothing."""

        await user_factory(telegram_id=660004, balance=1000)
        await item_factory(name="EndToEndBack", price=100, category="E2ECat",
                           stock=5)

        await shop_callback_handler(make_callback_query(data="shop", user_id=660004), fsm_context)
        await items_list_callback_handler(make_callback_query(data="cat:0:0", user_id=660004), fsm_context)
        await item_info_callback_handler(make_callback_query(data="itm:0:0", user_id=660004), fsm_context)

        await add_to_cart_handler(make_callback_query(data="add_to_cart", user_id=660004), fsm_context)
        await back_to_item_handler(make_callback_query(data="back_to_item", user_id=660004), fsm_context)

        # The card's Back is gp_0.
        page = make_callback_query(data="gp_0", user_id=660004)
        assert await self._passes_registered_filters(navigate_goods, page, fsm_context), \
            "gp_0 would not reach navigate_goods — the Back button is dead"

        await navigate_goods(page, fsm_context)
        page.message.edit_text.assert_called_once()
        assert page.message.edit_text.call_args[1].get("reply_markup") is not None

    async def test_the_filter_probe_can_fail(self, make_callback_query, fsm_context):
        """Guard: with the browsing state cleared, gp_0 must NOT route."""

        await fsm_context.set_state(None)
        page = make_callback_query(data="gp_0", user_id=660005)
        assert await self._passes_registered_filters(navigate_goods, page, fsm_context) is False
