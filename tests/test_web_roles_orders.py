"""Role permissions as tags, and the order details page's action bar."""
import re
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import select

from bot.database.main import Database
from bot.database.methods.create import add_to_cart
from bot.database.methods.orders import create_order_transaction
from bot.database.methods.web_users import create_web_user
from bot.database.models.main import (
    Fulfillment, OrderStatus, PaymentMethod, PaymentStatus, Permission, Role, WebRole,
)
from bot.web.admin import OrderAdmin, RoleAdmin, _PERM_FLAGS, create_admin_app
from bot.web.language import LANG_COOKIE

BOSS = ("boss", "boss-pass-1")
ROLES = RoleAdmin.identity
ORDERS = OrderAdmin.identity


def make_client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 5000)),
                             base_url="http://testserver")


@pytest.fixture
async def boss():
    assert (await create_web_user(*BOSS, WebRole.ADMIN))[0]
    app = create_admin_app()
    async with make_client(app) as c:
        resp = await c.post("/admin/login", data={"username": BOSS[0], "password": BOSS[1]})
        assert resp.status_code == 302
        yield c


async def role(name):
    async with Database().session() as s:
        return (await s.execute(select(Role).where(Role.name == name))).scalars().first()


class TestRolePermissionTags:

    def test_every_permission_bit_has_a_flag_and_a_label_in_every_language(self):
        from bot.i18n.strings import TRANSLATIONS
        bits = {v for k, v in vars(Permission).items() if k.isupper() and isinstance(v, int)}
        assert bits == {bit for bit, _ in _PERM_FLAGS}
        for lang, strings in TRANSLATIONS.items():
            for _bit, flag in _PERM_FLAGS:
                assert strings.get(f"web.perm.{flag}"), (lang, flag)

    async def test_form_shows_tags_not_a_number(self, boss):
        boss.cookies.set(LANG_COOKIE, "en")
        page = (await boss.get(f"/admin/{ROLES}/create")).text
        boxes = re.findall(r'<input[^>]*type="checkbox"[^>]*name="permissions"[^>]*value="(\d+)"', page)
        assert sorted(map(int, boxes)) == sorted(bit for bit, _ in _PERM_FLAGS)
        assert "Mass messaging" in page and "Orders" in page
        assert not re.search(r'<input[^>]*type="number"[^>]*name="permissions"', page)

    async def test_ticked_tags_are_summed_into_the_stored_number(self, boss):
        resp = await boss.post(f"/admin/{ROLES}/create", data={
            "name": "Packer", "permissions": ["1", "1024", "128"]})
        assert resp.status_code == 302, resp.text[:500]
        assert (await role("Packer")).permissions == 1 | 1024 | 128

    async def test_no_tag_ticked_stores_zero_and_edit_prefills_the_tags(self, boss):
        await boss.post(f"/admin/{ROLES}/create", data={"name": "Nobody", "permissions": "0"})
        assert (await role("Nobody")).permissions == 0
        await boss.post(f"/admin/{ROLES}/create", data={"name": "Seller", "permissions": ["0", "16", "1024"]})
        seller = await role("Seller")
        page = (await boss.get(f"/admin/{ROLES}/edit/{seller.id}")).text
        checked = {int(v) for v in re.findall(r'<input[^>]*type="checkbox"[^>]*value="(\d+)"[^>]*checked', page)}
        assert checked == {16, 1024}

    async def test_edit_changes_the_sum(self, boss):
        await boss.post(f"/admin/{ROLES}/create", data={"name": "Shifter", "permissions": ["1", "16"]})
        shifter = await role("Shifter")
        resp = await boss.post(f"/admin/{ROLES}/edit/{shifter.id}", data={
            "name": "Shifter", "permissions": ["0", "1", "1024"]})
        assert resp.status_code == 302, resp.text[:500]
        assert (await role("Shifter")).permissions == 1025

    async def test_list_shows_named_tags_without_the_number(self, boss):
        await boss.post(f"/admin/{ROLES}/create", data={"name": "Lister", "permissions": ["1", "1024"]})
        boss.cookies.set(LANG_COOKIE, "ro")
        page = (await boss.get(f"/admin/{ROLES}/list")).text
        assert "Comenzi" in page and "(1025)" not in page


def order_like(status, method=PaymentMethod.COD, payment=PaymentStatus.UNPAID):
    return SimpleNamespace(status=status, payment_method=method, payment_status=payment)


class TestAvailableActions:

    @pytest.mark.parametrize("order,expected", [
        (order_like(OrderStatus.NEW), ["confirm", "cancel"]),
        (order_like(OrderStatus.NEW, PaymentMethod.MIA, PaymentStatus.AWAITING_PAYMENT), ["confirm-payment", "cancel"]),
        (order_like(OrderStatus.NEW, PaymentMethod.MIA, PaymentStatus.AWAITING_CONFIRMATION),
         ["confirm-payment", "cancel"]),
        (order_like(OrderStatus.CONFIRMED), ["ship", "complete", "cancel"]),
        (order_like(OrderStatus.SHIPPED), ["complete", "cancel"]),
        (order_like(OrderStatus.COMPLETED), []),
        (order_like(OrderStatus.CANCELLED), []),
    ])
    def test_actions_follow_the_state(self, order, expected):
        assert OrderAdmin.available_actions(order) == expected


class TestOrderDetailsPage:

    async def _order(self, user_factory, item_factory, method):
        await user_factory(telegram_id=993001)
        await item_factory(name="BarGoods", price=100, stock=5)
        await add_to_cart(993001, "BarGoods", quantity=1)
        ok, code, order = await create_order_transaction(
            993001, fulfillment=Fulfillment.PICKUP, customer_name="Ann", phone="123456",
            address=None, comment=None, payment_method=method)
        assert ok, code
        return order

    async def test_buttons_are_spelled_out_wrap_and_match_the_order(self, boss, user_factory, item_factory):
        order = await self._order(user_factory, item_factory, PaymentMethod.COD)
        boss.cookies.set(LANG_COOKIE, "ru")
        page = (await boss.get(f"/admin/{ORDERS}/details/{order['id']}")).text
        assert "Подтвердить заказ" in page and "Отменить заказ" in page
        assert "Отметить отправленным" not in page and "Подтвердить оплату MIA" not in page
        assert "d-flex flex-wrap" in page and "col-md-1" not in page

    async def test_a_new_mia_order_offers_the_payment_check_instead_of_confirm(self, boss, user_factory, item_factory):
        order = await self._order(user_factory, item_factory, PaymentMethod.MIA)
        boss.cookies.set(LANG_COOKIE, "en")
        page = (await boss.get(f"/admin/{ORDERS}/details/{order['id']}")).text
        assert "Confirm MIA payment" in page and "Confirm order" not in page

    async def test_a_closed_order_has_no_buttons(self, boss, user_factory, item_factory):
        from bot.database.methods.orders import cancel_order_transaction
        order = await self._order(user_factory, item_factory, PaymentMethod.COD)
        await cancel_order_transaction(order["id"], reason="test")
        boss.cookies.set(LANG_COOKIE, "en")
        page = (await boss.get(f"/admin/{ORDERS}/details/{order['id']}")).text
        assert "No actions: this order is closed." in page and "Cancel order" not in page
