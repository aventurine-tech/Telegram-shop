"""Erasing a customer's personal data on request."""
from contextlib import asynccontextmanager

import httpx
from sqlalchemy import select

from bot.database.main import Database
from bot.database.methods.create import add_to_cart
from bot.database.methods.erasure import ERASED_NAME, erase_client
from bot.database.methods.orders import create_order_transaction, get_order, set_order_status
from bot.database.methods.web_users import create_web_user
from bot.database.models.main import (
    CartItems, Favorites, Fulfillment, Orders, PaymentMethod, Reviews, StockSubscriptions, User, WebRole,
)
from bot.web.admin import UserAdmin, create_admin_app
from bot.web.language import LANG_COOKIE

CLIENTS = UserAdmin.identity
UID = 995001


async def seed(user_factory, item_factory, uid=UID, *, finish=True):
    await user_factory(telegram_id=uid, balance=25)
    await item_factory(name=f"Erase{uid}", price=40, stock=9)
    await add_to_cart(uid, f"Erase{uid}", quantity=1)
    ok, code, order = await create_order_transaction(
        uid, fulfillment=Fulfillment.DELIVERY, customer_name="Ana Pop", phone="+37360001111",
        address="Str. Secret 9", comment="Gate code 1234", payment_method=PaymentMethod.COD)
    assert ok, code
    async with Database().session() as s:
        user = (await s.execute(select(User).where(User.telegram_id == uid))).scalars().one()
        user.first_name, user.last_name, user.username = "Ana", "Pop", "ana_pop"
        user.phone, user.address, user.city, user.contact_name, user.notes = "+37360001111", "Str. 9", "Chisinau", "Ana", "VIP"
        item_id = (await s.execute(select(CartItems.item_id).where(CartItems.user_id == uid))).scalar()
    if finish:
        await set_order_status(order["id"], "confirmed")
        await set_order_status(order["id"], "completed")
    # A cart, favorite, restock subscription and review for the person.
    from bot.database.models.main import Goods
    async with Database().session() as s:
        goods = (await s.execute(select(Goods).where(Goods.name == f"Erase{uid}"))).scalars().one()
        s.add_all([CartItems(user_id=uid, item_id=goods.id, quantity=1), Favorites(user_id=uid, item_id=goods.id),
                   StockSubscriptions(user_id=uid, item_id=goods.id),
                   Reviews(user_id=uid, item_id=goods.id, rating=4, text="Call me on 060011112")])
    return order


class TestEraseClient:

    async def test_personal_data_goes_and_the_books_stay(self, user_factory, item_factory):
        order = await seed(user_factory, item_factory)
        ok, code, counts = await erase_client(UID, by="boss")
        assert (ok, code) == (True, "success") and counts["orders"] == 1

        async with Database().session() as s:
            user = (await s.execute(select(User).where(User.telegram_id == UID))).scalars().one()
            assert all(getattr(user, c) is None for c in (
                "first_name", "last_name", "username", "phone", "address", "contact_name", "city", "notes"))
            assert user.balance == 25                                     # money is not personal data
            assert (await s.execute(select(CartItems).where(CartItems.user_id == UID))).first() is None
            assert (await s.execute(select(Favorites).where(Favorites.user_id == UID))).first() is None
            assert (await s.execute(select(StockSubscriptions).where(StockSubscriptions.user_id == UID))).first() is None
            review = (await s.execute(select(Reviews).where(Reviews.user_id == UID))).scalars().one()
            assert review.text is None and review.rating == 4

        kept = await get_order(order["id"])
        assert (kept["customer_name"], kept["phone"], kept["address"], kept["comment"]) == (
            ERASED_NAME, "-", None, None)
        assert kept["total"] == order["total"] and len(kept["items"]) == 1

    async def test_orders_in_progress_block_the_erasure(self, user_factory, item_factory):
        await seed(user_factory, item_factory, uid=UID + 1, finish=False)
        assert (await erase_client(UID + 1))[:2] == (False, "has_active_orders")
        async with Database().session() as s:
            assert (await s.execute(select(User.first_name).where(User.telegram_id == UID + 1))).scalar() == "Ana"

    async def test_owner_and_strangers_are_refused(self, user_factory):
        from bot.misc import EnvKeys
        await user_factory(telegram_id=int(EnvKeys.OWNER_ID))
        assert (await erase_client(int(EnvKeys.OWNER_ID)))[:2] == (False, "is_owner")
        assert (await erase_client(987654321))[:2] == (False, "user_not_found")

    async def test_it_is_audited_without_personal_data(self, user_factory, item_factory):
        from bot.database.models.main import AuditLog
        await seed(user_factory, item_factory, uid=UID + 2)
        await erase_client(UID + 2, by="boss")
        async with Database().session() as s:
            rows = (await s.execute(select(AuditLog).where(AuditLog.action == "client_erased",
                                                           AuditLog.resource_id == str(UID + 2)))).scalars().all()
        assert rows and "Ana" not in (rows[-1].details or "") and "boss" in rows[-1].details


@asynccontextmanager
async def panel(role):
    name = f"er-{role}"
    assert (await create_web_user(name, "erase-pass-1", role))[0]
    app = create_admin_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 5000)),
                                 base_url="http://testserver") as client:
        assert (await client.post("/admin/login", data={"username": name, "password": "erase-pass-1"})
                ).status_code == 302
        client.cookies.set(LANG_COOKIE, "en")
        yield client, app


class TestErasePanel:

    async def test_admin_erases_from_the_client_page(self, user_factory, item_factory):
        await seed(user_factory, item_factory, uid=UID + 3)
        async with panel(WebRole.ADMIN) as (client, _):
            page = (await client.get(f"/admin/{CLIENTS}/details/{UID + 3}")).text
            assert f"/clients/{UID + 3}/erase" in page and "Erase personal data" in page
            resp = await client.post(f"/clients/{UID + 3}/erase")
            assert resp.status_code == 303 and "erased=1" in resp.headers["location"]
            done = (await client.get(resp.headers["location"])).text
            assert "Personal data erased." in done and "ana_pop" not in done

    async def test_staff_cannot_see_or_use_it(self, user_factory, item_factory):
        await seed(user_factory, item_factory, uid=UID + 4)
        async with panel(WebRole.STAFF) as (client, app):
            page = (await client.get(f"/admin/{CLIENTS}/details/{UID + 4}")).text
            assert "modal-erase-client" not in page
            assert (await client.post(f"/clients/{UID + 4}/erase")).status_code == 403
        async with Database().session() as s:
            assert (await s.execute(select(User.username).where(User.telegram_id == UID + 4))).scalar() == "ana_pop"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as anon:
            assert (await anon.post(f"/clients/{UID + 4}/erase")).status_code == 401

    async def test_a_refusal_is_explained(self, user_factory, item_factory):
        await seed(user_factory, item_factory, uid=UID + 5, finish=False)
        async with panel(WebRole.ADMIN) as (client, _):
            resp = await client.post(f"/clients/{UID + 5}/erase")
            assert "erase_error=has_active_orders" in resp.headers["location"]
            assert "still has orders in progress" in (await client.get(resp.headers["location"])).text
