"""Persistent bottom keyboard: Catalog / Cart / Profile."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Dispatcher
from aiogram.enums.chat_type import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, ReplyKeyboardMarkup

from bot.handlers.main import register_all_handlers
from bot.handlers.user import bottom_nav
from bot.handlers.user import main as user_main
from bot.handlers.user.main import open_main_menu, start
from bot.i18n import main as i18n
from bot.i18n.strings import TRANSLATIONS
from bot.keyboards import reply
from bot.keyboards.reply import all_nav_labels, bottom_nav_keyboard
from bot.states import ShopStates
from bot.states.category_state import CategoryFSM
from bot.states.checkout_state import CheckoutFSM

_KEYS = ("btn.nav.catalog", "btn.nav.cart", "btn.nav.profile")


def _tap(text, user_id=910001, chat_type=ChatType.PRIVATE):
    """A real-Message-shaped mock (so `isinstance(.., Message)` holds) for a tap on the bottom keyboard."""
    msg = AsyncMock(spec=Message)
    msg.text = text
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.from_user.first_name = "Tester"
    msg.chat = MagicMock()
    msg.chat.type = chat_type
    msg.answer = AsyncMock()
    msg.delete = AsyncMock()
    return msg


def _callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


@pytest.fixture
def real_nav_localize():
    with patch('bot.keyboards.reply.localize', i18n.localize), \
            patch('bot.handlers.user.main.localize', i18n.localize):
        yield


@pytest.fixture
def env_menu():
    with patch('bot.handlers.user.main.EnvKeys') as env:
        env.OWNER_ID = 999999
        env.CHANNEL_URL = ""
        env.CHANNEL_ID = ""
        env.HELPER_ID = ""
        env.RULES = ""
        env.REFERRAL_PERCENT = 10
        env.PAY_CURRENCY = "MDL"
        yield env


class TestKeyboard:

    def test_persistent_resized_single_row_of_three(self):
        kb = bottom_nav_keyboard()
        assert isinstance(kb, ReplyKeyboardMarkup)
        assert kb.is_persistent is True and kb.resize_keyboard is True
        assert len(kb.keyboard) == 1 and len(kb.keyboard[0]) == 3
        assert [b.text for b in kb.keyboard[0]] == list(_KEYS)   # key echo under the autouse fixture

    @pytest.mark.parametrize("lang", sorted(TRANSLATIONS))
    def test_labels_localized_per_language(self, lang, real_nav_localize):
        with i18n.use_language(lang):
            kb = bottom_nav_keyboard()
        assert [b.text for b in kb.keyboard[0]] == [i18n.localize_in(lang, k) for k in _KEYS]

    def test_english_labels(self):
        assert [i18n.localize_in("en", k) for k in _KEYS] == ["🛍 Catalog", "🛒 Cart", "👤 Profile"]

    def test_all_nav_labels_cover_every_locale(self):
        labels = all_nav_labels()
        for lang, strings in TRANSLATIONS.items():
            for key, target in zip(_KEYS, ("catalog", "cart", "profile")):
                assert labels[strings[key]] == target
        assert set(labels.values()) == {"catalog", "cart", "profile"}

    def test_every_locale_defines_nav_keys(self):
        for strings in TRANSLATIONS.values():
            assert all(k in strings for k in (*_KEYS, "menu.quick"))


class TestTaps:

    async def test_catalog_opens_categories_as_new_message(self, fsm_context, category_factory):
        await category_factory("Shoes")
        msg = _tap("🛍 Catalog")
        await bottom_nav.bottom_nav_tap(msg, fsm_context)

        msg.answer.assert_awaited_once()
        assert msg.answer.await_args.args[0] == "shop.categories.title"
        assert "cat:0:0" in _callbacks(msg.answer.await_args.kwargs["reply_markup"])
        assert await fsm_context.get_state() == ShopStates.viewing_categories

    async def test_cart_opens_cart_as_new_message(self, fsm_context, user_factory):
        await user_factory(telegram_id=910002)
        msg = _tap("🛒 Cart", user_id=910002)
        await bottom_nav.bottom_nav_tap(msg, fsm_context)

        msg.answer.assert_awaited_once()
        assert msg.answer.await_args.args[0] == "cart.title\n\ncart.empty"
        assert _callbacks(msg.answer.await_args.kwargs["reply_markup"]) == ["profile"]

    async def test_profile_opens_profile_for_the_user_not_the_bot(self, fsm_context, user_factory, env_menu):
        await user_factory(telegram_id=910003)
        msg = _tap("👤 Profile", user_id=910003)
        await bottom_nav.bottom_nav_tap(msg, fsm_context)

        msg.answer.assert_awaited_once()
        assert msg.answer.await_args.args[0].startswith("profile.caption")
        assert msg.answer.await_args.kwargs["parse_mode"] == "HTML"

    @pytest.mark.parametrize("lang,target", [("ru", "cart"), ("en", "cart"), ("ro", "cart"),
                                             ("ru", "profile"), ("ro", "catalog")])
    async def test_label_in_any_language_matches(self, lang, target):
        key = {"catalog": _KEYS[0], "cart": _KEYS[1], "profile": _KEYS[2]}[target]
        assert all_nav_labels()[i18n.localize_in(lang, key)] == target

    @pytest.mark.parametrize("state", [CheckoutFSM.waiting_name, CheckoutFSM.waiting_address,
                                       CategoryFSM.waiting_add_category])
    async def test_tap_clears_any_flow(self, state, fsm_context, user_factory, env_menu):
        await user_factory(telegram_id=910004)
        await fsm_context.set_state(state)
        await fsm_context.update_data(name="x")
        msg = _tap("👤 Profile", user_id=910004)
        await bottom_nav.bottom_nav_tap(msg, fsm_context)
        assert await fsm_context.get_state() is None
        assert await fsm_context.get_data() == {}

    async def test_tap_message_deleted(self, fsm_context, user_factory):
        await user_factory(telegram_id=910005)
        msg = _tap("🛒 Cart", user_id=910005)
        await bottom_nav.bottom_nav_tap(msg, fsm_context)
        msg.delete.assert_awaited_once()

    @pytest.mark.parametrize("exc", [TelegramBadRequest(MagicMock(), "can't delete"), RuntimeError("boom")])
    async def test_delete_failure_ignored(self, exc, fsm_context, user_factory):
        await user_factory(telegram_id=910006)
        msg = _tap("🛒 Cart", user_id=910006)
        msg.delete.side_effect = exc
        await bottom_nav.bottom_nav_tap(msg, fsm_context)
        msg.answer.assert_awaited_once()

    async def test_handler_matches_only_nav_text_in_private_chats(self):
        handler = bottom_nav.router.message.handlers[0]
        assert await handler.filters[0].call(_tap("🛒 Cart")) is True
        assert not await handler.filters[0].call(_tap("hello"))
        chat_filter = bottom_nav.router.message._handler.filters[0]    # router-level: private chats only
        assert await chat_filter.call(_tap("x")) is True
        assert not await chat_filter.call(_tap("x", chat_type=ChatType.GROUP))


class TestSending:

    async def test_start_sends_keyboard_before_inline_menu(self, make_message, fsm_context, env_menu):
        msg = make_message(text="/start", user_id=910010)
        msg.chat.type = ChatType.PRIVATE
        await start(msg, fsm_context)

        calls = msg.answer.await_args_list
        assert [c.args[0] for c in calls] == ["menu.quick", "menu.title"]
        assert isinstance(calls[0].kwargs["reply_markup"], ReplyKeyboardMarkup)
        assert not isinstance(calls[1].kwargs["reply_markup"], ReplyKeyboardMarkup)

    async def test_not_sent_with_subscription_prompt(self, make_message, env_menu):
        msg = make_message(text="/start", user_id=910011)
        with patch('bot.handlers.user.main._parse_channel_username', return_value="chan"), \
                patch('bot.handlers.user.main._is_subscribed', new_callable=AsyncMock, return_value=False):
            await open_main_menu(msg, 910011, 1)
        assert [c.args[0] for c in msg.answer.await_args_list] == ["subscribe.prompt"]

    async def test_sent_after_language_change(self, make_callback_query, fsm_context, user_factory, env_menu):
        from bot.handlers.user import language as lang_h
        await user_factory(telegram_id=910012, language="en")
        call = make_callback_query(data="lang:ru", user_id=910012)
        await lang_h.choose_language(call, fsm_context)
        sent = call.message.answer.await_args
        assert sent.args[0] == "menu.quick"
        assert isinstance(sent.kwargs["reply_markup"], ReplyKeyboardMarkup)


class TestRouterOrder:

    def test_bottom_nav_after_language_before_admin_and_user(self):
        from bot.handlers.admin import router as admin_router
        from bot.handlers.user import router as user_router
        from bot.handlers.user.language import router as language_router
        dp = Dispatcher()
        register_all_handlers(dp)
        order = list(dp.sub_routers)
        assert order.index(language_router) < order.index(bottom_nav.router) < order.index(admin_router)
        assert order.index(bottom_nav.router) < order.index(user_router)
