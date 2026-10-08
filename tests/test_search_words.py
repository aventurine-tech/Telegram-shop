"""Catalog search by the words that describe a product."""
import pytest

from bot.database.methods.create import create_category, create_item, create_item_option
from bot.database.methods.lazy_queries import query_goods_search
from bot.misc.search_terms import MAX_TERMS, split_terms, term_patterns


class TestSplitTerms:

    def test_lower_case_unique_and_trimmed(self):
        assert split_terms('  Cherry,  "50mg" cherry ') == ["cherry", "50mg"]

    def test_empty_and_blank(self):
        assert split_terms("") == [] and split_terms("   ") == [] and split_terms(None) == []

    def test_capped(self):
        assert len(split_terms(" ".join(f"w{i}" for i in range(20)))) == MAX_TERMS

    def test_wildcards_are_escaped(self):
        assert term_patterns("100%") == ["%100\\%%"]

    def test_number_and_unit_may_be_apart(self):
        assert term_patterns("50mg") == ["%50%mg%"]

    def test_comma_and_cedilla_spellings_are_both_tried(self):
        assert len(term_patterns("şampon")) == 2 and len(term_patterns("șampon")) == 2


@pytest.fixture
async def shop():
    await create_category("Vapes")
    await create_category("Tea", names={"en": "Tea", "ro": "Ceai"})
    await create_item("Cherry Ice", "Sweet cherry with menthol", 10, "Vapes", stock=5)
    await create_item("Mango Bomb", "Tropical mango flavour", 10, "Vapes", stock=5, names={"ro": "Mango Explozie"})
    await create_item("Green Leaf", "Loose leaf green tea", 4, "Tea", stock=5)
    assert (await create_item_option("Cherry Ice", "20 mg", 10, stock=3))[0]
    assert (await create_item_option("Cherry Ice", "50 mg", 12, stock=3))[0]


class TestWordSearch:

    async def test_every_word_must_match(self, shop):
        assert await query_goods_search("cherry menthol") == ["Cherry Ice"]
        assert await query_goods_search("cherry mango") == []

    async def test_word_order_does_not_matter(self, shop):
        assert await query_goods_search("menthol cherry") == ["Cherry Ice"]

    async def test_finds_by_flavour_in_the_description(self, shop):
        assert await query_goods_search("tropical") == ["Mango Bomb"]

    async def test_finds_by_option_strength_and_returns_the_head_once(self, shop):
        assert await query_goods_search("50 mg") == ["Cherry Ice"]
        assert await query_goods_search("50mg") == ["Cherry Ice"]
        assert await query_goods_search("cherry 50mg", count_only=True) == 1
        assert await query_goods_search("90 mg") == []

    async def test_finds_by_category_in_any_language(self, shop):
        assert await query_goods_search("ceai") == ["Green Leaf"]
        assert await query_goods_search("vapes", count_only=True) == 2

    async def test_name_matches_come_first(self, shop):
        await create_item("Plain", "has mango in the text", 1, "Tea", stock=1)
        assert await query_goods_search("mango") == ["Mango Bomb", "Plain"]

    async def test_translated_name_still_matches(self, shop):
        assert await query_goods_search("explozie") == ["Mango Bomb"]

    async def test_blank_and_wildcard_queries_find_nothing(self, shop):
        assert await query_goods_search("   ") == [] and await query_goods_search("", count_only=True) == 0
        assert await query_goods_search("%") == [] and await query_goods_search("_") == []

    async def test_cedilla_typed_for_a_comma_name(self):
        await create_category("Cosmetice")
        await create_item("Bio șampon", "pentru păr", 5, "Cosmetice", stock=1)
        assert await query_goods_search("şampon") == ["Bio șampon"]
        assert await query_goods_search("șampon") == ["Bio șampon"]

    async def test_paging_and_count_agree(self, shop):
        assert await query_goods_search("vapes", count_only=True) == 2
        assert len(await query_goods_search("vapes", limit=1)) == 1
        assert len(await query_goods_search("vapes", offset=1, limit=1)) == 1
