"""The ☰ command menu: what is published per language and what each command opens."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import BotCommandScopeChat, BotCommandScopeDefault, Message

from bot.handlers.user.commands import (
    cart_command, catalog_command, favorites_command, language_command, orders_command, profile_command,
)
from bot.misc.bot_commands import COMMANDS, commands_for, set_user_commands, setup_bot_commands
from bot.states import ShopStates

UID = 950001


def _command(text, user_id=UID):
    """A real-Message-shaped mock (so `isinstance(.., Message)` holds), as the bottom-menu tests use."""
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


class TestMenuContent:

    def test_the_seven_commands_in_order(self):
        assert [c.command for c in commands_for("en")] == [
            "start", "catalog", "cart", "orders", "favorites", "profile", "language"]

    @pytest.mark.parametrize("lang", ["en", "ru", "ro"])
    def test_telegram_limits(self, lang):
        for c in commands_for(lang):
            assert c.command == c.command.lower() and 1 <= len(c.command) <= 32
            assert 3 <= len(c.description) <= 256

    def test_descriptions_are_translated(self):
        by = {lang: [c.description for c in commands_for(lang)] for lang in ("en", "ru", "ro")}
        assert by["en"][2] == "Cart" and by["ru"][2] == "Корзина" and by["ro"][2] == "Coș"
        assert len({tuple(v) for v in by.values()}) == 3
        assert all(d and not d.startswith("cmd.") for v in by.values() for d in v)

    def test_every_description_key_exists_in_every_language(self):
        from bot.i18n.strings import TRANSLATIONS
        for lang in ("en", "ru", "ro"):
            for _name, key in COMMANDS:
                assert TRANSLATIONS[lang].get(key), (lang, key)


class TestPublishing:

    async def test_one_list_per_language_plus_a_default(self):
        bot = MagicMock()
        bot.set_my_commands = AsyncMock()
        await setup_bot_commands(bot)
        calls = bot.set_my_commands.await_args_list
        languages = sorted(c.kwargs.get("language_code") or "-" for c in calls)
        assert languages == ["-", "en", "ro", "ru"]
        assert all(isinstance(c.kwargs["scope"], BotCommandScopeDefault) for c in calls)

    async def test_a_failure_never_stops_startup(self):
        bot = MagicMock()
        bot.set_my_commands = AsyncMock(side_effect=RuntimeError("telegram down"))
        await setup_bot_commands(bot)                       # no raise
        await set_user_commands(bot, UID, "ru")             # no raise

    async def test_per_chat_menu_uses_the_chosen_language(self):
        bot = MagicMock()
        bot.set_my_commands = AsyncMock()
        await set_user_commands(bot, UID, "ru")
        (call,) = bot.set_my_commands.await_args_list
        assert call.args[0][2].description == "Корзина"
        assert isinstance(call.kwargs["scope"], BotCommandScopeChat) and call.kwargs["scope"].chat_id == UID


class TestCommands:

    @pytest.fixture(autouse=True)
    async def _user(self, user_factory, item_factory):
        await user_factory(telegram_id=UID)
        await item_factory(name="CmdItem", price=10, stock=2)

    async def test_catalog_opens_the_categories(self, fsm_context):
        msg = _command("/catalog")
        await fsm_context.update_data(junk=1)
        await catalog_command(msg, fsm_context)
        assert await fsm_context.get_state() == ShopStates.viewing_categories
        assert "junk" not in await fsm_context.get_data()           # a flow in progress is dropped
        msg.answer.assert_awaited()
        msg.delete.assert_awaited()                                  # the typed command is removed (clean chat)

    async def test_cart_orders_favorites_profile_open_their_screens(self, fsm_context):
        for handler, expect in ((cart_command, "cart.empty"), (orders_command, "orders.empty"),
                                (favorites_command, "favorites.empty"), (profile_command, "profile.id")):
            msg = _command("/x")
            await handler(msg, fsm_context)
            sent = " ".join(str(c.args[0]) for c in msg.answer.await_args_list)
            assert expect in sent, (handler.__name__, sent)

    async def test_language_opens_the_picker(self, fsm_context):
        msg = _command("/language")
        await language_command(msg, fsm_context)
        markup = msg.answer.await_args.kwargs["reply_markup"]
        assert [b.callback_data for r in markup.inline_keyboard for b in r][:3] == ["lang:en", "lang:ru", "lang:ro"]

    async def test_a_command_abandons_a_text_state(self, fsm_context):
        from bot.states import CheckoutFSM
        await fsm_context.set_state(CheckoutFSM.waiting_address)
        await cart_command(_command("/cart"), fsm_context)
        assert await fsm_context.get_state() is None
