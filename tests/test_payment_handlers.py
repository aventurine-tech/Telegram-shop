"""Checkout (fulfilment -> contact -> payment -> summary -> order) and the MIA "I've paid" flow."""
import pytest
from decimal import Decimal
from unittest.mock import patch, AsyncMock, MagicMock

from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove

from bot.database.methods.create import add_to_cart
from bot.database.methods.orders import get_order, create_order_transaction
from bot.database.methods.read import check_user, get_cart_count, select_item_stock
from bot.database.main import Database
from bot.handlers.user.checkout import (
    cart_checkout_handler, checkout_cancel_handler, fulfillment_chosen_handler,
    name_from_telegram_handler, name_text_handler, phone_contact_handler, phone_text_handler,
    address_handler, comment_handler, skip_comment_handler, toggle_balance_handler,
    payment_chosen_handler, back_to_payment_handler, confirm_order_handler,
    stale_checkout_button_handler, mia_info_handler, mia_paid_handler, mia_skip_proof_handler,
    mia_proof_photo_handler, mia_proof_other_handler, mia_instructions,
)
from bot.states import CheckoutFSM


def _cbs(call_or_msg_mock, method="edit_text"):
    """Callback data of the keyboard attached to the last render."""
    markup = getattr(call_or_msg_mock, method).call_args[1]["reply_markup"]
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _text(mock, method="edit_text"):
    return getattr(mock, method).call_args[0][0]


async def _cart(user_id, item_name="Mug", price=40, qty=1, stock=5, item_factory=None):
    await item_factory(name=item_name, price=price, stock=stock)
    await add_to_cart(user_id, item_name, quantity=qty)


class TestCheckoutEntry:

    async def test_empty_cart_is_refused(self, make_callback_query, fsm_context, user_factory):
        await user_factory(telegram_id=700001)
        call = make_callback_query(data="cart_checkout", user_id=700001)

        await cart_checkout_handler(call, fsm_context)

        assert call.answer.call_args[1].get("show_alert") is True
        assert await fsm_context.get_state() is None

    async def test_both_fulfilments_asks_how_to_receive(self, make_callback_query, fsm_context,
                                                        user_factory, item_factory):
        await user_factory(telegram_id=700002)
        await _cart(700002, qty=2, price=40, item_factory=item_factory)
        call = make_callback_query(data="cart_checkout", user_id=700002)

        await cart_checkout_handler(call, fsm_context)

        assert await fsm_context.get_state() == CheckoutFSM.choosing_fulfillment
        assert {"co_ful:delivery", "co_ful:pickup"} <= set(_cbs(call.message))
        assert (await fsm_context.get_data())["co_total"] == "80.00"

    async def test_single_fulfilment_skips_the_choice(self, make_callback_query, fsm_context,
                                                      user_factory, item_factory):
        await user_factory(telegram_id=700003)
        await _cart(700003, item_factory=item_factory)
        call = make_callback_query(data="cart_checkout", user_id=700003)

        with patch('bot.handlers.user.checkout.available_fulfillments', return_value=["pickup"]):
            await cart_checkout_handler(call, fsm_context)

        assert (await fsm_context.get_data())["co_ful"] == "pickup"
        assert await fsm_context.get_state() == CheckoutFSM.waiting_name
        assert "co_name_tg" in _cbs(call.message)

    async def test_nothing_enabled_blocks_checkout(self, make_callback_query, fsm_context,
                                                   user_factory, item_factory):
        await user_factory(telegram_id=700004)
        await _cart(700004, item_factory=item_factory)
        call = make_callback_query(data="cart_checkout", user_id=700004)

        with patch('bot.handlers.user.checkout.available_payment_methods', return_value=[]):
            await cart_checkout_handler(call, fsm_context)

        assert "checkout.unavailable" in call.answer.call_args[0][0]
        assert await fsm_context.get_state() is None

    async def test_cancel_returns_to_the_cart_and_clears_the_flow(self, make_callback_query, fsm_context,
                                                                  user_factory, item_factory):
        await user_factory(telegram_id=700005)
        await _cart(700005, item_factory=item_factory)
        await fsm_context.set_state(CheckoutFSM.waiting_name)
        await fsm_context.update_data(co_name="x")

        call = make_callback_query(data="co_cancel", user_id=700005)
        await checkout_cancel_handler(call, fsm_context)

        assert await fsm_context.get_state() is None
        assert (await fsm_context.get_data()) == {}
        assert "cart.title" in _text(call.message)


class TestContactSteps:

    async def test_unavailable_fulfilment_is_refused(self, make_callback_query, fsm_context):
        await fsm_context.set_state(CheckoutFSM.choosing_fulfillment)
        call = make_callback_query(data="co_ful:delivery", user_id=700010)

        with patch('bot.handlers.user.checkout.available_fulfillments', return_value=["pickup"]):
            await fulfillment_chosen_handler(call, fsm_context)

        assert call.answer.call_args[1].get("show_alert") is True
        assert "co_ful" not in await fsm_context.get_data()

    async def test_fulfilment_leads_to_name(self, make_callback_query, fsm_context):
        await fsm_context.set_state(CheckoutFSM.choosing_fulfillment)
        call = make_callback_query(data="co_ful:delivery", user_id=700011, first_name="Ana")

        await fulfillment_chosen_handler(call, fsm_context)

        assert (await fsm_context.get_data())["co_ful"] == "delivery"
        assert await fsm_context.get_state() == CheckoutFSM.waiting_name
        assert "co_name_tg" in _cbs(call.message)

    async def test_telegram_first_name_button(self, make_callback_query, fsm_context):
        await fsm_context.set_state(CheckoutFSM.waiting_name)
        call = make_callback_query(data="co_name_tg", user_id=700012, first_name="Ana")

        await name_from_telegram_handler(call, fsm_context)

        assert (await fsm_context.get_data())["co_name"] == "Ana"
        assert await fsm_context.get_state() == CheckoutFSM.waiting_phone
        # The prompt keyboard is locked in, then the phone prompt arrives as a new message with a contact button.
        call.message.edit_text.assert_called_once()
        markup = call.message.answer.call_args[1]["reply_markup"]
        assert isinstance(markup, ReplyKeyboardMarkup)
        assert markup.keyboard[0][0].request_contact is True

    async def test_typed_name_is_stored_trimmed(self, make_message, fsm_context):
        await fsm_context.set_state(CheckoutFSM.waiting_name)
        msg = make_message(text="  Ion Popescu ", user_id=700013)

        await name_text_handler(msg, fsm_context)

        assert (await fsm_context.get_data())["co_name"] == "Ion Popescu"
        assert await fsm_context.get_state() == CheckoutFSM.waiting_phone

    @pytest.mark.parametrize("text", ["", "x" * 101, "two\nlines"])
    async def test_bad_name_keeps_the_step(self, make_message, fsm_context, text):
        await fsm_context.set_state(CheckoutFSM.waiting_name)
        msg = make_message(text=text, user_id=700014)

        await name_text_handler(msg, fsm_context)

        assert await fsm_context.get_state() == CheckoutFSM.waiting_name
        assert "co_name" not in await fsm_context.get_data()
        assert "checkout.name_invalid" in _text(msg, "answer")

    async def test_shared_contact_gets_a_plus(self, make_message, fsm_context):
        await fsm_context.set_state(CheckoutFSM.waiting_phone)
        await fsm_context.update_data(co_ful="pickup")
        msg = make_message(text=None, user_id=700015)
        msg.contact = MagicMock(phone_number="37369123456")

        await phone_contact_handler(msg, fsm_context)

        assert (await fsm_context.get_data())["co_phone"] == "+37369123456"

    async def test_phone_step_takes_the_contact_keyboard_away(self, make_message, fsm_context):
        await fsm_context.set_state(CheckoutFSM.waiting_phone)
        await fsm_context.update_data(co_ful="pickup")
        msg = make_message(text="069 123 456", user_id=700016)

        await phone_text_handler(msg, fsm_context)

        first = msg.answer.call_args_list[0]
        assert isinstance(first[1]["reply_markup"], ReplyKeyboardRemove)

    @pytest.mark.parametrize("text", ["call me", "12", "+" * 5, "1" * 25])
    async def test_bad_phone_keeps_the_step(self, make_message, fsm_context, text):
        await fsm_context.set_state(CheckoutFSM.waiting_phone)
        msg = make_message(text=text, user_id=700017)

        await phone_text_handler(msg, fsm_context)

        assert await fsm_context.get_state() == CheckoutFSM.waiting_phone
        assert "co_phone" not in await fsm_context.get_data()

    async def test_delivery_asks_for_an_address_pickup_skips_it(self, make_message, fsm_context):
        await fsm_context.set_state(CheckoutFSM.waiting_phone)
        await fsm_context.update_data(co_ful="delivery")
        await phone_text_handler(make_message(text="069 123 456", user_id=700018), fsm_context)
        assert await fsm_context.get_state() == CheckoutFSM.waiting_address

        await fsm_context.clear()
        await fsm_context.set_state(CheckoutFSM.waiting_phone)
        await fsm_context.update_data(co_ful="pickup")
        await phone_text_handler(make_message(text="069 123 456", user_id=700018), fsm_context)
        assert await fsm_context.get_state() == CheckoutFSM.waiting_comment

    async def test_address_is_validated_and_leads_to_comment(self, make_message, fsm_context):
        await fsm_context.set_state(CheckoutFSM.waiting_address)

        too_long = make_message(text="a" * 501, user_id=700019)
        await address_handler(too_long, fsm_context)
        assert await fsm_context.get_state() == CheckoutFSM.waiting_address

        ok = make_message(text="Str. Mare 1, ap. 4", user_id=700019)
        await address_handler(ok, fsm_context)
        assert (await fsm_context.get_data())["co_address"] == "Str. Mare 1, ap. 4"
        assert await fsm_context.get_state() == CheckoutFSM.waiting_comment

    async def test_delivery_info_is_shown_with_the_address_prompt(self, make_message, fsm_context):
        await fsm_context.set_state(CheckoutFSM.waiting_phone)
        await fsm_context.update_data(co_ful="delivery")

        with patch('bot.handlers.user.checkout.EnvKeys') as env:
            env.DELIVERY_INFO = "Free over 500 <MDL>"
            msg = make_message(text="069 123 456", user_id=700020)
            await phone_text_handler(msg, fsm_context)

        prompt = msg.answer.call_args_list[-1][0][0]
        assert "checkout.delivery_info" in prompt
        assert "&lt;MDL&gt;" in prompt                      # shop-provided text is escaped too

    async def test_comment_too_long_is_refused(self, make_message, fsm_context, user_factory):
        await fsm_context.set_state(CheckoutFSM.waiting_comment)
        msg = make_message(text="c" * 501, user_id=700021)

        await comment_handler(msg, fsm_context)

        assert await fsm_context.get_state() == CheckoutFSM.waiting_comment
        assert "co_comment" not in await fsm_context.get_data()


class TestPaymentStep:

    async def _at_comment(self, fsm_context, user_id, total="40.00", ful="pickup"):
        await fsm_context.set_state(CheckoutFSM.waiting_comment)
        await fsm_context.update_data(co_ful=ful, co_name="Ana", co_phone="+37369123456", co_total=total)

    async def test_skipping_the_comment_opens_payment(self, make_callback_query, fsm_context,
                                                      user_factory, item_factory):
        await user_factory(telegram_id=700030)
        await self._at_comment(fsm_context, 700030)
        call = make_callback_query(data="co_skip_comment", user_id=700030)

        await skip_comment_handler(call, fsm_context)

        assert await fsm_context.get_state() == CheckoutFSM.choosing_payment
        assert {"co_pay:mia", "co_pay:cod"} <= set(_cbs(call.message))
        assert "co_balance" not in _cbs(call.message)            # no balance, no toggle

    async def test_typed_comment_is_stored(self, make_message, fsm_context, user_factory):
        await user_factory(telegram_id=700031)
        await self._at_comment(fsm_context, 700031)

        await comment_handler(make_message(text="Ring twice", user_id=700031), fsm_context)

        assert (await fsm_context.get_data())["co_comment"] == "Ring twice"
        assert await fsm_context.get_state() == CheckoutFSM.choosing_payment

    async def test_only_enabled_methods_are_offered(self, make_callback_query, fsm_context, user_factory):
        await user_factory(telegram_id=700032)
        await self._at_comment(fsm_context, 700032)
        call = make_callback_query(data="co_skip_comment", user_id=700032)

        with patch('bot.handlers.user.checkout.available_payment_methods', return_value=["cod"]):
            await skip_comment_handler(call, fsm_context)

        cbs = _cbs(call.message)
        assert "co_pay:cod" in cbs and "co_pay:mia" not in cbs

    async def test_balance_toggle_appears_with_a_balance_and_flips(self, make_callback_query, fsm_context,
                                                                   user_factory):
        await user_factory(telegram_id=700033, balance=10)
        await self._at_comment(fsm_context, 700033)
        await skip_comment_handler(make_callback_query(data="co_skip_comment", user_id=700033), fsm_context)

        call = make_callback_query(data="co_balance", user_id=700033)
        await toggle_balance_handler(call, fsm_context)

        assert (await fsm_context.get_data())["co_use_balance"] is True
        assert "checkout.payment_balance_applied" in _text(call.message)
        assert "checkout.payment_due" in _text(call.message)       # 10 of 40 covered: 30 still due
        assert "co_pay:cod" in _cbs(call.message)

        await toggle_balance_handler(make_callback_query(data="co_balance", user_id=700033), fsm_context)
        assert (await fsm_context.get_data())["co_use_balance"] is False

    async def test_toggle_without_balance_is_refused(self, make_callback_query, fsm_context, user_factory):
        await user_factory(telegram_id=700034, balance=0)
        await fsm_context.set_state(CheckoutFSM.choosing_payment)
        call = make_callback_query(data="co_balance", user_id=700034)

        await toggle_balance_handler(call, fsm_context)

        assert call.answer.call_args[1].get("show_alert") is True
        assert "co_use_balance" not in await fsm_context.get_data()

    async def test_balance_covering_everything_replaces_the_methods(self, make_callback_query, fsm_context,
                                                                    user_factory):
        await user_factory(telegram_id=700035, balance=100)
        await self._at_comment(fsm_context, 700035, total="40.00")
        await fsm_context.update_data(co_use_balance=True)

        await skip_comment_handler(make_callback_query(data="co_skip_comment", user_id=700035), fsm_context)

        # Re-render through the toggle path to inspect the keyboard.
        call = make_callback_query(data="co_balance", user_id=700035)
        await toggle_balance_handler(call, fsm_context)        # flips to off
        await toggle_balance_handler(call, fsm_context)        # and back on
        cbs = _cbs(call.message)
        assert "co_pay:balance" in cbs
        assert "co_pay:mia" not in cbs and "co_pay:cod" not in cbs

    async def test_unknown_method_is_refused(self, make_callback_query, fsm_context, user_factory):
        await user_factory(telegram_id=700036)
        await fsm_context.set_state(CheckoutFSM.choosing_payment)
        await fsm_context.update_data(co_total="40.00")
        call = make_callback_query(data="co_pay:bitcoin", user_id=700036)

        await payment_chosen_handler(call, fsm_context)

        assert call.answer.call_args[1].get("show_alert") is True
        assert "co_method" not in await fsm_context.get_data()

    async def test_balance_continue_is_refused_when_it_does_not_cover(self, make_callback_query, fsm_context,
                                                                      user_factory):
        await user_factory(telegram_id=700037, balance=5)
        await fsm_context.set_state(CheckoutFSM.choosing_payment)
        await fsm_context.update_data(co_total="40.00", co_use_balance=True, co_ful="pickup")
        call = make_callback_query(data="co_pay:balance", user_id=700037)

        await payment_chosen_handler(call, fsm_context)

        assert call.answer.call_args[1].get("show_alert") is True
        assert await fsm_context.get_state() == CheckoutFSM.choosing_payment


class TestSummary:

    async def _to_payment(self, fsm_context, ful="pickup", comment=None, address=None):
        await fsm_context.set_state(CheckoutFSM.choosing_payment)
        await fsm_context.update_data(
            co_ful=ful, co_name="Ana <b>", co_phone="+37369123456", co_total="999.00",
            co_comment=comment, co_address=address,
        )

    async def test_summary_shows_everything_and_recomputes_the_total(self, make_callback_query, fsm_context,
                                                                     user_factory, item_factory):
        await user_factory(telegram_id=700040)
        await _cart(700040, qty=2, price=40, item_factory=item_factory)
        await self._to_payment(fsm_context, ful="delivery", comment="Ring <twice>", address="Str 1")
        call = make_callback_query(data="co_pay:cod", user_id=700040)

        await payment_chosen_handler(call, fsm_context)

        text = _text(call.message)
        assert await fsm_context.get_state() == CheckoutFSM.confirming
        assert (await fsm_context.get_data())["co_total"] == "80.00"     # stale 999 replaced by the live cart
        assert "Mug" in text
        assert "Ana &lt;b&gt;" in text and "Ring &lt;twice&gt;" in text   # user text escaped
        assert "Str 1" in text
        assert {"co_confirm", "co_to_payment", "co_cancel"} <= set(_cbs(call.message))

    async def test_summary_shows_the_balance_split(self, make_callback_query, fsm_context,
                                                   user_factory, item_factory):
        await user_factory(telegram_id=700041, balance=30)
        await _cart(700041, qty=1, price=40, item_factory=item_factory)
        await self._to_payment(fsm_context)
        await fsm_context.update_data(co_use_balance=True)

        call = make_callback_query(data="co_pay:mia", user_id=700041)
        await payment_chosen_handler(call, fsm_context)

        text = _text(call.message)
        assert "order.line.balance_used" in text and "'amount': Decimal('30.00')" in text
        assert "order.line.due" in text and "'amount': Decimal('10.00')" in text

    async def test_summary_with_an_emptied_cart_sends_the_customer_back(self, make_callback_query, fsm_context,
                                                                        user_factory):
        await user_factory(telegram_id=700042)
        await self._to_payment(fsm_context)
        call = make_callback_query(data="co_pay:cod", user_id=700042)

        await payment_chosen_handler(call, fsm_context)

        assert "checkout.session_expired" in _text(call.message)
        assert await fsm_context.get_state() is None

    async def test_change_payment_goes_back(self, make_callback_query, fsm_context, user_factory,
                                            item_factory):
        await user_factory(telegram_id=700043)
        await _cart(700043, item_factory=item_factory)
        await self._to_payment(fsm_context)
        await fsm_context.set_state(CheckoutFSM.confirming)
        call = make_callback_query(data="co_to_payment", user_id=700043)

        await back_to_payment_handler(call, fsm_context)

        assert await fsm_context.get_state() == CheckoutFSM.choosing_payment


class TestPlacingTheOrder:

    async def _ready(self, fsm_context, *, ful="pickup", method="cod", total="40.00",
                     use_balance=False, address=None, comment=None):
        await fsm_context.set_state(CheckoutFSM.confirming)
        await fsm_context.update_data(
            co_ful=ful, co_name="Ana", co_phone="+37369123456", co_total=total, co_method=method,
            co_use_balance=use_balance, co_address=address, co_comment=comment,
        )

    async def test_cod_pickup_order(self, make_callback_query, fsm_context, user_factory, item_factory):
        await user_factory(telegram_id=700050)
        await _cart(700050, qty=2, price=20, stock=5, item_factory=item_factory)
        await self._ready(fsm_context, total="40.00")
        call = make_callback_query(data="co_confirm", user_id=700050)

        with patch('bot.handlers.user.checkout.notify_new_order', new_callable=AsyncMock) as notify:
            await confirm_order_handler(call, fsm_context)

        notify.assert_awaited_once()
        order = notify.await_args.args[1]
        stored = await get_order(order["id"], user_id=700050)
        assert stored["payment_method"] == "cod" and stored["status"] == "new"
        assert stored["customer_name"] == "Ana" and stored["phone"] == "+37369123456"
        assert await select_item_stock("Mug") == 3                 # stock reserved
        assert await get_cart_count(700050) == 0
        assert await fsm_context.get_state() is None
        assert "checkout.placed" in _text(call.message)
        assert f"my_order:{order['id']}" in _cbs(call.message)

    async def test_delivery_order_keeps_address_and_comment(self, make_callback_query, fsm_context,
                                                            user_factory, item_factory):
        await user_factory(telegram_id=700051)
        await _cart(700051, price=40, item_factory=item_factory)
        await self._ready(fsm_context, ful="delivery", address="Str. Mare 1", comment="Ring twice")
        call = make_callback_query(data="co_confirm", user_id=700051)

        with patch('bot.handlers.user.checkout.notify_new_order', new_callable=AsyncMock) as notify:
            await confirm_order_handler(call, fsm_context)

        stored = await get_order(notify.await_args.args[1]["id"], user_id=700051)
        assert stored["fulfillment"] == "delivery"
        assert stored["address"] == "Str. Mare 1" and stored["comment"] == "Ring twice"

    async def test_mia_order_shows_payment_instructions(self, make_callback_query, fsm_context,
                                                        user_factory, item_factory):
        await user_factory(telegram_id=700052)
        await _cart(700052, price=40, item_factory=item_factory)
        await self._ready(fsm_context, method="mia")
        call = make_callback_query(data="co_confirm", user_id=700052)

        with patch('bot.handlers.user.checkout.notify_new_order', new_callable=AsyncMock) as notify:
            await confirm_order_handler(call, fsm_context)

        order = notify.await_args.args[1]
        text = _text(call.message)
        assert "mia.title" in text and f"'id': {order['id']}" in text
        for key in ("mia.recipient", "mia.phone", "mia.iban", "mia.reference", "mia.pay_by"):
            assert key in text
        assert "Test Shop SRL" in text and "MD00TEST000000000000" in text
        assert {f"mia_paid:{order['id']}", "my_orders"} <= set(_cbs(call.message))
        stored = await get_order(order["id"])
        assert stored["payment_status"] == "awaiting_payment" and stored["pay_by"] is not None

    async def test_balance_covers_everything(self, make_callback_query, fsm_context, user_factory,
                                             item_factory):
        await user_factory(telegram_id=700053, balance=100)
        await _cart(700053, price=40, item_factory=item_factory)
        await self._ready(fsm_context, method=None, use_balance=True)
        call = make_callback_query(data="co_confirm", user_id=700053)

        with patch('bot.handlers.user.checkout.notify_new_order', new_callable=AsyncMock) as notify:
            await confirm_order_handler(call, fsm_context)

        stored = await get_order(notify.await_args.args[1]["id"], user_id=700053)
        assert stored["payment_method"] == "balance" and stored["payment_status"] == "paid"
        assert Decimal((await check_user(700053))["balance"]) == Decimal("60")

    async def test_partial_balance_with_mia_asks_only_for_the_rest(self, make_callback_query, fsm_context,
                                                                    user_factory, item_factory):
        await user_factory(telegram_id=700054, balance=15)
        await _cart(700054, price=40, item_factory=item_factory)
        await self._ready(fsm_context, method="mia", use_balance=True)
        call = make_callback_query(data="co_confirm", user_id=700054)

        with patch('bot.handlers.user.checkout.notify_new_order', new_callable=AsyncMock):
            await confirm_order_handler(call, fsm_context)

        assert "'amount': Decimal('25.00')" in _text(call.message)

    async def test_out_of_stock_is_explained_and_nothing_is_taken(self, make_callback_query, fsm_context,
                                                                  user_factory, item_factory):
        await user_factory(telegram_id=700055)
        await _cart(700055, qty=3, price=10, stock=5, item_factory=item_factory)
        # Someone else buys most of it between the summary and the confirm.
        from sqlalchemy import update
        from bot.database.models.main import Goods
        async with Database().session() as s:
            await s.execute(update(Goods).where(Goods.name == "Mug").values(stock=1))
        await self._ready(fsm_context, total="30.00")
        call = make_callback_query(data="co_confirm", user_id=700055)

        with patch('bot.handlers.user.checkout.notify_new_order', new_callable=AsyncMock) as notify:
            await confirm_order_handler(call, fsm_context)

        notify.assert_not_awaited()
        text = _text(call.message)
        assert "checkout.fail.out_of_stock" in text and "'available': 1" in text and "Mug" in text
        assert await get_cart_count(700055) == 3
        assert await select_item_stock("Mug") == 1
        assert "cart" in _cbs(call.message)

    async def test_price_change_after_the_summary_is_refused(self, make_callback_query, fsm_context,
                                                             user_factory, item_factory):
        await user_factory(telegram_id=700056)
        await _cart(700056, price=40, item_factory=item_factory)
        await self._ready(fsm_context, total="30.00")           # the customer saw 30, the cart now costs 40
        call = make_callback_query(data="co_confirm", user_id=700056)

        with patch('bot.handlers.user.checkout.notify_new_order', new_callable=AsyncMock) as notify:
            await confirm_order_handler(call, fsm_context)

        notify.assert_not_awaited()
        assert "cart.price_changed" in _text(call.message)
        assert await get_cart_count(700056) == 1

    async def test_emptied_cart_is_reported(self, make_callback_query, fsm_context, user_factory):
        await user_factory(telegram_id=700057)
        await self._ready(fsm_context)
        call = make_callback_query(data="co_confirm", user_id=700057)

        await confirm_order_handler(call, fsm_context)

        assert "cart.empty" in _text(call.message)

    @pytest.mark.parametrize("code,key", [
        ("cart_items_unavailable", "cart.items_unavailable"),
        ("invalid_payment_method", "checkout.fail.invalid_payment_method"),
        ("invalid_fulfillment", "checkout.fail.invalid_fulfillment"),
        ("address_required", "checkout.fail.address_required"),
        ("user_not_found", "checkout.fail.user_not_found"),
        ("transaction_error", "errors.something_wrong"),
    ])
    async def test_failure_codes_map_to_messages(self, make_callback_query, fsm_context, code, key):
        await self._ready(fsm_context)
        call = make_callback_query(data="co_confirm", user_id=700058)

        with patch('bot.handlers.user.checkout.create_order_transaction',
                   new_callable=AsyncMock, return_value=(False, code, None)):
            await confirm_order_handler(call, fsm_context)

        assert key in _text(call.message)
        assert await fsm_context.get_state() is None

    async def test_staff_alert_failure_does_not_lose_the_order(self, make_callback_query, fsm_context,
                                                               user_factory, item_factory):
        await user_factory(telegram_id=700059)
        await _cart(700059, price=40, item_factory=item_factory)
        await self._ready(fsm_context)
        call = make_callback_query(data="co_confirm", user_id=700059)

        with patch('bot.handlers.user.checkout.notify_new_order',
                   new_callable=AsyncMock, side_effect=RuntimeError("db down")):
            await confirm_order_handler(call, fsm_context)

        assert "checkout.placed" in _text(call.message)
        assert await get_cart_count(700059) == 0

    async def test_stale_state_without_contact_data_is_refused(self, make_callback_query, fsm_context,
                                                                user_factory, item_factory):
        await user_factory(telegram_id=700060)
        await _cart(700060, item_factory=item_factory)
        await fsm_context.set_state(CheckoutFSM.confirming)
        call = make_callback_query(data="co_confirm", user_id=700060)

        await confirm_order_handler(call, fsm_context)

        assert call.answer.call_args[1].get("show_alert") is True
        assert await get_cart_count(700060) == 1                # nothing was ordered
        assert await fsm_context.get_state() is None

    async def test_a_double_tap_cannot_order_twice(self, make_callback_query, fsm_context,
                                                   user_factory, item_factory):
        await user_factory(telegram_id=700061)
        await _cart(700061, price=40, stock=5, item_factory=item_factory)
        await self._ready(fsm_context)

        with patch('bot.handlers.user.checkout.notify_new_order', new_callable=AsyncMock) as notify:
            await confirm_order_handler(make_callback_query(data="co_confirm", user_id=700061), fsm_context)
            # The FSM state is gone after the first press; aiogram would not route the second one here,
            # and the generic handler answers it.
            late = make_callback_query(data="co_confirm", user_id=700061)
            await stale_checkout_button_handler(late)

        assert notify.await_count == 1
        assert await select_item_stock("Mug") == 4
        assert late.answer.call_args[1].get("show_alert") is True


class TestFullFlow:

    async def test_cod_delivery_end_to_end(self, make_callback_query, make_message, fsm_context,
                                           user_factory, item_factory):
        uid = 700070
        await user_factory(telegram_id=uid)
        await _cart(uid, qty=2, price=25, item_factory=item_factory)

        await cart_checkout_handler(make_callback_query(data="cart_checkout", user_id=uid), fsm_context)
        await fulfillment_chosen_handler(make_callback_query(data="co_ful:delivery", user_id=uid), fsm_context)
        await name_text_handler(make_message(text="Ana", user_id=uid), fsm_context)
        await phone_text_handler(make_message(text="+373 69 123 456", user_id=uid), fsm_context)
        await address_handler(make_message(text="Str. Mare 1", user_id=uid), fsm_context)
        await skip_comment_handler(make_callback_query(data="co_skip_comment", user_id=uid), fsm_context)
        await payment_chosen_handler(make_callback_query(data="co_pay:cod", user_id=uid), fsm_context)
        assert await fsm_context.get_state() == CheckoutFSM.confirming

        done = make_callback_query(data="co_confirm", user_id=uid)
        with patch('bot.handlers.user.checkout.notify_new_order', new_callable=AsyncMock):
            await confirm_order_handler(done, fsm_context)

        assert "checkout.placed" in _text(done.message)
        assert await select_item_stock("Mug") == 3


class TestStaleButtons:

    async def test_checkout_button_without_a_flow_is_answered(self, make_callback_query):
        call = make_callback_query(data="co_pay:cod", user_id=700080)

        await stale_checkout_button_handler(call)

        assert call.answer.call_args[1].get("show_alert") is True
        assert "checkout.session_expired" in call.answer.call_args[0][0]


class TestMiaClaim:

    async def _mia_order(self, user_id, item_factory, name="MiaItem"):
        await item_factory(name=name, price=40, stock=5)
        await add_to_cart(user_id, name)
        ok, code, order = await create_order_transaction(
            user_id, fulfillment="pickup", customer_name="Ana", phone="+37369123456",
            address=None, comment=None, payment_method="mia",
        )
        assert ok, code
        return order

    async def test_instructions_skip_unset_fields_and_name_the_amount(self):
        order = {"id": 9, "total": Decimal("40.00"), "balance_used": Decimal("15.00"), "pay_by": None}
        with patch('bot.handlers.user.checkout.EnvKeys') as env:
            env.PAY_CURRENCY = "MDL"
            env.MIA_RECIPIENT = ""
            env.MIA_PHONE = "+37360000000"
            env.MIA_IBAN = ""
            text = mia_instructions(order)

        assert "'amount': Decimal('25.00')" in text
        assert "mia.phone" in text
        assert "mia.recipient" not in text and "mia.iban" not in text
        assert "mia.pay_by" not in text

    async def test_paid_asks_for_a_screenshot(self, make_callback_query, fsm_context, user_factory,
                                              item_factory):
        await user_factory(telegram_id=700090)
        order = await self._mia_order(700090, item_factory)
        call = make_callback_query(data=f"mia_paid:{order['id']}", user_id=700090)

        await mia_paid_handler(call, fsm_context)

        assert await fsm_context.get_state() == CheckoutFSM.waiting_proof
        assert (await fsm_context.get_data())["proof_order_id"] == order["id"]
        assert f"mia_skip:{order['id']}" in _cbs(call.message)

    async def test_paid_on_someone_elses_order_is_refused(self, make_callback_query, fsm_context,
                                                          user_factory, item_factory):
        await user_factory(telegram_id=700091)
        await user_factory(telegram_id=700092)
        order = await self._mia_order(700091, item_factory)
        call = make_callback_query(data=f"mia_paid:{order['id']}", user_id=700092)

        await mia_paid_handler(call, fsm_context)

        assert "mia.not_awaiting" in call.answer.call_args[0][0]
        assert await fsm_context.get_state() is None

    async def test_paid_with_bad_payload(self, make_callback_query, fsm_context):
        call = make_callback_query(data="mia_paid:abc", user_id=700093)

        await mia_paid_handler(call, fsm_context)

        assert "mia.not_awaiting" in call.answer.call_args[0][0]

    async def test_photo_proof_queues_the_order_and_alerts_staff(self, make_message, fsm_context,
                                                                 user_factory, item_factory):
        await user_factory(telegram_id=700094)
        order = await self._mia_order(700094, item_factory)
        await fsm_context.set_state(CheckoutFSM.waiting_proof)
        await fsm_context.update_data(proof_order_id=order["id"])
        msg = make_message(text=None, user_id=700094)
        msg.photo = [MagicMock(file_id="small"), MagicMock(file_id="BIG_FILE_ID")]

        with patch('bot.handlers.user.checkout.notify_mia_claim', new_callable=AsyncMock) as claim:
            await mia_proof_photo_handler(msg, fsm_context)

        stored = await get_order(order["id"])
        assert stored["payment_status"] == "awaiting_confirmation"
        assert stored["payment_proof"] == "BIG_FILE_ID"            # the largest size
        claim.assert_awaited_once()
        assert claim.await_args.args[1]["id"] == order["id"]
        assert "mia.claim_sent" in _text(msg, "answer")
        assert await fsm_context.get_state() is None

    async def test_skip_claims_without_a_screenshot(self, make_callback_query, fsm_context, user_factory,
                                                    item_factory):
        await user_factory(telegram_id=700095)
        order = await self._mia_order(700095, item_factory)
        await fsm_context.set_state(CheckoutFSM.waiting_proof)
        call = make_callback_query(data=f"mia_skip:{order['id']}", user_id=700095)

        with patch('bot.handlers.user.checkout.notify_mia_claim', new_callable=AsyncMock) as claim:
            await mia_skip_proof_handler(call, fsm_context)

        stored = await get_order(order["id"])
        assert stored["payment_status"] == "awaiting_confirmation" and stored["payment_proof"] is None
        claim.assert_awaited_once()
        assert "mia.claim_sent" in _text(call.message)
        assert await fsm_context.get_state() is None

    async def test_claiming_twice_is_harmless_for_the_second_press_on_a_cancelled_order(
            self, make_callback_query, fsm_context, user_factory, item_factory):
        from bot.database.methods.orders import cancel_order_transaction

        await user_factory(telegram_id=700096)
        order = await self._mia_order(700096, item_factory)
        await cancel_order_transaction(order["id"], by_customer_id=700096)
        call = make_callback_query(data=f"mia_skip:{order['id']}", user_id=700096)

        with patch('bot.handlers.user.checkout.notify_mia_claim', new_callable=AsyncMock) as claim:
            await mia_skip_proof_handler(call, fsm_context)

        claim.assert_not_awaited()
        assert "mia.not_awaiting" in _text(call.message)

    async def test_claim_alert_failure_does_not_lose_the_claim(self, make_callback_query, fsm_context,
                                                               user_factory, item_factory):
        await user_factory(telegram_id=700097)
        order = await self._mia_order(700097, item_factory)
        call = make_callback_query(data=f"mia_skip:{order['id']}", user_id=700097)

        with patch('bot.handlers.user.checkout.notify_mia_claim',
                   new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            await mia_skip_proof_handler(call, fsm_context)

        assert (await get_order(order["id"]))["payment_status"] == "awaiting_confirmation"
        assert "mia.claim_sent" in _text(call.message)

    async def test_text_while_waiting_for_the_screenshot_gets_a_hint(self, make_message, fsm_context):
        await fsm_context.set_state(CheckoutFSM.waiting_proof)
        await fsm_context.update_data(proof_order_id=5)
        msg = make_message(text="paid, trust me", user_id=700098)

        await mia_proof_other_handler(msg, fsm_context)

        assert "mia.proof_only_photo" in _text(msg, "answer")
        assert "mia_skip:5" in _cbs(msg, "answer")
        assert await fsm_context.get_state() == CheckoutFSM.waiting_proof

    async def test_info_shows_the_instructions_again(self, make_callback_query, user_factory, item_factory):
        await user_factory(telegram_id=700099)
        order = await self._mia_order(700099, item_factory)
        call = make_callback_query(data=f"mia_info:{order['id']}", user_id=700099)

        await mia_info_handler(call)

        assert "mia.title" in _text(call.message)
        assert f"mia_paid:{order['id']}" in _cbs(call.message)

    async def test_info_after_the_claim_is_refused(self, make_callback_query, user_factory, item_factory):
        from bot.database.methods.orders import mark_mia_paid

        await user_factory(telegram_id=700100)
        order = await self._mia_order(700100, item_factory)
        await mark_mia_paid(order["id"], 700100)
        call = make_callback_query(data=f"mia_info:{order['id']}", user_id=700100)

        await mia_info_handler(call)

        call.message.edit_text.assert_not_called()
        assert "mia.not_awaiting" in call.answer.call_args[0][0]
