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
        self.manager.remind_unpaid_orders = AsyncMock()
        self.manager.alert_stale_orders = AsyncMock()

        await self.manager.start()
        assert self.manager.running is True
        assert len(self.manager.recovery_tasks) == 5     # expiry, payment reminders, stale alerts, health, mailings

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


class TestOrderNudges:
    """The customer's "pay soon" reminder and staff's "this order is waiting" alert: once per order."""

    def setup_method(self):
        self.bot = AsyncMock()
        self.manager = RecoveryManager(self.bot)

    async def _order(self, uid, name, method="mia"):
        from bot.database.methods.create import add_to_cart
        from bot.database.methods.orders import create_order_transaction
        await add_to_cart(uid, name, quantity=1)
        ok, code, order = await create_order_transaction(
            uid, fulfillment="pickup", customer_name="Ana", phone="+37369123456",
            address=None, comment=None, payment_method=method)
        assert ok, code
        return order

    async def _age(self, order_id, *, created=None, pay_by=None, updated=None):
        """Move the order's clocks (minutes ago for created/updated, minutes from now for pay_by)."""
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import update
        from bot.database.models.main import Orders
        now = datetime.now(timezone.utc)
        values = {}
        if created is not None:
            values["created_at"] = now - timedelta(minutes=created)
        if pay_by is not None:
            values["pay_by"] = now + timedelta(minutes=pay_by)
        if updated is not None:
            values["updated_at"] = now - timedelta(minutes=updated)
        async with Database().session() as s:
            await s.execute(update(Orders).where(Orders.id == order_id).values(**values))

    async def test_reminder_goes_out_once_when_the_deadline_is_near(self, user_factory, item_factory):
        from bot.database.methods.orders import claim_payment_reminders
        await user_factory(telegram_id=500101)
        await item_factory(name="NudgeA", price=10, stock=5)
        order = await self._order(500101, "NudgeA")
        assert await claim_payment_reminders() == []                      # a fresh order has 120 min left

        await self._age(order["id"], created=95, pay_by=25)
        await self.manager.remind_unpaid_orders()
        self.bot.send_message.assert_awaited_once()
        assert self.bot.send_message.await_args.args[0] == 500101
        assert "notify.customer.mia_reminder" in self.bot.send_message.await_args.args[1]

        await self.manager.remind_unpaid_orders()
        assert self.bot.send_message.await_count == 1                      # never twice

    async def test_no_reminder_when_paid_claimed_expired_or_switched_off(self, user_factory, item_factory):
        from bot.database.methods.orders import claim_payment_reminders, mark_mia_paid
        await user_factory(telegram_id=500102)
        await item_factory(name="NudgeB", price=10, stock=5)
        claimed = await self._order(500102, "NudgeB")
        await self._age(claimed["id"], created=95, pay_by=25)
        await mark_mia_paid(claimed["id"], 500102)                          # says paid: nothing left to remind
        late = await self._order(500102, "NudgeB")
        await self._age(late["id"], created=130, pay_by=-10)                # already past its deadline
        short = await self._order(500102, "NudgeB")
        await self._age(short["id"], created=5, pay_by=20)                  # window shorter than the reminder lead
        assert await claim_payment_reminders() == []

        ready = await self._order(500102, "NudgeB")
        await self._age(ready["id"], created=95, pay_by=25)
        with patch("bot.misc.env.EnvKeys.MIA_REMIND_BEFORE_MIN", 0):
            assert await claim_payment_reminders() == []
        assert [o["id"] for o in await claim_payment_reminders()] == [ready["id"]]

    async def test_staff_hear_once_about_an_unchecked_transfer(self, user_factory, item_factory):
        from bot.database.methods.orders import mark_mia_paid
        await user_factory(telegram_id=500103)
        await item_factory(name="NudgeC", price=10, stock=5)
        order = await self._order(500103, "NudgeC")
        await mark_mia_paid(order["id"], 500103)

        with patch("bot.misc.services.order_view._send_to_staff", new_callable=AsyncMock) as staff:
            await self.manager.alert_stale_orders()
            staff.assert_not_awaited()                                     # claimed a moment ago: still fresh
            await self._age(order["id"], updated=45)
            await self.manager.alert_stale_orders()
            assert staff.await_count == 1
            await self.manager.alert_stale_orders()
            assert staff.await_count == 1

    async def test_staff_hear_once_about_an_untouched_cash_order(self, user_factory, item_factory):
        from bot.database.methods.orders import claim_stale_orders, set_order_status
        await user_factory(telegram_id=500104)
        await item_factory(name="NudgeD", price=10, stock=5)
        waiting = await self._order(500104, "NudgeD", method="cod")
        handled = await self._order(500104, "NudgeD", method="cod")
        await set_order_status(handled["id"], "confirmed")
        for o in (waiting, handled):
            await self._age(o["id"], created=90)

        found = await claim_stale_orders()
        assert [(kind, o["id"]) for kind, o in found] == [("unhandled", waiting["id"])]
        assert await claim_stale_orders() == []

    async def test_alerts_can_be_switched_off(self, user_factory, item_factory):
        from bot.database.methods.orders import claim_stale_orders
        await user_factory(telegram_id=500105)
        await item_factory(name="NudgeE", price=10, stock=5)
        order = await self._order(500105, "NudgeE", method="cod")
        await self._age(order["id"], created=90)
        with patch("bot.misc.env.EnvKeys.STALE_ORDER_ALERT_MIN", 0), \
                patch("bot.misc.env.EnvKeys.STALE_PAYMENT_ALERT_MIN", 0):
            assert await claim_stale_orders() == []
