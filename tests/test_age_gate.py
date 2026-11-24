"""The 18+ question asked before the menu and the catalog (D-27)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.enums.chat_type import ChatType
from aiogram.types import CallbackQuery, Message

from bot.database.methods.read import check_user, invalidate_user_cache
from bot.database.methods.update import set_age_confirmed, set_user_language
from bot.handlers.user import age_gate, language as lang_h, legal
from bot.handlers.user.age_gate import NeedsAge, needs_age
from bot.i18n import use_language
from bot.i18n.strings_legal import TRANSLATIONS

LANGS = ("en", "ru", "ro")


@pytest.fixture
def env(monkeypatch):
    def _set(**values):
        for name, value in values.items():
            monkeypatch.setattr(legal.EnvKeys, name, value, raising=False)
    _set(ADULTS_ONLY="1", BUSINESS_ONLY="0")
    return _set


@pytest.fixture
def customer(user_factory):
    """A registered person who has chosen a language and has not been asked their age."""
    async def _create(telegram_id: int, language: str | None = "en"):
        await user_factory(telegram_id=telegram_id)
        if language:
            await set_user_language(telegram_id, language)
        await invalidate_user_cache(telegram_id)
        return telegram_id
    return _create


def _message(text: str, user_id: int, chat_type=ChatType.PRIVATE):
    msg = MagicMock(spec=Message)
    msg.text = text
    msg.from_user = MagicMock(id=user_id)
    msg.chat = MagicMock(type=chat_type)
    return msg


def _call(data: str, user_id: int, chat_type=ChatType.PRIVATE):
    call = MagicMock(spec=CallbackQuery)
    call.data = data
    call.from_user = MagicMock(id=user_id)
    call.message = MagicMock()
    call.message.chat = MagicMock(type=chat_type)
    return call


class TestWhoIsAsked:

    async def test_everything_leads_to_the_question_until_it_is_answered(self, env, customer):
        user_id = await customer(940001)
        for text in ("/start", "/start 12345", "hello", "/orders", "/settings", "🛍 Catalog"):
            assert await NeedsAge()(_message(text, user_id)) is True, text
        for data in ("shop", "back_to_menu", "profile_language", "settings_mailings", "checkout_confirm"):
            assert await NeedsAge()(_call(data, user_id)) is True, data

    async def test_the_texts_help_support_and_language_stay_open(self, env, customer):
        user_id = await customer(940002)
        for text in ("/terms", "/privacy", "/help", "/support", "/paysupport", "/language", "/TERMS", "/terms@shop_bot"):
            assert await NeedsAge()(_message(text, user_id)) is False, text
        for data in ("age:yes", "age:no", "lang:ru", "close", "legal_privacy", "my_data", "my_data_erase",
                     "my_data_erase_yes"):
            assert await NeedsAge()(_call(data, user_id)) is False, data

    async def test_only_private_chats(self, env, customer):
        user_id = await customer(940003)
        assert await NeedsAge()(_message("/start", user_id, ChatType.GROUP)) is False
        assert await NeedsAge()(_call("shop", user_id, ChatType.SUPERGROUP)) is False

    async def test_the_language_is_asked_first(self, env, customer):
        user_id = await customer(940004, language=None)
        assert await NeedsAge()(_message("/start", user_id)) is False        # the language picker takes this one
        assert await NeedsAge()(_message("/start", 940099)) is False         # nobody we know yet

    async def test_asked_once(self, env, customer):
        user_id = await customer(940005)
        assert await needs_age(user_id) is True
        assert await set_age_confirmed(user_id) is True
        await invalidate_user_cache(user_id)
        assert await needs_age(user_id) is False
        assert await NeedsAge()(_message("/start", user_id)) is False
        assert await NeedsAge()(_call("shop", user_id)) is False

    async def test_follows_the_shop_settings(self, env, customer):
        user_id = await customer(940006)
        env(ADULTS_ONLY="0", BUSINESS_ONLY="0")
        assert await needs_age(user_id) is False              # a shop for everyone asks nothing
        env(ADULTS_ONLY="0", BUSINESS_ONLY="1")
        assert await needs_age(user_id) is True               # trade-only includes 18+
        env(ADULTS_ONLY="1", BUSINESS_ONLY="0")
        assert await needs_age(user_id) is True

    async def test_an_unknown_person_cannot_confirm(self):
        assert await set_age_confirmed(940098) is False


class TestTheQuestion:

    async def test_a_message_gets_the_question_and_drops_the_flow(self, env, customer, make_message, fsm_context):
        user_id = await customer(941001)
        await fsm_context.set_state("CheckoutFSM:confirming")
        msg = make_message(text="/start", user_id=user_id)
        with use_language("en"):
            await age_gate.message_before_age(msg, fsm_context)
        sent = msg.answer.await_args
        assert sent.args[0] == TRANSLATIONS["en"]["age.ask"]
        assert [b.callback_data for row in sent.kwargs["reply_markup"].inline_keyboard for b in row] == ["age:yes", "age:no"]
        msg.delete.assert_awaited_once()
        assert await fsm_context.get_state() is None

    async def test_an_old_button_gets_the_question(self, env, customer, make_callback_query):
        user_id = await customer(941002)
        call = make_callback_query(data="shop", user_id=user_id)
        call.message.answer = AsyncMock()
        with use_language("ru"):
            await age_gate.callback_before_age(call)
        call.answer.assert_awaited_once()
        assert call.message.answer.await_args.args[0] == TRANSLATIONS["ru"]["age.ask"]

    async def test_yes_is_saved_and_opens_the_menu(self, env, customer, make_callback_query, fsm_context):
        user_id = await customer(941003)
        call = make_callback_query(data="age:yes", user_id=user_id)
        call.message.delete = AsyncMock()
        with patch.object(age_gate, "open_main_menu", new=AsyncMock()) as menu:
            await age_gate.age_confirmed(call, fsm_context)
        user = await check_user(user_id)
        first = user["age_confirmed_at"]
        assert first is not None
        call.message.delete.assert_awaited_once()
        menu.assert_awaited_once()
        assert menu.await_args.args[1] == user_id
        assert await needs_age(user_id) is False

        with patch.object(age_gate, "open_main_menu", new=AsyncMock()):        # a second tap keeps the first date
            await age_gate.age_confirmed(make_callback_query(data="age:yes", user_id=user_id), fsm_context)
        assert (await check_user(user_id))["age_confirmed_at"] == first

    async def test_no_saves_nothing_and_keeps_the_bot_closed(self, env, customer, make_callback_query):
        user_id = await customer(941004)
        call = make_callback_query(data="age:no", user_id=user_id)
        with use_language("ro"):
            await age_gate.age_declined(call)
        assert call.message.edit_text.await_args.args[0] == TRANSLATIONS["ro"]["age.denied"]
        assert call.message.edit_text.await_args.kwargs.get("reply_markup") is None
        assert (await check_user(user_id))["age_confirmed_at"] is None
        assert await needs_age(user_id) is True               # asked again when they come back

    async def test_a_new_person_is_asked_right_after_choosing_a_language(self, env, make_callback_query, fsm_context):
        call = make_callback_query(data="lang:ro", user_id=941005)
        call.message.delete = AsyncMock()
        call.message.answer = AsyncMock()
        with patch.object(lang_h, "open_main_menu", new=AsyncMock()) as menu:
            await lang_h.choose_language(call, fsm_context)
        menu.assert_not_awaited()
        assert call.message.answer.await_args.args[0] == TRANSLATIONS["ro"]["age.ask"]
        assert (await check_user(941005))["language"] == "ro"

    async def test_changing_the_language_before_answering_asks_in_the_new_language(
            self, env, customer, make_callback_query, fsm_context):
        user_id = await customer(941006, language="en")
        call = make_callback_query(data="lang:ru", user_id=user_id)
        call.message.delete = AsyncMock()
        call.message.answer = AsyncMock()
        with patch.object(lang_h, "show_profile", new=AsyncMock()) as profile:
            await lang_h.choose_language(call, fsm_context)
        profile.assert_not_awaited()
        assert call.message.answer.await_args.args[0] == TRANSLATIONS["ru"]["age.ask"]


class TestAroundIt:

    @pytest.mark.parametrize("lang", LANGS)
    def test_the_question_points_at_the_texts_in_every_language(self, lang):
        text = TRANSLATIONS[lang]["age.ask"]
        assert "18" in text and "/terms" in text and "/privacy" in text
        assert "18" in TRANSLATIONS[lang]["btn.age.yes"] and TRANSLATIONS[lang]["btn.age.no"]
        assert "/privacy" in TRANSLATIONS[lang]["age.denied"]

    async def test_my_data_shows_the_confirmation(self, env, customer):
        user_id = await customer(942001)
        with use_language("en"):
            before = await legal.my_data_text(user_id)
            await set_age_confirmed(user_id)
            await invalidate_user_cache(user_id)
            after = await legal.my_data_text(user_id)
        label = TRANSLATIONS["en"]["my_data.label.age_confirmed"]
        assert label not in before and label in after
