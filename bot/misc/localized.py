"""Display text for catalog entries in the viewer's language.

``name`` / ``description`` on categories and products are the canonical main-language text and
the lookup keys; ``name_<lang>`` / ``description_<lang>`` are optional translations. A missing or
blank translation falls back to the canonical text, so nothing is ever empty.
"""
import re
from typing import Any

from bot.i18n.main import current_language

LANGS = ("en", "ru", "ro")
MAX_NAME_LEN = 100
MAX_DESCRIPTION_LEN = 4000

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TAGS = re.compile(r"<[^>]*>")
_SPACES = re.compile(r"[ \t]+")


def _get(row: Any, key: str):
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def pick(row: Any, field: str, lang: str | None = None) -> str:
    """``row[field_<lang>]`` if set and non-blank, else the canonical ``row[field]``.

    ``row`` may be an ORM object or a (cached) dict. ``lang`` defaults to the language of the
    update/recipient being rendered.
    """
    lang = lang or current_language()
    value = _get(row, f"{field}_{lang}") if lang in LANGS else None
    if value is not None and str(value).strip():
        return str(value)
    canonical = _get(row, field)
    return "" if canonical is None else str(canonical)


def clean_name(value: str | None) -> str | None:
    """Normalize a name translation: strip tags/control chars, collapse spaces. Blank -> None."""
    if value is None:
        return None
    text = re.sub(r"\s+", " ", _TAGS.sub("", _CONTROL.sub("", value))).strip()
    return text or None


def clean_description(value: str | None) -> str | None:
    """Normalize a description translation (keeps line breaks). Blank -> None."""
    if value is None:
        return None
    text = "\n".join(_SPACES.sub(" ", line).strip() for line in _TAGS.sub("", _CONTROL.sub("", value)).splitlines())
    text = text.strip()
    return text or None
