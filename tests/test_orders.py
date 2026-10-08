"""Order lifecycle: placing, stock reservation, cancelling, MIA verification, status changes."""
import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select, func, update as sa_update

from bot.database.main import Database
from bot.database.methods.create import add_to_cart
from bot.database.methods.lazy_queries import query_orders, query_user_orders
from bot.database.methods.orders import (
    create_order_transaction, cancel_order_transaction, confirm_mia_payment, reject_mia_payment,
    mark_mia_paid, set_order_status, expire_unpaid_orders, get_order, get_order_notify_ids,
    available_payment_methods, available_fulfillments,
)
from bot.database.methods.read import (
    has_purchased_item, select_item_stock, select_all_orders, select_count_bought_items,
    select_today_orders_count, select_user_items,
)
from bot.database.methods.update import set_item_stock, adjust_item_stock
from bot.database.models.main import (
    CartItems, Goods, Operations, Orders, OrderItems, OrderStatus, PaymentMethod, PaymentStatus,
    PromoCodes, PromoCodeUsages, ReferralEarnings, ShippingMethods, User, Fulfillment, Permission,
)

UID = 710001


def _order_kwargs(**over):
    kw = dict(
        fulfillment=Fulfillment.DELIVERY, customer_name="Ion Popescu", phone="+37360000001",
        address="Str. Test 1, Chisinau", comment=None, payment_method=PaymentMethod.COD,
    )
    kw.update(over)
    return kw


async def _balance(uid: int) -> Decimal:
    async with Database().session() as s:
        return (await s.execute(select(User.balance).where(User.telegram_id == uid))).scalar()


async def _stock(name: str) -> int:
    async with Database().session() as s:
        return (await s.execute(select(Goods.stock).where(Goods.name == name))).scalar()


async def _cart_rows(uid: int) -> int:
    async with Database().session() as s:
        return (await s.execute(
            select(func.count()).select_from(CartItems).where(CartItems.user_id == uid)
        )).scalar()


async def _make_promo(code, discount_type="percent", value="10"):
    async with Database().session() as s:
        s.add(PromoCodes(
            code=code.upper(), discount_type=discount_type, discount_value=Decimal(str(value)),
            max_uses=0, current_uses=0, is_active=True,
        ))


async def _place(uid=UID, item="Chair", qty=1, **over):
    await add_to_cart(uid, item, quantity=qty)
    ok, code, data = await create_order_transaction(uid, **_order_kwargs(**over))
    assert ok, code
    return data


@pytest.fixture
async def shop(user_factory, item_factory):
    """One customer with a balance of 0 and an item with 5 units."""
    await user_factory(telegram_id=UID)
    await item_factory(name="Chair", price=100, stock=5)
    await item_factory(name="Lamp", price=40, stock=2, category="Chair-cat")


class TestCreateOrder:

    async def test_cod_delivery_reserves_stock_and_clears_cart(self, shop):
        order = await _place(qty=2)

        assert order["status"] == OrderStatus.NEW
        assert order["payment_method"] == PaymentMethod.COD
        assert order["payment_status"] == PaymentStatus.UNPAID
        assert order["total"] == Decimal("200.00")
        assert order["due"] == Decimal("200.00")
        assert order["pay_by"] is None
        assert [(i["item_name"], i["quantity"], i["line_total"]) for i in order["items"]] == [
            ("Chair", 2, Decimal("200.00"))]
        assert await _stock("Chair") == 3
        assert await _cart_rows(UID) == 0

    async def test_mia_order_waits_for_payment_with_deadline(self, shop):
        before = datetime.datetime.now(datetime.timezone.utc)
        order = await _place(payment_method=PaymentMethod.MIA)

        assert order["payment_method"] == PaymentMethod.MIA
        assert order["payment_status"] == PaymentStatus.AWAITING_PAYMENT
        pay_by = order["pay_by"]
        if pay_by.tzinfo is None:
            pay_by = pay_by.replace(tzinfo=datetime.timezone.utc)
        assert pay_by > before + datetime.timedelta(minutes=119)

    async def test_pickup_needs_no_address(self, shop):
        order = await _place(fulfillment=Fulfillment.PICKUP, address=None)
        assert order["fulfillment"] == Fulfillment.PICKUP
        assert order["address"] is None

    async def test_delivery_requires_address(self, shop):
        await add_to_cart(UID, "Chair")
        ok, code, _ = await create_order_transaction(UID, **_order_kwargs(address="  "))
        assert (ok, code) == (False, "address_required")
        assert await _stock("Chair") == 5
        assert await _cart_rows(UID) == 1

    @pytest.mark.parametrize("over,code", [
        ({"payment_method": "bitcoin"}, "invalid_payment_method"),
        ({"fulfillment": "teleport"}, "invalid_fulfillment"),
    ])
    async def test_rejects_unknown_choices(self, shop, over, code):
        await add_to_cart(UID, "Chair")
        ok, got, _ = await create_order_transaction(UID, **_order_kwargs(**over))
        assert (ok, got) == (False, code)

    async def test_disabled_method_is_refused(self, shop):
        await add_to_cart(UID, "Chair")
        with patch('bot.misc.env.EnvKeys.COD_ENABLED', '0'):
            ok, code, _ = await create_order_transaction(UID, **_order_kwargs())
        assert (ok, code) == (False, "invalid_payment_method")
        assert await _stock("Chair") == 5

    async def test_disabled_fulfillment_is_refused(self, shop):
        await add_to_cart(UID, "Chair")
        with patch('bot.misc.env.EnvKeys.DELIVERY_ENABLED', '0'):
            ok, code, _ = await create_order_transaction(UID, **_order_kwargs())
        assert (ok, code) == (False, "invalid_fulfillment")

    async def test_mia_is_off_without_payout_details(self):
        with patch.multiple('bot.misc.env.EnvKeys', MIA_RECIPIENT='', MIA_PHONE='', MIA_IBAN=''):
            assert available_payment_methods() == [PaymentMethod.COD]
        assert available_payment_methods() == [PaymentMethod.MIA, PaymentMethod.COD]
        assert available_fulfillments() == [Fulfillment.DELIVERY, Fulfillment.PICKUP]

    async def test_out_of_stock_aborts_whole_order(self, shop):
        await add_to_cart(UID, "Lamp", quantity=1)
        await add_to_cart(UID, "Chair", quantity=6)   # only 5 on hand

        ok, code, data = await create_order_transaction(UID, **_order_kwargs())

        assert (ok, code) == (False, "out_of_stock")
        assert data == {"item_name": "Chair", "available": 5}
        # nothing was reserved, nothing was ordered, the cart is intact
        assert await _stock("Chair") == 5
        assert await _stock("Lamp") == 2
        assert await _cart_rows(UID) == 2
        async with Database().session() as s:
            assert (await s.execute(select(func.count()).select_from(Orders))).scalar() == 0

    async def test_last_unit_goes_to_first_buyer_only(self, shop, user_factory):
        await user_factory(telegram_id=UID + 1)
        await set_item_stock("Chair", 1)
        await add_to_cart(UID, "Chair")
        await add_to_cart(UID + 1, "Chair")

        first = await create_order_transaction(UID, **_order_kwargs())
        second = await create_order_transaction(UID + 1, **_order_kwargs())

        assert first[0] is True
        assert second[:2] == (False, "out_of_stock")
        assert await _stock("Chair") == 0

    async def test_empty_cart(self, shop):
        ok, code, _ = await create_order_transaction(UID, **_order_kwargs())
        assert (ok, code) == (False, "cart_empty")

    async def test_unknown_user(self, shop):
        ok, code, _ = await create_order_transaction(1, **_order_kwargs())
        assert (ok, code) == (False, "user_not_found")

    async def test_deleted_product_is_dropped_from_cart(self, shop):
        await add_to_cart(UID, "Chair")
        async with Database().session() as s:
            await s.execute(sa_update(CartItems).values(item_id=987654))  # dangling reference
        ok, code, _ = await create_order_transaction(UID, **_order_kwargs())
        assert (ok, code) == (False, "cart_items_unavailable")
        assert await _cart_rows(UID) == 0

    async def test_price_changed_since_confirmation(self, shop):
        await add_to_cart(UID, "Chair", quantity=2)
        ok, code, _ = await create_order_transaction(
            UID, **_order_kwargs(), expected_total=Decimal("150.00"))
        assert (ok, code) == (False, "price_changed")
        assert await _stock("Chair") == 5

    async def test_expected_total_matches(self, shop):
        await add_to_cart(UID, "Chair", quantity=2)
        ok, _, data = await create_order_transaction(
            UID, **_order_kwargs(), expected_total=Decimal("200.00"))
        assert ok and data["total"] == Decimal("200.00")

    async def test_active_sale_price_is_charged(self, shop):
        async with Database().session() as s:
            await s.execute(sa_update(Goods).where(Goods.name == "Chair").values(
                sale_percent=Decimal("25"),
                sale_until=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1),
            ))
        order = await _place()
        assert order["total"] == Decimal("75.00")
        assert order["items"][0]["unit_price"] == Decimal("75.00")

    async def test_percent_promo_and_usage_recorded(self, shop):
        await _make_promo("PCT10", "percent", 10)
        await add_to_cart(UID, "Chair", promo_code="PCT10", quantity=2)
        ok, _, order = await create_order_transaction(UID, **_order_kwargs())
        assert ok and order["total"] == Decimal("180.00")
        async with Database().session() as s:
            promo = (await s.execute(select(PromoCodes).where(PromoCodes.code == "PCT10"))).scalars().one()
            assert promo.current_uses == 1
            assert (await s.execute(select(func.count()).select_from(PromoCodeUsages))).scalar() == 1

    async def test_fixed_promo_comes_off_once_and_never_below_zero(self, shop):
        await _make_promo("FIX999", "fixed", 999)
        await add_to_cart(UID, "Lamp", promo_code="FIX999")
        ok, _, order = await create_order_transaction(UID, **_order_kwargs())
        assert ok and order["total"] == Decimal("0.00")

    async def test_promo_discounts_only_the_biggest_line(self, shop):
        await _make_promo("TEN", "percent", 10)
        await add_to_cart(UID, "Chair", promo_code="TEN")     # 100
        await add_to_cart(UID, "Lamp", promo_code="TEN")      # 40
        ok, _, order = await create_order_transaction(UID, **_order_kwargs())
        assert ok and order["total"] == Decimal("130.00")     # 90 + 40

    async def test_free_order_has_zero_due(self, shop):
        await _make_promo("FREE", "fixed", 999)
        await add_to_cart(UID, "Lamp", promo_code="FREE")
        ok, _, order = await create_order_transaction(UID, **_order_kwargs())
        assert ok
        assert order["payment_method"] == PaymentMethod.BALANCE
        assert order["payment_status"] == PaymentStatus.PAID


class TestUseBalance:

    async def test_partial_balance(self, shop):
        async with Database().session() as s:
            await s.execute(sa_update(User).where(User.telegram_id == UID).values(balance=30))
        order = await _place(payment_method=PaymentMethod.MIA, use_balance=True)
        assert order["balance_used"] == Decimal("30.00")
        assert order["due"] == Decimal("70.00")
        assert order["payment_method"] == PaymentMethod.MIA
        assert order["payment_status"] == PaymentStatus.AWAITING_PAYMENT
        assert await _balance(UID) == 0

    async def test_balance_covers_everything(self, shop):
        async with Database().session() as s:
            await s.execute(sa_update(User).where(User.telegram_id == UID).values(balance=500))
        order = await _place(use_balance=True)
        assert order["balance_used"] == Decimal("100.00")
        assert order["due"] == Decimal("0.00")
        assert order["payment_method"] == PaymentMethod.BALANCE
        assert order["payment_status"] == PaymentStatus.PAID
        assert order["pay_by"] is None
        assert await _balance(UID) == 400

    async def test_balance_untouched_unless_asked(self, shop):
        async with Database().session() as s:
            await s.execute(sa_update(User).where(User.telegram_id == UID).values(balance=500))
        order = await _place()
        assert order["balance_used"] == 0
        assert await _balance(UID) == 500

    async def test_balance_covered_order_needs_no_enabled_method(self, shop):
        async with Database().session() as s:
            await s.execute(sa_update(User).where(User.telegram_id == UID).values(balance=500))
        await add_to_cart(UID, "Chair")
        with patch('bot.misc.env.EnvKeys.COD_ENABLED', '0'):
            ok, _, order = await create_order_transaction(UID, **_order_kwargs(), use_balance=True)
        assert ok and order["payment_method"] == PaymentMethod.BALANCE


class TestCancel:

    async def test_cancel_restocks_and_refunds_balance(self, shop):
        async with Database().session() as s:
            await s.execute(sa_update(User).where(User.telegram_id == UID).values(balance=30))
        order = await _place(qty=2, use_balance=True)
        assert await _stock("Chair") == 3 and await _balance(UID) == 0

        ok, code, data = await cancel_order_transaction(order["id"])

        assert (ok, code) == (True, "success")
        assert data["status"] == OrderStatus.CANCELLED
        assert await _stock("Chair") == 5
        assert await _balance(UID) == 30
        assert data["restocked"] == []     # it was never at zero

    async def test_reports_items_that_came_back_from_zero(self, shop):
        await set_item_stock("Lamp", 1)
        order = await _place(item="Lamp")
        assert await _stock("Lamp") == 0
        _, _, data = await cancel_order_transaction(order["id"])
        assert data["restocked"] == ["Lamp"]

    async def test_cannot_cancel_twice(self, shop):
        order = await _place()
        await cancel_order_transaction(order["id"])
        ok, code, _ = await cancel_order_transaction(order["id"])
        assert (ok, code) == (False, "not_cancellable")
        assert await _stock("Chair") == 5   # restocked once only

    async def test_cannot_cancel_completed(self, shop):
        order = await _place()
        for status in (OrderStatus.CONFIRMED, OrderStatus.COMPLETED):
            assert (await set_order_status(order["id"], status))[0]
        ok, code, _ = await cancel_order_transaction(order["id"])
        assert (ok, code) == (False, "not_cancellable")

    async def test_customer_can_cancel_own_new_order(self, shop):
        order = await _place()
        ok, _, data = await cancel_order_transaction(order["id"], by_customer_id=UID)
        assert ok and data["status"] == OrderStatus.CANCELLED

    async def test_customer_cannot_cancel_someone_elses_order(self, shop):
        order = await _place()
        ok, code, _ = await cancel_order_transaction(order["id"], by_customer_id=UID + 5)
        assert (ok, code) == (False, "order_not_found")
        assert (await get_order(order["id"]))["status"] == OrderStatus.NEW

    async def test_customer_cannot_cancel_once_the_shop_accepted(self, shop):
        order = await _place()
        await set_order_status(order["id"], OrderStatus.CONFIRMED)
        ok, code, _ = await cancel_order_transaction(order["id"], by_customer_id=UID)
        assert (ok, code) == (False, "not_cancellable")

    async def test_customer_cannot_cancel_once_money_is_with_the_shop(self, shop):
        order = await _place(payment_method=PaymentMethod.MIA)
        await mark_mia_paid(order["id"], UID)
        ok, code, _ = await cancel_order_transaction(order["id"], by_customer_id=UID)
        assert (ok, code) == (False, "not_cancellable")

    async def test_admin_cancelling_a_paid_mia_order_flags_a_refund(self, shop):
        order = await _place(payment_method=PaymentMethod.MIA)
        await confirm_mia_payment(order["id"])
        ok, _, data = await cancel_order_transaction(order["id"])
        assert ok
        assert data["payment_status"] == PaymentStatus.REFUNDED
        assert await _stock("Chair") == 5

    async def test_cancelling_unpaid_cod_order_leaves_payment_unpaid(self, shop):
        order = await _place()
        _, _, data = await cancel_order_transaction(order["id"])
        assert data["payment_status"] == PaymentStatus.UNPAID

    async def test_restock_skips_a_deleted_product(self, shop):
        order = await _place(item="Lamp")
        async with Database().session() as s:
            await s.execute(sa_update(OrderItems).values(item_id=None))
            await s.execute(Goods.__table__.delete().where(Goods.name == "Lamp"))
        ok, _, data = await cancel_order_transaction(order["id"])
        assert ok and data["restocked"] == []

    async def test_unknown_order(self, shop):
        assert (await cancel_order_transaction(424242))[:2] == (False, "order_not_found")


class TestMiaPayment:

    async def test_customer_marks_paid_then_admin_confirms(self, shop):
        order = await _place(payment_method=PaymentMethod.MIA)

        ok, _, claimed = await mark_mia_paid(order["id"], UID, proof_file_id="file-123")
        assert ok
        assert claimed["payment_status"] == PaymentStatus.AWAITING_CONFIRMATION
        assert claimed["payment_proof"] == "file-123"
        assert claimed["pay_by"] is None          # the unpaid timer must stop

        ok, _, confirmed = await confirm_mia_payment(order["id"], admin_id=1)
        assert ok
        assert confirmed["payment_status"] == PaymentStatus.PAID
        assert confirmed["status"] == OrderStatus.CONFIRMED

    async def test_admin_may_confirm_without_the_customer_claiming(self, shop):
        order = await _place(payment_method=PaymentMethod.MIA)
        ok, _, data = await confirm_mia_payment(order["id"])
        assert ok and data["payment_status"] == PaymentStatus.PAID

    async def test_confirm_twice(self, shop):
        order = await _place(payment_method=PaymentMethod.MIA)
        await confirm_mia_payment(order["id"])
        assert (await confirm_mia_payment(order["id"]))[:2] == (False, "not_awaiting_payment")

    async def test_reject_returns_to_awaiting_payment_with_fresh_deadline(self, shop):
        order = await _place(payment_method=PaymentMethod.MIA)
        await mark_mia_paid(order["id"], UID, proof_file_id="f")

        ok, _, data = await reject_mia_payment(order["id"])

        assert ok
        assert data["payment_status"] == PaymentStatus.AWAITING_PAYMENT
        assert data["payment_proof"] is None
        assert data["pay_by"] is not None
        # ...and the customer can claim again
        assert (await mark_mia_paid(order["id"], UID))[0] is True

    async def test_reject_requires_a_claim(self, shop):
        order = await _place(payment_method=PaymentMethod.MIA)
        assert (await reject_mia_payment(order["id"]))[:2] == (False, "not_awaiting_payment")

    async def test_cod_order_is_not_mia(self, shop):
        order = await _place()
        assert (await mark_mia_paid(order["id"], UID))[:2] == (False, "not_mia")
        assert (await confirm_mia_payment(order["id"]))[:2] == (False, "not_mia")
        assert (await reject_mia_payment(order["id"]))[:2] == (False, "not_mia")

    async def test_other_user_cannot_claim_payment(self, shop):
        order = await _place(payment_method=PaymentMethod.MIA)
        assert (await mark_mia_paid(order["id"], UID + 9))[:2] == (False, "order_not_found")

    async def test_cannot_claim_on_cancelled_order(self, shop):
        order = await _place(payment_method=PaymentMethod.MIA)
        await cancel_order_transaction(order["id"])
        assert (await mark_mia_paid(order["id"], UID))[:2] == (False, "not_awaiting_payment")


class TestExpiry:

    async def _backdate(self, order_id, minutes):
        async with Database().session() as s:
            await s.execute(sa_update(Orders).where(Orders.id == order_id).values(
                pay_by=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)))

    async def test_overdue_unpaid_mia_order_is_cancelled_and_restocked(self, shop):
        order = await _place(payment_method=PaymentMethod.MIA, qty=2)
        await self._backdate(order["id"], -5)

        cancelled = await expire_unpaid_orders()

        assert [o["id"] for o in cancelled] == [order["id"]]
        assert (await get_order(order["id"]))["status"] == OrderStatus.CANCELLED
        assert await _stock("Chair") == 5

    async def test_orders_still_inside_the_window_survive(self, shop):
        order = await _place(payment_method=PaymentMethod.MIA)
        await self._backdate(order["id"], 30)
        assert await expire_unpaid_orders() == []
        assert (await get_order(order["id"]))["status"] == OrderStatus.NEW

    async def test_a_claimed_payment_is_never_expired(self, shop):
        order = await _place(payment_method=PaymentMethod.MIA)
        await mark_mia_paid(order["id"], UID)
        await self._backdate(order["id"], -500)   # even a stale deadline
        assert await expire_unpaid_orders() == []

    async def test_cod_orders_never_expire(self, shop):
        order = await _place()
        assert await expire_unpaid_orders() == []
        assert (await get_order(order["id"]))["status"] == OrderStatus.NEW


class TestStatusFlow:

    async def test_cod_happy_path_collects_cash_on_completion(self, shop):
        order = await _place()
        for status in (OrderStatus.CONFIRMED, OrderStatus.SHIPPED):
            ok, _, data = await set_order_status(order["id"], status, admin_id=1)
            assert ok and data["status"] == status
            assert data["payment_status"] == PaymentStatus.UNPAID
        ok, _, data = await set_order_status(order["id"], OrderStatus.COMPLETED, admin_id=1)
        assert ok
        assert data["payment_status"] == PaymentStatus.PAID

    async def test_pickup_can_skip_shipping(self, shop):
        order = await _place(fulfillment=Fulfillment.PICKUP, address=None)
        await set_order_status(order["id"], OrderStatus.CONFIRMED)
        assert (await set_order_status(order["id"], OrderStatus.COMPLETED))[0] is True

    @pytest.mark.parametrize("target", [OrderStatus.SHIPPED, OrderStatus.COMPLETED, OrderStatus.NEW])
    async def test_new_order_cannot_jump_ahead(self, shop, target):
        order = await _place()
        assert (await set_order_status(order["id"], target))[:2] == (False, "invalid_transition")

    async def test_cannot_move_backwards(self, shop):
        order = await _place()
        await set_order_status(order["id"], OrderStatus.CONFIRMED)
        await set_order_status(order["id"], OrderStatus.SHIPPED)
        assert (await set_order_status(order["id"], OrderStatus.CONFIRMED))[:2] == (False, "invalid_transition")

    async def test_unknown_status_and_order(self, shop):
        order = await _place()
        assert (await set_order_status(order["id"], "teleported"))[:2] == (False, "invalid_status")
        assert (await set_order_status(31337, OrderStatus.CONFIRMED))[:2] == (False, "order_not_found")

    async def test_mia_order_cannot_progress_before_payment_is_verified(self, shop):
        order = await _place(payment_method=PaymentMethod.MIA)
        ok, code, _ = await set_order_status(order["id"], OrderStatus.CONFIRMED)
        assert (ok, code) == (False, "payment_not_confirmed")
        await mark_mia_paid(order["id"], UID)
        ok, code, _ = await set_order_status(order["id"], OrderStatus.CONFIRMED)
        assert (ok, code) == (False, "payment_not_confirmed")   # claiming is not verifying

    async def test_mia_order_flows_after_verification(self, shop):
        order = await _place(payment_method=PaymentMethod.MIA)
        await confirm_mia_payment(order["id"])
        for status in (OrderStatus.SHIPPED, OrderStatus.COMPLETED):
            assert (await set_order_status(order["id"], status))[0] is True

    async def test_cancel_goes_through_the_cancel_path(self, shop):
        order = await _place(qty=2)
        ok, _, data = await set_order_status(order["id"], OrderStatus.CANCELLED, admin_id=1)
        assert ok and data["status"] == OrderStatus.CANCELLED
        assert await _stock("Chair") == 5


class TestReferralCommission:

    async def _referred_customer(self, user_factory, item_factory):
        await user_factory(telegram_id=720001)                       # referrer
        await user_factory(telegram_id=720002, referral_id=720001)   # customer
        await item_factory(name="Sofa", price=1000, stock=3)

    async def _complete(self, uid, **over):
        order = await _place(uid=uid, item="Sofa", **over)
        if order["payment_method"] == PaymentMethod.MIA:
            await confirm_mia_payment(order["id"])
        else:
            await set_order_status(order["id"], OrderStatus.CONFIRMED)
        return order, await set_order_status(order["id"], OrderStatus.COMPLETED)

    async def test_commission_is_paid_on_completion_not_before(self, user_factory, item_factory):
        await self._referred_customer(user_factory, item_factory)
        order = await _place(uid=720002, item="Sofa")
        assert await _balance(720001) == 0                           # placing pays nothing
        await set_order_status(order["id"], OrderStatus.CONFIRMED)
        assert await _balance(720001) == 0

        await set_order_status(order["id"], OrderStatus.COMPLETED)

        assert await _balance(720001) == Decimal("100.00")           # REFERRAL_PERCENT=10 of 1000
        async with Database().session() as s:
            earning = (await s.execute(select(ReferralEarnings))).scalars().one()
            assert (earning.referrer_id, earning.referral_id) == (720001, 720002)
            assert earning.amount == Decimal("100.00")
            assert earning.original_amount == Decimal("1000.00")

    async def test_delivery_fee_earns_no_commission(self, user_factory, item_factory):
        await self._referred_customer(user_factory, item_factory)
        async with Database().session() as s:
            s.add(ShippingMethods(name="Courier", price=Decimal("50"), is_active=True))
        async with Database().session() as s:
            ship = (await s.execute(select(ShippingMethods).where(ShippingMethods.name == "Courier"))).scalars().one()
        try:
            await self._complete(720002, shipping_method_id=ship.id)
            assert await _balance(720001) == Decimal("100.00")       # 10% of the 1000 goods, not of 1050
            async with Database().session() as s:
                earning = (await s.execute(select(ReferralEarnings))).scalars().all()[-1]
                assert earning.original_amount == Decimal("1000.00")
        finally:
            async with Database().session() as s:
                await s.execute(delete(ShippingMethods).where(ShippingMethods.name == "Courier"))

    async def test_commission_is_paid_once(self, user_factory, item_factory):
        await self._referred_customer(user_factory, item_factory)
        order, _ = await self._complete(720002)
        again = await set_order_status(order["id"], OrderStatus.COMPLETED)
        assert again[:2] == (False, "invalid_transition")
        assert await _balance(720001) == Decimal("100.00")

    async def test_mia_order_pays_commission_too(self, user_factory, item_factory):
        await self._referred_customer(user_factory, item_factory)
        await self._complete(720002, payment_method=PaymentMethod.MIA)
        assert await _balance(720001) == Decimal("100.00")

    async def test_cancelled_order_pays_nothing(self, user_factory, item_factory):
        await self._referred_customer(user_factory, item_factory)
        order = await _place(uid=720002, item="Sofa")
        await cancel_order_transaction(order["id"])
        assert await _balance(720001) == 0

    async def test_commission_is_on_the_cash_actually_paid(self, user_factory, item_factory):
        await self._referred_customer(user_factory, item_factory)
        async with Database().session() as s:
            await s.execute(sa_update(User).where(User.telegram_id == 720002).values(balance=400))
        await self._complete(720002, use_balance=True)               # 400 from balance, 600 cash
        assert await _balance(720001) == Decimal("60.00")

    async def test_no_commission_when_balance_paid_everything(self, user_factory, item_factory):
        await self._referred_customer(user_factory, item_factory)
        async with Database().session() as s:
            await s.execute(sa_update(User).where(User.telegram_id == 720002).values(balance=5000))
        await self._complete(720002, use_balance=True)
        assert await _balance(720001) == 0

    async def test_zero_percent_disables_commission(self, user_factory, item_factory):
        await self._referred_customer(user_factory, item_factory)
        with patch('bot.misc.env.EnvKeys.REFERRAL_PERCENT', 0):
            await self._complete(720002)
        assert await _balance(720001) == 0

    async def test_customer_without_referrer(self, user_factory, item_factory):
        await user_factory(telegram_id=720003)
        await item_factory(name="Sofa", price=1000, stock=3)
        await self._complete(720003)
        async with Database().session() as s:
            assert (await s.execute(select(func.count()).select_from(ReferralEarnings))).scalar() == 0


class TestQueriesAndStats:

    async def test_get_order_is_scoped_to_its_owner(self, shop):
        order = await _place()
        assert (await get_order(order["id"], user_id=UID))["id"] == order["id"]
        assert await get_order(order["id"], user_id=UID + 1) is None
        assert await get_order(999999) is None

    async def test_user_order_list_newest_first_and_counted(self, shop):
        first = await _place()
        second = await _place()
        rows = await query_user_orders(UID)
        assert [o.id for o in rows] == [second["id"], first["id"]]
        assert await query_user_orders(UID, count_only=True) == 2
        assert await query_user_orders(UID + 1, count_only=True) == 0

    async def test_admin_order_list_filters(self, shop):
        a = await _place()
        b = await _place(payment_method=PaymentMethod.MIA)
        await mark_mia_paid(b["id"], UID)
        await set_order_status(a["id"], OrderStatus.CONFIRMED)

        assert [o.id for o in await query_orders(status=OrderStatus.CONFIRMED)] == [a["id"]]
        assert [o.id for o in await query_orders(status=OrderStatus.NEW)] == [b["id"]]
        assert [o.id for o in await query_orders(awaiting_payment_check=True)] == [b["id"]]
        assert await query_orders(count_only=True) == 2
        assert await query_orders(status=OrderStatus.SHIPPED, count_only=True) == 0

    async def test_stats_ignore_cancelled_orders(self, shop):
        keep = await _place(qty=2)
        gone = await _place()
        await cancel_order_transaction(gone["id"])
        today = datetime.date.today().isoformat()

        assert await select_all_orders() == Decimal("200.00")
        assert await select_count_bought_items() == 2
        assert await select_user_items(UID) == 1
        assert await select_today_orders_count(today) == 1
        assert keep["id"] != gone["id"]

    async def test_has_purchased_means_completed(self, shop):
        order = await _place()
        assert await has_purchased_item(UID, "Chair") is False
        await set_order_status(order["id"], OrderStatus.CONFIRMED)
        assert await has_purchased_item(UID, "Chair") is False
        await set_order_status(order["id"], OrderStatus.COMPLETED)
        assert await has_purchased_item(UID, "Chair") is True
        assert await has_purchased_item(UID, "Lamp") is False

    async def test_notify_ids_are_everyone_with_orders_permission(self, user_factory, role_factory):
        await user_factory(telegram_id=730001, role_id=2)                    # ADMIN
        await user_factory(telegram_id=730002, role_id=1)                    # plain USER
        custom = await role_factory("PACKER", Permission.USE | Permission.ORDERS_MANAGE)
        await user_factory(telegram_id=730003, role_id=custom)
        blind = await role_factory("CLERK", Permission.USE | Permission.CATALOG_MANAGE)
        await user_factory(telegram_id=730004, role_id=blind)

        assert sorted(await get_order_notify_ids()) == [730001, 730003]


class TestStock:

    async def test_set_and_adjust(self, shop):
        assert await set_item_stock("Chair", 9) == (True, 5, 9)
        assert await adjust_item_stock("Chair", -4) == (True, 9, 5)
        assert await adjust_item_stock("Chair", 3) == (True, 5, 8)
        assert await select_item_stock("Chair") == 8

    async def test_stock_never_goes_negative(self, shop):
        assert await adjust_item_stock("Chair", -100) == (True, 5, 0)
        assert await set_item_stock("Chair", -3) == (True, 0, 0)

    async def test_unknown_item(self, shop):
        assert await set_item_stock("Nope", 1) == (False, 0, 0)
        assert await adjust_item_stock("Nope", 1) == (False, 0, 0)
        assert await select_item_stock("Nope") == 0

    async def test_database_refuses_negative_stock(self, shop):
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            async with Database().session() as s:
                await s.execute(sa_update(Goods).where(Goods.name == "Chair").values(stock=-1))
