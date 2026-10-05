"""Grouped sidebar menu and the payments-to-verify view."""
import re

import httpx
import pytest

from bot.database.methods.create import add_to_cart
from bot.database.methods.orders import create_order_transaction
from bot.database.methods.web_users import create_web_user
from bot.database.models.main import Fulfillment, PaymentMethod, WebRole
from bot.web.admin import create_admin_app
from bot.web.language import LANG_COOKIE

BOSS = ("boss", "boss-pass-1")
CLERK = ("clerk", "clerk-pass-1")


def make_client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 5000)),
                             base_url="http://testserver")


@pytest.fixture
async def app():
    assert (await create_web_user(*BOSS, WebRole.ADMIN))[0]
    assert (await create_web_user(*CLERK, WebRole.STAFF))[0]
    return create_admin_app()


async def signed_in(app, creds):
    c = make_client(app)
    resp = await c.post("/admin/login", data={"username": creds[0], "password": creds[1]})
    assert resp.status_code == 302
    return c


def sidebar(page):
    m = re.search(r'<ul class="navbar-nav pt-lg-3">(.*?)</ul>\s*</div>\s*</nav>', page, re.S)
    assert m, "sidebar not found"
    return m.group(1)


def titles(html):
    return [re.sub(r"\s+", " ", t).strip() for t in re.findall(r'nav-link-title">(.*?)</span>', html, re.S)]


class TestSidebar:

    @pytest.mark.parametrize("lang,top", [
        ("en", ["Orders", "Clients", "Payments", "Catalog", "Marketing", "Settings", "Log out"]),
        ("ru", ["Заказы", "Клиенты", "Платежи", "Каталог", "Маркетинг", "Настройки", "Выйти"]),
        ("ro", ["Comenzi", "Clienți", "Plăți", "Catalog", "Marketing", "Setări", "Ieșire"]),
    ])
    async def test_groups_in_order_and_in_the_panel_language(self, app, lang, top):
        c = await signed_in(app, BOSS)
        c.cookies.set(LANG_COOKIE, lang)
        html = sidebar((await c.get("/admin/")).text)
        tops = [t for t in re.findall(
            r'<li class="nav-item[^"]*">\s*<a class="nav-link[^"]*"[^>]*>\s*<span class="nav-link-icon[^>]*>.*?</span>\s*'
            r'<span class="nav-link-title">(.*?)</span>', html, re.S)]
        assert [re.sub(r"\s+", " ", t).strip() for t in tops] == top
        await c.aclose()

    async def test_children_sit_inside_their_groups(self, app):
        c = await signed_in(app, BOSS)
        c.cookies.set(LANG_COOKIE, "en")
        html = sidebar((await c.get("/admin/")).text)
        groups = {m.group(1): titles(m.group(2)) for m in re.finditer(
            r'id="menu-group-(\w+)">(.*?)</div>\s*</div>\s*</li>', html, re.S)}
        assert groups["clients"] == ["Customers", "Referral Earnings", "Cart Items"]
        assert groups["payments"] == ["Payments to verify", "Balance operations"]
        assert groups["catalog"] == ["Products", "Categories"]
        assert groups["marketing"][:2] == ["Mailings", "Promo Codes"]
        assert groups["settings"] == ["Web Accounts", "Roles", "Audit Logs", "My account"]
        assert "Order Lines" not in titles(html)           # reached from an order, not from the menu
        await c.aclose()

    async def test_the_group_of_the_current_page_is_open(self, app):
        c = await signed_in(app, BOSS)
        html = sidebar((await c.get("/admin/goods/list")).text)
        assert re.search(r'id="menu-group-catalog"', html)
        assert re.search(r'class="collapse show" id="menu-group-catalog"', html)
        assert not re.search(r'class="collapse show" id="menu-group-settings"', html)
        await c.aclose()

    async def test_staff_do_not_see_web_accounts(self, app):
        c = await signed_in(app, CLERK)
        c.cookies.set(LANG_COOKIE, "en")
        html = sidebar((await c.get("/admin/")).text)
        assert "Web Accounts" not in titles(html) and "Roles" in titles(html)
        await c.aclose()


class TestPaymentsToVerify:

    async def _order(self, user_factory, item_factory, user_id, method):
        await user_factory(telegram_id=user_id)
        await item_factory(name=f"PayGoods{user_id}", price=100, stock=5)
        await add_to_cart(user_id, f"PayGoods{user_id}", quantity=1)
        ok, code, order = await create_order_transaction(
            user_id, fulfillment=Fulfillment.PICKUP, customer_name="Ann", phone="123456",
            address=None, comment=None, payment_method=method)
        assert ok, code
        return order

    async def test_lists_only_mia_orders_waiting_for_a_check(self, app, user_factory, item_factory):
        mia = await self._order(user_factory, item_factory, 994001, PaymentMethod.MIA)
        cod = await self._order(user_factory, item_factory, 994002, PaymentMethod.COD)
        c = await signed_in(app, BOSS)
        page = (await c.get("/admin/payments/list")).text
        # SQLAdmin builds row links from the object's class, so a row opens the order's own details page.
        assert f"/admin/orders/details/{mia['id']}" in page
        assert f"/admin/orders/details/{cod['id']}" not in page
        await c.aclose()

    async def test_details_offer_the_payment_check(self, app, user_factory, item_factory):
        mia = await self._order(user_factory, item_factory, 994003, PaymentMethod.MIA)
        c = await signed_in(app, BOSS)
        c.cookies.set(LANG_COOKIE, "en")
        page = (await c.get(f"/admin/payments/details/{mia['id']}")).text
        assert "Confirm MIA payment" in page
        await c.aclose()
