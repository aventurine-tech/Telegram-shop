"""The panel home page: shop numbers for the last 7 / 30 / 90 days."""
import datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import update

from bot.database.main import Database
from bot.database.methods.create import add_to_cart, create_item_option
from bot.database.methods.dashboard import dashboard_data, parse_days
from bot.database.methods.orders import create_order_transaction, set_order_status
from bot.database.methods.web_users import create_web_user
from bot.database.models.main import Fulfillment, Goods, Orders, OrderStatus, PaymentMethod, User, WebRole
from bot.web.admin import create_admin_app
from bot.web.language import LANG_COOKIE

BOSS = ("dashboss", "dashboss-pass-1")


@pytest.fixture
async def boss():
    assert (await create_web_user(*BOSS, WebRole.ADMIN))[0]
    app = create_admin_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 5000)),
                                 base_url="http://testserver") as c:
        resp = await c.post("/admin/login", data={"username": BOSS[0], "password": BOSS[1]})
        assert resp.status_code == 302
        c.cookies.set(LANG_COOKIE, "en")
        yield c


async def place(user_factory, item_factory, uid, *, name, price=50, qty=2, method=PaymentMethod.COD, stock=20):
    await user_factory(telegram_id=uid)
    await item_factory(name=name, price=price, stock=stock)
    await add_to_cart(uid, name, quantity=qty)
    ok, code, order = await create_order_transaction(
        uid, fulfillment=Fulfillment.PICKUP, customer_name="Ana", phone="+37360000009",
        address=None, comment=None, payment_method=method)
    assert ok, code
    return order


async def days_ago(order_id, n):
    when = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=n)
    async with Database().session() as s:
        await s.execute(update(Orders).where(Orders.id == order_id).values(created_at=when))


class TestParseDays:

    @pytest.mark.parametrize("raw,expected", [("7", 7), ("30", 30), ("90", 90), ("5", 30), ("x", 30), (None, 30), ("-7", 30)])
    def test_only_known_periods_are_accepted(self, raw, expected):
        assert parse_days(raw) == expected


class TestDashboardData:

    async def test_counts_revenue_and_ranking(self, user_factory, item_factory):
        a = await place(user_factory, item_factory, 995001, name="DashA", price=50, qty=2)
        b = await place(user_factory, item_factory, 995002, name="DashB", price=10, qty=1)
        c = await place(user_factory, item_factory, 995003, name="DashC", price=70, qty=3)
        await set_order_status(a["id"], OrderStatus.CONFIRMED)
        await set_order_status(a["id"], OrderStatus.COMPLETED)
        await set_order_status(c["id"], OrderStatus.CANCELLED)

        data = await dashboard_data(30)
        assert data["orders"] == 3 and data["completed"] == 1 and data["cancelled"] == 1
        assert data["revenue"] == Decimal("100.00") and data["average"] == Decimal("100.00")
        assert data["cancelled_share"] == 33
        assert [p["name"] for p in data["top_products"]] == ["DashA", "DashB"]   # cancelled DashC is left out
        assert dict(data["statuses"]) == {"new": 1, "completed": 1, "cancelled": 1}
        assert data["attention"]["new_orders"] == 1

    async def test_period_cuts_off_older_orders(self, user_factory, item_factory):
        old = await place(user_factory, item_factory, 995010, name="DashOld")
        await place(user_factory, item_factory, 995011, name="DashNew")
        await days_ago(old["id"], 20)
        assert (await dashboard_data(7))["orders"] == 1
        assert (await dashboard_data(30))["orders"] == 2

    async def test_per_day_has_every_day_of_the_period_newest_first(self, user_factory, item_factory):
        order = await place(user_factory, item_factory, 995020, name="DashDay")
        await set_order_status(order["id"], OrderStatus.CONFIRMED)
        await set_order_status(order["id"], OrderStatus.COMPLETED)
        rows = (await dashboard_data(7))["per_day"]
        assert len(rows) == 7
        assert rows[0]["date"] > rows[-1]["date"]
        assert sum(r["orders"] for r in rows) == 1
        assert max(r["share"] for r in rows) == 100

    async def test_new_clients_counted_by_registration(self, user_factory):
        await user_factory(telegram_id=995030)
        await user_factory(telegram_id=995031)
        async with Database().session() as s:
            await s.execute(update(User).where(User.telegram_id == 995031).values(
                registration_date=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=60)))
        assert (await dashboard_data(7))["new_clients"] == 1
        assert (await dashboard_data(90))["new_clients"] == 2

    async def test_mia_payment_to_check_is_flagged(self, user_factory, item_factory):
        from bot.database.methods.orders import mark_mia_paid  # noqa: PLC0415
        order = await place(user_factory, item_factory, 995040, name="DashMia", method=PaymentMethod.MIA)
        assert (await dashboard_data(7))["attention"]["to_check"] == 0
        await mark_mia_paid(order["id"], 995040)
        assert (await dashboard_data(7))["attention"]["to_check"] == 1

    async def test_low_stock_lists_options_not_their_head(self, item_factory):
        await item_factory(name="DashHead", price=10, stock=0)
        ok, _ = await create_item_option("DashHead", "50 g", 20, stock=2)
        assert ok
        await item_factory(name="DashPlenty", price=10, stock=50)
        names = [p["name"] for p in (await dashboard_data(7))["attention"]["low_stock"]]
        assert "DashHead · 50 g" in names
        assert "DashHead" not in names and "DashPlenty" not in names


class TestHomePage:

    async def test_shows_the_numbers_and_still_has_the_help(self, boss, user_factory, item_factory):
        await place(user_factory, item_factory, 995050, name="DashPage", qty=2)
        page = (await boss.get("/admin/")).text
        assert 'id="dashboard"' in page and "Shop at a glance" in page
        assert "DashPage" in page
        assert "Telegram Shop — Admin Panel" in page

    @pytest.mark.parametrize("lang,title", [("ru", "Магазин в цифрах"), ("ro", "Magazinul pe scurt")])
    async def test_panel_language(self, boss, lang, title):
        boss.cookies.set(LANG_COOKIE, lang)
        assert title in (await boss.get("/admin/")).text

    async def test_period_switch_and_junk_value(self, boss):
        assert "7 days" in (await boss.get("/admin/?days=7")).text
        assert (await boss.get("/admin/?days=abc")).status_code == 200

    async def test_needs_a_login(self):
        app = create_admin_app()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 5000)),
                                     base_url="http://testserver") as c:
            resp = await c.get("/admin/", follow_redirects=False)
        assert resp.status_code in (302, 303) and "dashboard" not in resp.text
