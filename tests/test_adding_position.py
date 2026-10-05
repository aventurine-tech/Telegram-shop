from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from bot.database.methods.read import get_item_info, select_item_stock
from bot.handlers.admin.adding_position import (
    add_item_callback_handler, check_item_name_for_add, add_item_description,
    add_item_price, check_category_for_add_item, add_item_stock,
)
from bot.states import AddItemFSM


async def _walk_to_stock_prompt(make_message, fsm_context, *,
                                name="NewItem", price="100", category="AddCat"):
    """Drive the FSM from the name prompt up to the stock quantity prompt."""
    await check_item_name_for_add(make_message(text=name, user_id=1), fsm_context)
    await add_item_description(make_message(text="A description", user_id=1), fsm_context)
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

        assert await fsm_context.get_state() == AddItemFSM.waiting_item_description
        assert (await fsm_context.get_data())["item_name"] == "Fresh Item"

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

    async def test_creates_the_product_with_its_stock(self, make_message, fsm_context,
                                                      category_factory):
        await category_factory("AddCat")
        await _walk_to_stock_prompt(make_message, fsm_context, name="Lamp")

        msg = make_message(text="12", user_id=1)
        with patch('bot.handlers.admin.adding_position._notify_restock_safe', new_callable=AsyncMock), \
                patch('bot.handlers.admin.adding_position.announce_arrival', new_callable=AsyncMock):
            await add_item_stock(msg, fsm_context)

        item = await get_item_info("Lamp")
        assert item["price"] == Decimal("100")
        assert item["description"] == "A description"
        assert await select_item_stock("Lamp") == 12
        assert await fsm_context.get_state() is None
        msg.answer.assert_called_once()

    async def test_zero_stock_is_allowed_and_not_announced(self, make_message, fsm_context,
                                                           category_factory):
        await category_factory("AddCat")
        await _walk_to_stock_prompt(make_message, fsm_context, name="PreOrder")

        with patch('bot.handlers.admin.adding_position._notify_restock_safe',
                   new_callable=AsyncMock) as notify, \
                patch('bot.handlers.admin.adding_position.announce_arrival',
                      new_callable=AsyncMock) as announce:
            await add_item_stock(make_message(text="0", user_id=1), fsm_context)

        assert await get_item_info("PreOrder") is not None
        assert await select_item_stock("PreOrder") == 0
        notify.assert_not_awaited()
        announce.assert_not_awaited()

    async def test_in_stock_product_wakes_subscribers_and_channel(self, make_message, fsm_context,
                                                                  category_factory, mock_bot):
        await category_factory("AddCat")
        await _walk_to_stock_prompt(make_message, fsm_context, name="AwaitedItem")

        with patch('bot.handlers.admin.adding_position._notify_restock_safe',
                   new_callable=AsyncMock) as notify, \
                patch('bot.handlers.admin.adding_position.announce_arrival',
                      new_callable=AsyncMock) as announce:
            await add_item_stock(make_message(text="3", user_id=1), fsm_context)

        notify.assert_awaited_once_with(mock_bot, "AwaitedItem")
        announce.assert_awaited_once_with(mock_bot, "AwaitedItem", 3)

    async def test_creation_is_audited(self, make_message, fsm_context, category_factory):
        await category_factory("AddCat")
        await _walk_to_stock_prompt(make_message, fsm_context, name="Audited")

        with patch('bot.handlers.admin.adding_position.log_audit', new_callable=AsyncMock) as audit, \
                patch('bot.handlers.admin.adding_position.announce_arrival', new_callable=AsyncMock):
            await add_item_stock(make_message(text="1", user_id=77), fsm_context)

        assert audit.await_args[0][0] == "create_item"
        assert audit.await_args[1]["user_id"] == 77
        assert audit.await_args[1]["resource_id"] == "Audited"
