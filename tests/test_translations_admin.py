"""Admin entry of catalog translations: add wizards, the translations editor, permissions, audit."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.database.methods.read import check_category, get_item_info
from bot.database.models import Permission
from bot.filters import HasPermissionFilter
from bot.handlers.admin import adding_position as ap
from bot.handlers.admin import categories_management as cm
from bot.handlers.admin import translations as tr
from bot.handlers.admin._common import main_language, other_languages
from bot.misc.localized import MAX_NAME_LEN, MAX_DESCRIPTION_LEN
from bot.states import AddItemFSM, CategoryFSM, StockFSM, TranslationFSM

OTHERS = {"en": ["ru", "ro"], "ru": ["en", "ro"], "ro": ["en", "ru"]}


@pytest.fixture(params=["en", "ru", "ro"])
def main_lang(request):
    with patch('bot.i18n.main.get_locale', return_value=request.param):
        yield request.param


@pytest.fixture
def ru_main():
    with patch('bot.i18n.main.get_locale', return_value="ru"):
        yield "ru"


@pytest.fixture
def audit():
    with patch('bot.handlers.admin.translations.log_audit_bg') as bg:
        yield bg


@pytest.fixture
def hooks():
    with patch('bot.handlers.admin.adding_position._notify_restock_safe', new_callable=AsyncMock), \
            patch('bot.handlers.admin.adding_position.announce_arrival', new_callable=AsyncMock):
        yield


def _call(make_callback_query, data, user_id=1):
    return make_callback_query(data=data, user_id=user_id)


def _buttons(call_args, key="reply_markup"):
    markup = call_args[1][key]
    return [b.callback_data for row in markup.inline_keyboard for b in row]


# --- main language -------------------------------------------------------------------------

class TestLanguages:

    def test_other_languages_exclude_the_main_one(self, main_lang):
        assert main_language() == main_lang
        assert other_languages() == OTHERS[main_lang]


# --- add category --------------------------------------------------------------------------

async def _add_category(make_message, make_callback_query, fsm_context, name, answers):
    """Type the name, then per language either text or None (= Skip)."""
    await fsm_context.set_state(CategoryFSM.waiting_add_category)
    await cm.process_category_for_add(make_message(text=name, user_id=1), fsm_context)
    for answer in answers:
        if answer is None:
            await cm.skip_category_translation(_call(make_callback_query, "cat_tr_skip"), fsm_context)
        else:
            await cm.process_category_translation(make_message(text=answer, user_id=1), fsm_context)


class TestAddCategory:

    async def test_all_skipped_creates_without_translations(self, make_message, make_callback_query,
                                                            fsm_context, ru_main):
        await _add_category(make_message, make_callback_query, fsm_context, "Mobila", [None, None])

        cat = await check_category("Mobila")
        # Only the typed (main = admin default) language is stored.
        assert cat and cat["name_en"] is None and cat["name_ro"] is None and cat["name_ru"] == "Mobila"
        assert await fsm_context.get_state() is None

    async def test_partial_translations(self, make_message, make_callback_query, fsm_context, ru_main):
        await _add_category(make_message, make_callback_query, fsm_context, "Мебель", ["Furniture", None])

        cat = await check_category("Мебель")
        assert cat["name_en"] == "Furniture" and cat["name_ro"] is None

    async def test_full_translations_are_cleaned(self, make_message, make_callback_query, fsm_context, ru_main):
        await _add_category(make_message, make_callback_query, fsm_context, "Мебель",
                            ["  <b>Furniture</b> ", "Mobilă"])

        cat = await check_category("Мебель")
        assert (cat["name_en"], cat["name_ro"], cat["name_ru"]) == ("Furniture", "Mobilă", "Мебель")

    async def test_main_language_is_never_asked(self, make_message, make_callback_query, fsm_context, main_lang):
        await fsm_context.set_state(CategoryFSM.waiting_add_category)
        msg = make_message(text="Main", user_id=1)
        await cm.process_category_for_add(msg, fsm_context)

        asked = []
        while await fsm_context.get_state() == CategoryFSM.waiting_add_category_translation:
            asked.append((await fsm_context.get_data())["cat_queue"][0])
            await cm.skip_category_translation(_call(make_callback_query, "cat_tr_skip"), fsm_context)
        assert asked == OTHERS[main_lang]
        cat = await check_category("Main")
        assert all(cat[f"name_{l}"] is None for l in OTHERS[main_lang])
        assert cat[f"name_{main_lang}"] == "Main"

    async def test_main_language_text_stays_canonical(self, make_message, make_callback_query, fsm_context, main_lang):
        first, second = OTHERS[main_lang]
        await _add_category(make_message, make_callback_query, fsm_context, "Canon", ["one", "two"])

        cat = await check_category("Canon")
        assert cat["name"] == "Canon" and cat[f"name_{first}"] == "one" and cat[f"name_{second}"] == "two"
        assert cat[f"name_{main_lang}"] == "Canon"

    @pytest.mark.parametrize("bad,key", [("x" * (MAX_NAME_LEN + 1), "too_long"), ("<i></i>", "invalid"), ("  ", "invalid")])
    async def test_bad_translation_reprompts_and_stays(self, make_message, make_callback_query,
                                                       fsm_context, ru_main, bad, key):
        await fsm_context.set_state(CategoryFSM.waiting_add_category)
        await cm.process_category_for_add(make_message(text="Cat", user_id=1), fsm_context)

        msg = make_message(text=bad, user_id=1)
        await cm.process_category_translation(msg, fsm_context)

        assert key in msg.answer.call_args[0][0]
        assert _buttons(msg.answer.call_args) == ["cat_tr_skip", "categories_management"]
        assert await fsm_context.get_state() == CategoryFSM.waiting_add_category_translation
        assert (await fsm_context.get_data())["cat_queue"] == ["en", "ro"]
        assert await check_category("Cat") is None

    async def test_first_prompt_has_skip_button(self, make_message, fsm_context, ru_main):
        await fsm_context.set_state(CategoryFSM.waiting_add_category)
        msg = make_message(text="Cat", user_id=1)
        await cm.process_category_for_add(msg, fsm_context)

        assert "add.prompt.translation" in msg.answer.call_args[0][0]
        assert "English" in msg.answer.call_args[0][0]
        assert _buttons(msg.answer.call_args) == ["cat_tr_skip", "categories_management"]

    async def test_duplicate_main_name_stops_before_translations(self, make_message, fsm_context, category_factory):
        await category_factory("Dup")
        msg = make_message(text="Dup", user_id=1)
        await cm.process_category_for_add(msg, fsm_context)

        assert "exist" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() is None

    @pytest.mark.parametrize("bad", ["", "   ", "x" * 101, "<b></b>"])
    async def test_invalid_main_name_is_refused(self, make_message, fsm_context, bad):
        msg = make_message(text=bad, user_id=1)
        await cm.process_category_for_add(msg, fsm_context)

        assert "invalid_data" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() is None

    async def test_creation_is_audited_with_the_languages(self, make_message, make_callback_query,
                                                          fsm_context, ru_main):
        with patch('bot.handlers.admin.categories_management.log_audit', new_callable=AsyncMock) as audit:
            await _add_category(make_message, make_callback_query, fsm_context, "Aud", ["Furn", None])

        assert audit.await_args[0][0] == "create_category"
        assert audit.await_args[1]["resource_id"] == "Aud"
        assert "translations=en" in audit.await_args[1]["details"]

    def test_translation_handlers_need_catalog_manage(self):
        names = {"process_category_translation", "skip_category_translation"}
        hs = [h for h in cm.router.callback_query.handlers + cm.router.message.handlers
              if h.callback.__name__ in names]
        assert {h.callback.__name__ for h in hs} == names
        for h in hs:
            perms = [f.callback for f in h.filters if isinstance(f.callback, HasPermissionFilter)]
            assert perms and perms[0].permission == Permission.CATALOG_MANAGE

    async def test_menu_has_the_translations_entry(self, make_callback_query):
        call = _call(make_callback_query, "categories_management")
        await cm.categories_callback_handler(call)
        assert "tr:cat" in _buttons(call.message.edit_text.call_args)


# --- add product ---------------------------------------------------------------------------

async def _add_item(make_message, make_callback_query, fsm_context, *, name="Chair", names=(), description="Desc",
                    descriptions=()):
    """Name + per-language names (text/None=Skip), description + per-language descriptions, then price..stock."""
    await fsm_context.set_state(AddItemFSM.waiting_item_name)
    await ap.check_item_name_for_add(make_message(text=name, user_id=1), fsm_context)
    for value in names:
        await _answer(ap.add_item_name_translation, make_message, make_callback_query, fsm_context, value)
    await ap.add_item_description(make_message(text=description, user_id=1), fsm_context)
    for value in descriptions:
        await _answer(ap.add_item_description_translation, make_message, make_callback_query, fsm_context, value)


async def _answer(handler, make_message, make_callback_query, fsm_context, value):
    if value is None:
        await ap.add_item_skip_translation(_call(make_callback_query, "add_item_skip_tr"), fsm_context)
    else:
        await handler(make_message(text=value, user_id=1), fsm_context)


async def _finish(make_message, fsm_context, category_factory):
    await category_factory("AddCat")
    await ap.add_item_price(make_message(text="100", user_id=1), fsm_context)
    await ap.check_category_for_add_item(make_message(text="AddCat", user_id=1), fsm_context)
    await ap.add_item_stock(make_message(text="3", user_id=1), fsm_context)


class TestAddProduct:

    async def test_sequence_of_states(self, make_message, make_callback_query, fsm_context, ru_main):
        await fsm_context.set_state(AddItemFSM.waiting_item_name)
        await ap.check_item_name_for_add(make_message(text="Chair", user_id=1), fsm_context)
        assert await fsm_context.get_state() == AddItemFSM.waiting_item_name_translation
        await ap.add_item_skip_translation(_call(make_callback_query, "add_item_skip_tr"), fsm_context)
        assert await fsm_context.get_state() == AddItemFSM.waiting_item_name_translation
        await ap.add_item_skip_translation(_call(make_callback_query, "add_item_skip_tr"), fsm_context)
        assert await fsm_context.get_state() == AddItemFSM.waiting_item_description
        await ap.add_item_description(make_message(text="D", user_id=1), fsm_context)
        assert await fsm_context.get_state() == AddItemFSM.waiting_item_description_translation
        await ap.add_item_skip_translation(_call(make_callback_query, "add_item_skip_tr"), fsm_context)
        await ap.add_item_skip_translation(_call(make_callback_query, "add_item_skip_tr"), fsm_context)
        assert await fsm_context.get_state() == AddItemFSM.waiting_item_price

    async def test_all_skipped(self, make_message, make_callback_query, fsm_context, category_factory, hooks, ru_main):
        await _add_item(make_message, make_callback_query, fsm_context, names=[None, None], descriptions=[None, None])
        await _finish(make_message, fsm_context, category_factory)
        await ap.add_item_skip_photo(_call(make_callback_query, "add_item_skip_photo"), fsm_context)

        item = await get_item_info("Chair")
        assert item["description"] == "Desc"
        for lang in ("en", "ro"):
            assert item[f"name_{lang}"] is None and item[f"description_{lang}"] is None
        assert item["name_ru"] == "Chair" and item["description_ru"] == "Desc"

    async def test_partial_translations(self, make_message, make_callback_query, fsm_context, category_factory,
                                        hooks, ru_main):
        await _add_item(make_message, make_callback_query, fsm_context, name="Стул",
                        names=["Chair", None], description="Удобный", descriptions=[None, "Confortabil"])
        await _finish(make_message, fsm_context, category_factory)
        await ap.add_item_skip_photo(_call(make_callback_query, "add_item_skip_photo"), fsm_context)

        item = await get_item_info("Стул")
        assert (item["name_en"], item["name_ro"]) == ("Chair", None)
        assert (item["description_en"], item["description_ro"]) == (None, "Confortabil")
        assert item["name_ru"] == "Стул" and item["description_ru"] == "Удобный"

    async def test_full_translations_with_photo_step(self, make_message, make_callback_query, fsm_context,
                                                     category_factory, hooks, main_lang):
        a, b = OTHERS[main_lang]
        await _add_item(make_message, make_callback_query, fsm_context, names=["N-" + a, "N-" + b],
                        descriptions=["D-" + a, "D-" + b])
        await _finish(make_message, fsm_context, category_factory)
        assert await fsm_context.get_state() == AddItemFSM.waiting_photo
        assert await get_item_info("Chair") is None            # created only at the photo step
        await ap.add_item_skip_photo(_call(make_callback_query, "add_item_skip_photo"), fsm_context)

        item = await get_item_info("Chair")
        assert item["name"] == "Chair" and item["description"] == "Desc"
        assert item[f"name_{a}"] == "N-" + a and item[f"name_{b}"] == "N-" + b
        assert item[f"description_{a}"] == "D-" + a and item[f"description_{b}"] == "D-" + b
        assert item[f"name_{main_lang}"] == "Chair" and item[f"description_{main_lang}"] == "Desc"

    async def test_translations_are_audited(self, make_message, make_callback_query, fsm_context,
                                            category_factory, hooks, ru_main):
        await _add_item(make_message, make_callback_query, fsm_context, names=["Chair", None],
                        descriptions=[None, None])
        await _finish(make_message, fsm_context, category_factory)
        with patch('bot.handlers.admin.adding_position.log_audit', new_callable=AsyncMock) as audit:
            await ap.add_item_skip_photo(_call(make_callback_query, "add_item_skip_photo"), fsm_context)
        assert "translations=en" in audit.await_args[1]["details"]

    @pytest.mark.parametrize("handler,state,field,limit", [
        (ap.add_item_name_translation, AddItemFSM.waiting_item_name_translation, "name", MAX_NAME_LEN),
        (ap.add_item_description_translation, AddItemFSM.waiting_item_description_translation,
         "description", MAX_DESCRIPTION_LEN),
    ])
    async def test_too_long_and_invalid_reprompt(self, make_message, fsm_context, ru_main, handler, state,
                                                 field, limit):
        queue_key = "item_name_queue" if field == "name" else "item_desc_queue"
        await fsm_context.set_state(state)
        await fsm_context.update_data(**{queue_key: ["en", "ro"]})

        too_long = make_message(text="x" * (limit + 1), user_id=1)
        await handler(too_long, fsm_context)
        assert "too_long" in too_long.answer.call_args[0][0]
        assert f"'max': {limit}" in too_long.answer.call_args[0][0]

        blank = make_message(text="<b> </b>", user_id=1)
        await handler(blank, fsm_context)
        assert "invalid" in blank.answer.call_args[0][0]

        assert await fsm_context.get_state() == state
        assert (await fsm_context.get_data())[queue_key] == ["en", "ro"]
        assert _buttons(blank.answer.call_args) == ["add_item_skip_tr", "goods_management"]

    async def test_description_at_the_limit_is_accepted_and_longer_refused(self, make_message, fsm_context, ru_main):
        await fsm_context.set_state(AddItemFSM.waiting_item_description)
        long_msg = make_message(text="d" * (MAX_DESCRIPTION_LEN + 1), user_id=1)
        await ap.add_item_description(long_msg, fsm_context)
        assert "too_long" in long_msg.answer.call_args[0][0]
        assert await fsm_context.get_state() == AddItemFSM.waiting_item_description

        await ap.add_item_description(make_message(text="d" * MAX_DESCRIPTION_LEN, user_id=1), fsm_context)
        assert await fsm_context.get_state() == AddItemFSM.waiting_item_description_translation

    async def test_main_language_is_never_asked(self, make_message, make_callback_query, fsm_context, main_lang):
        await fsm_context.set_state(AddItemFSM.waiting_item_name)
        await ap.check_item_name_for_add(make_message(text="X", user_id=1), fsm_context)
        assert (await fsm_context.get_data())["item_name_queue"] == OTHERS[main_lang]
        await ap.add_item_skip_translation(_call(make_callback_query, "add_item_skip_tr"), fsm_context)
        await ap.add_item_skip_translation(_call(make_callback_query, "add_item_skip_tr"), fsm_context)
        await ap.add_item_description(make_message(text="D", user_id=1), fsm_context)
        assert (await fsm_context.get_data())["item_desc_queue"] == OTHERS[main_lang]

    async def test_duplicate_name_still_refused(self, make_message, fsm_context, item_factory):
        await item_factory(name="Taken", price=1, category="C", stock=1)
        await fsm_context.set_state(AddItemFSM.waiting_item_name)
        await ap.check_item_name_for_add(make_message(text="Taken", user_id=1), fsm_context)
        assert await fsm_context.get_state() == AddItemFSM.waiting_item_name

    def test_translation_handlers_need_catalog_manage(self):
        names = {"add_item_name_translation", "add_item_description_translation", "add_item_skip_translation"}
        hs = [h for h in ap.router.callback_query.handlers + ap.router.message.handlers
              if h.callback.__name__ in names]
        assert {h.callback.__name__ for h in hs} == names
        for h in hs:
            perms = [f.callback for f in h.filters if isinstance(f.callback, HasPermissionFilter)]
            assert perms and perms[0].permission == Permission.CATALOG_MANAGE


# --- translations editor -------------------------------------------------------------------

async def _open_category_editor(make_message, fsm_context, name="Mobila"):
    await fsm_context.set_state(TranslationFSM.waiting_category_name)
    msg = make_message(text=name, user_id=1)
    await tr.translations_category_name(msg, fsm_context)
    return msg


async def _open_item_editor(make_message, make_callback_query, fsm_context, name="Scaun"):
    await fsm_context.set_state(StockFSM.card)
    await fsm_context.update_data(stock_item_name=name)
    call = _call(make_callback_query, "tr:item")
    await tr.translations_item_start(call, fsm_context)
    return call


async def _pick(make_callback_query, fsm_context, lang, field):
    call = _call(make_callback_query, f"tr:e:{lang}:{field}")
    await tr.translations_pick_field(call, fsm_context)
    return call


class TestEditorCategory:

    async def test_start_asks_for_the_name(self, make_callback_query, fsm_context):
        call = _call(make_callback_query, "tr:cat")
        await tr.translations_category_start(call, fsm_context)

        assert await fsm_context.get_state() == TranslationFSM.waiting_category_name
        assert _buttons(call.message.edit_text.call_args) == ["categories_management"]

    async def test_unknown_category_reprompts(self, make_message, fsm_context):
        msg = await _open_category_editor(make_message, fsm_context, "Ghost")

        assert "category_not_found" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() == TranslationFSM.waiting_category_name

    async def test_view_shows_all_languages_with_main_as_canonical(self, make_message, fsm_context,
                                                                   category_factory, ru_main):
        from bot.database.methods.create import create_category
        await create_category("Мебель", names={"en": "Furniture"})

        msg = await _open_category_editor(make_message, fsm_context, "Мебель")

        text = msg.answer.call_args[0][0]
        for label in ("English", "Русский", "Română"):
            assert label in text
        assert "Furniture" in text and "Мебель" in text and "not_set" in text
        assert "admin.translations.main" in text
        assert _buttons(msg.answer.call_args) == ["tr:e:en:n", "tr:e:ro:n", "tr:back"]
        assert await fsm_context.get_state() == TranslationFSM.card
        assert (await fsm_context.get_data())["tr_name"] == "Мебель"

    @pytest.mark.parametrize("main", ["en", "ru", "ro"])
    async def test_editor_lists_only_non_main_languages(self, make_message, fsm_context, category_factory, main):
        await category_factory("Cat")
        with patch('bot.i18n.main.get_locale', return_value=main):
            msg = await _open_category_editor(make_message, fsm_context, "Cat")
        assert _buttons(msg.answer.call_args) == [f"tr:e:{l}:n" for l in OTHERS[main]] + ["tr:back"]

    async def test_set_translation_and_refresh(self, make_message, make_callback_query, fsm_context,
                                               category_factory, audit, ru_main):
        await category_factory("Cat")
        await _open_category_editor(make_message, fsm_context, "Cat")

        pick = await _pick(make_callback_query, fsm_context, "ro", "n")
        assert await fsm_context.get_state() == TranslationFSM.waiting_text
        assert "prompt.name" in pick.message.edit_text.call_args[0][0]
        assert _buttons(pick.message.edit_text.call_args) == ["tr:clear", "tr:card"]

        msg = make_message(text=" <b>Mobilă</b> ", user_id=7)
        await tr.translations_text(msg, fsm_context)

        assert (await check_category("Cat"))["name_ro"] == "Mobilă"
        assert "admin.translations.saved" in msg.answer.call_args[0][0]
        assert "Mobilă" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() == TranslationFSM.card
        assert audit.call_args[0][0] == "update_translation"
        assert audit.call_args[1]["user_id"] == 7
        assert audit.call_args[1]["resource_type"] == "Category" and audit.call_args[1]["resource_id"] == "Cat"
        assert "lang=ro" in audit.call_args[1]["details"] and "action=set" in audit.call_args[1]["details"]

    async def test_clear(self, make_message, make_callback_query, fsm_context, audit, ru_main):
        from bot.database.methods.create import create_category
        await create_category("Cat", names={"en": "Hello", "ro": "Salut"})
        await _open_category_editor(make_message, fsm_context, "Cat")
        await _pick(make_callback_query, fsm_context, "en", "n")

        call = _call(make_callback_query, "tr:clear", user_id=7)
        await tr.translations_clear(call, fsm_context)

        cat = await check_category("Cat")
        assert cat["name_en"] is None and cat["name_ro"] == "Salut"
        assert "admin.translations.cleared" in call.message.edit_text.call_args[0][0]
        assert await fsm_context.get_state() == TranslationFSM.card
        assert "action=clear" in audit.call_args[1]["details"]

    async def test_too_long_is_refused_and_keeps_the_prompt(self, make_message, make_callback_query, fsm_context,
                                                            category_factory, audit, ru_main):
        await category_factory("Cat")
        await _open_category_editor(make_message, fsm_context, "Cat")
        await _pick(make_callback_query, fsm_context, "en", "n")

        msg = make_message(text="x" * (MAX_NAME_LEN + 1), user_id=1)
        await tr.translations_text(msg, fsm_context)

        assert "too_long" in msg.answer.call_args[0][0]
        assert (await check_category("Cat"))["name_en"] is None
        assert await fsm_context.get_state() == TranslationFSM.waiting_text
        audit.assert_not_called()

    @pytest.mark.parametrize("bad", ["", "   ", "<i></i>"])
    async def test_blank_input_is_refused_not_cleared(self, make_message, make_callback_query, fsm_context,
                                                      audit, ru_main, bad):
        from bot.database.methods.create import create_category
        await create_category("Cat", names={"en": "Keep"})
        await _open_category_editor(make_message, fsm_context, "Cat")
        await _pick(make_callback_query, fsm_context, "en", "n")

        msg = make_message(text=bad, user_id=1)
        await tr.translations_text(msg, fsm_context)

        assert "invalid" in msg.answer.call_args[0][0]
        assert (await check_category("Cat"))["name_en"] == "Keep"
        audit.assert_not_called()

    @pytest.mark.parametrize("data", ["tr:e:ru:n", "tr:e:xx:n", "tr:e:en:d", "tr:e:en:z", "tr:e:en"])
    async def test_invalid_selection_is_rejected(self, make_message, make_callback_query, fsm_context,
                                                 category_factory, ru_main, data):
        await category_factory("Cat")
        await _open_category_editor(make_message, fsm_context, "Cat")

        call = _call(make_callback_query, data)
        await tr.translations_pick_field(call, fsm_context)

        # "ru" is the main language here (not editable), "d" does not exist for categories.
        assert call.answer.call_args[1].get("show_alert") is True
        assert await fsm_context.get_state() == TranslationFSM.card

    async def test_back_to_card_from_the_prompt(self, make_message, make_callback_query, fsm_context,
                                                category_factory, ru_main):
        await category_factory("Cat")
        await _open_category_editor(make_message, fsm_context, "Cat")
        await _pick(make_callback_query, fsm_context, "en", "n")

        call = _call(make_callback_query, "tr:card")
        await tr.translations_back_to_card(call, fsm_context)

        assert await fsm_context.get_state() == TranslationFSM.card
        assert "card.title.category" in call.message.edit_text.call_args[0][0]

    async def test_leave_returns_to_the_categories_menu(self, make_message, make_callback_query, fsm_context,
                                                        category_factory, ru_main):
        await category_factory("Cat")
        await _open_category_editor(make_message, fsm_context, "Cat")

        call = _call(make_callback_query, "tr:back")
        await tr.translations_leave(call, fsm_context)

        assert await fsm_context.get_state() is None
        assert "categories.menu.title" in call.message.edit_text.call_args[0][0]

    async def test_category_deleted_meanwhile(self, make_message, make_callback_query, fsm_context, audit, ru_main):
        from bot.database.methods.create import create_category
        from bot.database.methods.delete import delete_category
        await create_category("Gone")
        await _open_category_editor(make_message, fsm_context, "Gone")
        await _pick(make_callback_query, fsm_context, "en", "n")
        await delete_category("Gone")

        msg = make_message(text="Name", user_id=1)
        await tr.translations_text(msg, fsm_context)

        assert "category_not_found" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() is None
        audit.assert_not_called()


class TestEditorItem:

    async def _item(self, item_factory, **names):
        await item_factory(name="Scaun", price=10, category="C", description="Comod", stock=2)
        from bot.database.methods.translations import set_item_translations
        if names:
            await set_item_translations("Scaun", names)

    async def test_view_has_name_and_description_buttons_and_previews(self, make_callback_query, fsm_context,
                                                                       item_factory):
        await self._item(item_factory, en={"name": "Chair", "description": "D" * 500})
        with patch('bot.i18n.main.get_locale', return_value="ro"):
            call = await _open_item_editor(None, make_callback_query, fsm_context)

        text = call.message.edit_text.call_args[0][0]
        assert "card.title.item" in text and "Chair" in text and "Comod" in text
        assert "D" * 500 not in text and "…" in text                  # long descriptions are shortened
        assert _buttons(call.message.edit_text.call_args) == [
            "tr:e:en:n", "tr:e:en:d", "tr:e:ru:n", "tr:e:ru:d", "tr:back"]
        assert (await fsm_context.get_data())["tr_kind"] == "i"

    async def test_set_name_and_description(self, make_message, make_callback_query, fsm_context, item_factory,
                                            audit, ru_main):
        await self._item(item_factory)
        await _open_item_editor(None, make_callback_query, fsm_context)

        await _pick(make_callback_query, fsm_context, "en", "n")
        await tr.translations_text(make_message(text="Chair", user_id=5), fsm_context)
        pick = await _pick(make_callback_query, fsm_context, "en", "d")
        assert "prompt.description" in pick.message.edit_text.call_args[0][0]
        msg = make_message(text="Very  comfy\nline two", user_id=5)
        await tr.translations_text(msg, fsm_context)

        item = await get_item_info("Scaun")
        assert item["name_en"] == "Chair" and item["description_en"] == "Very comfy\nline two"
        assert item["name"] == "Scaun" and item["description"] == "Comod"
        assert [c[1]["details"].split("field=")[1].split(",")[0] for c in audit.call_args_list] == [
            "name", "description"]
        assert audit.call_args[1]["resource_type"] == "Item"

    async def test_clear_description(self, make_callback_query, fsm_context, item_factory, audit, ru_main):
        await self._item(item_factory, en={"name": "Chair", "description": "Comfy"})
        await _open_item_editor(None, make_callback_query, fsm_context)
        await _pick(make_callback_query, fsm_context, "en", "d")

        await tr.translations_clear(_call(make_callback_query, "tr:clear"), fsm_context)

        item = await get_item_info("Scaun")
        assert item["description_en"] is None and item["name_en"] == "Chair"

    async def test_description_limit(self, make_message, make_callback_query, fsm_context, item_factory,
                                     audit, ru_main):
        await self._item(item_factory)
        await _open_item_editor(None, make_callback_query, fsm_context)
        await _pick(make_callback_query, fsm_context, "en", "d")

        ok = make_message(text="d" * MAX_DESCRIPTION_LEN, user_id=1)
        await tr.translations_text(ok, fsm_context)
        assert len((await get_item_info("Scaun"))["description_en"]) == MAX_DESCRIPTION_LEN

        await _pick(make_callback_query, fsm_context, "en", "d")
        bad = make_message(text="d" * (MAX_DESCRIPTION_LEN + 1), user_id=1)
        await tr.translations_text(bad, fsm_context)
        assert "too_long" in bad.answer.call_args[0][0] and f"'max': {MAX_DESCRIPTION_LEN}" in bad.answer.call_args[0][0]
        assert await fsm_context.get_state() == TranslationFSM.waiting_text

    async def test_back_returns_to_the_stock_card(self, make_callback_query, fsm_context, item_factory, ru_main):
        await self._item(item_factory)
        await _open_item_editor(None, make_callback_query, fsm_context)

        call = _call(make_callback_query, "tr:back")
        await tr.translations_leave(call, fsm_context)

        assert await fsm_context.get_state() == StockFSM.card
        assert "admin.goods.stock.card" in call.message.edit_text.call_args[0][0]
        assert (await fsm_context.get_data())["stock_item_name"] == "Scaun"

    async def test_item_deleted_meanwhile(self, make_message, make_callback_query, fsm_context, item_factory,
                                          audit, ru_main):
        from bot.database.methods.delete import delete_item
        await self._item(item_factory)
        await _open_item_editor(None, make_callback_query, fsm_context)
        await _pick(make_callback_query, fsm_context, "en", "n")
        await delete_item("Scaun")

        msg = make_message(text="Chair", user_id=1)
        await tr.translations_text(msg, fsm_context)

        assert "item_not_found" in msg.answer.call_args[0][0]
        assert await fsm_context.get_state() is None
        audit.assert_not_called()

    @pytest.mark.parametrize("code", ["invalid_language", "invalid_field", "too_long", "weird"])
    async def test_error_codes_are_mapped(self, make_message, make_callback_query, fsm_context, item_factory, code, ru_main):
        await self._item(item_factory)
        await _open_item_editor(None, make_callback_query, fsm_context)
        await _pick(make_callback_query, fsm_context, "en", "n")

        with patch('bot.handlers.admin.translations.set_item_translations',
                   new_callable=AsyncMock, return_value=(False, code)):
            msg = make_message(text="Chair", user_id=1)
            await tr.translations_text(msg, fsm_context)

        expected = "errors.invalid_data" if code == "weird" else f"err.{code}"
        assert expected in msg.answer.call_args[0][0]

    async def test_stock_card_has_the_translations_button(self, make_message, fsm_context, item_factory):
        from bot.handlers.admin.goods_management import show_item_stock
        await item_factory(name="Kettle", price=1, stock=1)
        await fsm_context.set_state(StockFSM.waiting_item_name)
        msg = make_message(text="Kettle", user_id=1)
        await show_item_stock(msg, fsm_context)
        assert "tr:item" in _buttons(msg.answer.call_args)


# --- permissions & limits --------------------------------------------------------------------

class TestPermissions:

    def test_every_editor_handler_needs_catalog_manage(self):
        handlers = tr.router.callback_query.handlers + tr.router.message.handlers
        assert len(handlers) >= 8
        for h in handlers:
            perms = [f.callback for f in h.filters if isinstance(f.callback, HasPermissionFilter)]
            assert perms and perms[0].permission == Permission.CATALOG_MANAGE, h.callback.__name__

    @pytest.mark.parametrize("granted,expected", [
        (Permission.USE, False),
        (Permission.USE | Permission.PROMO_MANAGE, False),
        (Permission.USE | Permission.CATALOG_MANAGE, True),
    ])
    async def test_filter_denies_a_user_without_catalog_manage(self, granted, expected):
        f = HasPermissionFilter(permission=Permission.CATALOG_MANAGE)
        event = MagicMock()
        event.from_user.id = 5
        with patch('bot.filters.main.check_role_cached', new_callable=AsyncMock, return_value=granted):
            assert await f(event) is expected

    def test_callback_data_fits_telegram_limit(self):
        from bot.keyboards.translations import editor_keyboard, field_keyboard, skip_keyboard
        markups = [editor_keyboard(["en", "ru", "ro"], True), field_keyboard(), skip_keyboard("a", "b")]
        for m in markups:
            for row in m.inline_keyboard:
                for b in row:
                    assert len(b.callback_data.encode()) <= 64

    def test_router_is_registered(self):
        from bot.handlers.admin import router
        assert tr.router in router.sub_routers
