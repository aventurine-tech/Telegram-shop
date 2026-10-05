from sqlalchemy import select

from bot.database.main import Database
from bot.database.methods.transactions import admin_balance_change
from bot.database.models.main import Operations, User


async def _get_balance(telegram_id: int) -> float:
    """Read user balance directly from DB to avoid cache issues."""
    async with Database().session() as s:
        result = await s.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalars().one()
        return float(user.balance)


class TestAdminBalanceChange:

    async def test_topup_success(self, user_factory):
        await user_factory(telegram_id=300001, balance=100)

        success, msg = await admin_balance_change(300001, 500)

        assert success is True
        assert msg == "success"
        assert await _get_balance(300001) == 600.0

        # Operation record created
        async with Database().session() as s:
            ops = (await s.execute(select(Operations).where(
                Operations.user_id == 300001
            ))).scalars().all()
            assert len(ops) == 1
            assert float(ops[0].operation_value) == 500.0

    async def test_deduct_success(self, user_factory):
        await user_factory(telegram_id=300002, balance=500)

        success, msg = await admin_balance_change(300002, -200)

        assert success is True
        assert msg == "success"
        assert await _get_balance(300002) == 300.0

        # Operation record created with negative value
        async with Database().session() as s:
            ops = (await s.execute(select(Operations).where(
                Operations.user_id == 300002
            ))).scalars().all()
            assert len(ops) == 1
            assert float(ops[0].operation_value) == -200.0

    async def test_deduct_insufficient_funds(self, user_factory):
        await user_factory(telegram_id=300003, balance=100)

        success, msg = await admin_balance_change(300003, -200)
        assert success is False
        assert msg == "insufficient_funds"

        # Balance unchanged
        assert await _get_balance(300003) == 100.0

        # No operation record created
        async with Database().session() as s:
            ops = (await s.execute(select(Operations).where(
                Operations.user_id == 300003
            ))).scalars().all()
            assert len(ops) == 0

    async def test_deduct_exact_balance(self, user_factory):
        await user_factory(telegram_id=300004, balance=500)

        success, msg = await admin_balance_change(300004, -500)

        assert success is True
        assert await _get_balance(300004) == 0.0

    async def test_user_not_found(self):
        success, msg = await admin_balance_change(999888, 100)

        assert success is False
        assert msg == "user_not_found"

    async def test_topup_and_deduct_atomic(self, user_factory):
        """Verify that balance and operation are created atomically."""
        await user_factory(telegram_id=300005, balance=1000)

        await admin_balance_change(300005, 500)
        await admin_balance_change(300005, -300)

        assert await _get_balance(300005) == 1200.0

        async with Database().session() as s:
            ops = (await s.execute(select(Operations).where(
                Operations.user_id == 300005
            ).order_by(Operations.id))).scalars().all()
            assert len(ops) == 2
            assert float(ops[0].operation_value) == 500.0
            assert float(ops[1].operation_value) == -300.0
