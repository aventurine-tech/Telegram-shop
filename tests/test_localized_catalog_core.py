"""Catalog translations: storage, fallback, ordering, search and the order snapshot."""
import pytest
from sqlalchemy import select

from bot.database.main import Database
from bot.database.methods.create import create_category, create_item, add_to_cart
from bot.database.methods.lazy_queries import query_categories, query_items_in_category, query_goods_search
from bot.database.methods.orders import create_order_transaction, get_order
from bot.database.methods.read import get_cart_items, get_items_info, check_category, get_item_info
from bot.database.methods.translations import (
    set_category_translations, set_item_translations, category_labels, item_labels,
)
from bot.database.models.main import Categories, Goods, Fulfillment, PaymentMethod
from bot.i18n import use_language
from bot.misc.localized import pick, clean_name, clean_description


class TestPick:

    ROW = {"name": "Scaun", "name_en": "Chair", "name_ru": "Стул", "name_ro": None, "description": "d0"}

    @pytest.mark.parametrize("lang,expected", [("en", "Chair"), ("ru", "Стул"), ("ro", "Scaun")])
    def test_translation_or_fallback(self, lang, expected):
        assert pick(self.ROW, "name", lang) == expected

    @pytest.mark.parametrize("blank", ["", "   ", "\n", None])
    def test_blank_translation_falls_back(self, blank):
        assert pick({"name": "Main", "name_en": blank}, "name", "en") == "Main"

    def test_unknown_language_and_missing_field(self):
        assert pick(self.ROW, "name", "de") == "Scaun"
        assert pick(self.ROW, "description", "en") == "d0"       # no description_en column at all
        assert pick({}, "name", "en") == ""

    def test_works_on_orm_rows_and_defaults_to_current_language(self):
        row = Categories(name="Main", name_ru="Рус")
        assert pick(row, "name", "ru") == "Рус" and pick(row, "name", "en") == "Main"
        with use_language("ru"):
            assert pick(row, "name") == "Рус"
        with use_language("en"):
            assert pick(row, "name") == "Main"

    def test_cleaning(self):
        assert clean_name("  <b>Hi</b>\n  there\x00 ") == "Hi there"
        assert clean_name("   ") is None and clean_name(None) is None
        assert clean_description("line1  \n\n line2 <i>x</i>") == "line1\n\nline2 x"
        assert clean_description("  ") is None


class TestCreateAndSet:

    async def test_create_with_translations(self):
        await create_category("Mobilă", names={"en": "Furniture", "ru": "Мебель", "de": "ignored"})
        cat = await check_category("Mobilă")
        assert (cat["name_en"], cat["name_ru"], cat["name_ro"]) == ("Furniture", "Мебель", None)

        await create_item("Scaun", "Scaun de lemn", 100, "Mobilă", stock=2,
                          names={"en": "Chair"}, descriptions={"en": "Wooden chair", "ru": " "})
        item = await get_item_info("Scaun")
        assert item["name_en"] == "Chair" and item["description_en"] == "Wooden chair"
        assert item["description_ru"] is None and item["name"] == "Scaun" and item["description"] == "Scaun de lemn"

    async def test_set_and_clear_category_names(self, category_factory):
        await category_factory("Main")
        assert await set_category_translations("Main", {"ro": "Principal", "en": "Primary"}) == (True, "success")
        assert await set_category_translations("Main", {"en": "  "}) == (True, "success")   # blank clears
        cat = await check_category("Main")
        assert (cat["name_ro"], cat["name_en"], cat["name_ru"]) == ("Principal", None, None)

    @pytest.mark.parametrize("payload,code", [
        ({"de": "x"}, "invalid_language"),
        ({"en": "x" * 101}, "too_long"),
    ])
    async def test_category_validation(self, category_factory, payload, code):
        await category_factory("Main")
        assert await set_category_translations("Main", payload) == (False, code)
        assert (await check_category("Main"))["name_en"] is None

    async def test_unknown_category(self):
        assert await set_category_translations("Nope", {"en": "x"}) == (False, "category_not_found")

    async def test_set_item_translations_partial_update(self, item_factory):
        await item_factory(name="Item", description="main text")
        assert await set_item_translations("Item", {"ru": {"name": "Предмет", "description": "Описание"}}) \
            == (True, "success")
        assert await set_item_translations("Item", {"ru": {"description": None}, "en": {"name": "Thing"}}) \
            == (True, "success")
        item = await get_item_info("Item")
        assert (item["name_ru"], item["description_ru"], item["name_en"]) == ("Предмет", None, "Thing")
        assert item["name"] == "Item" and item["description"] == "main text"   # canonical untouched

    @pytest.mark.parametrize("payload,code", [
        ({"de": {"name": "x"}}, "invalid_language"),
        ({"en": {"title": "x"}}, "invalid_field"),
        ({"en": {"name": "x" * 101}}, "too_long"),
        ({"en": {"description": "x" * 4001}}, "too_long"),
    ])
    async def test_item_validation(self, item_factory, payload, code):
        await item_factory(name="Item")
        assert await set_item_translations("Item", payload) == (False, code)

    async def test_unknown_item(self):
        assert await set_item_translations("Nope", {"en": {"name": "x"}}) == (False, "item_not_found")

    async def test_cache_is_refreshed(self, item_factory, fake_cache):
        import asyncio
        await item_factory(name="Cached")
        fake_cache.store["item_info:Cached"] = {"name": "Cached"}
        await set_item_translations("Cached", {"en": {"name": "New"}})
        await asyncio.sleep(0)
        assert "item_info:Cached" not in fake_cache.store


class TestQueries:

    async def _catalog(self):
        await create_category("Cat-main", names={"en": "Zebra things", "ro": "Animale"})
        await create_category("Another", names={"en": "Apple things"})
        await create_item("Item A", "alpha text", 1, "Cat-main", names={"en": "Yacht"})
        await create_item("Item B", "beta text", 1, "Cat-main", names={"en": "Anchor"})

    async def test_lists_return_canonical_names_ordered_by_display(self):
        await self._catalog()
        assert await query_categories(lang="en") == ["Another", "Cat-main"]      # Apple < Zebra
        assert await query_categories(lang="ro") == ["Cat-main", "Another"]      # Animale < Another
        assert await query_items_in_category("Cat-main", lang="en") == ["Item B", "Item A"]   # Anchor < Yacht
        assert await query_items_in_category("Cat-main", lang="ru") == ["Item A", "Item B"]   # fallback: canonical

    async def test_default_language_comes_from_the_context(self):
        await self._catalog()
        with use_language("en"):
            assert await query_items_in_category("Cat-main") == ["Item B", "Item A"]
        with use_language("ru"):
            assert await query_items_in_category("Cat-main") == ["Item A", "Item B"]

    async def test_counts_and_paging_are_unchanged(self):
        await self._catalog()
        assert await query_categories(count_only=True) == 2
        assert await query_items_in_category("Cat-main", count_only=True) == 2
        assert await query_items_in_category("Cat-main", offset=1, limit=1, lang="en") == ["Item A"]

    @pytest.mark.parametrize("q,expected", [
        ("yacht", ["Item A"]), ("ANCHOR", ["Item B"]), ("alpha", ["Item A"]), ("zzz", []),
    ])
    async def test_search_matches_translated_names(self, q, expected):
        await self._catalog()
        assert await query_goods_search(q) == expected

    async def test_search_matches_translated_descriptions(self):
        await create_category("C")
        await create_item("X", "main", 1, "C", descriptions={"ro": "descriere unică", "ru": "уникальное описание"})
        assert await query_goods_search("unică") == ["X"]
        assert await query_goods_search("уникальное") == ["X"]
        assert await query_goods_search("уникальное", count_only=True) == 1

    async def test_search_still_escapes_wildcards(self):
        await create_category("C")
        await create_item("Plain", "text", 1, "C", names={"en": "Anything"})
        assert await query_goods_search("%") == []
        assert await query_goods_search("_") == []

    async def test_labels_for_a_page(self):
        await self._catalog()
        assert await category_labels(["Cat-main", "Another", "Missing"], "en") == {
            "Cat-main": "Zebra things", "Another": "Apple things", "Missing": "Missing"}
        assert await category_labels(["Cat-main"], "ru") == {"Cat-main": "Cat-main"}
        assert await item_labels(["Item A", "Item B"], "en") == {"Item A": "Yacht", "Item B": "Anchor"}
        assert await item_labels([]) == {}


class TestCartAndOrders:

    async def test_cart_items_carry_translations(self, user_factory):
        await user_factory(telegram_id=960001)
        await create_category("C")
        await create_item("Scaun", "d", 10, "C", stock=3, names={"en": "Chair", "ru": "Стул"})
        await add_to_cart(960001, "Scaun")
        [line] = await get_cart_items(960001)
        assert line["item_name"] == "Scaun"
        assert pick(line, "name", "en") == "Chair" and pick(line, "name", "ro") == "Scaun"
        assert (await get_items_info(["Scaun"]))["Scaun"]["name_ru"] == "Стул"

    async def test_order_snapshots_the_translated_names(self, user_factory):
        await user_factory(telegram_id=960002)
        await create_category("C")
        await create_item("Scaun", "d", 10, "C", stock=3, names={"en": "Chair", "ru": "Стул"})
        await add_to_cart(960002, "Scaun", quantity=2)
        ok, _, order = await create_order_transaction(
            960002, fulfillment=Fulfillment.PICKUP, customer_name="A", phone="123456",
            address=None, comment=None, payment_method=PaymentMethod.COD)
        assert ok

        # a later edit must not rewrite history
        await set_item_translations("Scaun", {"en": {"name": "Seat"}})
        [line] = (await get_order(order["id"]))["items"]
        assert (line["item_name"], line["name_en"], line["name_ru"], line["name_ro"]) == (
            "Scaun", "Chair", "Стул", None)
        assert pick(line, "name", "en") == "Chair" and pick(line, "name", "ro") == "Scaun"
