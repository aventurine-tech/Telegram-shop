"""Two-level categories: rules, queries, deletion and promo scope."""
import pytest
from sqlalchemy import select

from bot.database.main import Database
from bot.database.methods.create import create_category, create_subcategory, create_item
from bot.database.methods.delete import delete_category
from bot.database.methods.lazy_queries import query_categories, query_subcategories, query_items_in_category
from bot.database.methods.read import (
    check_category, get_category_by_id, category_children_count, category_items_count,
    category_accepts_items, promo_rule_error,
)
from bot.database.methods.translations import category_labels
from bot.database.models.main import Categories, Goods, PromoCodes


async def _tree():
    await create_category("Hookah tobacco", names={"en": "Hookah tobacco", "ro": "Tutun pentru narghilea"})
    await create_subcategory("Intense", "Hookah tobacco", names={"ro": "Intens"})
    await create_subcategory("Classic", "Hookah tobacco", names={"ro": "Clasic"})


class TestCreateRules:

    async def test_subcategory_points_at_its_parent(self):
        await _tree()
        parent = await check_category("Hookah tobacco")
        child = await check_category("Classic")
        assert child["parent_id"] == parent["id"] and parent["parent_id"] is None
        assert await category_children_count(parent["id"]) == 2

    @pytest.mark.parametrize("parent,code", [
        ("Nope", "parent_not_found"),
        ("Classic", "parent_not_top_level"),          # two levels at most
    ])
    async def test_invalid_parents(self, parent, code):
        await _tree()
        assert await create_subcategory("Child", parent) == (False, code)
        assert await check_category("Child") is None

    async def test_parent_with_products_cannot_get_children(self, item_factory):
        await item_factory(name="P", category="Plain")
        assert await create_subcategory("Sub", "Plain") == (False, "parent_has_items")

    async def test_duplicate_name(self):
        await _tree()
        assert await create_subcategory("Classic", "Hookah tobacco") == (False, "exists")
        assert await create_subcategory("Hookah tobacco", "Hookah tobacco") == (False, "exists")

    async def test_products_cannot_go_into_a_category_with_subcategories(self):
        await _tree()
        await create_item("Loose", "d", 1, "Hookah tobacco")
        assert await check_category("Hookah tobacco") is not None
        async with Database().session() as s:
            assert (await s.execute(select(Goods).where(Goods.name == "Loose"))).first() is None
        assert await category_accepts_items("Hookah tobacco") is False
        assert await category_accepts_items("Classic") is True
        assert await category_accepts_items("Missing") is False

    async def test_products_go_into_the_subcategory(self):
        await _tree()
        await create_item("SOLO 11", "d", 1, "Classic", stock=3)
        cat = await check_category("Classic")
        assert await category_items_count(cat["id"]) == 1
        assert await query_items_in_category("Classic") == ["SOLO 11"]


class TestQueries:

    async def test_top_level_list_hides_subcategories(self):
        await _tree()
        await create_category("Accessories")
        assert await query_categories(lang="en") == ["Accessories", "Hookah tobacco"]
        assert await query_categories(count_only=True) == 2

    async def test_subcategories_ordered_as_the_viewer_sees_them(self):
        await _tree()
        assert await query_subcategories("Hookah tobacco", lang="en") == ["Classic", "Intense"]
        assert await query_subcategories("Hookah tobacco", lang="ro") == ["Classic", "Intense"]  # Clasic < Intens
        assert await query_subcategories("Hookah tobacco", count_only=True) == 2
        assert await query_subcategories("Hookah tobacco", offset=1, limit=1, lang="en") == ["Intense"]

    async def test_unknown_parent_and_leaf(self):
        await _tree()
        assert await query_subcategories("Nope") == []
        assert await query_subcategories("Nope", count_only=True) == 0
        assert await query_subcategories("Classic") == []

    async def test_labels_and_lookup_by_id(self):
        await _tree()
        assert await category_labels(["Classic", "Intense"], "ro") == {"Classic": "Clasic", "Intense": "Intens"}
        child = await check_category("Classic")
        assert (await get_category_by_id(child["id"]))["name"] == "Classic"
        assert await get_category_by_id(999999) is None


class TestDelete:

    async def test_refuses_to_delete_a_parent_with_subcategories(self):
        await _tree()
        assert await delete_category("Hookah tobacco") == "has_subcategories"
        assert await check_category("Hookah tobacco") is not None
        assert await check_category("Classic") is not None

    async def test_deletes_children_first_then_the_parent(self, item_factory):
        await _tree()
        await create_item("SOLO 11", "d", 1, "Classic")
        assert await delete_category("Classic") == "ok"
        assert await delete_category("Intense") == "ok"
        assert await delete_category("Hookah tobacco") == "ok"
        assert await check_category("Hookah tobacco") is None

    async def test_unknown(self):
        assert await delete_category("Nope") == "not_found"


class _Goods:
    def __init__(self, id, category_id):
        self.id, self.category_id = id, category_id


class TestPromoScope:

    async def _promo(self, category_id):
        async with Database().session() as s:
            promo = PromoCodes(code="CAT10", discount_type="percent", discount_value=10, max_uses=0,
                               current_uses=0, is_active=True, category_id=category_id, scope="category")
            s.add(promo)
            await s.flush()
            await s.refresh(promo)
            return promo

    async def test_a_parent_promo_covers_its_subcategories(self, user_factory):
        await _tree()
        await user_factory(telegram_id=970001)
        parent = await check_category("Hookah tobacco")
        child = await check_category("Classic")
        other = await create_category("Elsewhere") or await check_category("Elsewhere")
        promo = await self._promo(parent["id"])
        async with Database().session() as s:
            assert await promo_rule_error(s, promo, 970001, goods=_Goods(1, child["id"])) is None
            assert await promo_rule_error(s, promo, 970001, goods=_Goods(1, parent["id"])) is None
            elsewhere = (await check_category("Elsewhere"))["id"]
            assert await promo_rule_error(s, promo, 970001, goods=_Goods(1, elsewhere)) == "wrong_category"

    async def test_a_child_promo_does_not_cover_the_parent_or_siblings(self, user_factory):
        await _tree()
        await user_factory(telegram_id=970002)
        parent = await check_category("Hookah tobacco")
        classic = await check_category("Classic")
        intense = await check_category("Intense")
        promo = await self._promo(classic["id"])
        async with Database().session() as s:
            assert await promo_rule_error(s, promo, 970002, goods=_Goods(1, classic["id"])) is None
            assert await promo_rule_error(s, promo, 970002, goods=_Goods(1, intense["id"])) == "wrong_category"
            assert await promo_rule_error(s, promo, 970002, goods=_Goods(1, parent["id"])) == "wrong_category"
