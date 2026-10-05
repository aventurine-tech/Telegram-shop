"""Customer navigation through subcategories and the category buttons of the main menu."""
import pytest

from bot.database.methods.create import create_category, create_subcategory, create_item
from bot.database.methods.read import check_category
from bot.handlers.user.main import back_to_menu_callback_handler, menu_categories, open_main_menu
from bot.handlers.user.shop_and_goods import (
    router, shop_callback_handler, navigate_categories, items_list_callback_handler,
    menu_category_handler, subcategory_callback_handler, navigate_subcategories,
    navigate_goods, item_info_callback_handler,
)
from bot.i18n import main as i18n
from bot.keyboards.inline import main_menu
from bot.states import ShopStates

UID = 930001


@pytest.fixture(autouse=True)
def _english():
    with i18n.use_language("en"):
        yield


def _cbs(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


def _shown(call):
    """(text, markup) of the last screen edited into the message."""
    args, kwargs = call.message.edit_text.call_args
    return args[0], kwargs["reply_markup"]


async def _tree():
    await create_category("Hookah", names={"ro": "Narghilea", "ru": "Кальян"})
    await create_subcategory("Intense", "Hookah", names={"ro": "Intens", "ru": "Крепкий"})
    await create_subcategory("Classic", "Hookah", names={"ro": "Clasic", "ru": "Классика"})
    await create_item("Tobacco A", "d", 5, "Classic")
    await create_category("Charcoal")
    await create_item("Coal 1", "d", 5, "Charcoal")


class TestDrillDown:

    async def test_top_level_list_excludes_subcategories(self, make_callback_query, fsm_context):
        await _tree()
        call = make_callback_query(data="shop", user_id=UID)
        await shop_callback_handler(call, fsm_context)
        _, markup = _shown(call)
        assert _texts(markup)[:2] == ["Charcoal", "Hookah"]
        assert "Classic" not in _texts(markup)

    async def test_opening_a_parent_lists_subcategories(self, make_callback_query, fsm_context):
        await _tree()
        await shop_callback_handler(make_callback_query(data="shop", user_id=UID), fsm_context)
        call = make_callback_query(data="cat:1:0", user_id=UID)       # Hookah (2nd alphabetically)
        await items_list_callback_handler(call, fsm_context)
        text, markup = _shown(call)
        assert "Hookah" in text
        assert _texts(markup)[:2] == ["Classic", "Intense"]
        assert _cbs(markup)[:2] == ["subcat:0:0", "subcat:1:0"]
        assert _cbs(markup)[-1] == "categories-page_0"               # Back -> top-level list
        data = await fsm_context.get_data()
        assert data["current_parent"] == "Hookah"
        assert data["subcategory_page_items"] == ["Classic", "Intense"]

    async def test_subcategories_are_localized_and_ordered_per_viewer(self, make_callback_query, fsm_context):
        await _tree()
        await shop_callback_handler(make_callback_query(data="shop", user_id=UID), fsm_context)
        with i18n.use_language("ro"):
            call = make_callback_query(data="cat:1:0", user_id=UID)
            await items_list_callback_handler(call, fsm_context)
            _, markup = _shown(call)
        # Romanian names sort Clasic < Intens; callbacks still index the canonical names.
        assert _texts(markup)[:2] == ["Clasic", "Intens"]
        with i18n.use_language("ru"):
            call = make_callback_query(data="cat:1:0", user_id=UID)
            await items_list_callback_handler(call, fsm_context)
            text, markup = _shown(call)
        assert _texts(markup)[:2] == ["Классика", "Крепкий"]
        assert "Кальян" in text

    async def test_subcategory_lists_its_products_and_back_returns_to_the_sublist(
            self, make_callback_query, fsm_context):
        await _tree()
        await shop_callback_handler(make_callback_query(data="shop", user_id=UID), fsm_context)
        await items_list_callback_handler(make_callback_query(data="cat:1:0", user_id=UID), fsm_context)
        call = make_callback_query(data="subcat:0:0", user_id=UID)
        await subcategory_callback_handler(call, fsm_context)
        _, markup = _shown(call)
        assert _texts(markup)[0] == "Tobacco A"
        assert _cbs(markup)[-1] == "subcat-page_0"
        assert await fsm_context.get_state() == ShopStates.viewing_goods.state

        back = make_callback_query(data="subcat-page_0", user_id=UID)
        await navigate_subcategories(back, fsm_context)
        text, markup = _shown(back)
        assert _texts(markup)[:2] == ["Classic", "Intense"]

    async def test_item_card_back_works_through_a_subcategory(self, make_callback_query, fsm_context):
        await _tree()
        await shop_callback_handler(make_callback_query(data="shop", user_id=UID), fsm_context)
        await items_list_callback_handler(make_callback_query(data="cat:1:0", user_id=UID), fsm_context)
        await subcategory_callback_handler(make_callback_query(data="subcat:0:0", user_id=UID), fsm_context)
        card = make_callback_query(data="itm:0:0", user_id=UID)
        await item_info_callback_handler(card, fsm_context)
        _, markup = _shown(card)
        assert _cbs(markup)[-1] == "gp_0"
        # gp_0 re-renders the subcategory's product list, whose Back still leads to the sub-list.
        back = make_callback_query(data="gp_0", user_id=UID)
        await navigate_goods(back, fsm_context)
        _, markup = _shown(back)
        assert _texts(markup)[0] == "Tobacco A"
        assert _cbs(markup)[-1] == "subcat-page_0"

    async def test_leaf_top_level_category_is_unchanged_and_clears_the_parent(
            self, make_callback_query, fsm_context):
        await _tree()
        await shop_callback_handler(make_callback_query(data="shop", user_id=UID), fsm_context)
        await items_list_callback_handler(make_callback_query(data="cat:1:0", user_id=UID), fsm_context)
        # Back to the list, then a leaf: its Back must not point at the earlier parent's sub-list.
        await navigate_categories(make_callback_query(data="categories-page_0", user_id=UID), fsm_context)
        call = make_callback_query(data="cat:0:0", user_id=UID)       # Charcoal
        await items_list_callback_handler(call, fsm_context)
        _, markup = _shown(call)
        assert _texts(markup)[0] == "Coal 1"
        assert _cbs(markup)[-1] == "categories-page_0"
        assert (await fsm_context.get_data())["current_parent"] is None

    async def test_stale_sublist_callbacks(self, make_callback_query, fsm_context):
        await _tree()
        call = make_callback_query(data="subcat:0:0", user_id=UID)    # no parent in FSM
        await subcategory_callback_handler(call, fsm_context)
        call.answer.assert_called_once()
        assert call.answer.call_args[1]["show_alert"] is True
        # Sub-list pagination without state falls back to the top-level list.
        page = make_callback_query(data="subcat-page_1", user_id=UID)
        await navigate_subcategories(page, fsm_context)
        _, markup = _shown(page)
        assert "Hookah" in _texts(markup)


class TestSubcategoryPagination:

    async def test_pages_and_back_pointers(self, make_callback_query, fsm_context):
        await create_category("Big")
        for i in range(12):
            await create_subcategory(f"Sub{i:02d}", "Big")
        await shop_callback_handler(make_callback_query(data="shop", user_id=UID), fsm_context)
        await items_list_callback_handler(make_callback_query(data="cat:0:0", user_id=UID), fsm_context)

        page2 = make_callback_query(data="subcat-page_1", user_id=UID)
        await navigate_subcategories(page2, fsm_context)
        _, markup = _shown(page2)
        assert _texts(markup)[:2] == ["Sub10", "Sub11"]
        assert "subcat-page_0" in _cbs(markup)

        opened = make_callback_query(data="subcat:1:1", user_id=UID)
        await subcategory_callback_handler(opened, fsm_context)
        assert (await fsm_context.get_data())["current_category"] == "Sub11"
        assert (await fsm_context.get_data())["categories_last_viewed_page"] == 1

    def test_every_prefix_the_view_produces_has_a_handler(self):
        from aiogram.types import CallbackQuery
        from unittest.mock import MagicMock

        def matches(payload):
            call = MagicMock(spec=CallbackQuery)
            call.data = payload
            for handler in router.callback_query.handlers:
                for f in handler.filters or ():
                    magic = getattr(f, "magic", None)
                    try:
                        if magic is not None and magic.resolve(call):
                            return True
                    except Exception:
                        continue
            return False

        for payload in ("subcat-page_1", "subcat:0:0", "mcat:12"):
            assert matches(payload), payload


class TestMainMenuCategories:

    def test_no_categories_keeps_the_shop_button(self):
        cbs = _cbs(main_menu(role=1))
        assert cbs[0] == "shop" and not any(c.startswith("mcat:") for c in cbs)
        assert _cbs(main_menu(role=1, categories=[]))[0] == "shop"

    def test_category_buttons_replace_shop_one_per_row(self):
        markup = main_menu(role=1, categories=[(5, "Tea"), (7, "Coffee")])
        assert _cbs(markup)[:2] == ["mcat:5", "mcat:7"]
        assert "shop" not in _cbs(markup)
        assert [len(r) for r in markup.inline_keyboard[:2]] == [1, 1]
        assert _texts(markup)[:2] == ["Tea", "Coffee"]

    def test_cap_of_six_plus_all_categories(self):
        cats = [(i, f"C{i}") for i in range(1, 8)]
        markup = main_menu(role=1, categories=cats)
        cbs = _cbs(markup)
        assert cbs[:6] == [f"mcat:{i}" for i in range(1, 7)]
        assert "mcat:7" not in cbs
        assert cbs[6] == "shop"
        assert "all categories" in _texts(markup)[6].lower()
        # exactly six: nothing is hidden, so no extra button
        assert "shop" not in _cbs(main_menu(role=1, categories=cats[:6]))

    def test_callback_data_fits_telegram_limit(self):
        markup = main_menu(role=1, categories=[(10 ** 15, "x")] * 7)
        assert all(len(c.encode()) <= 64 for c in _cbs(markup))
        assert len(f"subcat-page_{10 ** 6}") < 64 and len("subcat:99:99999") < 64

    async def test_menu_categories_are_localized_top_level_only(self):
        await _tree()
        cats = await menu_categories()
        assert [label for _id, label in cats] == ["Charcoal", "Hookah"]
        with i18n.use_language("ro"):
            assert [label for _id, label in await menu_categories()] == ["Charcoal", "Narghilea"]
        assert (await check_category("Hookah"))["id"] in [i for i, _ in cats]

    async def test_back_to_menu_shows_the_category_buttons(self, make_callback_query, fsm_context, user_factory):
        await user_factory(telegram_id=UID)
        await _tree()
        call = make_callback_query(data="back_to_menu", user_id=UID)
        await back_to_menu_callback_handler(call, fsm_context)
        _, markup = _shown(call)
        assert _cbs(markup)[:2] == [f"mcat:{(await check_category('Charcoal'))['id']}",
                                    f"mcat:{(await check_category('Hookah'))['id']}"]

    async def test_open_main_menu_shows_the_category_buttons(self, make_message, user_factory):
        await user_factory(telegram_id=UID)
        await _tree()
        msg = make_message(user_id=UID)
        await open_main_menu(msg, UID, 1)
        markup = msg.answer.call_args_list[-1][1]["reply_markup"]
        assert any(c.startswith("mcat:") for c in _cbs(markup))


class TestMenuCategoryOpen:

    async def test_parent_from_menu_shows_subcategories_and_back_leads_to_the_menu(
            self, make_callback_query, fsm_context):
        await _tree()
        cid = (await check_category("Hookah"))["id"]
        call = make_callback_query(data=f"mcat:{cid}", user_id=UID)
        await menu_category_handler(call, fsm_context)
        _, markup = _shown(call)
        assert _texts(markup)[:2] == ["Classic", "Intense"]
        assert _cbs(markup)[-1] == "back_to_menu"
        # product list inside keeps the chain: products -> sub-list -> menu
        await subcategory_callback_handler(make_callback_query(data="subcat:0:0", user_id=UID), fsm_context)
        inner = make_callback_query(data="gp_0", user_id=UID)
        await navigate_goods(inner, fsm_context)
        assert _cbs(_shown(inner)[1])[-1] == "subcat-page_0"
        sub = make_callback_query(data="subcat-page_0", user_id=UID)
        await navigate_subcategories(sub, fsm_context)
        assert _cbs(_shown(sub)[1])[-1] == "back_to_menu"

    async def test_leaf_from_menu_lists_products_and_back_leads_to_the_menu(
            self, make_callback_query, fsm_context):
        await _tree()
        cid = (await check_category("Charcoal"))["id"]
        call = make_callback_query(data=f"mcat:{cid}", user_id=UID)
        await menu_category_handler(call, fsm_context)
        _, markup = _shown(call)
        assert _texts(markup)[0] == "Coal 1"
        assert _cbs(markup)[-1] == "back_to_menu"
        # pagination callback of the product list keeps the menu as the origin
        again = make_callback_query(data="gp_0", user_id=UID)
        await navigate_goods(again, fsm_context)
        assert _cbs(_shown(again)[1])[-1] == "back_to_menu"

    async def test_shop_button_resets_the_menu_origin(self, make_callback_query, fsm_context):
        await _tree()
        cid = (await check_category("Charcoal"))["id"]
        await menu_category_handler(make_callback_query(data=f"mcat:{cid}", user_id=UID), fsm_context)
        await shop_callback_handler(make_callback_query(data="shop", user_id=UID), fsm_context)
        assert (await fsm_context.get_data())["shop_origin"] is None

    @pytest.mark.parametrize("payload", ["mcat:999999", "mcat:abc", "mcat:"])
    async def test_stale_or_bad_id(self, make_callback_query, fsm_context, payload):
        call = make_callback_query(data=payload, user_id=UID)
        await menu_category_handler(call, fsm_context)
        assert call.answer.call_args[1]["show_alert"] is True
        call.message.edit_text.assert_not_called()

    async def test_subcategory_id_is_not_a_menu_entry(self, make_callback_query, fsm_context):
        await _tree()
        cid = (await check_category("Classic"))["id"]
        call = make_callback_query(data=f"mcat:{cid}", user_id=UID)
        await menu_category_handler(call, fsm_context)
        assert call.answer.call_args[1]["show_alert"] is True
