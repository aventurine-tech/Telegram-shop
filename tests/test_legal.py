"""What Telegram's bot rules ask for: /help, /settings, /support, the terms, the privacy policy, "my data"."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message
from sqlalchemy import update

from bot.database.main import Database
from bot.database.methods.read import check_user
from bot.database.models.main import User
from bot.handlers.user import legal
from bot.handlers.user.legal import (
    agreement_line, help_command, my_data_erase_ask_handler, my_data_erase_handler, my_data_handler,
    privacy_back_handler, privacy_command, privacy_open_handler, privacy_text, settings_command,
    settings_mailings_handler, support_command, terms_command, terms_text,
)
from bot.i18n import use_language
from bot.i18n.strings import TRANSLATIONS
from bot.misc.bot_commands import COMMANDS
from bot.states import CheckoutFSM

UID = 960001
LANGS = ("en", "ru", "ro")


def _command(text, user_id=UID):
    msg = AsyncMock(spec=Message)
    msg.text = text
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.from_user.first_name = "Tester"
    msg.chat = MagicMock()
    msg.chat.type = "private"
    msg.answer = AsyncMock()
    msg.delete = AsyncMock()
    return msg


def _sent(msg):
    return msg.answer.await_args.args[0], msg.answer.await_args.kwargs.get("reply_markup")


def _callbacks(markup):
    return [b.callback_data or b.url for row in markup.inline_keyboard for b in row]


async def _profile(user_id=UID, **values):
    async with Database().session() as s:
        await s.execute(update(User).where(User.telegram_id == user_id).values(**values))
    from bot.database.methods.read import invalidate_user_cache
    await invalidate_user_cache(user_id)


@pytest.fixture
def env(monkeypatch):
    """EnvKeys attributes are read at call time, so a test can set them."""
    def _set(**values):
        for name, value in values.items():
            monkeypatch.setattr(legal.EnvKeys, name, value, raising=False)
    return _set


class TestTexts:

    @pytest.mark.parametrize("lang", LANGS)
    def test_every_text_fits_one_telegram_message(self, lang, env):
        env(SELLER_INFO="SRL Exemplu Comerț, IDNO 1000000000000, mun. Chișinău, str. Exemplu 1", ADULTS_ONLY="1")
        with use_language(lang):
            for text in (terms_text(), privacy_text(), legal.help_text()):
                assert 0 < len(text) < 4096
                assert "{" not in text and "}" not in text          # every placeholder was filled

    @pytest.mark.parametrize("lang", LANGS)
    def test_terms_name_the_seller_the_currency_and_the_payment_time(self, lang, env):
        env(SELLER_INFO="SRL Test <Shop>", PAY_CURRENCY="MDL", MIA_PAY_TIMEOUT_MIN=45, ADULTS_ONLY="0")
        with use_language(lang):
            text = terms_text()
        assert "SRL Test &lt;Shop&gt;" in text and "MDL" in text and "45" in text
        assert "/support" in text and "/privacy" in text and "@BotSupport" in text

    def test_without_seller_details_the_texts_still_read(self, env):
        env(SELLER_INFO="")
        with use_language("en"):
            assert "the shop that runs this bot" in terms_text()
            assert "the shop that runs this bot" in privacy_text()

    @pytest.mark.parametrize("lang", LANGS)
    def test_the_adults_clause_and_the_checkout_line_follow_the_switch(self, lang, env):
        with use_language(lang):
            env(ADULTS_ONLY="0")
            plain_terms, plain_line = terms_text(), agreement_line()
            env(ADULTS_ONLY="1")
            adult_terms, adult_line = terms_text(), agreement_line()
        assert "18" not in plain_terms and "18" not in plain_line
        assert "18" in adult_terms and "18" in adult_line
        assert "/terms" in plain_line and "/privacy" in adult_line

    def test_the_new_keys_exist_in_every_language(self):
        keys = set(TRANSLATIONS["en"]) & {k for k in __import__(
            "bot.i18n.strings_legal", fromlist=["TRANSLATIONS"]).TRANSLATIONS["en"]}
        assert len(keys) > 40
        for lang in LANGS:
            assert not [k for k in keys if not TRANSLATIONS[lang].get(k)], lang

    def test_the_menu_offers_what_telegram_asks_for(self):
        names = [name for name, _key in COMMANDS]
        assert {"help", "settings", "support", "terms", "privacy"} <= set(names)


class TestScreens:

    async def test_help_lists_every_command(self, fsm_context):
        msg = _command("/help")
        await help_command(msg, fsm_context)
        text, _markup = _sent(msg)
        for name, _key in COMMANDS:
            assert f"/{name} " in text

    async def test_support_links_the_support_account_and_says_telegram_cannot_help(self, fsm_context, env):
        env(HELPER_ID="555000")
        msg = _command("/support")
        await support_command(msg, fsm_context)
        text, markup = _sent(msg)
        assert "@BotSupport" in text and "tg://user?id=555000" in _callbacks(markup)

    async def test_support_falls_back_to_the_owner(self, fsm_context, env):
        env(HELPER_ID="", OWNER_ID=424242)
        msg = _command("/support")
        await support_command(msg, fsm_context)
        assert "tg://user?id=424242" in _callbacks(_sent(msg)[1])

    async def test_settings_show_language_news_and_privacy(self, fsm_context, user_factory):
        await user_factory(telegram_id=UID, language="ro")
        msg = _command("/settings")
        await settings_command(msg, fsm_context)
        text, markup = _sent(msg)
        assert "Română" in text
        assert _callbacks(markup) == ["profile_language", "settings_mailings", "legal_privacy_open", "back_to_menu"]

    async def test_settings_switch_turns_shop_news_off_and_on(self, make_callback_query, user_factory):
        await user_factory(telegram_id=UID)
        call = make_callback_query(data="settings_mailings", user_id=UID)
        await settings_mailings_handler(call)
        assert (await check_user(UID))["mailing_optout"] is True
        await settings_mailings_handler(call)
        assert (await check_user(UID))["mailing_optout"] is False
        assert call.message.edit_text.await_count == 2

    async def test_a_screen_command_ends_the_flow_in_progress(self, fsm_context):
        await fsm_context.set_state(CheckoutFSM.confirming)
        await help_command(_command("/help"), fsm_context)
        assert await fsm_context.get_state() is None


class TestDocuments:

    async def test_terms_are_a_separate_closable_message_and_keep_the_checkout(self, fsm_context):
        await fsm_context.set_state(CheckoutFSM.confirming)
        await fsm_context.update_data(co_name="Ana")
        msg = _command("/terms")
        await terms_command(msg)
        text, markup = _sent(msg)
        assert "<b>1." in text and _callbacks(markup) == ["close"]
        msg.delete.assert_awaited_once()
        assert await fsm_context.get_state() == CheckoutFSM.confirming
        assert (await fsm_context.get_data())["co_name"] == "Ana"

    async def test_terms_are_not_tracked_as_the_chat_screen(self):
        from bot.middleware.clean_chat import _serving_chat
        seen = []
        msg = _command("/terms")
        msg.answer = AsyncMock(side_effect=lambda *a, **k: seen.append(_serving_chat.get()))
        token = _serving_chat.set(UID)
        try:
            await terms_command(msg)
        finally:
            _serving_chat.reset(token)
        assert seen == [None]

    async def test_privacy_offers_my_data_and_delete(self):
        msg = _command("/privacy")
        await privacy_command(msg)
        text, markup = _sent(msg)
        assert "/settings" in text and _callbacks(markup) == ["my_data", "my_data_erase", "close"]

    async def test_privacy_from_settings_is_a_new_message(self, make_callback_query):
        call = make_callback_query(data="legal_privacy_open", user_id=UID)
        await privacy_open_handler(call)
        call.message.answer.assert_awaited_once()
        call.message.edit_text.assert_not_awaited()

    async def test_back_returns_to_the_policy(self, make_callback_query):
        call = make_callback_query(data="legal_privacy", user_id=UID)
        await privacy_back_handler(call)
        assert _callbacks(call.message.edit_text.await_args.kwargs["reply_markup"])[0] == "my_data"


class TestMyData:

    async def test_my_data_shows_what_the_profile_holds_escaped(self, make_callback_query, user_factory):
        await user_factory(telegram_id=UID, language="en")
        await _profile(first_name="Ana <b>", username="ana_m", phone="+37369000000", city="Chișinău",
                       address="str. Test 1")
        call = make_callback_query(data="my_data", user_id=UID)
        await my_data_handler(call)
        text = call.message.edit_text.await_args.args[0]
        assert str(UID) in text and "Ana &lt;b&gt;" in text and "@ana_m" in text
        assert "+37369000000" in text and "Chișinău" in text and "str. Test 1" in text
        assert "Last name" not in text                               # nothing stored, nothing shown
        assert _callbacks(call.message.edit_text.await_args.kwargs["reply_markup"]) == ["my_data_erase", "legal_privacy"]

    async def test_delete_asks_first(self, make_callback_query, user_factory):
        await user_factory(telegram_id=UID)
        await _profile(phone="+37369000000")
        call = make_callback_query(data="my_data_erase", user_id=UID)
        await my_data_erase_ask_handler(call)
        assert _callbacks(call.message.edit_text.await_args.kwargs["reply_markup"]) == ["my_data_erase_yes", "legal_privacy"]
        assert (await check_user(UID))["phone"] == "+37369000000"    # nothing deleted yet

    async def test_confirmed_delete_erases_the_personal_data(self, make_callback_query, fsm_context, user_factory):
        await user_factory(telegram_id=UID)
        await _profile(first_name="Ana", phone="+37369000000", address="str. Test 1", city="Chișinău")
        await fsm_context.set_state(CheckoutFSM.confirming)
        call = make_callback_query(data="my_data_erase_yes", user_id=UID)
        await my_data_erase_handler(call, fsm_context)
        user = await check_user(UID)
        assert (user["first_name"], user["phone"], user["address"], user["city"]) == (None, None, None, None)
        assert _callbacks(call.message.edit_text.await_args.kwargs["reply_markup"]) == ["close"]
        assert await fsm_context.get_state() is None

    async def test_delete_waits_for_an_order_in_progress(self, make_callback_query, fsm_context, user_factory,
                                                         item_factory):
        from bot.database.methods.create import add_to_cart
        from bot.database.methods.orders import create_order_transaction

        await user_factory(telegram_id=UID)
        await item_factory(name="Mug", price=40, stock=5)
        await add_to_cart(UID, "Mug", 1)
        ok, _code, _order = await create_order_transaction(
            UID, payment_method="cod", fulfillment="pickup", customer_name="Ana", phone="+37369000000",
            address=None, comment=None)
        assert ok, _code
        call = make_callback_query(data="my_data_erase_yes", user_id=UID)
        await my_data_erase_handler(call, fsm_context)
        text = call.message.edit_text.await_args.args[0]
        assert text in {TRANSLATIONS[lang]["my_data.erase.active_orders"] for lang in LANGS}
        assert (await check_user(UID)) is not None
