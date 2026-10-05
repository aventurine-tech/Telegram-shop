"""Web admin panel: product stock edits (caches, restock alerts) and order actions."""
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from bot.database.main import Database
from bot.database.methods.create import subscribe_to_stock, add_to_cart
from bot.database.methods.orders import create_order_transaction, get_order
from bot.database.methods.read import is_subscribed_to_stock, select_item_stock
from bot.database.models.main import Goods, Fulfillment, PaymentMethod, PaymentStatus, OrderStatus
from bot.web.admin import GoodsAdmin, OrderAdmin, apply_order_action, set_notifier_bot, _PERM_FLAGS


pytestmark = pytest.mark.usefixtures("english")


class TestWebPanelStockEdits:
    def _request(self):
        request = MagicMock()
        request.client.host = "127.0.0.1"
        return request

    async def _goods(self, name):
        async with Database().session() as s:
            return (await s.execute(select(Goods).where(Goods.name == name))).scalars().first()

    async def _edit(self, name, new_stock, *, is_created=False, request=None):
        """Replay SQLAdmin's edit: on_model_change sees the old row, then the stock changes."""
        request = request or self._request()
        view = GoodsAdmin()
        model = await self._goods(name)
        scheduled = []
        # A new product needs its name and description in the admin's language (the form has no other source).
        data = {"stock": new_stock, **({f"{f}_{lang}": v for lang in ("en", "ru", "ro") for f, v in (("name", name), ("description", "d"))}
                               if is_created else {})}
        with patch('bot.web.admin.safe_create_task', side_effect=scheduled.append):
            await view.on_model_change(data, model, is_created, request)
            model.stock = new_stock
            await view.after_model_change(data, model, is_created, request)
        for coro in scheduled:
            await coro

    async def test_edit_invalidates_item_cache(self, fake_cache, item_factory):
        await item_factory(name="PanelItem", price=10, stock=1)
        fake_cache.store["item_values:PanelItem"] = 0   # the stale read
        fake_cache.store["item_info:PanelItem"] = {"name": "PanelItem"}

        await self._edit("PanelItem", 4)

        assert "item_values:PanelItem" not in fake_cache.store
        assert "item_info:PanelItem" not in fake_cache.store

    async def test_delete_invalidates_item_cache(self, fake_cache, item_factory):
        await item_factory(name="PanelDel", price=10, stock=1)
        model = await self._goods("PanelDel")
        fake_cache.store["item_values:PanelDel"] = 1

        scheduled = []
        with patch('bot.web.admin.safe_create_task', side_effect=scheduled.append):
            await GoodsAdmin().after_model_delete(model, self._request())
        for coro in scheduled:
            await coro

        assert "item_values:PanelDel" not in fake_cache.store

    async def test_restock_from_zero_notifies_subscribers(self, mock_bot, item_factory, user_factory):
        await user_factory(telegram_id=990001)
        await item_factory(name="PanelRestock", price=10, stock=0)
        await subscribe_to_stock(990001, "PanelRestock")

        set_notifier_bot(mock_bot)
        try:
            await self._edit("PanelRestock", 5)
        finally:
            set_notifier_bot(None)

        mock_bot.send_message.assert_awaited_once()
        assert mock_bot.send_message.await_args.kwargs["chat_id"] == 990001
        assert await is_subscribed_to_stock(990001, "PanelRestock") is False

    async def test_new_product_with_stock_notifies_subscribers(self, mock_bot, item_factory, user_factory):
        await user_factory(telegram_id=990004)
        await item_factory(name="PanelNew", price=10, stock=3)
        await subscribe_to_stock(990004, "PanelNew")

        set_notifier_bot(mock_bot)
        try:
            await self._edit("PanelNew", 3, is_created=True)
        finally:
            set_notifier_bot(None)

        mock_bot.send_message.assert_awaited_once()

    @pytest.mark.parametrize("before,after", [(2, 7), (5, 0), (3, 3)])
    async def test_other_edits_do_not_notify(self, mock_bot, item_factory, user_factory, before, after):
        """Only an arrival (0 -> more) is news; adding to a non-empty shelf or selling out is not."""
        await user_factory(telegram_id=990002)
        await item_factory(name="PanelEdit", price=10, stock=before)
        await subscribe_to_stock(990002, "PanelEdit")

        set_notifier_bot(mock_bot)
        try:
            await self._edit("PanelEdit", after)
        finally:
            set_notifier_bot(None)

        mock_bot.send_message.assert_not_awaited()

    async def test_no_bot_configured_is_a_noop(self, item_factory, user_factory):
        await user_factory(telegram_id=990003)
        await item_factory(name="PanelNoBot", price=10, stock=0)
        await subscribe_to_stock(990003, "PanelNoBot")

        set_notifier_bot(None)
        # Must not raise even though someone is waiting.
        await self._edit("PanelNoBot", 2)

    def test_stock_is_shown_and_sortable(self):
        assert Goods.stock in GoodsAdmin.column_list
        assert Goods.stock in GoodsAdmin.column_sortable_list


class TestWebPanelOrders:

    async def _order(self, user_id, method=PaymentMethod.COD, qty=1, item="PanelGoods"):
        await add_to_cart(user_id, item, quantity=qty)
        ok, code, order = await create_order_transaction(
            user_id, fulfillment=Fulfillment.PICKUP, customer_name="Ann", phone="123456",
            address=None, comment=None, payment_method=method,
        )
        assert ok, code
        return order

    async def test_orders_view_is_read_only(self):
        assert not (OrderAdmin.can_create or OrderAdmin.can_edit or OrderAdmin.can_delete)

    async def test_actions_follow_the_order_lifecycle(self, user_factory, item_factory, mock_bot):
        await user_factory(telegram_id=991001)
        await item_factory(name="PanelGoods", price=100, stock=5)
        order = await self._order(991001, qty=2)

        set_notifier_bot(mock_bot)
        try:
            assert await apply_order_action("confirmed", order["id"]) == (True, "success")
            assert await apply_order_action("shipped", order["id"]) == (True, "success")
            assert await apply_order_action("completed", order["id"]) == (True, "success")
        finally:
            set_notifier_bot(None)

        done = await get_order(order["id"])
        assert done["status"] == OrderStatus.COMPLETED
        assert done["payment_status"] == PaymentStatus.PAID    # cash collected
        assert mock_bot.send_message.await_count == 3          # the customer heard about each step

    async def test_illegal_move_is_refused_and_nothing_changes(self, user_factory, item_factory, mock_bot):
        await user_factory(telegram_id=991002)
        await item_factory(name="PanelGoods", price=100, stock=5)
        order = await self._order(991002)

        set_notifier_bot(mock_bot)
        try:
            ok, code = await apply_order_action("completed", order["id"])   # new -> completed is not allowed
        finally:
            set_notifier_bot(None)

        assert (ok, code) == (False, "invalid_transition")
        assert (await get_order(order["id"]))["status"] == OrderStatus.NEW
        mock_bot.send_message.assert_not_awaited()

    async def test_unverified_mia_order_cannot_be_confirmed(self, user_factory, item_factory):
        await user_factory(telegram_id=991003)
        await item_factory(name="PanelGoods", price=100, stock=5)
        order = await self._order(991003, method=PaymentMethod.MIA)

        ok, code = await apply_order_action("confirmed", order["id"])

        assert (ok, code) == (False, "payment_not_confirmed")

    async def test_confirm_payment_accepts_a_mia_order(self, user_factory, item_factory, mock_bot):
        await user_factory(telegram_id=991004)
        await item_factory(name="PanelGoods", price=100, stock=5)
        order = await self._order(991004, method=PaymentMethod.MIA)

        set_notifier_bot(mock_bot)
        try:
            assert (await apply_order_action("payment_confirmed", order["id"]))[0] is True
        finally:
            set_notifier_bot(None)

        paid = await get_order(order["id"])
        assert (paid["status"], paid["payment_status"]) == (OrderStatus.CONFIRMED, PaymentStatus.PAID)

    async def test_cancel_restocks_through_the_shared_logic(self, user_factory, item_factory):
        await user_factory(telegram_id=991005)
        await item_factory(name="PanelGoods", price=100, stock=5)
        order = await self._order(991005, qty=3)
        assert await select_item_stock("PanelGoods") == 2

        assert await apply_order_action("cancelled", order["id"]) == (True, "success")

        assert await select_item_stock("PanelGoods") == 5
        assert (await get_order(order["id"]))["status"] == OrderStatus.CANCELLED

    async def test_unknown_order_is_reported(self):
        assert await apply_order_action("confirmed", 987654) == (False, "order_not_found")

    async def test_orders_permission_is_documented_in_the_role_editor(self):
        assert (1024, "ORDERS") in _PERM_FLAGS
