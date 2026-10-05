"""Weight options: each is its own Goods row grouped under a head product."""
import pytest
from sqlalchemy import select

from bot.database.main import Database
from bot.database.methods.create import (
    create_category, create_item, create_item_option, create_review,
)
from bot.database.methods.delete import delete_item
from bot.database.methods.lazy_queries import (
    query_items_in_category, query_goods_search, query_item_reviews,
)
from bot.database.methods.read import (
    get_item_info, get_item_family, get_head_name, get_item_avg_rating, has_purchased_item,
)
from bot.database.models.main import Goods


async def _head():
    await create_category("Tobacco")
    await create_item("SOLO 11", "Fruity", 0, "Tobacco", names={"ro": "SOLO 11 ro", "en": "SOLO 11 en"})
    assert await create_item_option("SOLO 11", "50 g", 90, 5) == (True, "success")
    assert await create_item_option("SOLO 11", "200 g", 300, 2) == (True, "success")


class TestCreateOption:

    async def test_option_is_its_own_row_in_the_head_category(self):
        await _head()
        opt = await get_item_info("SOLO 11 · 50 g")
        head = await get_item_info("SOLO 11")
        assert opt["variant_of"] == head["id"] and opt["variant_label"] == "50 g"
        assert opt["category_id"] == head["category_id"]
        assert opt["price"] == 90 and opt["stock"] == 5 and opt["description"] == ""
        assert opt["name_ro"] == "SOLO 11 ro · 50 g" and opt["name_en"] == "SOLO 11 en · 50 g"
        assert head["variant_of"] is None

    @pytest.mark.parametrize("head,label,code", [
        ("Nope", "50 g", "head_not_found"),
        ("SOLO 11 · 50 g", "10 g", "head_is_option"),
        ("SOLO 11", "", "bad_label"),
        ("SOLO 11", "a · b", "bad_label"),
        ("SOLO 11", "50 G", "exists"),
        ("SOLO 11", "50 g", "exists"),
    ])
    async def test_refusals(self, head, label, code):
        await _head()
        assert await create_item_option(head, label, 1) == (False, code)

    async def test_family_from_head_or_option(self):
        await _head()
        for name in ("SOLO 11", "SOLO 11 · 200 g"):
            fam = await get_item_family(name)
            assert fam["head"]["name"] == "SOLO 11"
            assert [o["variant_label"] for o in fam["options"]] == ["50 g", "200 g"]
            assert fam["current"]["name"] == name
        assert await get_item_family("Nope") is None

    async def test_standalone_has_no_options(self, item_factory):
        await item_factory(name="Plain")
        assert (await get_item_family("Plain"))["options"] == []


class TestListsShowHeadsOnly:

    async def test_category_list_and_count(self):
        await _head()
        assert await query_items_in_category("Tobacco") == ["SOLO 11"]
        assert await query_items_in_category("Tobacco", count_only=True) == 1

    async def test_search_hit_on_option_surfaces_head_once(self):
        await _head()
        assert await query_goods_search("SOLO") == ["SOLO 11"]
        assert await query_goods_search("200 g") == ["SOLO 11"]
        assert await query_goods_search("200 g", count_only=True) == 1


class TestReviewsViaHead:

    async def test_review_on_option_lands_on_head(self):
        await _head()
        assert await create_review(1, "SOLO 11 · 50 g", 4, "ok")
        assert await create_review(1, "SOLO 11", 5) is None          # one review per family member
        assert await get_item_avg_rating("SOLO 11 · 200 g") == 4.0
        assert await query_item_reviews("SOLO 11 · 200 g", count_only=True) == 1
        assert await get_head_name("SOLO 11 · 200 g") == "SOLO 11"
        assert await get_head_name("SOLO 11") == "SOLO 11" and await get_head_name("zz") == "zz"


class TestDelete:

    async def test_deleting_head_removes_options(self):
        await _head()
        await delete_item("SOLO 11")
        async with Database().session() as s:
            assert (await s.execute(select(Goods))).first() is None

    async def test_deleting_one_option_keeps_the_rest(self):
        await _head()
        await delete_item("SOLO 11 · 50 g")
        fam = await get_item_family("SOLO 11")
        assert [o["variant_label"] for o in fam["options"]] == ["200 g"]
