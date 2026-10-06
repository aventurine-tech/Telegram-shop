"""Apply promo code inside the cart (between Checkout and Clear cart)."""
from decimal import Decimal

import pytest

from bot.database.main import Database
from bot.database.methods.create import add_to_cart
from bot.database.methods.orders import create_order_transaction
from bot.database.methods.read import get_cart_items
from bot.database.models.main import PromoCodes
from bot.handlers.user.cart import (
    _cart_view_data, cart_promo_code_handler, cart_promo_handler, view_cart_handler,
)
from bot.keyboards.inline import cart_keyboard
from bot.states.promo_state import PromoFSM

UID = 931001


async def promo(code, *, percent="50", dtype="percent", **kw):
    async with Database().session() as s:
        s.add(PromoCodes(code=code, discount_type=dtype, discount_value=Decimal(percent), scope=kw.pop("scope", "global"),
                         is_active=kw.pop("is_active", True), **kw))


@pytest.fixture
async def cart(user_factory, item_factory):
    await user_factory(telegram_id=UID)
    await item_factory(name="Cheap", price=100, category="CatA", stock=9)
    await item_factory(name="Pricey", price=300, category="CatB", stock=9)
    await add_to_cart(UID, "Cheap", quantity=1)
    await add_to_cart(UID, "Pricey", quantity=1)


def _cbs(mock):
    return [b.callback_data for row in mock.edit_text.call_args[1]["reply_markup"].inline_keyboard for b in row]


class TestKeyboard:

    def test_promo_button_is_between_checkout_and_clear(self):
        rows = [[b.callback_data for b in row] for row in cart_keyboard([]).inline_keyboard]
        assert rows == [["cart_checkout"], ["cart_promo"], ["cart_clear"], ["profile"]]


class TestFlow:

    async def test_button_asks_for_the_code_and_back_leaves_the_prompt(self, cart, make_callback_query, fsm_context):
        call = make_callback_query(data="cart_promo", user_id=UID)
        await cart_promo_handler(call, fsm_context)
        assert await fsm_context.get_state() == PromoFSM.waiting_cart_code
        assert "promo.enter_code" in call.message.edit_text.call_args[0][0]
        await view_cart_handler(make_callback_query(data="cart", user_id=UID), fsm_context)
        assert await fsm_context.get_state() is None

    async def test_empty_cart_is_refused(self, user_factory, make_callback_query, fsm_context):
        await user_factory(telegram_id=UID + 5)
        call = make_callback_query(data="cart_promo", user_id=UID + 5)
        await cart_promo_handler(call, fsm_context)
        assert call.answer.call_args[1].get("show_alert") is True
        assert await fsm_context.get_state() is None

    async def test_a_global_code_goes_on_both_lines_and_discounts_the_best_one(
            self, cart, make_message, fsm_context):
        await promo("HALF")
        await fsm_context.set_state(PromoFSM.waiting_cart_code)
        msg = make_message(text=" half ", user_id=UID)
        await cart_promo_handler_text(msg, fsm_context)
        lines = await get_cart_items(UID)
        assert {l["promo_code"] for l in lines} == {"HALF"}
        assert await fsm_context.get_state() is None
        _items, _info, _data, total = await _cart_view_data(UID)
        assert total == Decimal("250.00")                      # one redemption: 300 -> 150, 100 untouched

    async def test_displayed_total_is_what_checkout_charges(self, cart, make_message, fsm_context):
        await promo("HALF")
        await cart_promo_handler_text(make_message(text="HALF", user_id=UID), fsm_context)
        _i, _n, _d, shown = await _cart_view_data(UID)
        ok, code, order = await create_order_transaction(
            UID, fulfillment="pickup", customer_name="Ana", phone="+37360000001", address=None, comment=None,
            payment_method="cod", expected_total=shown)
        assert ok, code
        assert order["total"] == shown

    async def test_category_code_marks_only_matching_lines(self, cart, make_message, fsm_context):
        from sqlalchemy import select
        from bot.database.models.main import Categories
        async with Database().session() as s:
            cat_id = (await s.execute(select(Categories.id).where(Categories.name == "CatA"))).scalar()
        await promo("ONLYA", scope="category", category_id=cat_id)
        await cart_promo_handler_text(make_message(text="ONLYA", user_id=UID), fsm_context)
        by_item = {l["item_name"]: l["promo_code"] for l in await get_cart_items(UID)}
        assert by_item == {"Cheap": "ONLYA", "Pricey": None}

    @pytest.mark.parametrize("code,key", [
        ("NOSUCH", "promo.not_found"),
    ])
    async def test_unknown_code(self, cart, make_message, fsm_context, code, key):
        msg = make_message(text=code, user_id=UID)
        await cart_promo_handler_text(msg, fsm_context)
        assert key in msg.answer.call_args[0][0]
        assert all(l["promo_code"] is None for l in await get_cart_items(UID))

    async def test_inactive_and_balance_codes_are_refused(self, cart, make_message, fsm_context):
        await promo("OFF", is_active=False)
        await promo("TOPUP", dtype="balance", percent="10")
        for code, key in (("OFF", "promo.inactive"), ("TOPUP", "promo.not_balance_type")):
            msg = make_message(text=code, user_id=UID)
            await cart_promo_handler_text(msg, fsm_context)
            assert key in msg.answer.call_args[0][0], code
        assert all(l["promo_code"] is None for l in await get_cart_items(UID))

    async def test_a_valid_code_that_fits_no_line(self, cart, make_message, fsm_context):
        await promo("NOMATCH", scope="item", item_id=None)       # bound to nothing → never applies
        msg = make_message(text="NOMATCH", user_id=UID)
        await cart_promo_handler_text(msg, fsm_context)
        assert "promo.not_applicable_cart" in msg.answer.call_args[0][0] or "promo.wrong_item" in msg.answer.call_args[0][0]
        assert all(l["promo_code"] is None for l in await get_cart_items(UID))


async def cart_promo_handler_text(msg, fsm_context):
    await cart_promo_code_handler(msg, fsm_context)
