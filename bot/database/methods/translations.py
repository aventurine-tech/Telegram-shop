"""Translations of category/product names and product descriptions (display text only).

The canonical ``name`` / ``description`` (main language) are never touched here — they are the
lookup keys. A blank value clears a translation, which then falls back to the canonical text.
"""
from sqlalchemy import select

from bot.database import Database
from bot.database.methods.cache_utils import safe_create_task
from bot.database.methods.read import invalidate_item_cache, invalidate_category_cache
from bot.database.models import Goods, Categories
from bot.misc.localized import (
    LANGS, MAX_NAME_LEN, MAX_DESCRIPTION_LEN, clean_name, clean_description, pick,
)


def _validate(translations: dict, fields: dict[str, int], cleaners: dict) -> tuple[dict, str | None]:
    """Normalize ``{lang: {field: text}}``; returns (clean, error_code)."""
    clean: dict[str, dict[str, str | None]] = {}
    for lang, values in translations.items():
        if lang not in LANGS:
            return {}, "invalid_language"
        clean[lang] = {}
        for field, text in values.items():
            if field not in fields:
                return {}, "invalid_field"
            value = cleaners[field](text)
            if value is not None and len(value) > fields[field]:
                return {}, "too_long"
            clean[lang][field] = value
    return clean, None


async def set_category_translations(category_name: str, names: dict[str, str | None]) -> tuple[bool, str]:
    """Set/clear category name translations: ``{"ro": "Mobilă", "en": None}`` (None/blank clears).

    Returns ``(ok, code)``; codes: success, category_not_found, invalid_language, too_long.
    """
    clean, err = _validate({l: {"name": v} for l, v in names.items()},
                           {"name": MAX_NAME_LEN}, {"name": clean_name})
    if err:
        return False, err
    async with Database().session() as s:
        cat = (await s.execute(
            select(Categories).where(Categories.name == category_name).with_for_update()
        )).scalars().one_or_none()
        if not cat:
            return False, "category_not_found"
        for lang, values in clean.items():
            setattr(cat, f"name_{lang}", values["name"])

    safe_create_task(invalidate_category_cache(category_name))
    return True, "success"


async def set_item_translations(item_name: str, translations: dict[str, dict[str, str | None]]
                                ) -> tuple[bool, str]:
    """Set/clear product translations: ``{"ro": {"name": "...", "description": "..."}}``.

    Only the fields present are changed. Codes: success, item_not_found, invalid_language,
    invalid_field, too_long.
    """
    clean, err = _validate(
        translations,
        {"name": MAX_NAME_LEN, "description": MAX_DESCRIPTION_LEN},
        {"name": clean_name, "description": clean_description},
    )
    if err:
        return False, err
    async with Database().session() as s:
        item = (await s.execute(
            select(Goods).where(Goods.name == item_name).with_for_update()
        )).scalars().one_or_none()
        if not item:
            return False, "item_not_found"
        for lang, values in clean.items():
            for field, value in values.items():
                setattr(item, f"{field}_{lang}", value)

    safe_create_task(invalidate_item_cache(item_name))
    return True, "success"


async def category_labels(names: list[str], lang: str | None = None) -> dict[str, str]:
    """``{canonical name: display name in lang}`` for a page of categories, in one query."""
    names = list(dict.fromkeys(names))
    if not names:
        return {}
    async with Database().session() as s:
        rows = (await s.execute(select(Categories).where(Categories.name.in_(names)))).scalars().all()
        found = {c.name: pick(c, "name", lang) for c in rows}
    return {n: found.get(n, n) for n in names}


async def item_labels(names: list[str], lang: str | None = None) -> dict[str, str]:
    """``{canonical name: display name in lang}`` for a page of products, in one query."""
    names = list(dict.fromkeys(names))
    if not names:
        return {}
    async with Database().session() as s:
        rows = (await s.execute(select(Goods).where(Goods.name.in_(names)))).scalars().all()
        found = {g.name: pick(g, "name", lang) for g in rows}
    return {n: found.get(n, n) for n in names}
