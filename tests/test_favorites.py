"""Favorites: the star on a product card, the favorites list, heads-only behaviour."""
import pytest
from sqlalchemy import select

from bot.database.main import Database
from bot.database.methods.create import create_category, create_item, create_item_option
from bot.database.methods.favorites import is_favorite, item_name_by_id, list_favorites, toggle_favorite
from bot.database.methods.read import get_item_info
from bot.database.models.main import Favorites
from bot.handlers.user.shop_and_goods import (
    favorite_toggle_handler, favorites_handler, favorites_open_handler, favorites_page_handler, _render_item_page,
)

UID = 930001


async def count(uid=UID):
    async with Database().session() as s:
        return len((await s.execute(select(Favorites).where(Favorites.user_id == uid))).all())


@pytest.fixture
async def shop(user_factory, item_factory):
    await user_factory(telegram_id=UID)
    for i in range(10):
        await item_factory(name=f"Fav{i:02d}", price=10 + i, stock=3)


class TestStorage:

    async def test_toggle_stars_and_unstars(self, shop):
        assert await is_favorite(UID, "Fav00") is False
        assert await toggle_favorite(UID, "Fav00") is True
        assert await is_favorite(UID, "Fav00") is True
        assert await toggle_favorite(UID, "Fav00") is False
        assert await is_favorite(UID, "Fav00") is False
        assert await count() == 0

    async def test_unknown_product(self, shop):
        assert await toggle_favorite(UID, "Nope") is None
        assert await is_favorite(UID, "Nope") is False

    async def test_an_option_stars_its_head(self, shop):
        await create_category("Tobacco")
        await create_item("SOLO 11", "x", 0, "Tobacco")
        await create_item_option("SOLO 11", "50 g", 90, 4)
        await create_item_option("SOLO 11", "200 g", 300, 4)
        assert await toggle_favorite(UID, "SOLO 11 · 50 g") is True
        assert await is_favorite(UID, "SOLO 11") is True
        assert await is_favorite(UID, "SOLO 11 · 200 g") is True       # same product
        names = [r["name"] for r in (await list_favorites(UID))[0]]
        assert names == ["SOLO 11"]
        assert await toggle_favorite(UID, "SOLO 11 · 200 g") is False   # un-star from another option
        assert await count() == 0

    async def test_favorites_are_per_user(self, shop, user_factory):
        await user_factory(telegram_id=UID + 1)
        await toggle_favorite(UID, "Fav01")
        assert await is_favorite(UID + 1, "Fav01") is False
        assert (await list_favorites(UID + 1))[1] == 0

    async def test_list_is_newest_first_and_paged(self, shop):
        for i in range(10):
            await toggle_favorite(UID, f"Fav{i:02d}")
        rows, total = await list_favorites(UID, 0, 4)
        assert total == 10 and [r["name"] for r in rows] == ["Fav09", "Fav08", "Fav07", "Fav06"]
        rows, _ = await list_favorites(UID, 2, 4)
        assert [r["name"] for r in rows] == ["Fav01", "Fav00"]

    async def test_item_name_by_id(self, shop):
        info = await get_item_info("Fav03")
        assert await item_name_by_id(info["id"]) == "Fav03"
        assert await item_name_by_id(10 ** 9) is None


def _cbs(mock, method="edit_text"):
    markup = getattr(mock, method).call_args[1]["reply_markup"]
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _star_label(call) -> str:
    markup = call.message.edit_text.call_args[1]["reply_markup"]
    return next(b.text for row in markup.inline_keyboard for b in row if b.callback_data == "fav_toggle")


class TestHandlers:

    async def test_star_on_the_card_toggles_and_rerenders(self, shop, make_callback_query, fsm_context):
        await fsm_context.update_data(csrf_item="Fav02", item_back_data="gp_0")
        call = make_callback_query(data="fav_toggle", user_id=UID)
        await favorite_toggle_handler(call, fsm_context)
        assert await is_favorite(UID, "Fav02")
        call.answer.assert_awaited_with("favorites.added")
        starred = _star_label(call)

        call = make_callback_query(data="fav_toggle", user_id=UID)
        await favorite_toggle_handler(call, fsm_context)
        assert not await is_favorite(UID, "Fav02")
        assert _star_label(call) != starred
        call.answer.assert_awaited_with("favorites.removed")

    async def test_star_without_a_product_on_screen(self, shop, make_callback_query, fsm_context):
        call = make_callback_query(data="fav_toggle", user_id=UID)
        await favorite_toggle_handler(call, fsm_context)
        assert call.answer.call_args[1].get("show_alert") is True

    async def test_empty_list(self, shop, make_callback_query, fsm_context):
        call = make_callback_query(data="favorites", user_id=UID)
        await favorites_handler(call, fsm_context)
        text = call.message.edit_text.call_args[0][0]
        assert "favorites.empty" in text
        assert _cbs(call.message) == ["profile"]

    async def test_list_pages_and_opens_a_card(self, shop, make_callback_query, fsm_context):
        for i in range(10):
            await toggle_favorite(UID, f"Fav{i:02d}")
        call = make_callback_query(data="favorites", user_id=UID)
        await favorites_handler(call, fsm_context)
        cbs = _cbs(call.message)
        assert sum(c.startswith("fav_open:") for c in cbs) == 8
        assert "fav_page:1" in cbs and "profile" in cbs

        page = make_callback_query(data="fav_page:1", user_id=UID)
        await favorites_page_handler(page, fsm_context)
        assert sum(c.startswith("fav_open:") for c in _cbs(page.message)) == 2

        first = next(c for c in cbs if c.startswith("fav_open:"))
        opened = make_callback_query(data=first, user_id=UID)
        await favorites_open_handler(opened, fsm_context)
        data = await fsm_context.get_data()
        assert data["csrf_item"] == "Fav09" and data["item_back_data"] == "favorites"
        assert "favorites" in _cbs(opened.message)            # the card's Back returns to the list

    async def test_bad_page_and_unknown_product(self, shop, make_callback_query, fsm_context):
        bad = make_callback_query(data="fav_page:x", user_id=UID)
        await favorites_page_handler(bad, fsm_context)
        assert bad.answer.call_args[1].get("show_alert") is True
        gone = make_callback_query(data="fav_open:999999", user_id=UID)
        await favorites_open_handler(gone, fsm_context)
        assert gone.answer.call_args[1].get("show_alert") is True

    async def test_page_beyond_the_end_is_clamped(self, shop, make_callback_query, fsm_context):
        await toggle_favorite(UID, "Fav00")
        call = make_callback_query(data="fav_page:7", user_id=UID)
        await favorites_page_handler(call, fsm_context)
        assert any(c.startswith("fav_open:") for c in _cbs(call.message))

    async def test_card_of_an_option_shows_the_head_as_starred(self, shop, make_callback_query, fsm_context):
        await create_category("Tobacco")
        await create_item("SOLO 12", "x", 0, "Tobacco")
        await create_item_option("SOLO 12", "50 g", 90, 4)
        await toggle_favorite(UID, "SOLO 12")
        call = make_callback_query(data="x", user_id=UID)
        await _render_item_page(call, fsm_context, "SOLO 12 · 50 g", "gp_0", user_id=UID)
        starred = _star_label(call)
        await toggle_favorite(UID, "SOLO 12")
        call = make_callback_query(data="x", user_id=UID)
        await _render_item_page(call, fsm_context, "SOLO 12 · 50 g", "gp_0", user_id=UID)
        assert _star_label(call) != starred
