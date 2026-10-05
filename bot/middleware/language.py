from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.database.methods.read import check_user_cached
from bot.i18n import use_language
from bot.logger_mesh import logger


class LanguageMiddleware(BaseMiddleware):
    """Run each update in its author's language.

    The language is read from the (cached) user row; no row or no choice yet means the bot default
    (BOT_LOCALE). It is held in a ContextVar for the handler's duration only, so concurrent updates
    never see each other's language, and it is reset even when the handler raises.
    """

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        lang = None
        if user is not None:
            try:
                row = await check_user_cached(user.id)
                lang = row.get("language") if row else None
            except Exception as e:  # a failed lookup must not take the update down: fall back to the default
                logger.warning("language lookup for %s failed: %s", user.id, e)

        with use_language(lang):
            return await handler(event, data)
