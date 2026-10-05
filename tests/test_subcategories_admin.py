"""Subcategories, admin side: the bot's add-category parent step, delete refusal, the product category
step, and the web panel's parent field, validation, list column, delete veto and cache invalidation."""
from unittest.mock import AsyncMock, patch

import pytest

from bot.database.methods.create import create_category, create_subcategory
from bot.database.methods.read import check_category, get_item_info, parent_assignment_error
from bot.database.models import Permission
from bot.database.main import Database
from bot.database.models.main import Categories
from bot.i18n import localize
from bot.filters import HasPermissionFilter
from bot.handlers.admin import adding_position as ap
from bot.handlers.admin import categories_management as cm
from bot.handlers.admin import translations as tr
from bot.handlers.admin import update_position as up
from bot.states import AddItemFSM, CategoryFSM, UpdateItemFSM
from bot.web.language import LANG_COOKIE

from tests.test_web_translations import CATS, app, boss, caches, category, main_is_russian  # noqa: F401 (fixtures)

ADMIN = 1


def _buttons(call_args):
    return [b.callback_data for row in call_args[1]["reply_markup"].inline_keyboard for b in row]


def _call(make_callback_query, data):
    return make_callback_query(data=data, user_id=ADMIN)


async def _to_parent_step(make_message, make_callback_query, fsm_context, name, translations=(None, None)):
    await fsm_context.set_state(CategoryFSM.waiting_add_category)
    await cm.process_category_for_add(make_message(text=name, user_id=ADMIN), fsm_context)
    for value in translations:
        if value is None:
            await cm.skip_category_translation(_call(make_callback_query, "cat_tr_skip"), fsm_context)
        else:
            await cm.process_category_translation(make_message(text=value, user_id=ADMIN), fsm_context)
    assert await fsm_context.get_state() == CategoryFSM.waiting_add_category_parent


@pytest.fixture
def ru_main():
    with patch('bot.i18n.main.get_locale', return_value="ru"):
        yield


# --- bot: add wizard -----------------------------------------------------------------------

@pytest.mark.usefixtures("ru_main")
class TestWizardParentStep:

    async def test_last_step_asks_for_a_parent_with_skip(self, make_message, make_callback_query, fsm_context):
        await _to_parent_step(make_message, make_callback_query, fsm_context, "Child")
        # Nothing is created before the parent step is answered.
        assert await check_category("Child") is None

    async def test_prompt_has_skip_and_back(self, make_message, make_callback_query, fsm_context):
        await fsm_context.set_state(CategoryFSM.waiting_add_category)
        await cm.process_category_for_add(make_message(text="Child", user_id=ADMIN), fsm_context)
        msg = make_message(text="x", user_id=ADMIN)
        await cm._ask_parent(msg, fsm_context)
        assert "prompt.parent" in msg.answer.call_args[0][0]
        assert _buttons(msg.answer.call_args) == ["cat_parent_skip", "categories_management"]

    async def test_skip_creates_a_top_level_category(self, make_message, make_callback_query, fsm_context):
        await _to_parent_step(make_message, make_callback_query, fsm_context, "Top")
        call = _call(make_callback_query, "cat_parent_skip")
        await cm.skip_category_parent(call, fsm_context)
        cat = await check_category("Top")
        assert cat and cat["parent_id"] is None
        assert "success" in call.message.answer.call_args[0][0]
        assert await fsm_context.get_state() is None

    @pytest.mark.parametrize("typed", ["Tobacco", "tobacco", "Tutun", "ТАБАК"])
    async def test_parent_typed_in_any_language(self, make_message, make_callback_query, fsm_context, typed):
        await create_category("Tobacco", names={"ro": "Tutun", "ru": "Табак"})
        await _to_parent_step(make_message, make_callback_query, fsm_context, "Classic", ["Classic EN", None])
        msg = make_message(text=typed, user_id=ADMIN)
        await cm.process_category_parent(msg, fsm_context)

        child = await check_category("Classic")
        parent = await check_category("Tobacco")
        assert child["parent_id"] == parent["id"]
        assert child["name_en"] == "Classic EN"                      # translations are kept
        assert "success" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() is None

    async def test_unknown_parent_reprompts_and_stays(self, make_message, make_callback_query, fsm_context):
        await _to_parent_step(make_message, make_callback_query, fsm_context, "Orphan")
        msg = make_message(text="Nowhere", user_id=ADMIN)
        await cm.process_category_parent(msg, fsm_context)

        assert "parent.not_found" in msg.answer.call_args[0][0]
        assert _buttons(msg.answer.call_args) == ["cat_parent_skip", "categories_management"]
        assert await fsm_context.get_state() == CategoryFSM.waiting_add_category_parent
        assert await check_category("Orphan") is None
        # ... and Skip still works afterwards
        await cm.skip_category_parent(_call(make_callback_query, "cat_parent_skip"), fsm_context)
        assert await check_category("Orphan") is not None

    @pytest.mark.parametrize("setup,parent,key", [
        ("child", "Leaf", "parent.not_top_level"),
        ("items", "Stocked", "parent.has_items"),
    ])
    async def test_refused_parent_reports_and_creates_nothing(self, make_message, make_callback_query, fsm_context,
                                                              item_factory, setup, parent, key):
        if setup == "child":
            await create_category("Root")
            await create_subcategory("Leaf", "Root")
        else:
            await item_factory(name="Thing", price=1, category="Stocked", stock=1)
        await _to_parent_step(make_message, make_callback_query, fsm_context, "Newcomer")
        msg = make_message(text=parent, user_id=ADMIN)
        await cm.process_category_parent(msg, fsm_context)

        assert key in msg.answer.call_args[0][0]
        assert await check_category("Newcomer") is None
        assert await fsm_context.get_state() is None

    async def test_name_taken_meanwhile_reports_exists(self, make_message, make_callback_query, fsm_context):
        await create_category("Root")
        await _to_parent_step(make_message, make_callback_query, fsm_context, "Racer")
        await create_category("Racer")                                # created by someone else in between
        msg = make_message(text="Root", user_id=ADMIN)
        await cm.process_category_parent(msg, fsm_context)
        assert "add.exist" in msg.answer.call_args[0][0]

    async def test_parent_vanishing_meanwhile_reports_not_found(self, make_message, make_callback_query, fsm_context):
        await _to_parent_step(make_message, make_callback_query, fsm_context, "Lonely")
        with patch.object(cm, "resolve_category_name", AsyncMock(return_value="Gone")):
            msg = make_message(text="Gone", user_id=ADMIN)
            await cm.process_category_parent(msg, fsm_context)
        assert "parent.not_found" in msg.answer.call_args[0][0]
        assert await check_category("Lonely") is None

    async def test_audit_mentions_the_parent(self, make_message, make_callback_query, fsm_context):
        await create_category("Root")
        await _to_parent_step(make_message, make_callback_query, fsm_context, "Sub")
        with patch.object(cm, "log_audit", new_callable=AsyncMock) as audit:
            await cm.process_category_parent(make_message(text="Root", user_id=ADMIN), fsm_context)
        assert audit.await_args[0][0] == "create_category"
        assert "parent=Root" in audit.await_args[1]["details"]

        await _to_parent_step(make_message, make_callback_query, fsm_context, "Top2")
        with patch.object(cm, "log_audit", new_callable=AsyncMock) as audit:
            await cm.skip_category_parent(_call(make_callback_query, "cat_parent_skip"), fsm_context)
        assert "parent=-" in audit.await_args[1]["details"]

    def test_parent_handlers_need_catalog_manage(self):
        names = {"process_category_parent", "skip_category_parent"}
        hs = [h for h in cm.router.callback_query.handlers + cm.router.message.handlers
              if h.callback.__name__ in names]
        assert {h.callback.__name__ for h in hs} == names
        for h in hs:
            perms = [f.callback for f in h.filters if isinstance(f.callback, HasPermissionFilter)]
            assert perms and perms[0].permission == Permission.CATALOG_MANAGE


# --- bot: delete / product category step / card -------------------------------------------

class TestBotRules:

    async def test_delete_of_a_parent_is_refused(self, make_message, fsm_context):
        await create_category("Root")
        await create_subcategory("Leaf", "Root")
        msg = make_message(text="Root", user_id=ADMIN)
        await cm.process_category_for_delete(msg, fsm_context)

        assert "delete.has_subcategories" in msg.answer.call_args[0][0]
        assert await check_category("Root") is not None and await check_category("Leaf") is not None

    async def test_delete_of_a_leaf_then_its_parent_works(self, make_message, fsm_context):
        await create_category("Root")
        await create_subcategory("Leaf", "Root")
        await cm.process_category_for_delete(make_message(text="Leaf", user_id=ADMIN), fsm_context)
        msg = make_message(text="Root", user_id=ADMIN)
        await cm.process_category_for_delete(msg, fsm_context)
        assert "delete.success" in msg.answer.call_args[0][0]
        assert await check_category("Root") is None

    async def test_delete_not_found_from_the_db_layer(self, make_message, fsm_context):
        msg = make_message(text="Vanishing", user_id=ADMIN)
        with patch.object(cm, "resolve_category_name", AsyncMock(return_value="Vanishing")):
            await cm.process_category_for_delete(msg, fsm_context)
        assert "delete.not_found" in msg.answer.call_args[0][0]

    async def test_add_item_rejects_a_parent_category(self, make_message, fsm_context):
        await create_category("Root")
        await create_subcategory("Leaf", "Root")
        await fsm_context.set_state(AddItemFSM.waiting_category)
        msg = make_message(text="Root", user_id=ADMIN)
        await ap.check_category_for_add_item(msg, fsm_context)

        assert "category.has_subcategories" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() == AddItemFSM.waiting_category
        assert "item_category" not in await fsm_context.get_data()

        msg = make_message(text="Leaf", user_id=ADMIN)
        await ap.check_category_for_add_item(msg, fsm_context)
        assert await fsm_context.get_state() == AddItemFSM.waiting_stock

    async def test_update_item_rejects_a_parent_category(self, make_message, fsm_context, item_factory):
        await item_factory(name="Mover", price=1, category="Home", stock=1)
        await create_category("Root")
        await create_subcategory("Leaf", "Root")
        await fsm_context.set_state(UpdateItemFSM.waiting_item_category)
        await fsm_context.update_data(item_old_name="Mover", item_new_name="Mover", item_description="d",
                                      item_price=1, item_category="Home")
        msg = make_message(text="Root", user_id=ADMIN)
        await up.update_item_category(msg, fsm_context)

        text = msg.answer.call_args[0][0]
        assert text in ("admin.goods.update.category.has_subcategories",
                        localize("admin.goods.update.category.has_subcategories"))
        assert await fsm_context.get_state() == UpdateItemFSM.waiting_item_category
        assert (await fsm_context.get_data())["item_category"] == "Home"

    async def test_translations_card_shows_the_parent(self, make_message, fsm_context):
        await create_category("Root", names={"en": "Roots"})
        await create_subcategory("Leaf", "Root")
        row = await check_category("Leaf")
        assert "card.parent" not in tr._card_text("c", "Leaf", row)
        text = tr._card_text("c", "Leaf", row, "en", parent_name="Roots")
        assert "card.parent" in text and "Roots" in text

        await fsm_context.update_data(tr_kind="c", tr_name="Leaf", tr_admin_lang="en")
        msg = make_message(text="x", user_id=ADMIN)
        await tr._show_card(msg, fsm_context)
        assert "card.parent" in msg.answer.call_args[0][0] and "Roots" in msg.answer.call_args[0][0]


# --- shared rule helper --------------------------------------------------------------------

class TestParentAssignmentError:

    async def test_codes(self, item_factory):
        await create_category("Root")
        await create_subcategory("Leaf", "Root")
        await create_category("Other")
        await item_factory(name="Thing", price=1, category="Stocked", stock=1)
        root, leaf, other, stocked = [await check_category(n) for n in ("Root", "Leaf", "Other", "Stocked")]
        async with Database().session() as s:
            get = lambda c: s.get(Categories, c["id"])
            assert await parent_assignment_error(s, await get(other), root["id"]) == "has_children"
            assert await parent_assignment_error(s, await get(root), root["id"]) == "self_parent"
            assert await parent_assignment_error(s, await get(leaf), other["id"]) == "parent_not_top_level"
            assert await parent_assignment_error(s, await get(stocked), other["id"]) == "parent_has_items"
            assert await parent_assignment_error(s, await get(other), None) is None


# --- web panel -----------------------------------------------------------------------------

def _select_options(page, field="parent_id"):
    import re
    block = re.search(rf'<select[^>]*name="{field}"[^>]*>(.*?)</select>', page, re.S)
    assert block, "parent select missing"
    return re.findall(r'<option[^>]*value="([^"]*)"[^>]*>\s*(.*?)\s*</option>', block.group(1), re.S)


async def _make(boss, name, parent=None):
    data = {"name_ru": name}
    if parent is not None:
        data["parent_id"] = str(parent)
    resp = await boss.post(f"/admin/{CATS}/create", data=data)
    assert resp.status_code == 302, resp.text[:300]
    return await category(name)


class TestWebParent:

    async def test_select_lists_only_top_level_categories(self, boss, caches):
        root = await _make(boss, "Root")
        await _make(boss, "Leaf", root.id)
        other = await _make(boss, "Other")
        boss.cookies.set(LANG_COOKIE, "en")
        options = _select_options((await boss.get(f"/admin/{CATS}/create")).text)
        assert [v for v, _ in options] == ["", str(root.id), str(other.id)] or \
               {v for v, _ in options} == {"", str(root.id), str(other.id)}
        assert "Leaf" not in [t for _, t in options]
        assert options[0][0] == ""

    async def test_select_labels_follow_the_viewer_language(self, boss, caches):
        await boss.post(f"/admin/{CATS}/create", data={"name_ru": "Мебель", "name_en": "Furniture"})
        for lang, shown in (("en", "Furniture"), ("ru", "Мебель")):
            boss.cookies.set(LANG_COOKIE, lang)
            texts = [t for _, t in _select_options((await boss.get(f"/admin/{CATS}/create")).text)]
            assert shown in texts

    @pytest.mark.parametrize("lang,label", [("en", "Parent category"), ("ru", "Родительская категория"),
                                            ("ro", "Categorie părinte")])
    async def test_field_is_labelled_in_the_viewer_language(self, boss, caches, lang, label):
        boss.cookies.set(LANG_COOKIE, lang)
        page = (await boss.get(f"/admin/{CATS}/create")).text
        assert label in page

    async def test_create_subcategory_and_edit_form_preselects_the_parent(self, boss, caches):
        root = await _make(boss, "Root")
        leaf = await _make(boss, "Leaf", root.id)
        assert leaf.parent_id == root.id and root.parent_id is None
        page = (await boss.get(f"/admin/{CATS}/edit/{leaf.id}")).text
        import re
        assert re.search(rf'<option(?=[^>]*value="{root.id}")(?=[^>]*selected)', page)

    async def test_empty_parent_means_top_level_and_can_clear_it(self, boss, caches):
        root = await _make(boss, "Root")
        leaf = await _make(boss, "Leaf", root.id)
        resp = await boss.post(f"/admin/{CATS}/edit/{leaf.id}", data={"name_ru": "Leaf", "parent_id": ""})
        assert resp.status_code == 302
        assert (await category("Leaf")).parent_id is None

    async def test_editing_the_name_keeps_the_parent(self, boss, caches):
        root = await _make(boss, "Root")
        leaf = await _make(boss, "Leaf", root.id)
        resp = await boss.post(f"/admin/{CATS}/edit/{leaf.id}",
                               data={"name_ru": "Leaf", "name_en": "Leaf EN", "parent_id": str(root.id)})
        assert resp.status_code == 302
        assert (await category("Leaf")).parent_id == root.id

    @pytest.mark.parametrize("lang,text", [("en", "its own parent"), ("ru", "родителем самой себя"),
                                           ("ro", "propriul părinte")])
    async def test_self_parent_is_refused(self, boss, caches, lang, text):
        root = await _make(boss, "Root")
        boss.cookies.set(LANG_COOKIE, lang)
        resp = await boss.post(f"/admin/{CATS}/edit/{root.id}", data={"name_ru": "Root", "parent_id": str(root.id)})
        assert resp.status_code == 400 and text in resp.text
        assert (await category("Root")).parent_id is None

    @pytest.mark.parametrize("lang,text", [("en", "top-level category"), ("ru", "верхнего уровня"),
                                           ("ro", "nivel superior")])
    async def test_a_subcategory_cannot_be_a_parent(self, boss, caches, lang, text):
        root = await _make(boss, "Root")
        leaf = await _make(boss, "Leaf", root.id)
        boss.cookies.set(LANG_COOKIE, lang)
        resp = await boss.post(f"/admin/{CATS}/create", data={"name_ru": "Deep", "name_en": "Deep", "name_ro": "Deep", "parent_id": str(leaf.id)})
        assert resp.status_code == 400 and text in resp.text
        assert await category("Deep") is None

    async def test_a_category_with_subcategories_cannot_get_a_parent(self, boss, caches):
        root = await _make(boss, "Root")
        await _make(boss, "Leaf", root.id)
        other = await _make(boss, "Other")
        boss.cookies.set(LANG_COOKIE, "en")
        resp = await boss.post(f"/admin/{CATS}/edit/{root.id}", data={"name_ru": "Root", "parent_id": str(other.id)})
        assert resp.status_code == 400 and "has subcategories" in resp.text
        assert (await category("Root")).parent_id is None

    async def test_a_parent_holding_products_is_refused(self, boss, caches, item_factory):
        await item_factory(name="Thing", price=1, category="Stocked", stock=1)
        stocked = await category("Stocked")
        boss.cookies.set(LANG_COOKIE, "en")
        resp = await boss.post(f"/admin/{CATS}/create", data={"name_ru": "Sub", "name_en": "Sub", "parent_id": str(stocked.id)})
        assert resp.status_code == 400 and "already holds products" in resp.text
        assert await category("Sub") is None

    async def test_a_category_with_products_can_become_a_subcategory(self, boss, caches, item_factory):
        await item_factory(name="Thing", price=1, category="Stocked", stock=1)
        root = await _make(boss, "Root")
        stocked = await category("Stocked")
        resp = await boss.post(f"/admin/{CATS}/edit/{stocked.id}",
                               data={"name_ru": "Stocked", "parent_id": str(root.id)})
        assert resp.status_code == 302
        assert (await category("Stocked")).parent_id == root.id

    async def test_unknown_parent_is_refused(self, boss, caches):
        boss.cookies.set(LANG_COOKIE, "en")
        resp = await boss.post(f"/admin/{CATS}/create", data={"name_ru": "Lost", "name_en": "Lost", "parent_id": "9999"})
        assert resp.status_code == 400 and "does not exist" in resp.text
        assert await category("Lost") is None

    async def test_list_has_a_parent_column(self, boss, caches):
        root = await _make(boss, "Root")
        await boss.post(f"/admin/{CATS}/edit/{root.id}", data={"name_ru": "Root", "name_en": "Roots"})
        await _make(boss, "Leaf", root.id)
        for lang, header, shown in (("en", "Parent category", "Roots"), ("ru", "Родительская категория", "Root"),
                                    ("ro", "Categorie părinte", "Root")):
            boss.cookies.set(LANG_COOKIE, lang)
            page = (await boss.get(f"/admin/{CATS}/list")).text
            assert header in page and shown in page

    async def test_delete_of_a_parent_is_vetoed(self, boss, caches):
        root = await _make(boss, "Root")
        await _make(boss, "Leaf", root.id)
        for lang, text in (("en", "has subcategories"), ("ru", "есть подкатегории"), ("ro", "are subcategorii")):
            boss.cookies.set(LANG_COOKIE, lang)
            resp = await boss.delete(f"/admin/{CATS}/delete?pks={root.id}")
            assert resp.status_code == 409 and text in resp.text
        assert await category("Root") is not None and await category("Leaf") is not None

    async def test_delete_of_a_leaf_then_its_parent_is_allowed(self, boss, caches):
        root = await _make(boss, "Root")
        leaf = await _make(boss, "Leaf", root.id)
        assert (await boss.delete(f"/admin/{CATS}/delete?pks={leaf.id}")).status_code == 200
        assert (await boss.delete(f"/admin/{CATS}/delete?pks={root.id}")).status_code == 200
        assert await category("Root") is None

    async def test_cache_invalidation_covers_old_and_new_parents(self, boss, caches):
        _, cat_cache = caches
        a = await _make(boss, "Alpha")
        b = await _make(boss, "Beta")
        cat_cache.reset_mock()
        leaf = await _make(boss, "Leaf", a.id)
        assert {c.args[0] for c in cat_cache.call_args_list} == {"Leaf", "Alpha"}

        cat_cache.reset_mock()
        await boss.post(f"/admin/{CATS}/edit/{leaf.id}", data={"name_ru": "Leaf", "parent_id": str(b.id)})
        assert {c.args[0] for c in cat_cache.call_args_list} == {"Leaf", "Alpha", "Beta"}

        cat_cache.reset_mock()
        await boss.delete(f"/admin/{CATS}/delete?pks={leaf.id}")
        assert {c.args[0] for c in cat_cache.call_args_list} == {"Leaf", "Beta"}
