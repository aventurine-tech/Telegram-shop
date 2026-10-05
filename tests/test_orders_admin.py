"""Admin orders console: lists, order card, payment checks, status moves, cancellation."""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramBadRequest

from bot.database.methods.create import add_to_cart
from bot.database.methods.orders import create_order_transaction, get_order, mark_mia_paid
from bot.database.methods.read import select_item_stock
from bot.database.models import Permission
from bot.database.models.main import Fulfillment, PaymentMethod, PaymentStatus, OrderStatus
from bot.filters import HasPermissionFilter
from bot.handlers.admin import orders_management as om
from bot.handlers.admin import user_management as um
from bot.handlers.admin.main import console_callback_handler
from bot.keyboards.inline import admin_console_keyboard
from bot.keyboards.orders_admin import (
    order_card_keyboard, cancel_confirm_keyboard, orders_menu_keyboard, ctx_suffix, parse_ctx,
)
from bot.states import OrdersAdminFSM

ADMIN = 995000


def _cbs(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]


def _edit_args(call):
    args, kwargs = call.message.edit_text.call_args
    return args[0], kwargs


@pytest.fixture
def notify():
    """Capture customer notices and restock fan-outs instead of sending them."""
    with patch.object(om, "notify_customer", new_callable=AsyncMock) as n, \
            patch.object(om, "_notify_restock_safe", new_callable=AsyncMock) as r:
        n.restock = r
        yield n


@pytest.fixture
async def shop(user_factory, item_factory):
    await user_factory(telegram_id=995100, balance=1000)
    await item_factory(name="Lamp", price=100, stock=10)
    return 995100


async def _place(user_id, *, method=PaymentMethod.COD, qty=1, use_balance=False, **over):
    await add_to_cart(user_id, "Lamp", quantity=qty)
    kw = dict(fulfillment=Fulfillment.PICKUP, customer_name="Ann", phone="123456",
              address=None, comment=None, payment_method=method)
    if use_balance:
        kw["use_balance"] = True
    kw.update(over)
    ok, code, order = await create_order_transaction(user_id, **kw)
    assert ok, code
    return order


class TestPermissions:

    def test_every_handler_requires_the_orders_permission(self):
        handlers = om.router.callback_query.handlers + om.router.message.handlers
        assert handlers
        for h in handlers:
            perms = [f.callback for f in h.filters if isinstance(f.callback, HasPermissionFilter)]
            assert perms and perms[0].permission == Permission.ORDERS_MANAGE, h.callback.__name__


class TestCallbackContext:

    def test_suffix_and_parse_roundtrip(self):
        assert ctx_suffix("new", 3) == ":new:3"
        assert parse_ctx(["new", "3"]) == ("new", 3)

    @pytest.mark.parametrize("parts", [[], ["new"], ["bogus", "1"], ["new", "x"]])
    def test_malformed_context_falls_back_to_the_menu(self, parts):
        assert parse_ctx(parts) == ("", 0)
        assert ctx_suffix("bogus", 1) == ""


class TestMenuAndLists:

    async def test_menu_shows_counts_of_what_needs_attention(self, shop, make_callback_query, fsm_context):
        await _place(shop)
        mia = await _place(shop, method=PaymentMethod.MIA)
        await mark_mia_paid(mia["id"], shop)
        call = make_callback_query(data="orders_mgmt", user_id=ADMIN)

        await om.orders_menu_handler(call, fsm_context)

        _, kwargs = _edit_args(call)
        labels = [b.text for row in kwargs["reply_markup"].inline_keyboard for b in row]
        assert any("(2)" in t for t in labels)   # two new orders
        assert any("(1)" in t for t in labels)   # one transfer to check
        assert _cbs(kwargs["reply_markup"]) == [
            "ords_new_0", "ords_chk_0", "ords_cnf_0", "ords_shp_0", "ords_cmp_0", "ords_can_0",
            "ord_find", "console",
        ]

    async def test_empty_list(self, make_callback_query):
        call = make_callback_query(data="ords_new_0", user_id=ADMIN)
        await om.orders_list_handler(call)
        assert "list.empty" in _edit_args(call)[0]

    async def test_list_opens_orders_with_a_way_back(self, shop, make_callback_query):
        order = await _place(shop)
        call = make_callback_query(data="ords_new_0", user_id=ADMIN)

        await om.orders_list_handler(call)

        text, kwargs = _edit_args(call)
        assert "list.new.title" in text
        assert f"ord:{order['id']}:new:0" in _cbs(kwargs["reply_markup"])

    async def test_check_list_holds_only_claimed_mia_payments(self, shop, make_callback_query):
        await _place(shop)
        mia = await _place(shop, method=PaymentMethod.MIA)
        await mark_mia_paid(mia["id"], shop)
        call = make_callback_query(data="ords_chk_0", user_id=ADMIN)

        await om.orders_list_handler(call)

        cbs = _cbs(_edit_args(call)[1]["reply_markup"])
        assert [c for c in cbs if c.startswith("ord:")] == [f"ord:{mia['id']}:chk:0"]

    async def test_bad_payload_is_rejected(self, make_callback_query):
        call = make_callback_query(data="ords_nope_0", user_id=ADMIN)
        await om.orders_list_handler(call)
        call.answer.assert_awaited_once()
        call.message.edit_text.assert_not_called()


class TestOrderCard:

    async def test_card_shows_the_order_and_actions(self, shop, make_callback_query, fsm_context):
        order = await _place(shop, qty=2)
        call = make_callback_query(data=f"ord:{order['id']}:new:0", user_id=ADMIN)

        await om.order_card_handler(call, fsm_context)

        text, kwargs = _edit_args(call)
        assert f"#{order['id']}" in text or str(order["id"]) in text
        cbs = _cbs(kwargs["reply_markup"])
        assert f"ord_st:{order['id']}:cnf:new:0" in cbs
        assert f"ord_cx:{order['id']}:new:0" in cbs
        assert cbs[-1] == "ords_new_0"

    async def test_card_from_a_notification_goes_back_to_the_menu(self, shop, make_callback_query,
                                                                  fsm_context):
        order = await _place(shop)
        call = make_callback_query(data=f"ord:{order['id']}", user_id=ADMIN)

        await om.order_card_handler(call, fsm_context)

        assert _cbs(_edit_args(call)[1]["reply_markup"])[-1] == "orders_mgmt"

    async def test_unknown_order(self, make_callback_query, fsm_context):
        call = make_callback_query(data="ord:424242", user_id=ADMIN)
        await om.order_card_handler(call, fsm_context)
        call.answer.assert_awaited_once()
        assert call.answer.call_args[1]["show_alert"] is True

    async def test_photo_alert_falls_back_to_a_new_message(self, shop, make_callback_query, fsm_context):
        order = await _place(shop)
        call = make_callback_query(data=f"ord:{order['id']}", user_id=ADMIN)
        call.message.edit_text.side_effect = TelegramBadRequest(
            method=MagicMock(), message="Bad Request: there is no text in the message to edit")

        await om.order_card_handler(call, fsm_context)

        call.message.answer.assert_awaited_once()

    async def test_unchanged_card_is_not_duplicated(self, shop, make_callback_query, fsm_context):
        order = await _place(shop)
        call = make_callback_query(data=f"ord:{order['id']}", user_id=ADMIN)
        call.message.edit_text.side_effect = TelegramBadRequest(
            method=MagicMock(), message="Bad Request: message is not modified")

        await om.order_card_handler(call, fsm_context)

        call.message.answer.assert_not_called()


class TestCardKeyboardPerState:

    async def test_cod_new_order(self, shop):
        order = await _place(shop)
        cbs = _cbs(order_card_keyboard(order))
        assert cbs == [f"ord_st:{order['id']}:cnf", f"ord_cx:{order['id']}", "orders_mgmt"]

    async def test_mia_awaiting_payment_can_be_confirmed_but_not_accepted(self, shop):
        order = await _place(shop, method=PaymentMethod.MIA)
        cbs = _cbs(order_card_keyboard(order))
        assert f"ord_mia_ok:{order['id']}" in cbs
        assert f"ord_mia_no:{order['id']}" not in cbs
        assert not any(c.startswith("ord_st:") for c in cbs)

    async def test_mia_claim_offers_both_verdicts_and_the_screenshot(self, shop):
        order = await _place(shop, method=PaymentMethod.MIA)
        await mark_mia_paid(order["id"], shop, "file123")
        cbs = _cbs(order_card_keyboard(await get_order(order["id"])))
        assert cbs[:3] == [f"ord_mia_ok:{order['id']}", f"ord_mia_no:{order['id']}",
                           f"ord_proof:{order['id']}"]

    async def test_confirmed_order_can_ship_or_complete(self, shop):
        order = await _place(shop)
        order["status"] = OrderStatus.CONFIRMED
        cbs = _cbs(order_card_keyboard(order))
        assert f"ord_st:{order['id']}:shp" in cbs and f"ord_st:{order['id']}:cmp" in cbs
        assert f"ord_st:{order['id']}:cnf" not in cbs

    async def test_shipped_order_can_only_complete(self, shop):
        order = await _place(shop)
        order["status"] = OrderStatus.SHIPPED
        cbs = _cbs(order_card_keyboard(order))
        assert f"ord_st:{order['id']}:cmp" in cbs
        assert f"ord_st:{order['id']}:shp" not in cbs

    @pytest.mark.parametrize("status", [OrderStatus.COMPLETED, OrderStatus.CANCELLED])
    async def test_finished_order_has_no_actions(self, shop, status):
        order = await _place(shop)
        order["status"] = status
        assert _cbs(order_card_keyboard(order)) == ["orders_mgmt"]

    async def test_contact_link_points_at_the_customer(self, shop):
        order = await _place(shop)
        urls = [b.url for row in order_card_keyboard(order).inline_keyboard for b in row if b.url]
        assert urls == [f"tg://user?id={shop}"]

    async def test_callback_data_fits_telegram_limit(self, shop):
        order = await _place(shop)
        order["id"] = 2_000_000_000
        for markup in (order_card_keyboard(order, "chk", 999), cancel_confirm_keyboard(order["id"], "chk", 999),
                       orders_menu_keyboard(5, 5)):
            assert all(len(c.encode()) <= 64 for c in _cbs(markup))


class TestMiaVerdicts:

    async def test_confirm_accepts_the_order_and_tells_the_customer(self, shop, make_callback_query, notify):
        order = await _place(shop, method=PaymentMethod.MIA)
        await mark_mia_paid(order["id"], shop)
        call = make_callback_query(data=f"ord_mia_ok:{order['id']}", user_id=ADMIN)

        await om.mia_confirm_handler(call)

        done = await get_order(order["id"])
        assert (done["status"], done["payment_status"]) == (OrderStatus.CONFIRMED, PaymentStatus.PAID)
        assert notify.await_args[0][2] == "payment_confirmed"
        assert "done.payment_confirmed" in _edit_args(call)[0]

    async def test_confirm_works_before_the_customer_taps_paid(self, shop, make_callback_query, notify):
        order = await _place(shop, method=PaymentMethod.MIA)
        call = make_callback_query(data=f"ord_mia_ok:{order['id']}:new:0", user_id=ADMIN)

        await om.mia_confirm_handler(call)

        assert (await get_order(order["id"]))["payment_status"] == PaymentStatus.PAID
        assert _cbs(_edit_args(call)[1]["reply_markup"])[-1] == "ords_new_0"

    async def test_reject_sends_the_order_back_to_awaiting_payment(self, shop, make_callback_query, notify):
        order = await _place(shop, method=PaymentMethod.MIA)
        await mark_mia_paid(order["id"], shop, "file1")
        call = make_callback_query(data=f"ord_mia_no:{order['id']}", user_id=ADMIN)

        await om.mia_reject_handler(call)

        again = await get_order(order["id"])
        assert again["payment_status"] == PaymentStatus.AWAITING_PAYMENT
        assert again["payment_proof"] is None
        assert notify.await_args[0][2] == "payment_rejected"

    async def test_second_staff_member_gets_an_alert_not_a_duplicate_notice(self, shop,
                                                                           make_callback_query, notify):
        order = await _place(shop, method=PaymentMethod.MIA)
        await mark_mia_paid(order["id"], shop)
        await om.mia_confirm_handler(make_callback_query(data=f"ord_mia_ok:{order['id']}", user_id=ADMIN))
        notify.reset_mock()

        late = make_callback_query(data=f"ord_mia_no:{order['id']}", user_id=ADMIN + 1)
        await om.mia_reject_handler(late)

        late.answer.assert_awaited_once()
        assert late.answer.call_args[1]["show_alert"] is True
        notify.assert_not_awaited()
        assert (await get_order(order["id"]))["payment_status"] == PaymentStatus.PAID

    async def test_cod_order_is_not_an_mia_order(self, shop, make_callback_query, notify):
        order = await _place(shop)
        call = make_callback_query(data=f"ord_mia_ok:{order['id']}", user_id=ADMIN)

        await om.mia_confirm_handler(call)

        assert "err.not_mia" in call.answer.call_args[0][0]
        notify.assert_not_awaited()


class TestStatusMoves:

    @pytest.mark.parametrize("code,status,notice", [
        ("cnf", OrderStatus.CONFIRMED, "confirmed"),
    ])
    async def test_confirm(self, shop, make_callback_query, notify, code, status, notice):
        order = await _place(shop)
        call = make_callback_query(data=f"ord_st:{order['id']}:{code}", user_id=ADMIN)

        await om.order_status_handler(call)

        assert (await get_order(order["id"]))["status"] == status
        assert notify.await_args[0][2] == notice

    async def test_full_lifecycle_notifies_at_every_step(self, shop, make_callback_query, notify):
        order = await _place(shop)
        for code in ("cnf", "shp", "cmp"):
            await om.order_status_handler(make_callback_query(data=f"ord_st:{order['id']}:{code}",
                                                              user_id=ADMIN))

        done = await get_order(order["id"])
        assert done["status"] == OrderStatus.COMPLETED
        assert done["payment_status"] == PaymentStatus.PAID   # cash collected on hand-over
        assert [c[0][2] for c in notify.await_args_list] == ["confirmed", "shipped", "completed"]

    async def test_unverified_mia_order_is_blocked(self, shop, make_callback_query, notify):
        order = await _place(shop, method=PaymentMethod.MIA)
        call = make_callback_query(data=f"ord_st:{order['id']}:cnf", user_id=ADMIN)

        await om.order_status_handler(call)

        assert "payment_not_confirmed" in call.answer.call_args[0][0]
        assert (await get_order(order["id"]))["status"] == OrderStatus.NEW
        notify.assert_not_awaited()

    async def test_skipping_a_step_is_refused(self, shop, make_callback_query, notify):
        order = await _place(shop)
        call = make_callback_query(data=f"ord_st:{order['id']}:shp", user_id=ADMIN)

        await om.order_status_handler(call)

        assert "invalid_transition" in call.answer.call_args[0][0]
        assert (await get_order(order["id"]))["status"] == OrderStatus.NEW

    @pytest.mark.parametrize("data", ["ord_st:abc:cnf", "ord_st:1", "ord_st:1:zzz", "ord_st"])
    async def test_malformed_payload(self, make_callback_query, notify, data):
        call = make_callback_query(data=data, user_id=ADMIN)
        await om.order_status_handler(call)
        call.answer.assert_awaited_once()
        notify.assert_not_awaited()


class TestCancel:

    async def test_cancel_asks_first(self, shop, make_callback_query):
        order = await _place(shop)
        call = make_callback_query(data=f"ord_cx:{order['id']}:new:1", user_id=ADMIN)

        await om.order_cancel_ask_handler(call)

        text, kwargs = _edit_args(call)
        assert "cancel.confirm" in text and "refund_warning" not in text
        assert _cbs(kwargs["reply_markup"]) == [f"ord_cxy:{order['id']}:new:1", f"ord:{order['id']}:new:1"]
        assert (await get_order(order["id"]))["status"] == OrderStatus.NEW   # nothing happened yet

    async def test_paid_mia_cancel_warns_about_the_manual_refund(self, shop, make_callback_query):
        order = await _place(shop, method=PaymentMethod.MIA, qty=2)
        await mark_mia_paid(order["id"], shop)
        call = make_callback_query(data=f"ord_cx:{order['id']}", user_id=ADMIN)

        await om.order_cancel_ask_handler(call)

        text = _edit_args(call)[0]
        assert "refund_warning" in text and "200" in text

    async def test_cancel_restocks_notifies_and_audits(self, shop, make_callback_query, notify):
        order = await _place(shop, qty=4)
        assert await select_item_stock("Lamp") == 6
        call = make_callback_query(data=f"ord_cxy:{order['id']}", user_id=ADMIN)

        with patch.object(om, "log_audit", new_callable=AsyncMock) as audit:
            await om.order_cancel_handler(call)

        assert await select_item_stock("Lamp") == 10
        assert (await get_order(order["id"]))["status"] == OrderStatus.CANCELLED
        assert notify.await_args[0][2] == "cancelled"
        assert audit.await_args[0][0] == "admin_cancel_order"
        assert audit.await_args[1]["user_id"] == ADMIN
        assert "refund_manual" not in _edit_args(call)[0]     # cash was never collected

    async def test_cancel_from_sold_out_announces_the_restock(self, shop, item_factory, make_callback_query,
                                                              notify):
        order = await _place(shop, qty=10)
        assert await select_item_stock("Lamp") == 0
        call = make_callback_query(data=f"ord_cxy:{order['id']}", user_id=ADMIN)

        await om.order_cancel_handler(call)

        notify.restock.assert_awaited_once_with(call.message.bot, "Lamp")

    async def test_paid_order_is_flagged_for_a_manual_refund(self, shop, make_callback_query, notify):
        order = await _place(shop, method=PaymentMethod.MIA, qty=2)
        await mark_mia_paid(order["id"], shop)
        call = make_callback_query(data=f"ord_cxy:{order['id']}", user_id=ADMIN)

        await om.order_cancel_handler(call)

        assert (await get_order(order["id"]))["payment_status"] == PaymentStatus.REFUNDED
        assert "refund_manual" in _edit_args(call)[0]

    async def test_balance_part_is_refunded_automatically(self, shop, make_callback_query, notify):
        from bot.database.methods.read import check_user
        order = await _place(shop, qty=3, use_balance=True)
        spent = Decimal(str(order["balance_used"]))
        assert spent > 0
        before = Decimal(str((await check_user(shop))["balance"]))
        call = make_callback_query(data=f"ord_cxy:{order['id']}", user_id=ADMIN)

        await om.order_cancel_handler(call)

        assert Decimal(str((await check_user(shop))["balance"])) == before + spent

    async def test_finished_order_cannot_be_cancelled(self, shop, make_callback_query, notify):
        order = await _place(shop)
        for code in ("cnf", "cmp"):
            await om.order_status_handler(make_callback_query(data=f"ord_st:{order['id']}:{code}",
                                                              user_id=ADMIN))
        notify.reset_mock()
        call = make_callback_query(data=f"ord_cxy:{order['id']}", user_id=ADMIN)

        await om.order_cancel_handler(call)

        assert "not_cancellable" in call.answer.call_args[0][0]
        notify.assert_not_awaited()
        assert await select_item_stock("Lamp") == 9


class TestProof:

    async def test_sends_the_screenshot(self, shop, make_callback_query, mock_bot):
        order = await _place(shop, method=PaymentMethod.MIA)
        await mark_mia_paid(order["id"], shop, "FILEID")
        call = make_callback_query(data=f"ord_proof:{order['id']}", user_id=ADMIN)
        call.message.chat.id = 555

        await om.order_proof_handler(call)

        assert mock_bot.send_photo.await_args[0][:2] == (555, "FILEID")

    async def test_no_screenshot(self, shop, make_callback_query, mock_bot):
        order = await _place(shop, method=PaymentMethod.MIA)
        call = make_callback_query(data=f"ord_proof:{order['id']}", user_id=ADMIN)

        await om.order_proof_handler(call)

        assert "no_proof" in call.answer.call_args[0][0]
        mock_bot.send_photo.assert_not_awaited()

    async def test_stale_file_id_is_reported(self, shop, make_callback_query, mock_bot):
        order = await _place(shop, method=PaymentMethod.MIA)
        await mark_mia_paid(order["id"], shop, "OLD")
        mock_bot.send_photo.side_effect = TelegramBadRequest(method=MagicMock(), message="wrong file id")
        call = make_callback_query(data=f"ord_proof:{order['id']}", user_id=ADMIN)

        await om.order_proof_handler(call)

        assert "proof_unavailable" in call.answer.call_args[0][0]


class TestFindOrder:

    async def test_prompt_sets_the_state(self, make_callback_query, fsm_context):
        await om.order_find_handler(make_callback_query(data="ord_find", user_id=ADMIN), fsm_context)
        assert await fsm_context.get_state() == OrdersAdminFSM.waiting_order_id

    @pytest.mark.parametrize("text", ["#{id}", "{id}", " {id} "])
    async def test_shows_the_order(self, shop, make_message, fsm_context, text):
        order = await _place(shop)
        await fsm_context.set_state(OrdersAdminFSM.waiting_order_id)
        msg = make_message(text=text.format(id=order["id"]), user_id=ADMIN)

        await om.order_find_process(msg, fsm_context)

        assert f"ord_cx:{order['id']}" in _cbs(msg.answer.call_args[1]["reply_markup"])
        assert await fsm_context.get_state() is None

    @pytest.mark.parametrize("text", ["abc", "", "-1", "1" * 12])
    async def test_bad_number_keeps_the_prompt(self, make_message, fsm_context, text):
        await fsm_context.set_state(OrdersAdminFSM.waiting_order_id)
        await om.order_find_process(make_message(text=text, user_id=ADMIN), fsm_context)
        assert await fsm_context.get_state() == OrdersAdminFSM.waiting_order_id

    async def test_unknown_order(self, make_message, fsm_context):
        await fsm_context.set_state(OrdersAdminFSM.waiting_order_id)
        msg = make_message(text="999999", user_id=ADMIN)
        await om.order_find_process(msg, fsm_context)
        assert "err.not_found" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() == OrdersAdminFSM.waiting_order_id


class TestUserOrdersFromProfile:

    async def test_profile_shows_the_orders_button_only_with_the_permission(self, shop, mock_bot):
        await _place(shop)
        with_perm = await um._build_user_profile(mock_bot, shop, Permission.USERS_MANAGE | Permission.ORDERS_MANAGE)
        without = await um._build_user_profile(mock_bot, shop, Permission.USERS_MANAGE)

        def cbs(result):
            return _cbs(result[1])

        assert f"user-orders_{shop}" in cbs(with_perm)
        assert f"user-orders_{shop}" not in cbs(without)

    async def test_list_and_open_an_order(self, shop, make_callback_query):
        order = await _place(shop)
        call = make_callback_query(data=f"user-orders_{shop}", user_id=ADMIN)

        await um.user_orders_callback_handler(call, MagicMock())

        cbs = _cbs(_edit_args(call)[1]["reply_markup"])
        assert f"uord:{order['id']}:{shop}:0" in cbs

        card = make_callback_query(data=f"uord:{order['id']}:{shop}:0", user_id=ADMIN)
        await um.user_order_card_handler(card)

        assert _cbs(_edit_args(card)[1]["reply_markup"])[-1] == f"user-orders-page_{shop}_0"

    async def test_empty_list(self, user_factory, make_callback_query):
        await user_factory(telegram_id=995200)
        call = make_callback_query(data="user-orders_995200", user_id=ADMIN)
        await um.user_orders_callback_handler(call, MagicMock())
        assert "orders.empty" in _edit_args(call)[0]

    async def test_order_of_another_customer_is_not_shown(self, shop, user_factory, make_callback_query):
        await user_factory(telegram_id=995201)
        order = await _place(shop)
        call = make_callback_query(data=f"uord:{order['id']}:995201:0", user_id=ADMIN)

        await um.user_order_card_handler(call)

        call.answer.assert_awaited_once()
        call.message.edit_text.assert_not_called()

    async def test_handlers_need_both_permissions(self):
        for fn in (um.user_orders_callback_handler, um.user_orders_pagination_handler, um.user_order_card_handler):
            handler = next(h for h in um.router.callback_query.handlers if h.callback is fn)
            perm = next(f.callback for f in handler.filters if isinstance(f.callback, HasPermissionFilter))
            assert perm.permission == Permission.USERS_MANAGE | Permission.ORDERS_MANAGE


class TestConsoleEntry:

    def test_orders_button_requires_the_permission(self):
        with_perm = _cbs(admin_console_keyboard(role=Permission.USE | Permission.ORDERS_MANAGE))
        without = _cbs(admin_console_keyboard(role=Permission.USE | Permission.CATALOG_MANAGE))
        assert "orders_mgmt" in with_perm
        assert "orders_mgmt" not in without

    def test_badge_counts_new_orders(self):
        markup = admin_console_keyboard(role=Permission.ORDERS_MANAGE, new_orders=7)
        button = next(b for row in markup.inline_keyboard for b in row if b.callback_data == "orders_mgmt")
        assert "(7)" in button.text

    async def test_console_passes_the_live_count(self, shop, make_callback_query, fsm_context):
        await _place(shop)
        await _place(shop)
        call = make_callback_query(data="console", user_id=ADMIN)

        with patch("bot.handlers.admin.main.check_role_cached", new_callable=AsyncMock,
                   return_value=Permission.USE | Permission.ORDERS_MANAGE):
            await console_callback_handler(call, fsm_context)

        markup = call.message.edit_text.call_args[1]["reply_markup"]
        button = next(b for row in markup.inline_keyboard for b in row if b.callback_data == "orders_mgmt")
        assert "(2)" in button.text
