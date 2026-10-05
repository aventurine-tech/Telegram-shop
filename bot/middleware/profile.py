from typing import Any, Awaitable, Callable, Dict
import time

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from bot.database.methods.profiles import refresh_profile
from bot.logger_mesh import logger


class ProfileMiddleware(BaseMiddleware):
    """Keep each customer's name, @username and "last seen" up to date.

    Runs after the handler (a brand-new person is created by /start itself), writes only when something changed
    or the last write is older than ``INTERVAL`` seconds, so a busy chat costs no database write per tap.
    """

    INTERVAL = 300
    MAX_ENTRIES = 50_000

    def __init__(self) -> None:
        self._seen: dict[int, tuple[tuple, float]] = {}

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        finally:
            await self._touch(event)

    async def _touch(self, event: TelegramObject) -> None:
        user = getattr(event, "from_user", None)
        if user is None or getattr(user, "is_bot", False):
            return
        chat = getattr(event, "chat", None) or getattr(getattr(event, "message", None), "chat", None)
        if chat is not None and getattr(chat, "type", "private") != "private":
            return
        key = (user.username, user.first_name, user.last_name)
        now = time.monotonic()
        previous = self._seen.get(user.id)
        if previous and previous[0] == key and now - previous[1] < self.INTERVAL:
            return
        try:
            if await refresh_profile(user.id, user.username, user.first_name, user.last_name):
                if len(self._seen) >= self.MAX_ENTRIES:
                    self._seen.clear()
                self._seen[user.id] = (key, now)
        except Exception as e:                 # a profile refresh must never break the update
            logger.warning("profile refresh for %s failed: %s", user.id, e)
