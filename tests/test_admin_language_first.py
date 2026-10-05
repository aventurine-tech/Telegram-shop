"""Admin catalog flows in the admin's own language: wizard order, canonical derivation, and typed
category/product names accepted in any language."""
from unittest.mock import AsyncMock, patch

import pytest

from bot.database.methods.create import create_category, create_item
from bot.database.methods.read import (
    check_category, get_item_info, get_promo_code, resolve_category_name, resolve_item_name,
)
from bot.handlers.admin import adding_position as ap
from bot.handlers.admin import categories_management as cm
from bot.handlers.admin import goods_management as gm
from bot.handlers.admin import promo_management as pm
from bot.handlers.admin import sale_management as sm
from bot.handlers.admin import translations as tr
from bot.handlers.admin import update_position as up
from bot.i18n import localize
from bot.handlers.admin._common import wizard_languages, language_label
from bot.states import (
    AddItemFSM, CategoryFSM, GoodsFSM, PromoFSM, SaleFSM, StockFSM, TranslationFSM, UpdateItemFSM,
)

LANGS = ["en", "ru", "ro"]
ADMIN_ID = 777001


@pytest.fixture(autouse=True)
def hooks():
    with patch('bot.handlers.admin.adding_position._notify_restock_safe', new_callable=AsyncMock), \
            patch('bot.handlers.admin.adding_position.announce_arrival', new_callable=AsyncMock):
        yield


def _main(lang):
    return patch('bot.i18n.main.get_locale', return_value=lang)


def _skip(make_callback_query, data):
    return make_callback_query(data=data, user_id=ADMIN_ID)


def _others(admin):
    return [c for c in LANGS if c != admin]


# --- wizard_languages ----------------------------------------------------------------------

class TestWizardLanguages:

    @pytest.mark.parametrize("admin,expected", [
        ("en", ["en", "ru", "ro"]), ("ru", ["ru", "en", "ro"]), ("ro", ["ro", "en", "ru"]),
    ])
    def test_admin_language_first_then_the_rest_in_order(self, admin, expected):
        assert wizard_languages(admin) == expected

    @pytest.mark.parametrize("bad", [None, "", "de"])
    def test_unknown_falls_back_to_the_default(self, bad):
        with _main("ro"):
            assert wizard_languages(bad) == ["ro", "en", "ru"]


# --- add category --------------------------------------------------------------------------

async def _cat_wizard(make_message, make_callback_query, fsm_context, texts):
    """``texts``: per wizard step the typed text, None = Skip. Returns the first prompt."""
    await fsm_context.set_state(CategoryFSM.waiting_add_category)
    first = make_message(text=texts[0], user_id=ADMIN_ID)
    await cm.process_category_for_add(first, fsm_context)
    for text in texts[1:]:
        if text is None:
            await cm.skip_category_translation(_skip(make_callback_query, "cat_tr_skip"), fsm_context)
        else:
            await cm.process_category_translation(make_message(text=text, user_id=ADMIN_ID), fsm_context)
    await cm.skip_category_parent(_skip(make_callback_query, "cat_parent_skip"), fsm_context)
    return first


class TestAddCategoryLanguageFirst:

    @pytest.mark.parametrize("admin", LANGS)
    async def test_start_prompt_names_the_admins_language(self, make_callback_query, fsm_context, user_factory, admin):
        await user_factory(telegram_id=ADMIN_ID, language=admin)
        call = make_callback_query(data="add_category", user_id=ADMIN_ID)
        await cm.add_category_callback_handler(call, fsm_context)
        assert language_label(admin) in call.message.edit_text.call_args[0][0]
        assert await fsm_context.get_state() == CategoryFSM.waiting_add_category

    @pytest.mark.parametrize("admin", LANGS)
    async def test_next_prompts_exclude_the_admins_language_and_are_skippable(
            self, make_message, make_callback_query, fsm_context, user_factory, admin):
        await user_factory(telegram_id=ADMIN_ID, language=admin)
        await fsm_context.set_state(CategoryFSM.waiting_add_category)
        msg = make_message(text="Name", user_id=ADMIN_ID)
        await cm.process_category_for_add(msg, fsm_context)

        markup = msg.answer.call_args[1]["reply_markup"]
        assert "cat_tr_skip" in [b.callback_data for row in markup.inline_keyboard for b in row]
        assert language_label(_others(admin)[0]) in msg.answer.call_args[0][0]
        asked = []
        while await fsm_context.get_state() == CategoryFSM.waiting_add_category_translation:
            asked.append((await fsm_context.get_data())["cat_queue"][0])
            await cm.skip_category_translation(_skip(make_callback_query, "cat_tr_skip"), fsm_context)
        await cm.skip_category_parent(_skip(make_callback_query, "cat_parent_skip"), fsm_context)
        assert asked == _others(admin)
        # Only the admin's language was entered -> it is the canonical name.
        cat = await check_category("Name")
        assert cat[f"name_{admin}"] == "Name"

    @pytest.mark.parametrize("main", LANGS)
    @pytest.mark.parametrize("admin", LANGS)
    async def test_canonical_is_the_main_language_text(self, make_message, make_callback_query, fsm_context,
                                                      user_factory, admin, main):
        await user_factory(telegram_id=ADMIN_ID, language=admin)
        texts = {lang: f"cat-{lang}" for lang in LANGS}
        with _main(main):
            await _cat_wizard(make_message, make_callback_query, fsm_context,
                              [texts[c] for c in wizard_languages(admin)])
        cat = await check_category(f"cat-{main}")
        assert cat is not None
        for lang in LANGS:
            assert cat[f"name_{lang}"] == texts[lang]

    @pytest.mark.parametrize("main", LANGS)
    @pytest.mark.parametrize("admin", LANGS)
    async def test_canonical_falls_back_to_the_admins_language(self, make_message, make_callback_query,
                                                              fsm_context, user_factory, admin, main):
        if admin == main:
            pytest.skip("covered above")
        await user_factory(telegram_id=ADMIN_ID, language=admin)
        steps = [f"cat-{admin}"] + [None] * 2
        with _main(main):
            await _cat_wizard(make_message, make_callback_query, fsm_context, steps)
        cat = await check_category(f"cat-{admin}")
        assert cat is not None
        assert cat[f"name_{admin}"] == f"cat-{admin}" and cat[f"name_{main}"] is None   # main column stays NULL

    async def test_canonical_is_main_even_when_entered_last(self, make_message, make_callback_query,
                                                           fsm_context, user_factory):
        await user_factory(telegram_id=ADMIN_ID, language="ru")
        with _main("ro"):
            await _cat_wizard(make_message, make_callback_query, fsm_context, ["Мебель", None, "Mobilă"])
        cat = await check_category("Mobilă")
        assert cat["name_ru"] == "Мебель" and cat["name_ro"] == "Mobilă" and cat["name_en"] is None
        assert await check_category("Мебель") is None

    async def test_duplicate_against_a_translation_is_refused_at_step_one(self, make_message, fsm_context,
                                                                         user_factory):
        await user_factory(telegram_id=ADMIN_ID, language="ro")
        await create_category("Furniture", names={"ro": "Mobilă"})
        await fsm_context.set_state(CategoryFSM.waiting_add_category)
        msg = make_message(text="mobilă", user_id=ADMIN_ID)
        await cm.process_category_for_add(msg, fsm_context)
        assert "exist" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() is None

    async def test_duplicate_translation_is_refused_and_reprompts(self, make_message, fsm_context, user_factory):
        await user_factory(telegram_id=ADMIN_ID, language="en")
        await create_category("Furniture", names={"ro": "Mobilă"})
        await fsm_context.set_state(CategoryFSM.waiting_add_category)
        await cm.process_category_for_add(make_message(text="Chairs", user_id=ADMIN_ID), fsm_context)
        msg = make_message(text="Mobilă", user_id=ADMIN_ID)
        await cm.process_category_translation(msg, fsm_context)
        assert "exist" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() == CategoryFSM.waiting_add_category_translation
        assert (await fsm_context.get_data())["cat_queue"] == ["ru", "ro"]


# --- add product ---------------------------------------------------------------------------

async def _item_wizard(make_message, make_callback_query, fsm_context, names, descriptions, admin):
    langs = wizard_languages(admin)
    await fsm_context.set_state(AddItemFSM.waiting_item_name)
    await ap.check_item_name_for_add(make_message(text=names[0], user_id=ADMIN_ID), fsm_context)
    for value in names[1:]:
        if value is None:
            await ap.add_item_skip_translation(_skip(make_callback_query, "add_item_skip_tr"), fsm_context)
        else:
            await ap.add_item_name_translation(make_message(text=value, user_id=ADMIN_ID), fsm_context)
    await ap.add_item_description(make_message(text=descriptions[0], user_id=ADMIN_ID), fsm_context)
    for value in descriptions[1:]:
        if value is None:
            await ap.add_item_skip_translation(_skip(make_callback_query, "add_item_skip_tr"), fsm_context)
        else:
            await ap.add_item_description_translation(make_message(text=value, user_id=ADMIN_ID), fsm_context)
    assert langs  # (kept for readability of the call sites)
    await create_category("WizCat")
    await ap.add_item_price(make_message(text="10", user_id=ADMIN_ID), fsm_context)
    await ap.check_category_for_add_item(make_message(text="WizCat", user_id=ADMIN_ID), fsm_context)
    await ap.add_item_stock(make_message(text="2", user_id=ADMIN_ID), fsm_context)
    await ap.add_item_skip_photo(_skip(make_callback_query, "add_item_skip_photo"), fsm_context)


class TestAddItemLanguageFirst:

    @pytest.mark.parametrize("admin", LANGS)
    async def test_name_and_description_prompts_are_in_the_admins_language(
            self, make_message, make_callback_query, fsm_context, user_factory, admin):
        await user_factory(telegram_id=ADMIN_ID, language=admin)
        call = make_callback_query(data="add_item", user_id=ADMIN_ID)
        await ap.add_item_callback_handler(call, fsm_context)
        assert language_label(admin) in call.message.edit_text.call_args[0][0]

        msg = make_message(text="Thing", user_id=ADMIN_ID)
        await ap.check_item_name_for_add(msg, fsm_context)
        asked = []
        while await fsm_context.get_state() == AddItemFSM.waiting_item_name_translation:
            asked.append((await fsm_context.get_data())["item_name_queue"][0])
            await ap.add_item_skip_translation(_skip(make_callback_query, "add_item_skip_tr"), fsm_context)
        assert asked == _others(admin)
        assert await fsm_context.get_state() == AddItemFSM.waiting_item_description

        await ap.add_item_description(make_message(text="Desc", user_id=ADMIN_ID), fsm_context)
        asked = []
        while await fsm_context.get_state() == AddItemFSM.waiting_item_description_translation:
            asked.append((await fsm_context.get_data())["item_desc_queue"][0])
            await ap.add_item_skip_translation(_skip(make_callback_query, "add_item_skip_tr"), fsm_context)
        assert asked == _others(admin)

    @pytest.mark.parametrize("admin", LANGS)
    async def test_description_prompt_names_the_admins_language(self, make_message, make_callback_query,
                                                               fsm_context, user_factory, admin):
        await user_factory(telegram_id=ADMIN_ID, language=admin)
        await fsm_context.set_state(AddItemFSM.waiting_item_name)
        await ap.check_item_name_for_add(make_message(text="Thing", user_id=ADMIN_ID), fsm_context)
        cb = _skip(make_callback_query, "add_item_skip_tr")
        for _ in range(2):
            await ap.add_item_skip_translation(cb, fsm_context)
        assert language_label(admin) in cb.message.answer.call_args[0][0]

    @pytest.mark.parametrize("main", LANGS)
    @pytest.mark.parametrize("admin", LANGS)
    async def test_canonical_derived_from_the_main_language(self, make_message, make_callback_query,
                                                           fsm_context, user_factory, admin, main):
        await user_factory(telegram_id=ADMIN_ID, language=admin)
        order = wizard_languages(admin)
        with _main(main):
            await _item_wizard(make_message, make_callback_query, fsm_context,
                               [f"n-{c}" for c in order], [f"d-{c}" for c in order], admin)
        item = await get_item_info(f"n-{main}")
        assert item and item["description"] == f"d-{main}"
        for lang in LANGS:
            assert item[f"name_{lang}"] == f"n-{lang}" and item[f"description_{lang}"] == f"d-{lang}"

    @pytest.mark.parametrize("main", LANGS)
    @pytest.mark.parametrize("admin", LANGS)
    async def test_canonical_falls_back_to_the_admins_language(self, make_message, make_callback_query,
                                                              fsm_context, user_factory, admin, main):
        if admin == main:
            pytest.skip("same as the main-language case")
        await user_factory(telegram_id=ADMIN_ID, language=admin)
        with _main(main):
            await _item_wizard(make_message, make_callback_query, fsm_context,
                               [f"n-{admin}", None, None], [f"d-{admin}", None, None], admin)
        item = await get_item_info(f"n-{admin}")
        assert item and item["description"] == f"d-{admin}"
        assert item[f"name_{main}"] is None and item[f"description_{main}"] is None
        assert item[f"name_{admin}"] == f"n-{admin}"

    async def test_canonical_is_main_even_when_entered_after_the_admins_language(
            self, make_message, make_callback_query, fsm_context, user_factory):
        await user_factory(telegram_id=ADMIN_ID, language="ru")
        with _main("en"):
            await _item_wizard(make_message, make_callback_query, fsm_context,
                               ["Стул", "Chair", None], ["Удобный", None, None], "ru")
        item = await get_item_info("Chair")
        assert item and item["description"] == "Удобный"          # main description not entered -> admin's
        assert item["name_ru"] == "Стул"
        assert await get_item_info("Стул") is None

    async def test_duplicate_against_a_translation_at_step_one(self, make_message, fsm_context, user_factory):
        await user_factory(telegram_id=ADMIN_ID, language="ro")
        await create_category("C")
        await create_item("Chair", "d", 1, "C", names={"ro": "Scaun"})
        await fsm_context.set_state(AddItemFSM.waiting_item_name)
        msg = make_message(text="SCAUN", user_id=ADMIN_ID)
        await ap.check_item_name_for_add(msg, fsm_context)
        assert "name.exists" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() == AddItemFSM.waiting_item_name

    async def test_duplicate_translation_is_refused_and_reprompts(self, make_message, fsm_context, user_factory):
        await user_factory(telegram_id=ADMIN_ID, language="en")
        await create_category("C")
        await create_item("Chair", "d", 1, "C", names={"ro": "Scaun"})
        await fsm_context.set_state(AddItemFSM.waiting_item_name)
        await ap.check_item_name_for_add(make_message(text="Seat", user_id=ADMIN_ID), fsm_context)
        msg = make_message(text="Scaun", user_id=ADMIN_ID)
        await ap.add_item_name_translation(msg, fsm_context)
        assert "name.exists" in msg.answer.call_args[0][0]
        assert (await fsm_context.get_data())["item_name_queue"] == ["ru", "ro"]

    async def test_category_step_accepts_a_translated_name(self, make_message, fsm_context):
        await create_category("Furniture", names={"ro": "Mobilă"})
        await fsm_context.set_state(AddItemFSM.waiting_category)
        await ap.check_category_for_add_item(make_message(text="MOBILĂ", user_id=1), fsm_context)
        assert (await fsm_context.get_data())["item_category"] == "Furniture"
        assert await fsm_context.get_state() == AddItemFSM.waiting_stock

    async def test_category_step_unknown(self, make_message, fsm_context):
        await fsm_context.set_state(AddItemFSM.waiting_category)
        msg = make_message(text="Nope", user_id=1)
        await ap.check_category_for_add_item(msg, fsm_context)
        assert "category.not_found" in msg.answer.call_args[0][0]


# --- typed names in any language -----------------------------------------------------------

@pytest.fixture
async def catalog():
    """Furniture (ro: Mobilă, ru: Мебель) with the product Chair (ro: Scaun, ru: Стул), 5 in stock."""
    await create_category("Furniture", names={"ro": "Mobilă", "ru": "Мебель"})
    await create_item("Chair", "d", 10, "Furniture", stock=5, names={"ro": "Scaun", "ru": "Стул"})


CAT_TYPED = ["Furniture", "furniture", "Mobilă", "MOBILĂ", "мебель"]
ITEM_TYPED = ["Chair", "chair", "Scaun", "SCAUN", "стул"]


class TestResolveHelpers:

    @pytest.mark.parametrize("typed", CAT_TYPED + ["  Mobilă  "])
    async def test_category(self, catalog, typed):
        assert await resolve_category_name(typed) == "Furniture"

    @pytest.mark.parametrize("typed", ITEM_TYPED)
    async def test_item(self, catalog, typed):
        assert await resolve_item_name(typed) == "Chair"

    @pytest.mark.parametrize("typed", ["", "  ", "Nope"])
    async def test_unknown(self, catalog, typed):
        assert await resolve_category_name(typed) is None and await resolve_item_name(typed) is None


class TestCategoryFlows:

    @pytest.mark.parametrize("typed", CAT_TYPED)
    async def test_delete(self, make_message, fsm_context, catalog, typed):
        await create_category("Other")
        await fsm_context.set_state(CategoryFSM.waiting_delete_category)
        with patch('bot.handlers.admin.categories_management.log_audit', new_callable=AsyncMock) as audit:
            await cm.process_category_for_delete(make_message(text=typed, user_id=1), fsm_context)
        assert audit.await_args[1]["resource_id"] == "Furniture"
        assert await check_category("Furniture") is None and await check_category("Other")

    async def test_delete_unknown(self, make_message, fsm_context, catalog):
        msg = make_message(text="Nope", user_id=1)
        await cm.process_category_for_delete(msg, fsm_context)
        assert "delete.not_found" in msg.answer.call_args[0][0]
        assert await check_category("Furniture")

    @pytest.mark.parametrize("typed", CAT_TYPED)
    async def test_rename_old_name(self, make_message, fsm_context, catalog, typed):
        await fsm_context.set_state(CategoryFSM.waiting_update_category)
        await cm.check_category_for_update(make_message(text=typed, user_id=1), fsm_context)
        assert (await fsm_context.get_data())["old_category"] == "Furniture"
        assert await fsm_context.get_state() == CategoryFSM.waiting_update_category_name

    async def test_rename_old_unknown(self, make_message, fsm_context, catalog):
        msg = make_message(text="Nope", user_id=1)
        await cm.check_category_for_update(msg, fsm_context)
        assert "rename.not_found" in msg.answer.call_args[0][0]

    async def test_rename_new_name_uniqueness_includes_translations(self, make_message, fsm_context, catalog):
        await create_category("Other")
        await fsm_context.update_data(old_category="Other")
        msg = make_message(text="mobilă", user_id=1)
        await cm.check_category_name_for_update(msg, fsm_context)
        assert "rename.exist" in msg.answer.call_args[0][0]
        assert await check_category("Other")

    async def test_rename_to_own_translation_is_allowed(self, make_message, fsm_context, catalog):
        await fsm_context.update_data(old_category="Furniture")
        await cm.check_category_name_for_update(make_message(text="Mobilă", user_id=1), fsm_context)
        assert await check_category("Mobilă") and await check_category("Furniture") is None

    @pytest.mark.parametrize("typed", CAT_TYPED)
    async def test_translations_editor_entry(self, make_message, fsm_context, catalog, typed):
        await fsm_context.set_state(TranslationFSM.waiting_category_name)
        await tr.translations_category_name(make_message(text=typed, user_id=1), fsm_context)
        assert (await fsm_context.get_data())["tr_name"] == "Furniture"
        assert await fsm_context.get_state() == TranslationFSM.card

    async def test_translations_editor_unknown(self, make_message, fsm_context, catalog):
        msg = make_message(text="Nope", user_id=1)
        await tr.translations_category_name(msg, fsm_context)
        assert "category_not_found" in msg.answer.call_args[0][0]

    @pytest.mark.parametrize("admin", LANGS)
    async def test_editor_lists_the_admins_language_first(self, make_message, fsm_context, catalog,
                                                         user_factory, admin):
        await user_factory(telegram_id=ADMIN_ID, language=admin)
        await fsm_context.set_state(TranslationFSM.waiting_category_name)
        msg = make_message(text="Furniture", user_id=ADMIN_ID)
        with _main("en"):
            await tr.translations_category_name(msg, fsm_context)
        text = msg.answer.call_args[0][0]
        positions = [text.index(language_label(c)) for c in wizard_languages(admin)]
        assert positions == sorted(positions)


class TestItemFlows:

    @pytest.mark.parametrize("typed", ITEM_TYPED)
    async def test_delete(self, make_message, fsm_context, catalog, typed):
        await fsm_context.set_state(GoodsFSM.waiting_item_name_delete)
        await gm.delete_str_item(make_message(text=typed, user_id=1), fsm_context)
        assert await get_item_info("Chair") is None

    async def test_delete_unknown(self, make_message, fsm_context, catalog):
        msg = make_message(text="Nope", user_id=1)
        await gm.delete_str_item(msg, fsm_context)
        assert "delete.position.not_found" in msg.answer.call_args[0][0]
        assert await get_item_info("Chair")

    @pytest.mark.parametrize("typed", ITEM_TYPED)
    async def test_stock_card(self, make_message, fsm_context, catalog, typed):
        await fsm_context.set_state(StockFSM.waiting_item_name)
        await gm.show_item_stock(make_message(text=typed, user_id=1), fsm_context)
        assert (await fsm_context.get_data())["stock_item_name"] == "Chair"
        assert await fsm_context.get_state() == StockFSM.card

    async def test_stock_card_unknown(self, make_message, fsm_context, catalog):
        msg = make_message(text="Nope", user_id=1)
        await gm.show_item_stock(msg, fsm_context)
        assert "position.not_found" in msg.answer.call_args[0][0]

    @pytest.mark.parametrize("typed", ITEM_TYPED)
    async def test_update_old_name(self, make_message, fsm_context, catalog, typed):
        await fsm_context.set_state(UpdateItemFSM.waiting_item_name_for_update)
        await up.check_item_name_for_update(make_message(text=typed, user_id=1), fsm_context)
        data = await fsm_context.get_data()
        assert data["item_old_name"] == "Chair" and data["item_category"] == "Furniture"
        assert await fsm_context.get_state() == UpdateItemFSM.waiting_item_new_name

    async def test_update_old_name_unknown(self, make_message, fsm_context, catalog):
        msg = make_message(text="Nope", user_id=1)
        await up.check_item_name_for_update(msg, fsm_context)
        assert msg.answer.call_args[0][0] == localize("admin.goods.update.not_exists")

    @pytest.mark.parametrize("typed", CAT_TYPED)
    async def test_update_category(self, make_message, fsm_context, catalog, typed):
        await fsm_context.update_data(item_old_name="Chair", item_new_name="Chair", item_description="d",
                                      item_price=10, item_category="Furniture")
        await fsm_context.set_state(UpdateItemFSM.waiting_item_category)
        with patch('bot.handlers.admin.update_position.log_audit', new_callable=AsyncMock):
            await up.update_item_category(make_message(text=typed, user_id=1), fsm_context)
        assert (await get_item_info("Chair"))["category_id"] == (await check_category("Furniture"))["id"]

    async def test_update_category_unknown(self, make_message, fsm_context, catalog):
        msg = make_message(text="Nope", user_id=1)
        await up.update_item_category(msg, fsm_context)
        assert msg.answer.call_args[0][0] == localize("admin.goods.update.category.not_found")

    @pytest.mark.parametrize("typed", ITEM_TYPED)
    async def test_sale(self, make_message, fsm_context, catalog, typed):
        await fsm_context.set_state(SaleFSM.waiting_item_name)
        await sm.sale_item_name(make_message(text=typed, user_id=1), fsm_context)
        assert (await fsm_context.get_data())["sale_item_name"] == "Chair"
        assert await fsm_context.get_state() == SaleFSM.waiting_percent

    async def test_sale_unknown(self, make_message, fsm_context, catalog):
        msg = make_message(text="Nope", user_id=1)
        await sm.sale_item_name(msg, fsm_context)
        assert "sale.not_found" in msg.answer.call_args[0][0]


class TestPromoBinding:

    async def _bind(self, make_message, fsm_context, kind, typed, code):
        await fsm_context.update_data(promo_binding_type=kind, promo_code=code, promo_type="percent",
                                      promo_value=10, promo_max_uses=0, promo_expires=None)
        await fsm_context.set_state(PromoFSM.waiting_binding_name)
        msg = make_message(text=typed, user_id=1)
        await pm.promo_receive_binding_name(msg, fsm_context)
        return msg

    @pytest.mark.parametrize("typed", CAT_TYPED)
    async def test_category(self, make_message, fsm_context, catalog, typed):
        await self._bind(make_message, fsm_context, "category", typed, "CATBIND")
        promo = await get_promo_code("CATBIND")
        assert promo and promo["category_id"] == (await check_category("Furniture"))["id"]

    @pytest.mark.parametrize("typed", ITEM_TYPED)
    async def test_item(self, make_message, fsm_context, catalog, typed):
        await self._bind(make_message, fsm_context, "item", typed, "ITEMBIND")
        promo = await get_promo_code("ITEMBIND")
        assert promo and promo["item_id"] == (await get_item_info("Chair"))["id"]

    @pytest.mark.parametrize("kind,key", [("category", "admin.promo.category_not_found"),
                                          ("item", "admin.promo.item_not_found")])
    async def test_unknown(self, make_message, fsm_context, catalog, kind, key):
        msg = await self._bind(make_message, fsm_context, kind, "Nope", "NOBIND")
        assert msg.answer.call_args[0][0] == localize(key)
        assert await get_promo_code("NOBIND") is None
