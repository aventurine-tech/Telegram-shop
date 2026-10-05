import pytest

from bot.keyboards.inline import (
    main_menu, profile_keyboard, simple_buttons, back, close, item_info,
    checkout_fulfillment_keyboard, checkout_name_keyboard, checkout_cancel_keyboard, checkout_comment_keyboard,
    checkout_payment_keyboard, checkout_confirm_keyboard, mia_keyboard, order_keyboard, question_buttons, check_sub, referral_system_keyboard,
    admin_console_keyboard, cart_keyboard, rating_keyboard,
)


def _all_callback_data(markup):
    """Extract all callback_data values from markup."""
    result = []
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.callback_data:
                result.append(btn.callback_data)
    return result


def _all_button_texts(markup):
    """Extract all button texts from markup."""
    result = []
    for row in markup.inline_keyboard:
        for btn in row:
            result.append(btn.text)
    return result


def _has_url_button(markup):
    """Check if any button has a URL."""
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.url:
                return True
    return False


class TestMainMenu:

    @pytest.mark.parametrize("callback", ["shop", "rules", "profile"])
    def test_basic_buttons_present(self, callback):
        assert callback in _all_callback_data(main_menu(role=1))

    @pytest.mark.parametrize("role,has_console", [
        (1, False),  # regular user
        (2, True),   # admin
    ])
    def test_console_button_follows_role(self, role, has_console):
        assert ("console" in _all_callback_data(main_menu(role=role))) is has_console

    @pytest.mark.parametrize("kwargs,expected", [
        ({"channel": "test_channel"}, True),
        ({"helper": "12345"}, True),
        ({}, False),
    ])
    def test_url_buttons(self, kwargs, expected):
        assert _has_url_button(main_menu(role=1, **kwargs)) is expected


class TestProfileKeyboard:

    @pytest.mark.parametrize("kwargs,callback,expected", [
        ({"referral_percent": 0, "user_orders": 0}, "replenish_balance", False),
        ({"referral_percent": 0}, "back_to_menu", True),
        ({"referral_percent": 10}, "referral_system", True),
        ({"referral_percent": 0}, "referral_system", False),
        ({"referral_percent": 0, "user_orders": 5}, "my_orders", True),
        ({"referral_percent": 0, "user_orders": 0}, "my_orders", False),
    ])
    def test_conditional_buttons(self, kwargs, callback, expected):
        assert (callback in _all_callback_data(profile_keyboard(**kwargs))) is expected


class TestCheckoutKeyboards:

    def test_fulfillment_offers_only_given_kinds(self):
        cbs = _all_callback_data(checkout_fulfillment_keyboard(["pickup"]))
        assert "co_ful:pickup" in cbs and "co_ful:delivery" not in cbs
        assert "co_cancel" in cbs

    def test_name_button_only_with_a_first_name(self):
        assert "co_name_tg" in _all_callback_data(checkout_name_keyboard("Ana"))
        assert "co_name_tg" not in _all_callback_data(checkout_name_keyboard(None))

    def test_text_steps_can_go_back_to_the_cart(self):
        assert "co_cancel" in _all_callback_data(checkout_cancel_keyboard())
        cbs = _all_callback_data(checkout_comment_keyboard())
        assert "co_skip_comment" in cbs and "co_cancel" in cbs

    def test_confirm_screen(self):
        cbs = _all_callback_data(checkout_confirm_keyboard())
        assert {"co_confirm", "co_to_payment", "co_cancel"} <= set(cbs)

    def test_cod_is_labelled_by_fulfillment(self):
        def cod_label(fulfillment):
            markup = checkout_payment_keyboard(["mia", "cod"], fulfillment)
            buttons = {b.callback_data: b.text for row in markup.inline_keyboard for b in row}
            assert "co_pay:mia" in buttons
            return buttons["co_pay:cod"]

        assert cod_label("delivery") != cod_label("pickup")

    def test_balance_toggle_only_with_a_balance(self):
        from decimal import Decimal
        assert "co_balance" not in _all_callback_data(checkout_payment_keyboard(["cod"], "pickup"))
        assert "co_balance" not in _all_callback_data(
            checkout_payment_keyboard(["cod"], "pickup", balance=Decimal("0")))
        assert "co_balance" in _all_callback_data(
            checkout_payment_keyboard(["cod"], "pickup", balance=Decimal("5")))

    def test_balance_toggle_text_follows_state(self):
        from decimal import Decimal
        def toggle(use):
            m = checkout_payment_keyboard([], "pickup", balance=Decimal("5"), use_balance=use)
            return next(b.text for row in m.inline_keyboard for b in row if b.callback_data == "co_balance")
        assert toggle(True) != toggle(False)

    def test_covered_by_balance_offers_continue(self):
        from decimal import Decimal
        cbs = _all_callback_data(checkout_payment_keyboard(
            [], "pickup", balance=Decimal("50"), use_balance=True, covered=True))
        assert "co_pay:balance" in cbs


class TestMiaKeyboard:

    def test_buttons(self):
        cbs = _all_callback_data(mia_keyboard(12))
        assert {"mia_paid:12", "my_order:12", "my_orders"} <= set(cbs)


class TestOrderKeyboard:

    def _order(self, **kw):
        base = {"id": 5, "status": "new", "payment_method": "cod", "payment_status": "unpaid"}
        return {**base, **kw}

    def test_fresh_cod_order_can_be_cancelled(self):
        cbs = _all_callback_data(order_keyboard(self._order()))
        assert "my_order_cancel:5" in cbs
        assert "mia_paid:5" not in cbs
        assert "my_orders" in cbs                    # default back target

    def test_mia_awaiting_payment_shows_payment_actions(self):
        cbs = _all_callback_data(order_keyboard(
            self._order(payment_method="mia", payment_status="awaiting_payment"), back_cb="my-orders-page_2"))
        assert {"mia_info:5", "mia_paid:5", "my_order_cancel:5", "my-orders-page_2"} <= set(cbs)

    @pytest.mark.parametrize("kw", [
        {"status": "confirmed"},
        {"status": "cancelled"},
        {"payment_method": "mia", "payment_status": "awaiting_confirmation"},
        {"payment_method": "mia", "payment_status": "paid"},
    ])
    def test_no_cancel_once_handled_or_money_is_in(self, kw):
        cbs = _all_callback_data(order_keyboard(self._order(**kw)))
        assert "my_order_cancel:5" not in cbs
        assert "mia_paid:5" not in cbs


class TestItemInfoKeyboard:

    @pytest.mark.parametrize("callback", ["buy_item", "add_to_cart", "gp_0"])
    def test_has_buy_and_back(self, callback):
        assert callback in _all_callback_data(item_info("gp_0"))

    def test_out_of_stock_hides_the_order_buttons(self):
        cbs = _all_callback_data(item_info("gp_0", out_of_stock=True))
        assert "buy_item" not in cbs and "add_to_cart" not in cbs
        assert "gp_0" in cbs

    @pytest.mark.parametrize("kwargs,expected_sub,expected_unsub", [
        ({}, False, False),                                   # in stock: no notify button
        ({"out_of_stock": True}, True, False),                # offer to subscribe
        ({"out_of_stock": True, "subscribed": True}, False, True),  # offer to unsubscribe
    ])
    def test_restock_notify_button(self, kwargs, expected_sub, expected_unsub):
        cbs = _all_callback_data(item_info("gp_0", **kwargs))
        assert ("sub_stock" in cbs) is expected_sub
        assert ("unsub_stock" in cbs) is expected_unsub

    def test_review_buttons_carry_no_item_name(self):
        """Telegram caps callback_data at 64 bytes; a 100-char Cyrillic product
        name embedded in it made the whole card unopenable."""
        cbs = _all_callback_data(item_info("gp_0", review_count=3, has_purchased=True))
        assert "reviews:0" in cbs
        assert "review" in cbs
        assert all(len(cb.encode("utf-8")) <= 64 for cb in cbs)


class TestCartKeyboard:

    def _items(self):
        return [{"id": 7, "item_name": "Widget", "quantity": 3}]

    def test_has_quantity_stepper(self):
        cbs = _all_callback_data(cart_keyboard(self._items()))
        assert "cart_qty:7:1" in cbs
        assert "cart_qty:7:-1" in cbs

    def test_has_remove_checkout_and_clear(self):
        cbs = _all_callback_data(cart_keyboard(self._items()))
        assert "cart_remove:7" in cbs
        assert "cart_checkout" in cbs
        assert "cart_clear" in cbs

    def test_shows_quantity_in_label(self):
        markup = cart_keyboard(self._items())
        labels = [b.text for row in markup.inline_keyboard for b in row]
        assert any("×3" in t for t in labels)


class TestLazyPaginatedExtraRows:

    async def test_extra_row_is_rendered(self):
        from aiogram.types import InlineKeyboardButton
        from bot.keyboards.inline import lazy_paginated_keyboard
        from bot.misc import LazyPaginator

        async def _query(offset=0, limit=10, count_only=False):
            return 1 if count_only else ["OnlyCat"]

        markup = await lazy_paginated_keyboard(
            paginator=LazyPaginator(_query, per_page=10),
            item_text=lambda c: c,
            item_callback=lambda c: f"cat:0:0",
            page=0,
            back_cb="back_to_menu",
            nav_cb_prefix="categories-page_",
            extra_rows=[[InlineKeyboardButton(text="🔍", callback_data="shop_search")]],
        )
        assert "shop_search" in _all_callback_data(markup)

    async def test_without_extra_rows_output_is_unchanged(self):
        """The 6 existing call sites must be byte-identical."""
        from bot.keyboards.inline import lazy_paginated_keyboard
        from bot.misc import LazyPaginator

        async def _query(offset=0, limit=10, count_only=False):
            return 1 if count_only else ["OnlyCat"]

        def _kb():
            return lazy_paginated_keyboard(
                paginator=LazyPaginator(_query, per_page=10),
                item_text=lambda c: c,
                item_callback=lambda c: "cat:0:0",
                page=0,
                back_cb="back_to_menu",
                nav_cb_prefix="categories-page_",
            )

        markup = await _kb()
        assert _all_callback_data(markup) == ["cat:0:0", "back_to_menu"]


class TestSimpleButtons:

    def test_creates_buttons(self):
        markup = simple_buttons([("A", "a"), ("B", "b")])
        cbs = _all_callback_data(markup)
        assert "a" in cbs
        assert "b" in cbs

    def test_button_count(self):
        markup = simple_buttons([("A", "a"), ("B", "b"), ("C", "c")])
        total = sum(len(row) for row in markup.inline_keyboard)
        assert total == 3


class TestBackAndClose:

    @pytest.mark.parametrize("args,expected", [
        ((), "menu"),           # default target
        (("profile",), "profile"),
    ])
    def test_back(self, args, expected):
        assert expected in _all_callback_data(back(*args))

    def test_close_button(self):
        assert "close" in _all_callback_data(close())


class TestReferralSystemKeyboard:

    @pytest.mark.parametrize("has_referrals,has_earnings", [
        (False, False),
        (True, False),
        (False, True),
        (True, True),
    ])
    def test_buttons_follow_available_data(self, has_referrals, has_earnings):
        cbs = _all_callback_data(
            referral_system_keyboard(has_referrals=has_referrals, has_earnings=has_earnings)
        )
        assert ("view_referrals" in cbs) is has_referrals
        assert ("view_all_earnings" in cbs) is has_earnings
        assert "profile" in cbs  # back button is always there


class TestQuestionButtons:

    def test_has_yes_no_back(self):
        markup = question_buttons("confirm_delete", "shop")
        cbs = _all_callback_data(markup)
        assert "confirm_delete_yes" in cbs
        assert "confirm_delete_no" in cbs
        assert "shop" in cbs


class TestCheckSub:

    def test_has_channel_url(self):
        markup = check_sub("test_channel")
        has_url = False
        for row in markup.inline_keyboard:
            for btn in row:
                if btn.url and "test_channel" in btn.url:
                    has_url = True
        assert has_url

    def test_has_check_callback(self):
        markup = check_sub("test_channel")
        cbs = _all_callback_data(markup)
        assert "sub_channel_done" in cbs


class TestAdminConsoleKeyboard:

    def test_has_roles_button(self):
        markup = admin_console_keyboard()
        cbs = _all_callback_data(markup)
        assert "role_mgmt" in cbs

    def test_has_all_admin_buttons(self):
        markup = admin_console_keyboard()
        cbs = _all_callback_data(markup)
        assert "shop_management" in cbs
        assert "goods_management" in cbs
        assert "categories_management" in cbs
        assert "user_management" in cbs
        assert "send_message" in cbs
        assert "role_mgmt" in cbs

    def test_maintenance_toggle(self):
        markup_on = admin_console_keyboard(maintenance_mode=True)
        markup_off = admin_console_keyboard(maintenance_mode=False)
        texts_on = _all_button_texts(markup_on)
        texts_off = _all_button_texts(markup_off)
        # The maintenance button text should differ between states
        assert texts_on != texts_off


class TestCallbackDataFitsTelegramLimit:
    LONG_CYRILLIC = "Подарочный сертификат Steam на 1000 рублей регион свободный"
    LONG_ASCII = "S" * 100

    def _assert_all_fit(self, markup):
        for cb in _all_callback_data(markup):
            assert len(cb.encode("utf-8")) <= 64, f"too long ({len(cb.encode())}B): {cb!r}"

    def test_item_card_fits_with_every_button_shown(self):
        markup = item_info(
            "gp_0", avg_rating=4.5, review_count=7, has_purchased=True,
            out_of_stock=True, subscribed=False,
        )
        self._assert_all_fit(markup)

    def test_item_card_fits_with_promo_applied(self):
        self._assert_all_fit(item_info("gp_0", applied_promo="SUMMER-2026", review_count=3))

    def test_cart_keyboard_fits_for_long_names(self):
        for name in (self.LONG_CYRILLIC, self.LONG_ASCII):
            items = [{"id": 987654, "item_name": name, "quantity": 99}]
            self._assert_all_fit(cart_keyboard(items))

    def test_checkout_and_order_keyboards_fit(self):
        from decimal import Decimal
        order = {"id": 2 ** 40, "status": "new", "payment_method": "mia", "payment_status": "awaiting_payment"}
        for markup in (
            checkout_fulfillment_keyboard(["delivery", "pickup"]),
            checkout_name_keyboard(self.LONG_ASCII),
            checkout_payment_keyboard(["mia", "cod"], "pickup", balance=Decimal("5"), covered=True),
            checkout_confirm_keyboard(),
            mia_keyboard(2 ** 40),
            order_keyboard(order, back_cb="my-orders-page_99999"),
        ):
            self._assert_all_fit(markup)

    def test_rating_keyboard_fits(self):
        self._assert_all_fit(rating_keyboard())
