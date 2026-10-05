"""Language picker, the middleware that applies the choice, and messages sent in the recipient's language."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.enums.chat_type import ChatType
from aiogram.types import CallbackQuery, Message

from bot.database.methods.create import subscribe_to_stock
from bot.database.methods.read import check_user, check_user_cached
from bot.database.methods.update import set_user_language
from bot.handlers.user import language as lang_h
from bot.handlers.user.language import NoLanguage, _parse_choice
from bot.handlers.user.main import start, profile_callback_handler
from bot.i18n import main as i18n
from bot.keyboards.inline import language_keyboard, profile_keyboard
from bot.middleware.language import LanguageMiddleware


def _buttons(markup):
    return [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]


@pytest.fixture
def env_menu():
    """No channel / helper so /start goes straight to the menu."""
    with patch('bot.handlers.user.main.EnvKeys') as env:
        env.OWNER_ID = 999999
        env.CHANNEL_URL = ""
        env.CHANNEL_ID = ""
        env.HELPER_ID = ""
        env.RULES = ""
        env.REFERRAL_PERCENT = 10
        env.PAY_CURRENCY = "MDL"
        yield env


@pytest.fixture
def real_localize():
    """Real translations in the modules the autouse fixture turns into a key echo."""
    with patch('bot.misc.services.order_view.localize', i18n.localize), \
            patch('bot.handlers.user.language.localize', i18n.localize), \
            patch('bot.handlers.user.main.localize', i18n.localize), \
            patch('bot.keyboards.reply.localize', i18n.localize), \
            patch('bot.keyboards.inline.localize', i18n.localize):
        yield


class TestKeyboard:

    def test_one_button_per_language(self):
        buttons = _buttons(language_keyboard())
        assert [cb for _, cb in buttons] == ["lang:en", "lang:ru", "lang:ro"]

    def test_payload_is_carried_in_every_button(self):
        assert [cb for _, cb in _buttons(language_keyboard(payload="12345"))] == [
            "lang:en:12345", "lang:ru:12345", "lang:ro:12345"]

    @pytest.mark.parametrize("payload", ["abc", "1; DROP", "9" * 40, "", None])
    def test_bad_payload_is_dropped_and_data_stays_short(self, payload):
        for _, cb in _buttons(language_keyboard(payload=payload)):
            assert len(cb.encode()) <= 64
            assert cb.count(":") == 1

    def test_back_button_optional(self):
        assert _buttons(language_keyboard(back_to="profile"))[-1][1] == "profile"

    def test_profile_has_language_button(self):
        assert "profile_language" in [cb for _, cb in _buttons(profile_keyboard(0))]

    def test_title_lists_all_languages_whatever_the_current_one(self):
        for lang in ("en", "ru", "ro"):
            title = i18n.localize_in(lang, "language.picker.title")
            assert "Choose your language" in title and "Выберите язык" in title and "Alegeți limba" in title


class TestParseChoice:

    @pytest.mark.parametrize("data,expected", [
        ("lang:en", ("en", None)),
        ("lang:ro:555", ("ro", "555")),
    ])
    def test_valid(self, data, expected):
        assert _parse_choice(data) == expected

    @pytest.mark.parametrize("data", [
        "lang:xx", "lang:", "lang", "lang:en:abc", "lang:en:1:2", "lang:EN", "lang:en:" + "1" * 30, None,
    ])
    def test_invalid(self, data):
        assert _parse_choice(data) is None


class TestNoLanguageFilter:

    async def test_new_user_without_row_matches(self, make_message):
        assert await NoLanguage()(make_message(text="hi", user_id=710001)) is True

    async def test_user_without_language_matches(self, make_message, user_factory):
        await user_factory(telegram_id=710002)
        assert await NoLanguage()(make_message(text="hi", user_id=710002)) is True

    async def test_user_with_language_does_not_match(self, make_message, user_factory):
        await user_factory(telegram_id=710003, language="ro")
        assert await NoLanguage()(make_message(text="hi", user_id=710003)) is False

    async def test_group_chat_ignored(self, make_message):
        msg = MagicMock(spec=Message)
        msg.from_user = MagicMock(id=710004)
        msg.chat = MagicMock(type=ChatType.GROUP)
        assert await NoLanguage()(msg) is False
        msg.chat.type = ChatType.PRIVATE
        assert await NoLanguage()(msg) is True

    @staticmethod
    def _call(data, user_id):
        call = MagicMock(spec=CallbackQuery)
        call.data = data
        call.from_user = MagicMock(id=user_id)
        return call

    async def test_picker_buttons_pass_through(self):
        assert await NoLanguage()(self._call("lang:en", 710005)) is False

    async def test_stale_callback_matches(self):
        assert await NoLanguage()(self._call("shop", 710006)) is True


class TestStartWithoutLanguage:

    async def test_start_shows_only_the_picker(self, make_message, fsm_context, env_menu):
        msg = make_message(text="/start", user_id=720001)
        await lang_h.start_without_language(msg, fsm_context)

        msg.answer.assert_awaited_once()
        assert msg.answer.await_args.args[0] == "language.picker.title"
        assert [cb for _, cb in _buttons(msg.answer.await_args.kwargs["reply_markup"])] == [
            "lang:en", "lang:ru", "lang:ro"]
        assert await check_user(720001) is None   # nothing registered until they choose

    async def test_start_payload_survives_in_the_buttons(self, make_message, fsm_context):
        msg = make_message(text="/start 4242", user_id=720002)
        await lang_h.start_without_language(msg, fsm_context)
        cbs = [cb for _, cb in _buttons(msg.answer.await_args.kwargs["reply_markup"])]
        assert cbs == ["lang:en:4242", "lang:ru:4242", "lang:ro:4242"]

    async def test_any_text_gets_the_picker(self, make_message):
        msg = make_message(text="hello there", user_id=720003)
        await lang_h.text_without_language(msg)
        assert msg.answer.await_args.args[0] == "language.picker.title"

    async def test_stale_callback_gets_the_picker(self, make_callback_query):
        call = make_callback_query(data="cart", user_id=720004)
        await lang_h.callback_without_language(call)
        call.answer.assert_awaited_once()
        assert call.message.answer.await_args.args[0] == "language.picker.title"

    async def test_returning_user_does_not_match_so_start_runs_normally(
            self, make_message, fsm_context, user_factory, env_menu):
        await user_factory(telegram_id=720005, language="en")
        msg = make_message(text="/start", user_id=720005)
        assert await NoLanguage()(msg) is False
        await start(msg, fsm_context)
        assert msg.answer.await_args.args[0] == "menu.title"


class TestChoosing:

    async def test_choice_registers_saves_and_opens_the_menu(
            self, make_callback_query, fsm_context, env_menu, real_localize):
        call = make_callback_query(data="lang:ro", user_id=730001)
        await lang_h.choose_language(call, fsm_context)

        user = await check_user(730001)
        assert user["language"] == "ro"
        call.message.delete.assert_awaited()
        sent = call.message.answer.await_args
        assert sent.args[0] == i18n.localize_in("ro", "menu.title")
        # The menu buttons are in the chosen language too.
        texts = [t for t, _ in _buttons(sent.kwargs["reply_markup"])]
        assert i18n.localize_in("ro", "btn.shop") in texts
        assert i18n.localize_in("ru", "btn.shop") not in texts

    async def test_referral_payload_is_registered_after_the_choice(
            self, make_callback_query, fsm_context, user_factory, env_menu):
        await user_factory(telegram_id=730010)
        call = make_callback_query(data="lang:en:730010", user_id=730011)
        await lang_h.choose_language(call, fsm_context)

        user = await check_user(730011)
        assert user["referral_id"] == 730010 and user["language"] == "en"

    async def test_self_referral_ignored(self, make_callback_query, fsm_context, env_menu):
        call = make_callback_query(data="lang:en:730020", user_id=730020)
        await lang_h.choose_language(call, fsm_context)
        assert (await check_user(730020))["referral_id"] is None

    async def test_unknown_referrer_ignored(self, make_callback_query, fsm_context, env_menu):
        call = make_callback_query(data="lang:en:99999999", user_id=730021)
        await lang_h.choose_language(call, fsm_context)
        user = await check_user(730021)
        assert user["referral_id"] is None and user["language"] == "en"

    async def test_existing_user_without_language_just_gets_one(
            self, make_callback_query, fsm_context, user_factory, env_menu):
        await user_factory(telegram_id=730030, balance=50)
        call = make_callback_query(data="lang:ru", user_id=730030)
        await lang_h.choose_language(call, fsm_context)
        user = await check_user(730030)
        assert user["language"] == "ru" and user["balance"] == 50
        assert call.message.answer.await_args.args[0] == "menu.title"

    async def test_subscription_gate_still_applies(self, make_callback_query, fsm_context, env_menu):
        call = make_callback_query(data="lang:en", user_id=730040)
        with patch('bot.handlers.user.main._parse_channel_username', return_value="shopchan"), \
                patch('bot.handlers.user.main._is_subscribed', new_callable=AsyncMock, return_value=False):
            await lang_h.choose_language(call, fsm_context)
        assert call.message.answer.await_args.args[0] == "subscribe.prompt"
        assert (await check_user(730040))["language"] == "en"

    @pytest.mark.parametrize("data", ["lang:xx", "lang:en:abc", "lang:", "lang:en:1:2"])
    async def test_invalid_payload_rejected(self, make_callback_query, fsm_context, data):
        call = make_callback_query(data=data, user_id=730050)
        await lang_h.choose_language(call, fsm_context)
        assert call.answer.await_args.kwargs.get("show_alert") is True
        call.message.answer.assert_not_awaited()
        assert await check_user(730050) is None


class TestProfileLanguage:

    async def test_profile_button_shows_the_picker_with_back(self, make_callback_query):
        call = make_callback_query(data="profile_language", user_id=740001)
        await lang_h.profile_language(call)
        text, = call.message.edit_text.await_args.args
        assert text == "language.picker.title"
        buttons = _buttons(call.message.edit_text.await_args.kwargs["reply_markup"])
        assert [cb for _, cb in buttons] == ["lang:en", "lang:ru", "lang:ro", "profile"]

    async def test_switching_returns_to_the_profile_in_the_new_language(
            self, make_callback_query, fsm_context, user_factory, env_menu, real_localize):
        await user_factory(telegram_id=740002, language="en")
        call = make_callback_query(data="lang:ro", user_id=740002)
        await lang_h.choose_language(call, fsm_context)

        assert (await check_user_cached(740002))["language"] == "ro"
        # The picker is removed, the welcome line (it carries the keyboard) is sent first, the profile follows
        # below it: the welcome line is always above the menu.
        call.message.delete.assert_awaited_once()
        sent = call.message.answer.await_args_list
        assert len(sent) == 2
        assert sent[0].args[0] == i18n.localize_in("ro", "menu.welcome")
        assert [b.text for b in sent[0].kwargs["reply_markup"].keyboard[0]] == [
            i18n.localize_in("ro", k) for k in ("btn.nav.catalog", "btn.nav.cart", "btn.nav.profile")]
        assert i18n.localize_in("ro", "profile.id", id=740002) in sent[1].args[0]
        call.message.edit_text.assert_not_awaited()


class TestLanguageMiddleware:

    async def _run(self, user_id, seen):
        mw = LanguageMiddleware()
        event = MagicMock()
        event.from_user.id = user_id

        async def handler(ev, data):
            seen.append(i18n.current_language())
            await asyncio.sleep(0)
            seen.append(i18n.current_language())
            return "ok"

        return await mw(handler, event, {})

    @pytest.fixture(autouse=True)
    def _default_ru(self):
        i18n.get_locale.cache_clear()
        with patch('bot.i18n.main.EnvKeys') as env:
            env.BOT_LOCALE = "ru"
            yield
        i18n.get_locale.cache_clear()

    async def test_sets_the_users_language_and_resets(self, user_factory):
        await user_factory(telegram_id=750001, language="ro")
        seen = []
        assert await self._run(750001, seen) == "ok"
        assert seen == ["ro", "ro"]
        assert i18n.current_language() == "ru"

    async def test_no_row_or_no_choice_uses_default(self, user_factory):
        await user_factory(telegram_id=750002)
        seen = []
        await self._run(750002, seen)
        await self._run(750003, seen)
        assert seen == ["ru"] * 4

    async def test_reset_even_when_the_handler_raises(self, user_factory):
        await user_factory(telegram_id=750004, language="en")
        mw = LanguageMiddleware()
        event = MagicMock()
        event.from_user.id = 750004

        async def boom(ev, data):
            assert i18n.current_language() == "en"
            raise RuntimeError("handler failed")

        with pytest.raises(RuntimeError):
            await mw(boom, event, {})
        assert i18n.current_language() == "ru"

    async def test_concurrent_updates_do_not_leak(self, user_factory):
        for uid, lang in ((750010, "en"), (750011, "ro"), (750012, "ru")):
            await user_factory(telegram_id=uid, language=lang)
        results = {uid: [] for uid in (750010, 750011, 750012)}
        await asyncio.gather(*(self._run(uid, results[uid]) for uid in results))
        assert results == {750010: ["en"] * 2, 750011: ["ro"] * 2, 750012: ["ru"] * 2}

    async def test_event_without_user_runs_in_default(self):
        mw = LanguageMiddleware()
        event = MagicMock(spec=[])
        seen = []

        async def handler(ev, data):
            seen.append(i18n.current_language())

        await mw(handler, event, {})
        assert seen == ["ru"]

    async def test_registered_for_messages_and_callbacks_between_auth_and_security(self):
        from aiogram import Dispatcher
        from bot.main import _register_middlewares
        from bot.middleware.security import SecurityMiddleware, AuthenticationMiddleware
        dp = Dispatcher()
        _register_middlewares(dp, AsyncMock(), AuthenticationMiddleware(), SecurityMiddleware())
        for observer in (dp.message, dp.callback_query):
            kinds = [type(m).__name__ for m in observer.middleware._middlewares]
            assert kinds.index("AuthenticationMiddleware") < kinds.index("LanguageMiddleware") \
                < kinds.index("SecurityMiddleware")


# --- Messages to other people use THEIR language ---

def _order(user_id, oid=7):
    import datetime
    return {
        "id": oid, "user_id": user_id, "status": "new", "payment_status": "unpaid",
        "payment_method": "cod", "fulfillment": "pickup", "total": 100, "balance_used": 0,
        "items": [{"item_name": "Chair", "quantity": 1, "line_total": 100}],
        "customer_name": "Ana", "phone": "+373", "address": None, "comment": None,
        "created_at": datetime.datetime(2026, 1, 1, 12, 0),
    }


class TestRecipientLanguage:

    async def test_customer_notice_in_customers_language(self, mock_bot, user_factory, real_localize):
        from bot.misc.services.order_view import notify_customer
        await user_factory(telegram_id=760001, language="ro")
        with i18n.use_language("en"):   # the admin pressing the button speaks English
            assert await notify_customer(mock_bot, _order(760001), "confirmed") is True
        args = mock_bot.send_message.await_args
        assert args.args[1] == i18n.localize_in("ro", "notify.customer.confirmed", id=7)
        assert args.args[1] != i18n.localize_in("en", "notify.customer.confirmed", id=7)
        button = args.kwargs["reply_markup"].inline_keyboard[0][0]
        assert button.text == i18n.localize_in("ro", "btn.order.open")

    async def test_customer_without_language_gets_the_default(self, mock_bot, user_factory, real_localize):
        from bot.misc.services.order_view import notify_customer
        await user_factory(telegram_id=760002)
        i18n.get_locale.cache_clear()
        with patch('bot.i18n.main.EnvKeys') as env:
            env.BOT_LOCALE = "ru"
            i18n.get_locale.cache_clear()
            await notify_customer(mock_bot, _order(760002), "shipped")
            expected = i18n.localize_in(None, "notify.customer.shipped", id=7)
        i18n.get_locale.cache_clear()
        assert mock_bot.send_message.await_args.args[1] == expected

    async def test_each_staff_member_gets_their_own_language(self, mock_bot, user_factory, real_localize):
        from bot.misc.services.order_view import notify_new_order
        await user_factory(telegram_id=760010, role_id=3, language="en")
        await user_factory(telegram_id=760011, role_id=3, language="ro")
        await user_factory(telegram_id=760012, role_id=3, language="ro")
        with i18n.use_language("ru"):
            sent = await notify_new_order(mock_bot, _order(760099))
        assert sent == 3
        by_chat = {c.args[0]: c.args[1] for c in mock_bot.send_message.await_args_list}
        head = {l: i18n.localize_in(l, "notify.admin.new_order") for l in ("en", "ro")}
        assert by_chat[760010].startswith(head["en"])
        assert by_chat[760011].startswith(head["ro"]) and by_chat[760012].startswith(head["ro"])
        assert by_chat[760010] != by_chat[760011]

    async def test_orders_group_chat_gets_the_default_language(self, mock_bot, user_factory, real_localize):
        from bot.misc.services.order_view import notify_new_order
        await user_factory(telegram_id=760020, role_id=3, language="ro")
        i18n.get_locale.cache_clear()
        with patch('bot.misc.services.order_view.EnvKeys') as env, \
                patch('bot.i18n.main.EnvKeys') as env2:
            env.ORDERS_CHAT_ID = "-100500"
            env.PAY_CURRENCY = "MDL"
            env2.BOT_LOCALE = "en"
            i18n.get_locale.cache_clear()
            await notify_new_order(mock_bot, _order(760098))
        i18n.get_locale.cache_clear()
        by_chat = {c.args[0]: c.args[1] for c in mock_bot.send_message.await_args_list}
        assert by_chat[-100500].startswith(i18n.localize_in("en", "notify.admin.new_order"))
        assert by_chat[760020].startswith(i18n.localize_in("ro", "notify.admin.new_order"))

    async def test_mia_claim_per_staff_language_with_photo(self, mock_bot, user_factory, real_localize):
        from bot.misc.services.order_view import notify_mia_claim
        await user_factory(telegram_id=760030, role_id=3, language="en")
        await user_factory(telegram_id=760031, role_id=3, language="ru")
        order = _order(760097)
        order["payment_proof"] = "file123"
        order["payment_status"] = "awaiting_confirmation"
        await notify_mia_claim(mock_bot, order)
        by_chat = {c.args[0]: c.kwargs["caption"] for c in mock_bot.send_photo.await_args_list}
        assert by_chat[760030] != by_chat[760031]
        assert by_chat[760030].startswith(i18n.localize_in("en", "notify.admin.mia_claim", amount=100, currency="MDL", id=7)[:15])

    async def test_restock_each_subscriber_in_their_language(self, mock_bot, user_factory, item_factory):
        from bot.misc.services.restock_notifier import notify_restock
        await item_factory(name="Lamp", price=10, stock=0)
        for uid, lang in ((760040, "en"), (760041, "ro"), (760042, "ro"), (760043, None)):
            await user_factory(telegram_id=uid, language=lang)
            await subscribe_to_stock(uid, "Lamp")
        sent = await notify_restock(mock_bot, "Lamp")
        assert sent == 4
        by_chat = {c.kwargs["chat_id"]: c.kwargs["text"] for c in mock_bot.send_message.await_args_list}
        assert by_chat[760040] == i18n.localize_in("en", "stock.back_in_stock", name="Lamp")
        assert by_chat[760041] == by_chat[760042] == i18n.localize_in("ro", "stock.back_in_stock", name="Lamp")
        assert by_chat[760040] != by_chat[760041]

    async def test_mia_expiry_notice_in_customers_language(self, mock_bot, user_factory, real_localize):
        from bot.misc.services.recovery import RecoveryManager
        await user_factory(telegram_id=760050, language="ro")
        manager = RecoveryManager(mock_bot)
        order = _order(760050)
        with patch("bot.database.methods.orders.expire_unpaid_orders",
                   new_callable=AsyncMock, return_value=[order]):
            await manager.expire_unpaid_orders()
        assert mock_bot.send_message.await_args.args[1] == i18n.localize_in("ro", "notify.customer.mia_expired", id=7)

    async def test_balance_topup_notice_in_users_language(self, user_factory):
        from bot.misc.services.recipients import language_of
        await user_factory(telegram_id=760060, language="ro")
        await user_factory(telegram_id=760061)
        assert await language_of(760060) == "ro"
        assert await language_of(760061) is None
        assert await language_of(1) is None
