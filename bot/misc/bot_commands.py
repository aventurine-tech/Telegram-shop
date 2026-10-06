"""The ☰ command menu next to the input field: one list per language."""
import logging

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from bot.i18n.main import LANGUAGE_CODES, get_locale, localize_in

logger = logging.getLogger(__name__)

# (command, description key) in menu order; /start already existed.
COMMANDS: tuple[tuple[str, str], ...] = (
    ("start", "cmd.start"),
    ("catalog", "cmd.catalog"),
    ("cart", "cmd.cart"),
    ("orders", "cmd.orders"),
    ("favorites", "cmd.favorites"),
    ("profile", "cmd.profile"),
    ("language", "cmd.language"),
)


def commands_for(lang: str | None) -> list[BotCommand]:
    return [BotCommand(command=name, description=localize_in(lang, key)) for name, key in COMMANDS]


async def setup_bot_commands(bot: Bot) -> None:
    """Publish the menu: one list per interface language (Telegram picks by the client's language) and a default
    in the shop's main language. A failure is logged and never stops the bot."""
    try:
        for lang in sorted(LANGUAGE_CODES):
            await bot.set_my_commands(commands_for(lang), scope=BotCommandScopeDefault(), language_code=lang)
        await bot.set_my_commands(commands_for(get_locale()), scope=BotCommandScopeDefault())
    except Exception as e:
        logger.warning("could not set the bot command menu: %s", e)


async def set_user_commands(bot: Bot, chat_id: int, lang: str) -> None:
    """Menu for one private chat in the language the person picked in the bot (it may differ from Telegram's)."""
    try:
        await bot.set_my_commands(commands_for(lang), scope=BotCommandScopeChat(chat_id=chat_id))
    except Exception as e:
        logger.warning("could not set the command menu of chat %s: %s", chat_id, e)
