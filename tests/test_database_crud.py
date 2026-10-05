import asyncio
import datetime
from decimal import Decimal

import pytest

from sqlalchemy import select

from bot.database.methods.create import create_user, create_item
from bot.database.methods.read import (
    check_user, check_role, get_role_id_by_name,
    check_role_name_by_id,
    select_today_users, get_user_count,
    get_all_users, check_category,
    get_item_info, select_item_stock,
    select_count_items, select_count_goods,
    select_count_categories, select_user_items,
    check_user_referrals, get_user_referral,
    get_referral_earnings_stats,
    get_one_referral_earning,
    select_today_orders, select_all_orders,
    select_today_operations, select_all_operations,
    select_users_balance,
    get_roles_with_max_perms,
    count_users_with_role,
)
from bot.database.methods.update import (
    set_role, set_user_blocked,
    is_user_blocked, update_item, update_category,
)
from bot.database.methods.delete import delete_item, delete_category

NOW = datetime.datetime.now(datetime.timezone.utc)

async def _add_order(user_id, total, *, status="completed", at=None):
    from bot.database import Database as DB
    from bot.database.models.main import Orders
    async with DB().session() as s:
        s.add(Orders(
            user_id=user_id, status=status, payment_method="cod", payment_status="unpaid",
            fulfillment="pickup", customer_name="T", phone="123456", total=total,
            created_at=at or NOW,
        ))

TODAY_STR = NOW.strftime("%Y-%m-%d")


class TestUserCRUD:
    async def test_create_user_and_check(self, user_factory):
        user = await user_factory(telegram_id=1001)
        assert user is not None
        assert user["telegram_id"] == 1001

    async def test_create_user_duplicate_ignored(self, user_factory):
        await user_factory(telegram_id=2001)
        # Creating again should not raise
        await create_user(2001, NOW, referral_id=None, role=1)
        assert await get_user_count() == 1

    async def test_create_user_swallows_insert_conflict(self, user_factory, monkeypatch):
        await user_factory(telegram_id=2002)

        import bot.database.methods.create as create_mod

        class _Miss:
            def scalar(self):
                return False

        from sqlalchemy.ext.asyncio import AsyncSession
        orig_execute = AsyncSession.execute
        state = {"first": True}

        async def fake_execute(self, statement, *a, **k):
            if state["first"]:
                state["first"] = False
                return _Miss()  # existence pre-check sees "not exists"
            return await orig_execute(self, statement, *a, **k)

        monkeypatch.setattr(AsyncSession, "execute", fake_execute)

        # Should not raise even though 2002 already exists.
        await create_mod.create_user(2002, NOW, referral_id=None, role=1)

        monkeypatch.undo()
        assert await get_user_count() == 1
        assert (await check_user(2002))["telegram_id"] == 2002

    async def test_check_user_not_found(self):
        result = await check_user(999999)
        assert result is None

    async def test_get_user_count(self, user_factory):
        assert await get_user_count() == 0
        await user_factory(telegram_id=3001)
        await user_factory(telegram_id=3002)
        assert await get_user_count() == 2

    async def test_get_all_users(self, user_factory):
        await user_factory(telegram_id=4001)
        await user_factory(telegram_id=4002)
        users = await get_all_users()
        ids = [row[0] for row in users]
        assert 4001 in ids
        assert 4002 in ids

    async def test_select_today_users(self, user_factory):
        await user_factory(telegram_id=5001)
        count = await select_today_users(TODAY_STR)
        assert count == 1

    async def test_select_today_users_wrong_date(self, user_factory):
        await user_factory(telegram_id=5002)
        count = await select_today_users("2000-01-01")
        assert count == 0

    async def test_create_user_with_referral(self, user_factory):
        await user_factory(telegram_id=6001)
        await user_factory(telegram_id=6002, referral_id=6001)
        ref = await get_user_referral(6002)
        assert ref == 6001


class TestRoleCRUD:
    # Role listing/lookup by id lives in test_role_management.py — this class only covers name->id resolution and the per-user permission read.

    @pytest.mark.parametrize("name,found", [
        ("USER", True),
        ("ADMIN", True),
        ("NONEXISTENT", False),
    ])
    async def test_get_role_id_by_name(self, name, found):
        role_id = await get_role_id_by_name(name)
        assert (role_id is not None) is found

    async def test_check_role_name_by_id(self):
        role_id = await get_role_id_by_name("USER")
        name = await check_role_name_by_id(role_id)
        assert name == "USER"

    async def test_check_role_returns_permissions(self, user_factory):
        await user_factory(telegram_id=7001)
        perms = await check_role(7001)
        # USER role has USE=1 permission
        assert perms & 1 == 1

    async def test_check_role_nonexistent_user(self):
        perms = await check_role(999888)
        assert perms == 0

    async def test_set_role(self, user_factory):
        await user_factory(telegram_id=7002)
        admin_role_id = await get_role_id_by_name("ADMIN")
        await set_role(7002, admin_role_id)
        perms = await check_role(7002)
        # ADMIN has BROADCAST=2 permission
        assert perms & 2 == 2

    async def test_get_roles_with_max_perms(self):
        roles = await get_roles_with_max_perms(1)
        assert all((r['permissions'] & ~1) == 0 for r in roles)

    async def test_count_users_with_role(self, user_factory):
        await user_factory(telegram_id=7003, role_id=1)
        user_role = await get_role_id_by_name('USER')
        assert await count_users_with_role(user_role) == 1


class TestCategoryCRUD:
    async def test_create_and_check_category(self, category_factory):
        await category_factory("Electronics")
        cat = await check_category("Electronics")
        assert cat is not None
        assert cat["name"] == "Electronics"

    async def test_create_category_duplicate_ignored(self, category_factory):
        await category_factory("Books")
        await category_factory("Books")
        assert await select_count_categories() == 1

    async def test_check_category_not_found(self):
        assert await check_category("Nonexistent") is None

    async def test_select_count_categories(self, category_factory):
        await category_factory("CatA")
        await category_factory("CatB")
        assert await select_count_categories() == 2

    async def test_update_category_rename(self, category_factory):
        await category_factory("OldCat")
        await update_category("OldCat", "NewCat")
        assert await check_category("OldCat") is None
        assert await check_category("NewCat") is not None

    async def test_delete_category(self, category_factory):
        await category_factory("ToDelete")
        await delete_category("ToDelete")
        assert await check_category("ToDelete") is None

    async def test_delete_category_with_items_no_crash(self, item_factory):
        await item_factory(name="test", category="lol", stock=1)
        await delete_category("lol")
        assert await check_category("lol") is None


class TestItemCRUD:
    async def test_create_and_get_item_info(self, item_factory):
        await item_factory(name="Widget", price=50, category="Gadgets",
                           description="Desc here")
        item = await get_item_info("Widget")
        assert item is not None
        assert item["name"] == "Widget"
        assert item["price"] == Decimal("50")
        assert item["description"] == "Desc here"

    async def test_create_item_duplicate_ignored(self, item_factory):
        await item_factory(name="DupItem", category="DupCat")
        await create_item("DupItem", "desc2", 200, "DupCat")
        assert await select_count_goods() == 1

    async def test_create_item_with_initial_stock(self, item_factory):
        await item_factory(name="Stocked", category="StockCat", stock=7)
        assert await select_item_stock("Stocked") == 7

    async def test_create_item_never_starts_negative(self, category_factory):
        await category_factory("NegCat")
        await create_item("NegItem", "d", 5, "NegCat", stock=-4)
        assert await select_item_stock("NegItem") == 0

    async def test_select_count_items(self, item_factory):
        await item_factory(name="CI1", category="CICat", stock=2)
        assert await select_count_items() == 2

    async def test_select_count_goods(self, item_factory):
        await item_factory(name="G1", category="GCat")
        await item_factory(name="G2", category="GCat")
        assert await select_count_goods() == 2

    async def test_update_item_same_name(self, item_factory):
        await item_factory(name="UpdItem", price=100, category="UpdCat", description="old desc")
        ok, err = await update_item("UpdItem", "UpdItem", "new desc", 200, "UpdCat")
        assert ok is True
        assert err is None
        info = await get_item_info("UpdItem")
        assert info["description"] == "new desc"
        assert info["price"] == Decimal("200")

    async def test_update_item_rename(self, item_factory):
        await item_factory(name="RenameOld", price=10, category="RenCat")
        ok, err = await update_item("RenameOld", "RenameNew", "desc", 10, "RenCat")
        assert ok is True
        assert await get_item_info("RenameOld") is None
        assert await get_item_info("RenameNew") is not None

    async def test_update_item_not_found(self):
        ok, err = await update_item("Ghost", "Ghost2", "d", 1, "c")
        assert (ok, err) == (False, "position_invalid")

    async def test_update_item_rename_conflict(self, item_factory):
        await item_factory(name="Keep", price=10, category="ConflictCat")
        await item_factory(name="Taken", price=10, category="ConflictCat")
        ok, err = await update_item("Keep", "Taken", "d", 10, "ConflictCat")
        assert (ok, err) == (False, "position_exists")
        assert await get_item_info("Keep") is not None

    async def test_delete_item(self, item_factory):
        await item_factory(name="DelItem", category="DelCat", stock=1)
        await delete_item("DelItem")
        assert await get_item_info("DelItem") is None
        assert await select_item_stock("DelItem") == 0

    async def test_delete_item_keeps_order_history(self, user_factory, item_factory):
        from bot.database import Database as DB
        from bot.database.methods.create import add_to_cart
        from bot.database.methods.orders import create_order_transaction
        from bot.database.models.main import OrderItems, Fulfillment, PaymentMethod
        await user_factory(telegram_id=9100)
        await item_factory(name="Gone", category="GoneCat", price=30, stock=2)
        await add_to_cart(9100, "Gone")
        ok, _, order = await create_order_transaction(
            9100, fulfillment=Fulfillment.PICKUP, customer_name="A", phone="123456",
            address=None, comment=None, payment_method=PaymentMethod.COD)
        assert ok

        await delete_item("Gone")

        async with DB().session() as s:
            line = (await s.execute(select(OrderItems).where(OrderItems.order_id == order["id"]))).scalars().one()
        assert (line.item_name, line.unit_price) == ("Gone", Decimal("30"))   # the snapshot survives


class TestBalanceOperations:
    async def test_select_users_balance(self, user_factory):
        await user_factory(telegram_id=8003, balance=100)
        await user_factory(telegram_id=8004, balance=250)
        total = await select_users_balance()
        assert total == Decimal("350")

    async def test_select_user_operations_total_sums_every_row(self, user_factory, operation_factory):
        from bot.database.methods.read import select_user_operations_total

        await user_factory(telegram_id=8016)
        assert await select_user_operations_total(8016) == Decimal("0")

        await operation_factory(8016, 100, NOW)
        assert await select_user_operations_total(8016) == Decimal("100")

        await operation_factory(8016, 250, NOW)
        assert await select_user_operations_total(8016) == Decimal("350")

    async def test_select_today_operations(self, user_factory, operation_factory):
        await user_factory(telegram_id=8007)
        await operation_factory(8007, 300, NOW)
        total = await select_today_operations(TODAY_STR)
        assert total == Decimal("300")

    async def test_select_all_operations(self, user_factory, operation_factory):
        await user_factory(telegram_id=8008)
        await operation_factory(8008, 400, NOW)
        total = await select_all_operations()
        assert total == Decimal("400")

    async def test_set_user_blocked(self, user_factory):
        await user_factory(telegram_id=8009)
        result = await set_user_blocked(8009, True)
        assert result is True
        assert await is_user_blocked(8009) is True

    async def test_set_user_blocked_nonexistent(self):
        result = await set_user_blocked(999777, True)
        assert result is False

    async def test_is_user_blocked_default_false(self, user_factory):
        await user_factory(telegram_id=8010)
        assert await is_user_blocked(8010) is False

    async def test_unblock_user(self, user_factory):
        await user_factory(telegram_id=8011)
        await set_user_blocked(8011, True)
        await set_user_blocked(8011, False)
        assert await is_user_blocked(8011) is False


class TestReferrals:
    async def test_check_user_referrals_count(self, user_factory):
        await user_factory(telegram_id=10001)
        await user_factory(telegram_id=10002, referral_id=10001)
        await user_factory(telegram_id=10003, referral_id=10001)
        assert await check_user_referrals(10001) == 2

    async def test_check_user_referrals_zero(self, user_factory):
        await user_factory(telegram_id=10004)
        assert await check_user_referrals(10004) == 0

    async def test_get_user_referral(self, user_factory):
        await user_factory(telegram_id=10005)
        await user_factory(telegram_id=10006, referral_id=10005)
        assert await get_user_referral(10006) == 10005

    async def test_get_user_referral_none(self, user_factory):
        await user_factory(telegram_id=10007)
        assert await get_user_referral(10007) is None

    async def test_referral_earnings_stats(self, user_factory, referral_earning_factory):
        await user_factory(telegram_id=10008)
        await user_factory(telegram_id=10009, referral_id=10008)
        await referral_earning_factory(10008, 10009, 50, 500)
        stats = await get_referral_earnings_stats(10008)
        assert stats["total_earnings_count"] == 1
        assert stats["total_amount"] == Decimal("50")
        assert stats["total_original_amount"] == Decimal("500")
        assert stats["active_referrals_count"] == 1

    async def test_get_one_referral_earning(self, user_factory, referral_earning_factory):
        await user_factory(telegram_id=10010)
        await user_factory(telegram_id=10011, referral_id=10010)
        await referral_earning_factory(10010, 10011, 25, 250)
        # Get the earning id via async DB session
        from bot.database import Database as DB
        from bot.database.models import ReferralEarnings
        async with DB().session() as s:
            result = await s.execute(
                select(ReferralEarnings).where(ReferralEarnings.referrer_id == 10010)
            )
            e = result.scalars().first()
            eid = e.id
        earning = await get_one_referral_earning(eid)
        assert earning is not None
        assert earning["referrer_id"] == 10010
        assert earning["amount"] == Decimal("25")

    async def test_get_one_referral_earning_not_found(self):
        result = await get_one_referral_earning(999999)
        assert result is None

    async def test_referral_earnings_stats_empty(self, user_factory):
        await user_factory(telegram_id=10012)
        stats = await get_referral_earnings_stats(10012)
        assert stats["total_earnings_count"] == 0
        assert stats["total_amount"] == Decimal("0")


class TestStats:
    async def test_select_today_orders_no_orders(self):
        total = await select_today_orders(TODAY_STR)
        assert total == Decimal("0")

    async def test_select_all_orders_no_orders(self):
        total = await select_all_orders()
        assert total == Decimal("0")

    async def test_select_today_orders_with_orders(self, user_factory):
        await user_factory(telegram_id=11001)
        await _add_order(11001, 150)
        await _add_order(11001, 999, status="cancelled")      # cancelled orders are not revenue
        total = await select_today_orders(TODAY_STR)
        assert total == Decimal("150")

    async def test_select_all_orders_with_orders(self, user_factory):
        await user_factory(telegram_id=11002)
        await _add_order(11002, 100)
        await _add_order(11002, 200)
        total = await select_all_orders()
        assert total == Decimal("300")

    async def test_select_user_items_count(self, user_factory):
        await user_factory(telegram_id=11003)
        await _add_order(11003, 10)
        await _add_order(11003, 20)
        await _add_order(11003, 30, status="cancelled")
        assert await select_user_items(11003) == 2

    async def test_select_users_balance_empty(self):
        assert await select_users_balance() == Decimal(0)

    async def test_select_all_operations_empty(self):
        assert await select_all_operations() == Decimal("0")

    async def test_select_today_operations_empty(self):
        assert await select_today_operations(TODAY_STR) == Decimal("0")
