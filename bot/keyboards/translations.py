"""Keyboards of the catalog translations: the Skip prompt of the add wizards and the editor."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.i18n import localize, LANGUAGES


def language_label(code: str) -> str:
    return dict(LANGUAGES).get(code, code)


def skip_keyboard(skip_cb: str, back_cb: str) -> InlineKeyboardMarkup:
    """Skip + Back under a translation prompt of an add wizard."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=localize('admin.translations.btn.skip'), callback_data=skip_cb))
    kb.row(InlineKeyboardButton(text=localize('btn.back'), callback_data=back_cb))
    return kb.as_markup()


def editor_keyboard(langs: list[str], with_description: bool) -> InlineKeyboardMarkup:
    """One row per editable language: its name (and description) button. ``tr:e:<lang>:<n|d>``."""
    kb = InlineKeyboardBuilder()
    for lang in langs:
        row = [InlineKeyboardButton(
            text=f"{language_label(lang)} · {localize('admin.translations.btn.name')}",
            callback_data=f"tr:e:{lang}:n")]
        if with_description:
            row.append(InlineKeyboardButton(
                text=f"{language_label(lang)} · {localize('admin.translations.btn.description')}",
                callback_data=f"tr:e:{lang}:d"))
        kb.row(*row)
    kb.row(InlineKeyboardButton(text=localize('btn.back'), callback_data='tr:back'))
    return kb.as_markup()


def field_keyboard() -> InlineKeyboardMarkup:
    """Under the "type the text" prompt: Clear and Back to the editor."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=localize('admin.translations.btn.clear'), callback_data='tr:clear'))
    kb.row(InlineKeyboardButton(text=localize('btn.back'), callback_data='tr:card'))
    return kb.as_markup()
