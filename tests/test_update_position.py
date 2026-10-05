from unittest.mock import AsyncMock, patch

import pytest

from bot.database.methods.read import get_item_info, select_item_stock
from bot.handlers.admin.update_position import (
    _show_update_item_error, _UPDATE_ITEM_ERRORS,
    update_item_callback_handler, check_item_name_for_update, update_item_name,
    update_item_description, update_item_price, update_item_category, update_item_keep_category,
)
from bot.states import UpdateItemFSM


async def _walk_to_category_step(make_message, fsm_context, *, old_name, new_name, price="200"):
    """Drive the edit flow from the name prompt to the category step."""
    await check_item_name_for_update(make_message(text=old_name, user_id=1), fsm_context)
    await update_item_name(make_message(text=new_name, user_id=1), fsm_context)
    await update_item_description(make_message(text="New description", user_id=1), fsm_context)
    await update_item_price(make_message(text=price, user_id=1), fsm_context)


class TestUpdateItemErrorMapping:

    @pytest.mark.parametrize("code,expected_key", [
        ("position_invalid", "admin.goods.update.position.invalid"),
        ("position_exists", "admin.goods.update.position.exists"),
        ("db_error", "errors.something_wrong"),
        ("something_unmapped", "errors.something_wrong"),  # unknown codes fall back
        (None, "errors.something_wrong"),
    ])
    async def test_every_code_maps_to_a_message(self, code, expected_key):
        send = AsyncMock()
        with patch('bot.handlers.admin.update_position.localize',
                   side_effect=lambda key, **kw: key):
            await _show_update_item_error(send, code)
        assert send.await_args[0][0] == expected_key

    def test_mapping_covers_the_documented_codes(self):
        assert set(_UPDATE_ITEM_ERRORS) == {"position_invalid", "position_exists", "db_error"}


class TestUpdateFlowSteps:

    async def test_start_sets_the_name_state(self, make_callback_query, fsm_context):
        call = make_callback_query(data="update_item", user_id=900720)
        await update_item_callback_handler(call, fsm_context)

        assert await fsm_context.get_state() == UpdateItemFSM.waiting_item_name_for_update

    async def test_known_item_remembers_name_and_category(self, make_message, fsm_context,
                                                          item_factory):
        await item_factory(name="Editable", price=100, category="EditCat", stock=2)

        await check_item_name_for_update(make_message(text="Editable", user_id=1), fsm_context)

        data = await fsm_context.get_data()
        assert data["item_old_name"] == "Editable"
        assert data["item_category"] == "EditCat"
        assert await fsm_context.get_state() == UpdateItemFSM.waiting_item_new_name

    async def test_unknown_item_keeps_the_state(self, make_message, fsm_context):
        await fsm_context.set_state(UpdateItemFSM.waiting_item_name_for_update)
        await check_item_name_for_update(make_message(text="Ghost", user_id=1), fsm_context)

        assert await fsm_context.get_state() == UpdateItemFSM.waiting_item_name_for_update

    @pytest.mark.parametrize("bad_name", ["", "A" * 101, "bad\x00name"])
    async def test_unsafe_new_name_is_refused(self, make_message, fsm_context, bad_name):
        await fsm_context.set_state(UpdateItemFSM.waiting_item_new_name)
        await update_item_name(make_message(text=bad_name, user_id=1), fsm_context)

        assert await fsm_context.get_state() == UpdateItemFSM.waiting_item_new_name

    @pytest.mark.parametrize("bad_price", ["abc", "0", "-5", "9.99", "100000000"])
    async def test_invalid_price_keeps_the_state(self, make_message, fsm_context, bad_price):
        await fsm_context.set_state(UpdateItemFSM.waiting_item_price)
        await update_item_price(make_message(text=bad_price, user_id=1), fsm_context)

        assert await fsm_context.get_state() == UpdateItemFSM.waiting_item_price

    async def test_price_step_offers_to_keep_the_category(self, make_message, fsm_context,
                                                          item_factory):
        await item_factory(name="Editable", price=100, category="EditCat", stock=2)
        await check_item_name_for_update(make_message(text="Editable", user_id=1), fsm_context)
        await update_item_name(make_message(text="Editable", user_id=1), fsm_context)
        await update_item_description(make_message(text="d", user_id=1), fsm_context)

        msg = make_message(text="150", user_id=1)
        await update_item_price(msg, fsm_context)

        markup = msg.answer.call_args[1]["reply_markup"]
        assert [b.callback_data for row in markup.inline_keyboard for b in row] == [
            "update_keep_category", "goods_management",
        ]
        assert await fsm_context.get_state() == UpdateItemFSM.waiting_item_category


class TestApplyUpdate:

    async def test_keep_category_updates_details_and_leaves_stock_alone(
            self, make_message, make_callback_query, fsm_context, item_factory):
        await item_factory(name="OldName", price=100, category="KeepCat", stock=7)
        await _walk_to_category_step(make_message, fsm_context, old_name="OldName", new_name="NewName")

        call = make_callback_query(data="update_keep_category", user_id=1)
        await update_item_keep_category(call, fsm_context)

        assert await get_item_info("OldName") is None
        item = await get_item_info("NewName")
        assert item["description"] == "New description"
        assert int(item["price"]) == 200
        assert await select_item_stock("NewName") == 7
        assert await fsm_context.get_state() is None

    async def test_new_category_moves_the_product(self, make_message, fsm_context, item_factory,
                                                  category_factory):
        await item_factory(name="Mover", price=100, category="FromCat", stock=1)
        await category_factory("ToCat")
        await _walk_to_category_step(make_message, fsm_context, old_name="Mover", new_name="Mover")

        await update_item_category(make_message(text="ToCat", user_id=1), fsm_context)

        from bot.database.methods.read import get_category_name_by_id
        item = await get_item_info("Mover")
        assert await get_category_name_by_id(item["category_id"]) == "ToCat"
        assert await fsm_context.get_state() is None

    async def test_unknown_category_keeps_the_state_and_changes_nothing(
            self, make_message, fsm_context, item_factory):
        await item_factory(name="Stays", price=100, category="HomeCat", stock=1)
        await _walk_to_category_step(make_message, fsm_context, old_name="Stays", new_name="Renamed")

        await update_item_category(make_message(text="NoSuchCat", user_id=1), fsm_context)

        assert await fsm_context.get_state() == UpdateItemFSM.waiting_item_category
        assert await get_item_info("Stays") is not None
        assert await get_item_info("Renamed") is None

    async def test_name_taken_by_another_product_is_reported(
            self, make_message, make_callback_query, fsm_context, item_factory):
        await item_factory(name="First", price=100, category="DupCat", stock=1)
        await item_factory(name="Second", price=100, category="DupCat", stock=1)
        await _walk_to_category_step(make_message, fsm_context, old_name="First", new_name="Second")

        call = make_callback_query(data="update_keep_category", user_id=1)
        await update_item_keep_category(call, fsm_context)

        from bot.i18n.strings import TRANSLATIONS
        assert call.message.edit_text.call_args[0][0] in (
            TRANSLATIONS["ru"]["admin.goods.update.position.exists"],
            TRANSLATIONS["en"]["admin.goods.update.position.exists"],
        )
        assert await get_item_info("First") is not None
        assert await fsm_context.get_state() is None

    async def test_update_is_audited(self, make_message, make_callback_query, fsm_context,
                                     item_factory):
        await item_factory(name="Auditable", price=100, category="AudCat", stock=1)
        await _walk_to_category_step(make_message, fsm_context, old_name="Auditable",
                                     new_name="Auditable2")

        with patch('bot.handlers.admin.update_position.log_audit', new_callable=AsyncMock) as audit:
            await update_item_keep_category(make_callback_query(data="update_keep_category", user_id=55),
                                            fsm_context)

        assert audit.await_args[0][0] == "update_item"
        assert audit.await_args[1]["resource_id"] == "Auditable2"
        assert audit.await_args[1]["user_id"] == 55
