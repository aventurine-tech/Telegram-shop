from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from html import escape as _html_escape
from typing import Any, Iterator

from bot.misc import EnvKeys
from .strings import TRANSLATIONS, DEFAULT_LOCALE
from bot.logger_mesh import logger

# Languages a person can choose, in picker order: (code, name shown in the picker).
LANGUAGES: tuple[tuple[str, str], ...] = (
    ("en", "🇬🇧 English"),
    ("ru", "🇷🇺 Русский"),
    ("ro", "🇷🇴 Română"),
)
LANGUAGE_CODES = frozenset(code for code, _ in LANGUAGES)

# The language of whoever the current update/request belongs to. Unset = use the bot default.
_current_language: ContextVar[str | None] = ContextVar("current_language", default=None)


def esc(value: Any) -> str:
    """Escape a value for interpolation into a message."""
    return _html_escape("" if value is None else str(value), quote=False)


@lru_cache(maxsize=1)
def get_locale() -> str:
    """The bot-wide default (BOT_LOCALE): used for people who haven't chosen a language and for system text."""
    loc = EnvKeys.BOT_LOCALE.lower().strip()
    return loc if loc in TRANSLATIONS else DEFAULT_LOCALE


def current_language() -> str:
    """Language `localize` will use right now."""
    lang = _current_language.get()
    return lang if lang in TRANSLATIONS else get_locale()


def set_language(lang: str | None):
    """Set the current language; returns the token for `reset_language`."""
    return _current_language.set(lang if lang in LANGUAGE_CODES else None)


def reset_language(token) -> None:
    _current_language.reset(token)


@contextmanager
def use_language(lang: str | None) -> Iterator[None]:
    """Render everything inside the block in ``lang`` (None/unknown = the bot default)."""
    token = set_language(lang)
    try:
        yield
    finally:
        reset_language(token)


def localize(key: str, /, **kwargs: Any) -> str:
    """
    Get translation by key.
    Fallback: current language -> DEFAULT_LOCALE -> the key itself.
    """
    loc = current_language()

    text = TRANSLATIONS.get(loc, {}).get(key)
    if text is None:
        text = TRANSLATIONS.get(DEFAULT_LOCALE, {}).get(key)
    if text is None:
        text = key

    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Failed to format translation key '{key}' with kwargs {kwargs}: {e}")

    return str(text)


def localize_in(lang: str | None, key: str, /, **kwargs: Any) -> str:
    """`localize` for a specific recipient's language (a message sent to someone else)."""
    with use_language(lang):
        return localize(key, **kwargs)
