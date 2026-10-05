"""Persistent bottom keyboard (Telegram reply keyboard): Catalog, Cart, Profile on every screen."""
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from bot.i18n import localize
from bot.i18n.strings import TRANSLATIONS

# Button key -> the screen it opens.
_NAV_KEYS = (
    ("btn.nav.catalog", "catalog"),
    ("btn.nav.cart", "cart"),
    ("btn.nav.profile", "profile"),
)


def bottom_nav_keyboard() -> ReplyKeyboardMarkup:
    """One persistent row, labelled in the current user's language (no live counts: it can't be refreshed silently)."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=localize(key)) for key, _ in _NAV_KEYS]],
        is_persistent=True,
        resize_keyboard=True,
    )


def all_nav_labels() -> dict[str, str]:
    """{label in any language: "catalog" | "cart" | "profile"}.

    The user may have switched language since the keyboard was shown, so a tap is matched against every locale.
    """
    labels: dict[str, str] = {}
    for strings in TRANSLATIONS.values():
        for key, target in _NAV_KEYS:
            label = strings.get(key)
            if label:
                labels[label] = target
    return labels
