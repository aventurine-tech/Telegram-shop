import asyncio
import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


class RecoveryManager:
    """Disaster Recovery Manager — unpaid-order expiry and health monitoring"""

    UNPAID_ORDER_INTERVAL = 60
    HEALTH_CHECK_INTERVAL = 60
    REMINDER_INTERVAL = 60
    MAILING_INTERVAL = 15
    ERROR_BACKOFF = 30

    def __init__(self, bot):
        self.bot = bot
        self.recovery_tasks = []
        self.mailing_tasks: set = set()
        self.running = False

    async def start(self):
        """Starting the recovery system"""
        logger.info("Starting recovery manager...")
        self.running = True

        self.recovery_tasks.append(asyncio.create_task(
            self._run_periodically(self.expire_unpaid_orders, self.UNPAID_ORDER_INTERVAL)
        ))

        self.recovery_tasks.append(asyncio.create_task(
            self._run_periodically(self.remind_unpaid_orders, self.REMINDER_INTERVAL)
        ))

        self.recovery_tasks.append(asyncio.create_task(
            self._run_periodically(self.alert_stale_orders, self.REMINDER_INTERVAL)
        ))

        self.recovery_tasks.append(asyncio.create_task(
            self._run_periodically(self.periodic_health_check, self.HEALTH_CHECK_INTERVAL)
        ))

        # A mailing still 'sending' lost its sender with the previous process. It carries on with the people the delivery
        # log does not list (MAILING_RESUME=0: it is marked Interrupted instead).
        try:
            from bot.database.methods.mailings import fail_interrupted_mailings, resume_interrupted_mailings
            from bot.misc import EnvKeys
            if EnvKeys.MAILING_RESUME == "1":
                resumed, failed = await resume_interrupted_mailings()
                if resumed or failed:
                    logger.warning("%s mailing(s) resume after a restart, %s too old and marked failed", resumed, failed)
            else:
                interrupted = await fail_interrupted_mailings()
                if interrupted:
                    logger.warning("%s mailing(s) were interrupted by a restart and marked failed", interrupted)
        except Exception as e:
            logger.error("could not check interrupted mailings: %s", e)
        self.recovery_tasks.append(asyncio.create_task(
            self._run_periodically(self.dispatch_due_mailings, self.MAILING_INTERVAL)
        ))

    async def stop(self):
        """Stopping the recovery system"""
        self.running = False
        for task in [*self.recovery_tasks, *self.mailing_tasks]:
            task.cancel()
        await asyncio.gather(*self.recovery_tasks, *self.mailing_tasks, return_exceptions=True)
        logger.info("Recovery manager stopped")

    async def _run_periodically(self, step, interval: int):
        """Run one pass of `step` every `interval` seconds until stopped"""
        while self.running:
            try:
                await step()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(
                    "Recovery task %s failed: %s",
                    getattr(step, "__name__", step), e, exc_info=True,
                )
                await asyncio.sleep(self.ERROR_BACKOFF)
                continue
            await asyncio.sleep(interval)

    async def expire_unpaid_orders(self):
        """One sweep: cancel MIA orders nobody paid for in time, tell the customers, wake restock subscribers."""
        from bot.database.methods.orders import expire_unpaid_orders
        from bot.misc.services.order_view import notify_customer
        from bot.misc.services.restock_notifier import notify_restock

        for order in await expire_unpaid_orders():
            logger.info("Order %s cancelled: MIA payment not received in time", order["id"])
            await notify_customer(self.bot, order, "mia_expired")
            for name in order.get("restocked", []):
                await notify_restock(self.bot, name)

    async def remind_unpaid_orders(self):
        """One sweep: remind customers whose MIA order expires soon (once per order)."""
        from bot.database.methods.orders import claim_payment_reminders
        from bot.misc.services.order_view import notify_customer

        for order in await claim_payment_reminders():
            logger.info("Order %s: payment reminder", order["id"])
            await notify_customer(self.bot, order, "mia_reminder")

    async def alert_stale_orders(self):
        """One sweep: tell staff about orders that have waited too long for them (once per order)."""
        from bot.database.methods.orders import claim_stale_orders
        from bot.misc.services.order_view import notify_stale_order

        for kind, order in await claim_stale_orders():
            logger.info("Order %s: staff alert (%s)", order["id"], kind)
            await notify_stale_order(self.bot, order, kind)

    async def dispatch_due_mailings(self):
        """Start every scheduled mailing whose time has come (each runs as its own task)."""
        from bot.database.methods.mailings import claim_due_mailing
        from bot.misc.services.mailing_sender import MailingSender

        while True:
            mailing = await claim_due_mailing()
            if mailing is None:
                return
            logger.info("Mailing %s started (%s)", mailing["id"], mailing["segment"])
            task = asyncio.create_task(MailingSender(self.bot).run(mailing["id"]))
            self.mailing_tasks.add(task)
            task.add_done_callback(self.mailing_tasks.discard)

    async def periodic_health_check(self):
        """One DB + cache health probe"""
        from bot.database import Database

        async with Database().session() as s:
            await s.execute(text("SELECT 1"))

        from bot.misc.caching.cache import get_cache_manager
        cache = get_cache_manager()
        if cache:
            await cache.check_health()
            await cache.set("health:check", "ok", ttl=60)

        logger.debug("Health check passed: DB and cache are alive")
