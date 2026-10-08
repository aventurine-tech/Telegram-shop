"""Orders in the web panel: list filters, localized statuses, packing slip, tracking note."""
import datetime
import re
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import update

from bot.database.main import Database
from bot.database.methods.create import add_to_cart
from bot.database.methods.orders import create_order_transaction, get_order, set_order_status, set_tracking_note
from bot.database.methods.web_users import create_web_user
from bot.database.models.main import Fulfillment, Orders, OrderStatus, PaymentMethod, WebRole
from bot.misc.services.order_view import format_order, notify_customer
from bot.web.admin import OrderAdmin, PaymentsAdmin, create_admin_app
from bot.web.language import LANG_COOKIE

BOSS = ("slipboss", "slipboss-pass-1")
ORDERS = OrderAdmin.identity


@pytest.fixture
async def boss():
    assert (await create_web_user(*BOSS, WebRole.ADMIN))[0]
    app = create_admin_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 5000)),
                                 base_url="http://testserver") as c:
        resp = await c.post("/admin/login", data={"username": BOSS[0], "password": BOSS[1]})
        assert resp.status_code == 302
        c.cookies.set(LANG_COOKIE, "en")
        yield c, app


async def place(user_factory, item_factory, uid, *, method=PaymentMethod.COD, name=None, qty=2):
    await user_factory(telegram_id=uid)
    name = name or f"Slip{uid}"
    await item_factory(name=name, price=50, stock=20)
    await add_to_cart(uid, name, quantity=qty)
    ok, code, order = await create_order_transaction(
        uid, fulfillment=Fulfillment.DELIVERY, customer_name="Ana <b>Pop</b>", phone="+37360000009",
        address="Str. 1", comment="Ring twice", payment_method=method)
    assert ok, code
    return order


async def backdate(order_id, day):
    async with Database().session() as s:
        await s.execute(update(Orders).where(Orders.id == order_id).values(
            created_at=datetime.datetime.strptime(day, "%Y-%m-%d").replace(hour=12, tzinfo=datetime.timezone.utc)))


def ids_on(page: str) -> set[int]:
    return {int(i) for i in re.findall(rf"/admin/{ORDERS}/details/(\d+)", page)}


class TestListFilters:

    async def test_filters_narrow_the_list_and_the_count(self, boss, user_factory, item_factory):
        client, _ = boss
        a = await place(user_factory, item_factory, 994001)
        b = await place(user_factory, item_factory, 994002, method=PaymentMethod.MIA)
        await set_order_status(a["id"], OrderStatus.CONFIRMED)

        everything = ids_on((await client.get(f"/admin/{ORDERS}/list")).text)
        assert {a["id"], b["id"]} <= everything

        confirmed = ids_on((await client.get(f"/admin/{ORDERS}/list?status=confirmed")).text)
        assert a["id"] in confirmed and b["id"] not in confirmed

        mia = ids_on((await client.get(f"/admin/{ORDERS}/list?method=mia")).text)
        assert b["id"] in mia and a["id"] not in mia

        awaiting = ids_on((await client.get(f"/admin/{ORDERS}/list?pay=awaiting_payment")).text)
        assert b["id"] in awaiting and a["id"] not in awaiting

    async def test_date_range_includes_the_last_day(self, boss, user_factory, item_factory):
        client, _ = boss
        old = await place(user_factory, item_factory, 994003)
        await backdate(old["id"], "2020-03-10")
        page = (await client.get(f"/admin/{ORDERS}/list?date_from=2020-03-10&date_to=2020-03-10")).text
        assert old["id"] in ids_on(page)
        assert old["id"] not in ids_on((await client.get(f"/admin/{ORDERS}/list?date_from=2020-03-11")).text)
        assert old["id"] not in ids_on((await client.get(f"/admin/{ORDERS}/list?date_to=2020-03-09")).text)

    async def test_junk_filter_values_are_ignored(self, boss, user_factory, item_factory):
        client, _ = boss
        a = await place(user_factory, item_factory, 994004)
        resp = await client.get(f"/admin/{ORDERS}/list?status=x%27%3B--&date_from=nope&method=zzz")
        assert resp.status_code == 200 and a["id"] in ids_on(resp.text)

    async def test_filter_bar_is_on_orders_not_on_payments(self, boss):
        client, _ = boss
        assert 'id="order-filters"' in (await client.get(f"/admin/{ORDERS}/list")).text
        assert 'id="order-filters"' not in (await client.get(f"/admin/{PaymentsAdmin.identity}/list")).text

    async def test_statuses_are_localized_in_the_list(self, boss, user_factory, item_factory):
        client, _ = boss
        order = await place(user_factory, item_factory, 994005)
        await set_order_status(order["id"], OrderStatus.CONFIRMED)
        client.cookies.set(LANG_COOKIE, "ro")
        page = (await client.get(f"/admin/{ORDERS}/list?status=confirmed")).text
        assert "Confirmat" in page and ">confirmed<" not in page

    async def test_payments_page_counts_only_waiting_transfers(self, boss, user_factory, item_factory):
        client, _ = boss
        await place(user_factory, item_factory, 994006)                          # cash: never listed there
        waiting = await place(user_factory, item_factory, 994007, method=PaymentMethod.MIA)
        page = (await client.get(f"/admin/{PaymentsAdmin.identity}/list?pageSize=100")).text
        shown = len(set(re.findall(rf"/admin/{ORDERS}/details/(\d+)", page)))
        count = int(re.search(r"of (\d+)", page).group(1))
        assert shown == count >= 1
        assert str(waiting["id"]) in re.findall(rf"/admin/{ORDERS}/details/(\d+)", page)


class TestPackingSlip:

    async def test_slip_shows_the_order_and_escapes_text(self, boss, user_factory, item_factory):
        client, _ = boss
        order = await place(user_factory, item_factory, 994010)
        resp = await client.get(f"/orders/{order['id']}/slip")
        assert resp.status_code == 200
        html = resp.text
        assert f"Order #{order['id']}" in html and "Slip994010" in html and "+37360000009" in html
        assert "Ring twice" in html and "Str. 1" in html
        assert "<b>Pop</b>" not in html and "&lt;b&gt;Pop&lt;/b&gt;" in html
        assert resp.headers["cache-control"] == "no-store"

    async def test_slip_follows_the_panel_language(self, boss, user_factory, item_factory):
        client, _ = boss
        order = await place(user_factory, item_factory, 994011)
        client.cookies.set(LANG_COOKIE, "ru")
        assert f"Заказ №{order['id']}" in (await client.get(f"/orders/{order['id']}/slip")).text

    async def test_slip_needs_a_signed_in_account_and_a_real_order(self, boss, user_factory, item_factory):
        client, app = boss
        order = await place(user_factory, item_factory, 994012)
        assert (await client.get("/orders/99999999/slip")).status_code == 404
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as anon:
            assert (await anon.get(f"/orders/{order['id']}/slip")).status_code == 401

    async def test_details_page_links_to_the_slip(self, boss, user_factory, item_factory):
        client, _ = boss
        order = await place(user_factory, item_factory, 994013)
        page = (await client.get(f"/admin/{ORDERS}/details/{order['id']}")).text
        assert f"/orders/{order['id']}/slip" in page and f"/orders/{order['id']}/tracking" in page


class TestTrackingNote:

    async def test_note_is_stored_cleaned_and_shown_to_the_customer(self, user_factory, item_factory):
        order = await place(user_factory, item_factory, 994020)
        ok, code, saved = await set_tracking_note(order["id"], "  Courier Ion\x00, parcel 77  ")
        assert (ok, code, saved["note_changed"]) == (True, "success", True)
        assert saved["tracking_note"] == "Courier Ion, parcel 77"
        assert "Courier Ion, parcel 77" in format_order(await get_order(order["id"]))
        again = await set_tracking_note(order["id"], "Courier Ion, parcel 77")
        assert again[2]["note_changed"] is False
        cleared = await set_tracking_note(order["id"], "   ")
        assert cleared[2]["tracking_note"] is None

    async def test_too_long_missing_and_cancelled_are_refused(self, user_factory, item_factory):
        order = await place(user_factory, item_factory, 994021)
        assert (await set_tracking_note(order["id"], "x" * 301))[:2] == (False, "note_too_long")
        assert (await set_tracking_note(99999999, "hi"))[:2] == (False, "order_not_found")
        await set_order_status(order["id"], OrderStatus.CANCELLED)
        assert (await set_tracking_note(order["id"], "hi"))[:2] == (False, "order_closed")

    async def test_shipped_notice_carries_the_note(self, user_factory, item_factory):
        order = await place(user_factory, item_factory, 994022)
        await set_tracking_note(order["id"], "Parcel 55")
        bot = AsyncMock()
        assert await notify_customer(bot, await get_order(order["id"]), "shipped")
        assert "Parcel 55" in bot.send_message.call_args[0][1]

    async def test_form_saves_and_messages_only_a_shipped_order(self, boss, user_factory, item_factory):
        client, _ = boss
        order = await place(user_factory, item_factory, 994023)
        bot = AsyncMock()
        with patch("bot.web.admin._notifier_bot", bot):
            resp = await client.post(f"/orders/{order['id']}/tracking", data={"tracking_note": "Pickup after 5pm"})
            assert resp.status_code == 303 and "tracking_saved=1" in resp.headers["location"]
            assert (await get_order(order["id"]))["tracking_note"] == "Pickup after 5pm"
            bot.send_message.assert_not_called()                  # not shipped yet: stored for the shipped notice

            await set_order_status(order["id"], OrderStatus.CONFIRMED)
            await set_order_status(order["id"], OrderStatus.SHIPPED)
            await client.post(f"/orders/{order['id']}/tracking", data={"tracking_note": "Pickup after 6pm"})
            assert "Pickup after 6pm" in bot.send_message.call_args[0][1]
            sent = bot.send_message.call_count
            await client.post(f"/orders/{order['id']}/tracking", data={"tracking_note": "Pickup after 6pm"})
            assert bot.send_message.call_count == sent             # unchanged note: no second message

    async def test_form_refuses_strangers_and_bad_input(self, boss, user_factory, item_factory):
        client, app = boss
        order = await place(user_factory, item_factory, 994024)
        resp = await client.post(f"/orders/{order['id']}/tracking", data={"tracking_note": "x" * 400})
        assert "tracking_error=note_too_long" in resp.headers["location"]
        assert (await get_order(order["id"]))["tracking_note"] is None
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as anon:
            assert (await anon.post(f"/orders/{order['id']}/tracking", data={"tracking_note": "hi"})
                    ).status_code == 401
        assert (await client.get(f"/orders/{order['id']}/tracking")).status_code == 405
