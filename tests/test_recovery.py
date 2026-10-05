from unittest.mock import AsyncMock, MagicMock, patch

from bot.misc.services.cleanup import CleanupManager
from bot.misc.services.recovery import RecoveryManager
from bot.database.main import Database
from bot.database.models.main import Orders  # noqa: F401  (registers the tables before the session DB is built)


class TestRecoveryManager:

    def setup_method(self):
        self.bot = AsyncMock()
        self.bot.get_me = AsyncMock(return_value=MagicMock(username="test_bot"))
        self.manager = RecoveryManager(self.bot)

    async def _order(self, user_id, item_name, stock=3, qty=1, method="mia"):
        from bot.database.methods.create import add_to_cart
        from bot.database.methods.orders import create_order_transaction
        await add_to_cart(user_id, item_name, quantity=qty)
        ok, code, order = await create_order_transaction(
            user_id, fulfillment="pickup", customer_name="Ana", phone="+37369123456",
            address=None, comment=None, payment_method=method,
        )
        assert ok, code
        return order

    async def _expire(self, order_id):
        """Pretend the pay-by deadline passed an hour ago."""
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import update
        from bot.database.models.main import Orders
        async with Database().session() as s:
            await s.execute(update(Orders).where(Orders.id == order_id).values(
                pay_by=datetime.now(timezone.utc) - timedelta(hours=1)))

    async def test_sweep_cancels_overdue_mia_order_and_tells_the_customer(self, user_factory, item_factory):
        from bot.database.methods.orders import get_order
        from bot.database.methods.read import select_item_stock

        await user_factory(telegram_id=500001)
        await item_factory(name="SweepItem", price=10, stock=2)
        order = await self._order(500001, "SweepItem", qty=2)
        assert await select_item_stock("SweepItem") == 0
        await self._expire(order["id"])

        with patch("bot.misc.services.restock_notifier.notify_restock", new_callable=AsyncMock) as restock:
            await self.manager.expire_unpaid_orders()

        assert (await get_order(order["id"]))["status"] == "cancelled"
        assert await select_item_stock("SweepItem") == 2
        self.bot.send_message.assert_awaited_once()
        assert self.bot.send_message.await_args.args[0] == 500001
        assert "notify.customer.mia_expired" in self.bot.send_message.await_args.args[1]
        restock.assert_awaited_once_with(self.bot, "SweepItem")   # 0 -> 2 wakes the waiting list

    async def test_sweep_leaves_orders_within_their_deadline_alone(self, user_factory, item_factory):
        from bot.database.methods.orders import get_order

        await user_factory(telegram_id=500002)
        await item_factory(name="FreshItem", price=10, stock=2)
        order = await self._order(500002, "FreshItem")

        await self.manager.expire_unpaid_orders()

        assert (await get_order(order["id"]))["status"] == "new"
        self.bot.send_message.assert_not_awaited()

    async def test_sweep_skips_cod_and_claimed_orders(self, user_factory, item_factory):
        from bot.database.methods.orders import get_order, mark_mia_paid

        await user_factory(telegram_id=500003)
        await user_factory(telegram_id=500004)
        await item_factory(name="CodItem", price=10, stock=5)
        cod = await self._order(500003, "CodItem", method="cod")
        mia = await self._order(500004, "CodItem")
        await mark_mia_paid(mia["id"], 500004)            # the shop is verifying: the timer must not cancel it
        await self._expire(cod["id"])
        await self._expire(mia["id"])

        await self.manager.expire_unpaid_orders()

        assert (await get_order(cod["id"]))["status"] == "new"
        assert (await get_order(mia["id"]))["status"] == "new"

    async def test_health_check_does_not_call_telegram(self, fake_cache):
        """The per-minute health check must not spend a Telegram API call —
        polling already proves connectivity."""
        await self.manager.periodic_health_check()

        self.bot.get_me.assert_not_awaited()
        assert fake_cache.store.get("health:check") == "ok"

    async def test_start_creates_tasks(self):
        # Patch the recovery methods to not actually run
        self.manager.expire_unpaid_orders = AsyncMock()
        self.manager.periodic_health_check = AsyncMock()
        self.manager.dispatch_due_mailings = AsyncMock()

        await self.manager.start()
        assert self.manager.running is True
        assert len(self.manager.recovery_tasks) == 3     # expiry, health check, due mailings

        await self.manager.stop()
        assert self.manager.running is False

    async def test_run_periodically_survives_a_crash(self):
        """A failing pass must back off and be retried, not kill the task."""
        self.manager.running = True
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("test error")
            # Second iteration: stop the loop so the test terminates.
            self.manager.running = False

        # Patch the sleeps so neither the backoff nor the interval really waits.
        with patch("bot.misc.services.recovery.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            await self.manager._run_periodically(flaky, interval=300)

        assert call_count == 2  # crashed once, then retried
        # Backoff after the crash, then the normal interval after the good pass.
        assert [c.args[0] for c in mock_sleep.await_args_list] == [
            self.manager.ERROR_BACKOFF, 300,
        ]

    async def test_sweep_failure_to_notify_does_not_undo_the_cancellation(self, user_factory, item_factory):
        from bot.database.methods.orders import get_order

        await user_factory(telegram_id=500005)
        await item_factory(name="BlockedItem", price=10, stock=1)
        order = await self._order(500005, "BlockedItem")
        await self._expire(order["id"])
        self.bot.send_message.side_effect = RuntimeError("bot was blocked by the user")

        await self.manager.expire_unpaid_orders()

        assert (await get_order(order["id"]))["status"] == "cancelled"


class TestCleanupRetention:
    def setup_method(self):
        self.manager = CleanupManager()

    async def _run_one_sweep(self, monkeypatch, *, audit_days):
        from bot.misc.env import EnvKeys
        monkeypatch.setattr(EnvKeys, "AUDIT_RETENTION_DAYS", audit_days, raising=False)

        self.manager.running = True

        async def stop_before_working(_delay):
            # daily_cleanup sleeps until 04:00 UTC first; skip the wait, then
            # end the loop after this single pass.
            self.manager.running = False

        with patch("bot.misc.services.cleanup.asyncio.sleep", side_effect=stop_before_working):
            await self.manager.daily_cleanup()

    async def _seed(self):
        from datetime import datetime, timedelta, timezone
        from bot.database.models.main import AuditLog
        old = datetime.now(timezone.utc) - timedelta(days=365)
        async with Database().session() as s:
            s.add(AuditLog(timestamp=old, level="INFO", action="ancient"))

    async def _ancient_rows(self):
        from sqlalchemy import func, select
        from bot.database.models.main import AuditLog
        async with Database().session() as s:
            return (await s.execute(
                select(func.count(AuditLog.id)).where(AuditLog.action == "ancient")
            )).scalar()

    async def test_zero_retention_deletes_nothing(self, monkeypatch):
        await self._seed()

        await self._run_one_sweep(monkeypatch, audit_days=0)

        assert await self._ancient_rows() == 1

    async def test_positive_retention_still_prunes(self, monkeypatch):
        await self._seed()

        await self._run_one_sweep(monkeypatch, audit_days=90)

        assert await self._ancient_rows() == 0
