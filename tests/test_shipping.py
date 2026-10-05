"""Shipping methods: price rules, the order transaction, the checkout flow, the web page."""
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import delete, select

from bot.database.main import Database
from bot.database.methods.create import add_to_cart
from bot.database.methods.orders import create_order_transaction
from bot.database.methods.shipping import active_methods, delivery_fee
from bot.database.methods.web_users import create_web_user
from bot.database.models.main import Fulfillment, Orders, PaymentMethod, ShippingMethods, WebRole
from bot.handlers.user.checkout import (
    address_handler, cart_checkout_handler, confirm_order_handler, fulfillment_chosen_handler,
    name_text_handler, payment_chosen_handler, phone_text_handler, shipping_chosen_handler,
    skip_comment_handler,
)
from bot.misc.services.order_view import format_order
from bot.states import CheckoutFSM
from bot.web.admin import ShippingAdmin, create_admin_app
from bot.web.language import LANG_COOKIE

UID = 990001


async def set_methods(*rows):
    """Replace all shipping methods with ``rows`` of (name, price, free_from, active)."""
    async with Database().session() as s:
        await s.execute(delete(ShippingMethods))
        for i, (name, price, free_from, active) in enumerate(rows):
            s.add(ShippingMethods(name=name, price=Decimal(str(price)),
                                  free_from=None if free_from is None else Decimal(str(free_from)),
                                  is_active=active, position=i))
    async with Database().session() as s:
        return {m.name: m.id for m in (await s.execute(select(ShippingMethods))).scalars().all()}


@pytest.fixture(autouse=True)
async def _clean():
    await set_methods()
    yield
    await set_methods()


class TestFee:

    def test_price_and_free_threshold(self):
        m = {"price": Decimal("30"), "free_from": Decimal("500")}
        assert delivery_fee(m, 100) == Decimal("30.00")
        assert delivery_fee(m, 499.99) == Decimal("30.00")
        assert delivery_fee(m, 500) == Decimal("0.00")
        assert delivery_fee({"price": 30, "free_from": None}, 10 ** 6) == Decimal("30.00")

    async def test_only_active_methods_in_the_shops_order(self):
        await set_methods(("Courier", 30, None, True), ("Old", 5, None, False), ("Post", 20, None, True))
        assert [m["name"] for m in await active_methods()] == ["Courier", "Post"]


class TestTransaction:

    async def _place(self, item_factory, user_factory, uid=UID, **over):
        await user_factory(telegram_id=uid)
        await item_factory(name=f"Item{uid}", price=100, stock=9)
        await add_to_cart(uid, f"Item{uid}", quantity=2)
        kw = dict(fulfillment=Fulfillment.DELIVERY, customer_name="Ana", phone="+37360000001",
                  address="Str. 1", comment=None, payment_method=PaymentMethod.COD)
        kw.update(over)
        return await create_order_transaction(uid, **kw)

    async def test_without_methods_delivery_is_free_and_unpriced(self, item_factory, user_factory):
        ok, code, order = await self._place(item_factory, user_factory)
        assert ok, code
        assert order["total"] == Decimal("200.00") and order["delivery_fee"] == 0 and order["shipping_name"] is None

    async def test_a_method_is_required_when_the_shop_offers_some(self, item_factory, user_factory):
        await set_methods(("Courier", 30, None, True))
        ok, code, _ = await self._place(item_factory, user_factory)
        assert (ok, code) == (False, "shipping_required")

    async def test_unknown_or_inactive_method_is_refused(self, item_factory, user_factory):
        ids = await set_methods(("Courier", 30, None, True), ("Old", 5, None, False))
        assert (await self._place(item_factory, user_factory, shipping_method_id=999999))[1] == "invalid_shipping"
        assert (await self._place(item_factory, user_factory, shipping_method_id=ids["Old"]))[1] == "invalid_shipping"

    async def test_the_price_is_added_to_the_total(self, item_factory, user_factory):
        ids = await set_methods(("Courier", 30, None, True))
        ok, code, order = await self._place(item_factory, user_factory, shipping_method_id=ids["Courier"],
                                            expected_total=Decimal("230.00"))
        assert ok, code
        assert (order["total"], order["delivery_fee"], order["shipping_name"]) == (
            Decimal("230.00"), Decimal("30.00"), "Courier")
        async with Database().session() as s:
            stored = (await s.execute(select(Orders).where(Orders.id == order["id"]))).scalars().one()
        assert stored.total == Decimal("230.00") and stored.delivery_fee == Decimal("30.00")

    async def test_expected_total_must_include_the_fee(self, item_factory, user_factory):
        ids = await set_methods(("Courier", 30, None, True))
        ok, code, _ = await self._place(item_factory, user_factory, shipping_method_id=ids["Courier"],
                                        expected_total=Decimal("200.00"))
        assert (ok, code) == (False, "price_changed")

    async def test_free_above_the_threshold(self, item_factory, user_factory):
        ids = await set_methods(("Courier", 30, 150, True))
        ok, code, order = await self._place(item_factory, user_factory, shipping_method_id=ids["Courier"])
        assert ok, code
        assert order["total"] == Decimal("200.00") and order["delivery_fee"] == 0 and order["shipping_name"] == "Courier"

    async def test_pickup_never_pays_delivery(self, item_factory, user_factory):
        ids = await set_methods(("Courier", 30, None, True))
        ok, code, order = await self._place(item_factory, user_factory, fulfillment=Fulfillment.PICKUP, address=None,
                                            shipping_method_id=ids["Courier"])
        assert ok, code
        assert order["total"] == Decimal("200.00") and order["shipping_name"] is None

    async def test_the_order_card_shows_the_delivery_line(self, item_factory, user_factory):
        ids = await set_methods(("Courier", 30, None, True))
        _, _, order = await self._place(item_factory, user_factory, shipping_method_id=ids["Courier"])
        assert "order.line.delivery" in format_order(order)
        ids = await set_methods(("Courier", 30, 100, True))
        _, _, free = await self._place(item_factory, user_factory, uid=UID + 1, shipping_method_id=ids["Courier"])
        assert "order.line.delivery_free" in format_order(free)
        _, _, pick = await self._place(item_factory, user_factory, uid=UID + 2, fulfillment=Fulfillment.PICKUP,
                                       address=None)
        assert "order.line.delivery" not in format_order(pick)


def _cbs(mock):
    markup = mock.edit_text.call_args[1]["reply_markup"]
    return [b.callback_data for row in markup.inline_keyboard for b in row]


class TestCheckoutFlow:

    async def _until_address(self, uid, make_callback_query, make_message, fsm_context, user_factory, item_factory):
        await user_factory(telegram_id=uid)
        await item_factory(name=f"Mug{uid}", price=40, stock=9)
        await add_to_cart(uid, f"Mug{uid}", quantity=2)
        await cart_checkout_handler(make_callback_query(data="cart_checkout", user_id=uid), fsm_context)
        await fulfillment_chosen_handler(make_callback_query(data="co_ful:delivery", user_id=uid), fsm_context)
        await name_text_handler(make_message(text="Ana", user_id=uid), fsm_context)
        await phone_text_handler(make_message(text="+373 69 123 456", user_id=uid), fsm_context)
        address = make_message(text="Str. Mare 1", user_id=uid)
        await address_handler(address, fsm_context)
        return address

    async def test_no_methods_goes_straight_to_the_comment(self, make_callback_query, make_message, fsm_context,
                                                           user_factory, item_factory):
        await self._until_address(990101, make_callback_query, make_message, fsm_context, user_factory, item_factory)
        assert await fsm_context.get_state() == CheckoutFSM.waiting_comment

    async def test_several_methods_are_offered_with_prices(self, make_callback_query, make_message, fsm_context,
                                                           user_factory, item_factory):
        ids = await set_methods(("Courier", 30, None, True), ("Post", 20, 50, True))
        msg = await self._until_address(990102, make_callback_query, make_message, fsm_context, user_factory, item_factory)
        assert await fsm_context.get_state() == CheckoutFSM.choosing_shipping
        markup = msg.answer.call_args[1]["reply_markup"]
        assert [b.callback_data for row in markup.inline_keyboard for b in row] == [
            f"co_ship:{ids['Courier']}", f"co_ship:{ids['Post']}", "co_cancel"]
        # goods 80 MDL: Courier 30 -> 110; Post is free from 50 -> 80
        call = make_callback_query(data=f"co_ship:{ids['Courier']}", user_id=990102)
        await shipping_chosen_handler(call, fsm_context)
        assert await fsm_context.get_state() == CheckoutFSM.waiting_comment
        assert (await fsm_context.get_data())["co_total"] == "110.00"

    async def test_a_single_method_is_taken_automatically(self, make_callback_query, make_message, fsm_context,
                                                          user_factory, item_factory):
        await set_methods(("Courier", 30, None, True))
        await self._until_address(990103, make_callback_query, make_message, fsm_context, user_factory, item_factory)
        assert await fsm_context.get_state() == CheckoutFSM.waiting_comment
        assert (await fsm_context.get_data())["co_total"] == "110.00"

    async def test_a_method_switched_off_meanwhile_is_refused(self, make_callback_query, make_message, fsm_context,
                                                              user_factory, item_factory):
        ids = await set_methods(("Courier", 30, None, True), ("Post", 20, None, True))
        await self._until_address(990104, make_callback_query, make_message, fsm_context, user_factory, item_factory)
        await set_methods(("Courier", 30, None, False), ("Post", 20, None, True))
        call = make_callback_query(data=f"co_ship:{ids['Courier']}", user_id=990104)
        await shipping_chosen_handler(call, fsm_context)
        assert call.answer.call_args[1].get("show_alert") is True
        assert await fsm_context.get_state() == CheckoutFSM.waiting_comment     # the one left is taken
        assert (await fsm_context.get_data())["co_total"] == "100.00"

    async def test_end_to_end_charges_the_fee(self, make_callback_query, make_message, fsm_context,
                                              user_factory, item_factory):
        uid = 990105
        ids = await set_methods(("Courier", 30, None, True), ("Post", 20, None, True))
        await self._until_address(uid, make_callback_query, make_message, fsm_context, user_factory, item_factory)
        await shipping_chosen_handler(make_callback_query(data=f"co_ship:{ids['Post']}", user_id=uid), fsm_context)
        await skip_comment_handler(make_callback_query(data="co_skip_comment", user_id=uid), fsm_context)
        await payment_chosen_handler(make_callback_query(data="co_pay:cod", user_id=uid), fsm_context)
        done = make_callback_query(data="co_confirm", user_id=uid)
        with patch("bot.handlers.user.checkout.notify_new_order", new_callable=AsyncMock):
            await confirm_order_handler(done, fsm_context)
        assert "checkout.placed" in done.message.edit_text.call_args[0][0]
        async with Database().session() as s:
            order = (await s.execute(select(Orders).where(Orders.user_id == uid))).scalars().one()
        assert (order.total, order.delivery_fee, order.shipping_name) == (Decimal("100.00"), Decimal("20.00"), "Post")


BOSS = ("shipboss", "boss-pass-1")


@pytest.fixture
async def boss():
    await create_web_user(*BOSS, WebRole.ADMIN)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_admin_app(), client=("127.0.0.1", 5000)),
                                 base_url="http://testserver") as c:
        assert (await c.post("/admin/login", data={"username": BOSS[0], "password": BOSS[1]})).status_code == 302
        c.cookies.set(LANG_COOKIE, "en")
        yield c


SHIP = ShippingAdmin.identity


class TestWeb:

    async def test_create_a_method(self, boss):
        resp = await boss.post(f"/admin/{SHIP}/create", data={
            "name_en": "Courier", "name_ru": "Курьер", "name_ro": "Curier", "price": "35", "free_from": "500",
            "is_active": "y", "position": "1"})
        assert resp.status_code == 302, resp.text[:400]
        (m,) = await active_methods()
        assert m["price"] == Decimal("35.00") and m["free_from"] == Decimal("500.00") and m["name_ru"] == "Курьер"

    async def test_validation(self, boss):
        bad = {"name_en": "X", "price": "-1"}
        assert (await boss.post(f"/admin/{SHIP}/create", data=bad)).status_code == 400
        assert (await boss.post(f"/admin/{SHIP}/create", data={"name_en": "X", "price": "abc"})).status_code == 400
        assert (await boss.post(f"/admin/{SHIP}/create", data={"name_en": "X", "price": "5", "free_from": "-3"})).status_code == 400
        assert (await boss.post(f"/admin/{SHIP}/create", data={"name_en": "", "price": "5"})).status_code == 400
        assert await active_methods() == []

    async def test_inactive_method_is_not_offered_and_name_must_be_unique(self, boss):
        await boss.post(f"/admin/{SHIP}/create", data={"name_en": "Post", "price": "10", "position": "0"})
        assert await active_methods() == []                    # is_active left unticked
        dup = await boss.post(f"/admin/{SHIP}/create", data={"name_en": "Post", "price": "10", "is_active": "y"})
        assert dup.status_code == 400

    async def test_list_and_menu_in_every_language(self, boss):
        await set_methods(("Courier", 30, None, True))
        for lang, word in (("en", "Shipping"), ("ru", "Доставка"), ("ro", "Livrare")):
            boss.cookies.set(LANG_COOKIE, lang)
            page = (await boss.get(f"/admin/{SHIP}/list")).text
            assert word in page and "Courier" in page, lang

    async def test_order_details_show_the_fee(self, boss, item_factory, user_factory):
        ids = await set_methods(("Courier", 30, None, True))
        await user_factory(telegram_id=990200)
        await item_factory(name="Lamp990200", price=100, stock=3)
        await add_to_cart(990200, "Lamp990200")
        ok, code, order = await create_order_transaction(
            990200, fulfillment=Fulfillment.DELIVERY, customer_name="Ana", phone="+37360000001", address="Str 1",
            comment=None, payment_method=PaymentMethod.COD, shipping_method_id=ids["Courier"])
        assert ok, code
        page = (await boss.get(f"/admin/orders/details/{order['id']}")).text
        assert "Shipping method" in page and "Courier" in page and "Delivery fee" in page and "30" in page
