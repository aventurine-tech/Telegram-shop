"""Screen helper for handlers reachable from a product card, which may be a photo message."""
import contextlib

from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message


def is_photo_message(message) -> bool:
    """True for a real photo message (a non-empty list), never for a bare mock attribute."""
    photo = getattr(message, 'photo', None)
    return isinstance(photo, list) and bool(photo)


async def edit_screen(target, text: str, reply_markup=None, **kwargs):
    """Show `text` in place of the message the user pressed a button on.

    Telegram cannot edit a photo message into text, so a photo message is deleted and the screen
    is sent as a fresh message; anything else is edited exactly as `edit_text` would.
    `target` is a CallbackQuery (its `.message` is used) or a Message. A real Message (e.g. a bottom-keyboard
    tap) has nothing to edit, so the screen is answered as a new message.
    """
    if isinstance(target, Message):
        return await target.answer(text, reply_markup=reply_markup, **kwargs)
    message = target.message if hasattr(target, 'message') else target
    if is_photo_message(message):
        with contextlib.suppress(TelegramAPIError):
            await message.delete()
        return await message.answer(text, reply_markup=reply_markup, **kwargs)
    return await message.edit_text(text, reply_markup=reply_markup, **kwargs)
