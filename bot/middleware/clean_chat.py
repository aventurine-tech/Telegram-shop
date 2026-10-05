"""Keep a private chat down to the one screen the user is on.

Every bot message sent while serving a user's update replaces the screen shown before it, and the
user's own messages are removed once handled, so the chat never accumulates navigation history.
Messages sent to *other* chats (staff notifications) or outside any update (broadcasts, sweeps) are
left alone. Everything here is best-effort: a message that cannot be deleted (older than 48 h,
already gone) is simply skipped.
"""
import contextlib
import contextvars
import os
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

# How many message ids before /start are swept in one go (Telegram's deleteMessages limit is 100).
START_SWEEP = 100
_MAX_TRACKED_CHATS = 50_000

_serving_chat: contextvars.ContextVar[int | None] = contextvars.ContextVar("clean_chat_serving", default=None)


def clean_chat_enabled() -> bool:
    return os.getenv("CLEAN_CHAT", "1").strip().lower() not in ("0", "false", "no", "off")


class ScreenTracker:
    """chat_id -> id of the bot message currently serving as that chat's screen (bounded LRU)."""

    def __init__(self, limit: int = _MAX_TRACKED_CHATS):
        self._limit = limit
        self._ids: OrderedDict[int, int] = OrderedDict()

    def get(self, chat_id: int) -> int | None:
        return self._ids.get(chat_id)

    def set(self, chat_id: int, message_id: int) -> None:
        self._ids[chat_id] = message_id
        self._ids.move_to_end(chat_id)
        while len(self._ids) > self._limit:
            self._ids.popitem(last=False)


tracker = ScreenTracker()


class CleanChatRequestMiddleware(BaseRequestMiddleware):
    """On a successful ``Send*`` into the chat being served: delete the previous screen, track the new one."""

    async def __call__(self, make_request, bot, method):
        result = await make_request(bot, method)
        chat_id = _serving_chat.get()
        if chat_id is None or not type(method).__name__.startswith("Send"):
            return result
        if getattr(method, "chat_id", None) != chat_id:
            return result
        sent = result[-1] if isinstance(result, list) and result else result
        message_id = getattr(sent, "message_id", None)
        if not isinstance(message_id, int):
            return result
        previous = tracker.get(chat_id)
        tracker.set(chat_id, message_id)
        if previous and previous != message_id:
            with contextlib.suppress(TelegramAPIError):
                await bot.delete_message(chat_id=chat_id, message_id=previous)
        return result


class CleanChatMiddleware(BaseMiddleware):
    """Outer middleware for messages and callbacks: marks the chat being served and tidies up after the handler."""

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any],
    ) -> Any:
        message = event if isinstance(event, Message) else getattr(event, "message", None)
        chat = getattr(message, "chat", None)
        if chat is None or getattr(chat, "type", None) != "private":
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            # The screen the user pressed a button on is the current one.
            tracker.set(chat.id, message.message_id)
        elif (event.text or "").startswith("/start"):
            await _sweep_before(event)

        token = _serving_chat.set(chat.id)
        try:
            return await handler(event, data)
        finally:
            _serving_chat.reset(token)
            if isinstance(event, Message):
                with contextlib.suppress(TelegramAPIError):
                    await event.delete()


async def _sweep_before(message: Message) -> None:
    """Clear the history above a /start: the ids just before it in the private chat."""
    first = max(1, message.message_id - START_SWEEP)
    ids = list(range(first, message.message_id))
    if not ids:
        return
    with contextlib.suppress(TelegramAPIError):
        await message.bot.delete_messages(chat_id=message.chat.id, message_ids=ids)
