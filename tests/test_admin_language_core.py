"""Shared rules for entering catalog text in several languages."""
import pytest

from bot.database.methods.create import create_category, create_item
from bot.database.methods.read import resolve_item_name, resolve_category_name
from bot.misc.localized import derive_canonical


class TestDeriveCanonical:

    @pytest.mark.parametrize("texts,main,viewer,expected", [
        ({"ro": "Scaun", "en": "Chair"}, "ro", "en", "Scaun"),          # main language wins
        ({"en": "Chair"}, "ro", "en", "Chair"),                          # else the admin's language
        ({"ru": "Стул", "en": "Chair"}, "ro", "ro", "Chair"),            # else first filled: en, ru, ro
        ({"ru": "Стул"}, "ro", "en", "Стул"),
        ({"ro": "  ", "en": " Chair "}, "ro", "en", "Chair"),            # blank main is ignored, text is stripped
        ({}, "ro", "en", None),
        ({"ro": None, "en": "", "ru": "  "}, "ro", None, None),
        ({"en": "Chair"}, "ro", None, "Chair"),
    ])
    def test_rule(self, texts, main, viewer, expected):
        assert derive_canonical(texts, main, viewer) == expected


class TestResolveNames:

    async def _setup(self):
        await create_category("Mobilă", names={"en": "Furniture", "ru": "Мебель"})
        await create_item("Scaun", "d", 10, "Mobilă", names={"en": "Chair", "ru": "Стул"})
        await create_item("Masă", "d", 10, "Mobilă")

    async def test_canonical_name_resolves_to_itself(self):
        await self._setup()
        assert await resolve_item_name("Scaun") == "Scaun"
        assert await resolve_category_name("Mobilă") == "Mobilă"

    @pytest.mark.parametrize("typed", ["Chair", "chair", " CHAIR ", "Стул", "стул"])
    async def test_translated_names_resolve_to_canonical(self, typed):
        await self._setup()
        assert await resolve_item_name(typed) == "Scaun"

    async def test_category_translations(self):
        await self._setup()
        assert await resolve_category_name("furniture") == "Mobilă"
        assert await resolve_category_name("Мебель") == "Mobilă"

    @pytest.mark.parametrize("typed", ["", "   ", "Nope", "Chai"])
    async def test_unknown_or_blank(self, typed):
        await self._setup()
        assert await resolve_item_name(typed) is None
        assert await resolve_category_name(typed) is None

    async def test_canonical_beats_a_translation_of_another_item(self):
        await create_category("C")
        await create_item("Alpha", "d", 1, "C")
        await create_item("Beta", "d", 1, "C", names={"en": "Alpha"})
        assert await resolve_item_name("Alpha") == "Alpha"
