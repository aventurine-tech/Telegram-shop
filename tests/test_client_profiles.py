"""Client profiles: Telegram names kept fresh, contact details from orders, the Clients pages."""
import re
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from bot.database.main import Database
from bot.database.methods.create import add_to_cart
from bot.database.methods.orders import create_order_transaction
from bot.database.methods.profiles import refresh_profile
from bot.database.methods.web_users import create_web_user
from bot.database.models.main import Fulfillment, PaymentMethod, User, WebRole
from bot.middleware.profile import ProfileMiddleware
from bot.web.admin import UserAdmin, create_admin_app
from bot.web.language import LANG_COOKIE

BOSS = ("cboss", "boss-pass-1")
UID = 880001


async def row(uid=UID):
    async with Database().session() as s:
        return (await s.execute(select(User).where(User.telegram_id == uid))).scalars().one()


def event(uid=UID, username="anna_p", first="Anna", last="Popescu", chat="private", bot=False):
    return SimpleNamespace(from_user=SimpleNamespace(id=uid, username=username, first_name=first, last_name=last,
                                                     is_bot=bot), chat=SimpleNamespace(type=chat))


async def noop(event, data):
    return "ok"


class TestRefresh:

    async def test_stores_names_username_and_last_seen(self, user_factory):
        await user_factory(telegram_id=UID)
        assert await refresh_profile(UID, " anna_p ", "Anna", "Popescu")
        u = await row()
        assert (u.username, u.first_name, u.last_name) == ("anna_p", "Anna", "Popescu") and u.last_seen_at

    async def test_unknown_user_is_not_created(self):
        assert await refresh_profile(999999991, "x", "X", None) is False

    async def test_empty_values_become_null_and_long_ones_are_cut(self, user_factory):
        await user_factory(telegram_id=UID)
        await refresh_profile(UID, "", "A" * 500, "   ")
        u = await row()
        assert u.username is None and u.last_name is None and len(u.first_name) == 128


class TestMiddleware:

    async def test_writes_once_then_only_on_change(self, user_factory, monkeypatch):
        await user_factory(telegram_id=UID)
        calls = []
        real = refresh_profile

        async def spy(*a):
            calls.append(a)
            return await real(*a)
        monkeypatch.setattr("bot.middleware.profile.refresh_profile", spy)
        mw = ProfileMiddleware()
        assert await mw(noop, event(), {}) == "ok"
        await mw(noop, event(), {})
        await mw(noop, event(), {})
        assert len(calls) == 1
        await mw(noop, event(first="Ana"), {})          # the name changed
        assert len(calls) == 2
        assert (await row()).first_name == "Ana"

    async def test_rewrites_after_the_interval(self, user_factory, monkeypatch):
        await user_factory(telegram_id=UID)
        calls = []

        async def spy(*a):
            calls.append(a)
            return True
        monkeypatch.setattr("bot.middleware.profile.refresh_profile", spy)
        mw = ProfileMiddleware()
        mw.INTERVAL = 0
        await mw(noop, event(), {})
        await mw(noop, event(), {})
        assert len(calls) == 2

    async def test_groups_bots_and_unknown_people_are_ignored(self, monkeypatch):
        calls = []

        async def spy(*a):
            calls.append(a)
            return False
        monkeypatch.setattr("bot.middleware.profile.refresh_profile", spy)
        mw = ProfileMiddleware()
        await mw(noop, event(chat="supergroup"), {})
        await mw(noop, event(bot=True), {})
        await mw(noop, SimpleNamespace(from_user=None), {})
        assert calls == []
        await mw(noop, event(uid=999999992), {})        # not registered yet: tried again next time
        await mw(noop, event(uid=999999992), {})
        assert len(calls) == 2

    async def test_a_failing_write_never_breaks_the_update(self, monkeypatch):
        async def boom(*a):
            raise RuntimeError("db down")
        monkeypatch.setattr("bot.middleware.profile.refresh_profile", boom)
        assert await ProfileMiddleware()(noop, event(), {}) == "ok"

    async def test_handler_errors_still_propagate(self):
        async def bad(event, data):
            raise ValueError("handler")
        with pytest.raises(ValueError):
            await ProfileMiddleware()(bad, event(uid=999999993), {})


class TestOrderSavesContact:

    async def _order(self, **over):
        await add_to_cart(UID, "Table", quantity=1)
        kw = dict(fulfillment=Fulfillment.DELIVERY, customer_name="Ion", phone="+37360000009",
                  address="Str. Mare 5", comment=None, payment_method=PaymentMethod.COD)
        kw.update(over)
        ok, code, _ = await create_order_transaction(UID, **kw)
        assert ok, code

    async def test_delivery_saves_phone_and_address(self, user_factory, item_factory):
        await user_factory(telegram_id=UID)
        await item_factory(name="Table", price=50, stock=9)
        await self._order()
        u = await row()
        assert (u.phone, u.address) == ("+37360000009", "Str. Mare 5")

    async def test_pickup_updates_the_phone_but_keeps_the_address(self, user_factory, item_factory):
        await user_factory(telegram_id=UID)
        await item_factory(name="Table", price=50, stock=9)
        await self._order()
        await self._order(fulfillment=Fulfillment.PICKUP, address=None, phone="+37360000010")
        u = await row()
        assert (u.phone, u.address) == ("+37360000010", "Str. Mare 5")


@pytest.fixture
async def boss():
    await create_web_user(*BOSS, WebRole.ADMIN)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_admin_app(), client=("127.0.0.1", 5000)),
                                 base_url="http://testserver") as c:
        assert (await c.post("/admin/login", data={"username": BOSS[0], "password": BOSS[1]})).status_code == 302
        c.cookies.set(LANG_COOKIE, "en")
        yield c


CLIENTS = UserAdmin.identity


class TestClientsPages:

    async def _client(self, user_factory, item_factory):
        await user_factory(telegram_id=UID)
        await refresh_profile(UID, "anna_p", "Anna", "Popescu")
        await item_factory(name="Table", price=50, stock=9)
        await add_to_cart(UID, "Table", quantity=2)
        ok, code, order = await create_order_transaction(
            UID, fulfillment=Fulfillment.DELIVERY, customer_name="Anna", phone="+37369111222",
            address="Str. Ion Creanga 3", comment=None, payment_method=PaymentMethod.COD)
        assert ok, code
        return order

    async def test_list_shows_name_username_phone_address(self, boss, user_factory, item_factory):
        await self._client(user_factory, item_factory)
        page = (await boss.get(f"/admin/{CLIENTS}/list")).text
        assert "Anna" in page and "Popescu" in page and 'href="https://t.me/anna_p"' in page
        assert "+37369111222" in page and "Ion Creanga" in page

    async def test_search_by_name_username_phone_and_address(self, boss, user_factory, item_factory):
        await self._client(user_factory, item_factory)
        for term in ("popescu", "anna_p", "69111222", "creanga"):
            page = (await boss.get(f"/admin/{CLIENTS}/list?search={term}")).text
            assert 'href="https://t.me/anna_p"' in page, term
        page = (await boss.get(f"/admin/{CLIENTS}/list?search=nobodyhere")).text
        assert 'href="https://t.me/anna_p"' not in page

    async def test_details_show_profile_and_order_history(self, boss, user_factory, item_factory):
        order = await self._client(user_factory, item_factory)
        page = (await boss.get(f"/admin/{CLIENTS}/details/{UID}")).text
        assert "+37369111222" in page and "Str. Ion Creanga 3" in page
        assert re.search(rf'/admin/orders/details/{order["id"]}"', page)
        assert "100" in page and "New" in page             # total and the localized status

    async def test_details_without_orders(self, boss, user_factory):
        await user_factory(telegram_id=UID + 1)
        page = (await boss.get(f"/admin/{CLIENTS}/details/{UID + 1}")).text
        assert "No orders yet." in page

    async def test_staff_can_save_notes_and_phone(self, boss, user_factory):
        await user_factory(telegram_id=UID + 2)
        resp = await boss.post(f"/admin/{CLIENTS}/edit/{UID + 2}", data={
            "role": "1", "balance": "0", "phone": "+37360000000", "notes": "Prefers evening calls"})
        assert resp.status_code == 302, resp.text[:400]
        u = await row(UID + 2)
        assert u.phone == "+37360000000" and u.notes == "Prefers evening calls"

    async def test_labels_in_every_language(self, boss, user_factory):
        await user_factory(telegram_id=UID + 3)
        for lang, words in (("ru", ["Имя", "Фамилия", "Телефон", "Адрес"]), ("ro", ["Prenume", "Nume", "Telefon", "Adresă"])):
            boss.cookies.set(LANG_COOKIE, lang)
            page = (await boss.get(f"/admin/{CLIENTS}/list")).text
            for w in words:
                assert w in page, (lang, w)

    async def test_csv_export_has_the_profile_columns(self, boss, user_factory, item_factory):
        await self._client(user_factory, item_factory)
        text = (await boss.get("/export/users")).text
        assert text.splitlines()[0].startswith("telegram_id,first_name,last_name,username,phone,address")
        assert "anna_p" in text and "+37369111222" in text
