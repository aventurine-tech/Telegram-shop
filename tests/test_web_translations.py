"""Web panel: per-language names/descriptions of categories and products, end to end through SQLAdmin."""
import re
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select

from bot.database.main import Database
from bot.database.methods.web_users import create_web_user
from bot.database.models.main import Categories, Goods, WebRole
from bot.misc.localized import MAX_DESCRIPTION_LEN, MAX_NAME_LEN
from bot.web.admin import CategoryAdmin, GoodsAdmin, create_admin_app
from bot.web.language import LANG_COOKIE

CATS = CategoryAdmin.identity
GOODS = GoodsAdmin.identity
BOSS = ("boss", "boss-pass-1")
CLERK = ("clerk", "clerk-pass-1")


def make_client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 5000)),
                             base_url="http://testserver")


async def login(c, creds):
    resp = await c.post("/admin/login", data={"username": creds[0], "password": creds[1]})
    assert resp.status_code == 302, resp.text[:300]


@contextmanager
def main_language(lang):
    """The shop's main language (BOT_LOCALE); get_locale is lru_cached, so patch it."""
    with patch("bot.i18n.main.get_locale", return_value=lang):
        yield


@pytest.fixture(autouse=True)
def main_is_russian():
    with main_language("ru"):
        yield


def label(page, field):
    """Visible label text of a form field."""
    m = re.search(rf'<label[^>]*for="{field}"[^>]*>(.*?)</label>', page, re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


@pytest.fixture
async def app():
    assert (await create_web_user(*BOSS, WebRole.ADMIN))[0]
    assert (await create_web_user(*CLERK, WebRole.STAFF))[0]
    return create_admin_app()


@pytest.fixture
async def boss(app):
    async with make_client(app) as c:
        await login(c, BOSS)
        yield c


@pytest.fixture
async def caches():
    """Record cache invalidations instead of scheduling them."""
    with patch("bot.web.admin.invalidate_item_cache", new=AsyncMock()) as item, \
            patch("bot.web.admin.invalidate_category_cache", new=AsyncMock()) as cat, \
            patch("bot.web.admin.safe_create_task", side_effect=lambda c: c.close()):
        yield item, cat


async def category(name):
    async with Database().session() as s:
        return (await s.execute(select(Categories).where(Categories.name == name))).scalars().first()


async def goods(name):
    async with Database().session() as s:
        return (await s.execute(select(Goods).where(Goods.name == name))).scalars().first()


def product_form(category_id, **extra):
    form = {"name": "Chair", "description_ru": "A chair", "price": "10", "category": str(category_id),
            "stock": "1", "sale_percent": "", "sale_until": ""}
    form.update(extra)
    return form


class TestForms:

    @pytest.mark.parametrize("lang,own,others", [
        ("en", "Name", {"ru": "Name (Russian)", "ro": "Name (Romanian)"}),
        ("ru", "Название", {"en": "Название (английский)", "ro": "Название (румынский)"}),
        ("ro", "Denumire", {"en": "Denumire (engleză)", "ru": "Denumire (rusă)"}),
    ])
    async def test_category_form_labels_the_viewers_language_plain(self, boss, lang, own, others):
        boss.cookies.set(LANG_COOKIE, lang)
        page = (await boss.get(f"/admin/{CATS}/create")).text
        assert label(page, f"name_{lang}") == own
        for other, text in others.items():
            assert label(page, f"name_{other}") == text
        assert 'name="name"' not in page
        assert page.index('name="name_en"') < page.index('name="name_ru"') < page.index('name="name_ro"')

    @pytest.mark.parametrize("lang,descr_own", [("en", "Description"), ("ru", "Описание"), ("ro", "Descriere")])
    async def test_product_form_description_labels_and_textareas(self, boss, category_factory, lang, descr_own):
        await category_factory("Furniture")
        boss.cookies.set(LANG_COOKIE, lang)
        page = (await boss.get(f"/admin/{GOODS}/create")).text
        assert label(page, f"description_{lang}") == descr_own
        for other in {"en", "ru", "ro"} - {lang}:
            assert "(" in label(page, f"description_{other}")
        for code in ("en", "ru", "ro"):
            assert re.search(rf'<textarea[^>]*name="description_{code}"', page)
        assert 'name="description"' not in page
        assert page.index('name="description_ro"') < page.index('name="price"')
        assert 'name="picture"' in page and 'name="remove_picture"' in page

    async def test_hints_say_which_field_is_required_and_which_is_the_main_language(self, boss):
        boss.cookies.set(LANG_COOKIE, "en")
        page = (await boss.get(f"/admin/{CATS}/create")).text
        assert "Required. Customers whose language is English" in page
        assert "main language (Russian)" in page
        assert "Leave empty to use the main-language name" in page  # Romanian
        with main_language("en"):
            page = (await boss.get(f"/admin/{CATS}/create")).text
        assert "English is the shop&#39;s main language" in page or "English is the shop's main language" in page


class TestCategories:

    async def test_create_with_only_the_viewers_language_uses_it_as_canonical(self, boss, caches):
        boss.cookies.set(LANG_COOKIE, "en")
        resp = await boss.post(f"/admin/{CATS}/create", data={"name_en": " Furniture "})
        assert resp.status_code == 302, resp.text[:400]
        cat = await category("Furniture")
        # Main language is Russian but empty: the admin's English text becomes the canonical name.
        assert (cat.name_en, cat.name_ru, cat.name_ro) == ("Furniture", "Furniture", None)

    async def test_main_language_text_wins_as_canonical(self, boss, caches):
        boss.cookies.set(LANG_COOKIE, "en")
        resp = await boss.post(f"/admin/{CATS}/create",
                               data={"name_en": "Furniture", "name_ru": "Мебель", "name_ro": ""})
        assert resp.status_code == 302, resp.text[:400]
        assert await category("Furniture") is None
        cat = await category("Мебель")
        assert (cat.name_en, cat.name_ru, cat.name_ro) == ("Furniture", "Мебель", None)

    async def test_main_language_follows_bot_locale(self, boss, caches):
        boss.cookies.set(LANG_COOKIE, "ro")
        with main_language("en"):
            resp = await boss.post(f"/admin/{CATS}/create", data={"name_ro": "Mobilă", "name_en": "Furniture"})
        assert resp.status_code == 302, resp.text[:400]
        cat = await category("Furniture")
        assert (cat.name_en, cat.name_ro) == ("Furniture", "Mobilă")

    @pytest.mark.parametrize("lang,text", [("en", "Enter the name in English"), ("ru", "Укажите название (русский)"),
                                           ("ro", "Introduceți denumirea (română)")])
    async def test_the_viewers_field_is_required_on_create(self, boss, caches, lang, text):
        boss.cookies.set(LANG_COOKIE, lang)
        other = "ru" if lang != "ru" else "en"
        resp = await boss.post(f"/admin/{CATS}/create", data={f"name_{other}": "Furniture"})
        assert resp.status_code == 400 and text in resp.text
        assert await category("Furniture") is None
        resp = await boss.post(f"/admin/{CATS}/create", data={f"name_{lang}": "   "})
        assert resp.status_code == 400 and text in resp.text

    async def test_edit_with_blank_main_field_keeps_the_canonical_name(self, boss, caches):
        boss.cookies.set(LANG_COOKIE, "en")
        await boss.post(f"/admin/{CATS}/create", data={"name_en": "Furniture", "name_ru": "Мебель"})
        cat = await category("Мебель")
        resp = await boss.post(f"/admin/{CATS}/edit/{cat.id}",
                               data={"name_en": "Home furniture", "name_ru": "", "name_ro": "Mobilă"})
        assert resp.status_code == 302, resp.text[:400]
        cat = await category("Мебель")
        assert (cat.name_en, cat.name_ru, cat.name_ro) == ("Home furniture", "Мебель", "Mobilă")

    async def test_edit_blank_translations_clear_to_null(self, boss, caches):
        await boss.post(f"/admin/{CATS}/create", data={"name_ru": "Мебель", "name_en": "Furniture", "name_ro": "Mobilă"})
        cat = await category("Мебель")
        resp = await boss.post(f"/admin/{CATS}/edit/{cat.id}",
                               data={"name_ru": "Мебель", "name_en": "", "name_ro": "   "})
        assert resp.status_code == 302, resp.text[:400]
        cat = await category("Мебель")
        assert (cat.name_en, cat.name_ru, cat.name_ro) == (None, "Мебель", None)

    async def test_edit_form_prefills_the_main_language_field_of_a_legacy_row(self, boss, category_factory):
        await category_factory("Мебель")
        cat = await category("Мебель")
        assert cat.name_ru is None  # legacy: only the canonical column is filled
        boss.cookies.set(LANG_COOKIE, "en")
        page = (await boss.get(f"/admin/{CATS}/edit/{cat.id}")).text
        assert re.search(r'name="name_ru"[^>]*value="Мебель"', page)
        assert not re.search(r'name="name_en"[^>]*value="[^"]', page)
        # Saving what the form shows keeps the item as it was.
        resp = await boss.post(f"/admin/{CATS}/edit/{cat.id}", data={"name_en": "Furniture", "name_ru": "Мебель"})
        assert resp.status_code == 302
        cat = await category("Мебель")
        assert (cat.name_en, cat.name_ru) == ("Furniture", "Мебель")

    async def test_duplicate_name_is_a_translated_error(self, boss, category_factory, caches):
        await category_factory("Мебель")
        boss.cookies.set(LANG_COOKIE, "en")
        resp = await boss.post(f"/admin/{CATS}/create", data={"name_en": "Мебель"})
        assert resp.status_code == 400 and "already exists" in resp.text
        boss.cookies.set(LANG_COOKIE, "ru")
        resp = await boss.post(f"/admin/{CATS}/create", data={"name_ru": "Мебель"})
        assert resp.status_code == 400 and "уже существует" in resp.text
        # Renaming onto another item's name is refused too; keeping one's own name is fine.
        await boss.post(f"/admin/{CATS}/create", data={"name_ru": "Игрушки"})
        toys = await category("Игрушки")
        resp = await boss.post(f"/admin/{CATS}/edit/{toys.id}", data={"name_ru": "Мебель"})
        assert resp.status_code == 400 and "уже существует" in resp.text
        resp = await boss.post(f"/admin/{CATS}/edit/{toys.id}", data={"name_ru": "Игрушки", "name_en": "Toys"})
        assert resp.status_code == 302

    async def test_too_long_name_is_rejected_with_a_translated_error(self, boss, caches):
        resp = await boss.post(f"/admin/{CATS}/create",
                               data={"name_ru": "Long", "name_ro": "x" * (MAX_NAME_LEN + 1)})
        assert resp.status_code == 400
        assert await category("Long") is None
        boss.cookies.set(LANG_COOKIE, "ro")
        resp = await boss.post(f"/admin/{CATS}/create",
                               data={"name_ro": "Long", "name_en": "x" * (MAX_NAME_LEN + 1)})
        assert resp.status_code == 400 and "prea lungă" in resp.text

    async def test_edit_invalidates_the_cache_and_a_rename_both_names(self, boss, caches):
        item, cat_cache = caches
        await boss.post(f"/admin/{CATS}/create", data={"name_ru": "Old"})
        cat_cache.reset_mock()
        cat = await category("Old")

        await boss.post(f"/admin/{CATS}/edit/{cat.id}", data={"name_ru": "Old", "name_ro": "Vechi"})
        assert {c.args[0] for c in cat_cache.call_args_list} == {"Old"}

        cat_cache.reset_mock()
        await boss.post(f"/admin/{CATS}/edit/{cat.id}", data={"name_ru": "New"})
        assert {c.args[0] for c in cat_cache.call_args_list} == {"Old", "New"}

        cat_cache.reset_mock()
        await boss.delete(f"/admin/{CATS}/delete?pks={cat.id}")
        assert await category("New") is None
        assert {c.args[0] for c in cat_cache.call_args_list} == {"New"}

    async def test_list_shows_the_name_in_the_viewers_language(self, boss, caches):
        await boss.post(f"/admin/{CATS}/create", data={"name_ru": "Мебель", "name_en": "Furniture", "name_ro": "Mobilă"})
        await boss.post(f"/admin/{CATS}/create", data={"name_ru": "Игрушки"})
        for lang, shown in (("en", "Furniture"), ("ro", "Mobilă"), ("ru", "Мебель")):
            boss.cookies.set(LANG_COOKIE, lang)
            page = (await boss.get(f"/admin/{CATS}/list")).text
            assert shown in page
            assert "Игрушки" in page  # no translation: the canonical name
        boss.cookies.set(LANG_COOKIE, "en")
        assert "Мебель" not in (await boss.get(f"/admin/{CATS}/list")).text

    async def test_search_finds_translated_names(self, boss, caches):
        await boss.post(f"/admin/{CATS}/create", data={"name_ru": "Furniture", "name_ro": "Mobilă"})
        await boss.post(f"/admin/{CATS}/create", data={"name_ru": "Toys", "name_en": "Игрушки"})
        found = (await boss.get(f"/admin/{CATS}/list?search=Mobil")).text
        assert "Furniture" in found and "Toys" not in found
        found = (await boss.get(f"/admin/{CATS}/list?search=Игруш")).text
        assert "Toys" in found and "Furniture" not in found


class TestProducts:

    async def test_form_has_one_name_labelled_in_the_viewers_language(self, boss, category_factory):
        await category_factory("Furniture")
        for lang, own in (("en", "Name"), ("ru", "Название"), ("ro", "Denumire")):
            boss.cookies.set(LANG_COOKIE, lang)
            page = (await boss.get(f"/admin/{GOODS}/create")).text
            assert label(page, "name") == own
            assert not re.search(r'name="name_(en|ru|ro)"', page)
            assert re.search(r'<textarea[^>]*name="description_en"', page)

    async def test_category_dropdown_follows_the_interface_language(self, boss, category_factory):
        from bot.database.methods.create import create_category
        await create_category("Мебель", names={"ro": "Mobilă", "en": "Furniture"})
        for lang, shown in (("ro", "Mobilă"), ("en", "Furniture"), ("ru", "Мебель")):
            boss.cookies.set(LANG_COOKIE, lang)
            page = (await boss.get(f"/admin/{GOODS}/create")).text
            select = re.search(r'<select[^>]*name="category".*?</select>', page, re.S).group(0)
            assert shown in select

    async def test_option_fields_sit_together_after_the_main_fields_and_are_styled(self, boss, category_factory):
        await category_factory("Furniture")
        page = (await boss.get(f"/admin/{GOODS}/create")).text
        assert page.index('name="sale_until"') < page.index('name="variant_of"') < page.index('name="variant_label"')
        assert re.search(r'<select[^>]*class="[^"]*form-select[^"]*"[^>]*name="variant_of"|'
                         r'<select[^>]*name="variant_of"[^>]*class="[^"]*form-select', page)

    async def test_create_with_one_name(self, boss, category_factory, caches):
        await category_factory("Furniture")
        cat = await category("Furniture")
        boss.cookies.set(LANG_COOKIE, "en")
        resp = await boss.post(f"/admin/{GOODS}/create", data={
            "name": "  Chair ", "description_en": "  A chair ", "price": "10", "category": str(cat.id),
            "stock": "1", "sale_percent": "", "sale_until": ""})
        assert resp.status_code == 302, resp.text[:400]
        item = await goods("Chair")
        assert (item.name, item.name_en, item.name_ru, item.name_ro) == ("Chair", "Chair", "Chair", "Chair")
        assert (item.description, item.description_en, item.description_ru) == ("A chair", "A chair", "A chair")

    async def test_descriptions_keep_their_translations(self, boss, category_factory, caches):
        await category_factory("Furniture")
        cat = await category("Furniture")
        resp = await boss.post(f"/admin/{GOODS}/create", data=product_form(
            cat.id, description_ru="Стул\n\nудобный", description_ro="  Confortabil "))
        assert resp.status_code == 302, resp.text[:400]
        item = await goods("Chair")
        assert (item.description, item.description_ru, item.description_ro) == (
            "Стул\n\nудобный", "Стул\n\nудобный", "Confortabil")

    async def test_name_and_description_of_the_viewer_are_required_on_create(self, boss, category_factory, caches):
        await category_factory("Furniture")
        cat = await category("Furniture")
        boss.cookies.set(LANG_COOKIE, "ro")
        resp = await boss.post(f"/admin/{GOODS}/create", data=product_form(cat.id, name=""))
        assert resp.status_code == 400 and "Introduceți denumirea produsului" in resp.text
        resp = await boss.post(f"/admin/{GOODS}/create", data=product_form(cat.id, name="Scaun", description_ru=""))
        assert resp.status_code == 400 and "Introduceți descrierea (română)" in resp.text
        assert await goods("Chair") is None and await goods("Scaun") is None

    async def test_edit_rename_resets_every_language_and_blank_translations_clear(self, boss, category_factory, caches):
        await category_factory("Furniture")
        cat = await category("Furniture")
        await boss.post(f"/admin/{GOODS}/create", data=product_form(cat.id, description_ro="Confortabil"))
        item = await goods("Chair")
        boss.cookies.set(LANG_COOKIE, "en")
        resp = await boss.post(f"/admin/{GOODS}/edit/{item.id}", data={
            "name": "Armchair", "description_en": "Soft",
            "description_ru": "", "description_ro": "", "price": "10", "category": str(cat.id), "stock": "1"})
        assert resp.status_code == 302, resp.text[:400]
        item = await goods("Armchair")
        assert (item.name, item.name_en, item.name_ru, item.name_ro) == ("Armchair",) * 4
        assert (item.description, item.description_en, item.description_ru, item.description_ro) == (
            "A chair", "Soft", "A chair", None)

    async def test_edit_without_a_rename_keeps_existing_translated_names(self, boss, category_factory, caches):
        from bot.database.methods.create import create_item
        await category_factory("Furniture")
        cat = await category("Furniture")
        await create_item("Chair", "d", 10, "Furniture", names={"ro": "Scaun"})
        item = await goods("Chair")
        resp = await boss.post(f"/admin/{GOODS}/edit/{item.id}", data={
            "name": "Chair", "description_ru": "d", "price": "12", "category": str(cat.id), "stock": "1"})
        assert resp.status_code == 302, resp.text[:400]
        assert (await goods("Chair")).name_ro == "Scaun"

    async def test_edit_form_prefills_the_description_of_a_legacy_row(self, boss, item_factory):
        await item_factory(name="Chair", price=10, stock=1)
        item = await goods("Chair")
        assert item.name_ru is None and item.description_ru is None
        boss.cookies.set(LANG_COOKIE, "en")
        page = (await boss.get(f"/admin/{GOODS}/edit/{item.id}")).text
        assert re.search(r'name="name"[^>]*value="Chair"', page)
        assert re.search(rf'<textarea[^>]*name="description_ru"[^>]*>\s*{re.escape(item.description)}', page)

    async def test_duplicate_name_is_a_translated_error(self, boss, item_factory, caches):
        await item_factory(name="Chair", price=10, stock=1)
        item = await goods("Chair")
        boss.cookies.set(LANG_COOKIE, "ru")
        resp = await boss.post(f"/admin/{GOODS}/create", data=product_form(item.category_id))
        assert resp.status_code == 400 and "уже существует" in resp.text

    @pytest.mark.parametrize("field,limit", [("name", MAX_NAME_LEN), ("description_en", MAX_DESCRIPTION_LEN)])
    async def test_too_long_is_rejected_with_a_translated_error(self, boss, category_factory, caches, field, limit):
        await category_factory("Furniture")
        cat = await category("Furniture")
        boss.cookies.set(LANG_COOKIE, "ru")
        resp = await boss.post(f"/admin/{GOODS}/create", data=product_form(cat.id, **{field: "x" * (limit + 1)}))
        assert resp.status_code == 400
        assert "слишком длинное" in resp.text and str(limit) in resp.text
        assert await goods("Chair") is None

    async def test_edit_invalidates_the_item_cache_and_a_rename_both_names(self, boss, item_factory, caches):
        item_cache, _ = caches
        await item_factory(name="Chair", price=10, stock=1)
        item = await goods("Chair")
        cat_id = item.category_id

        await boss.post(f"/admin/{GOODS}/edit/{item.id}", data=product_form(cat_id, description_ru=item.description))
        assert {c.args[0] for c in item_cache.call_args_list} == {"Chair"}

        item_cache.reset_mock()
        resp = await boss.post(f"/admin/{GOODS}/edit/{item.id}",
                               data=product_form(cat_id, name="Armchair", description_ru=item.description))
        assert resp.status_code == 302, resp.text[:400]
        assert {c.args[0] for c in item_cache.call_args_list} == {"Chair", "Armchair"}

    async def test_list_shows_the_translated_name_in_the_viewers_language(self, boss, category_factory, caches):
        from bot.database.methods.create import create_item
        await category_factory("Furniture")
        await create_item("Chair", "d", 10, "Furniture", names={"ro": "Scaun", "en": "Seat"})
        boss.cookies.set(LANG_COOKIE, "ro")
        assert "Scaun" in (await boss.get(f"/admin/{GOODS}/list")).text
        boss.cookies.set(LANG_COOKIE, "en")
        assert "Seat" in (await boss.get(f"/admin/{GOODS}/list")).text

    async def test_search_finds_translated_names(self, boss, item_factory, caches):
        from bot.database.methods.create import create_item
        await item_factory(name="Chair", price=10, stock=1)
        await item_factory(name="Table", price=10, stock=1)
        async with Database().session() as sess:
            row = (await sess.execute(select(Goods).where(Goods.name == "Chair"))).scalars().one()
            row.name_ro = "Scaun"
        found = (await boss.get(f"/admin/{GOODS}/list?search=Scaun")).text
        assert "Chair" in found
        assert "Table" not in found


class TestAccountsAndLabels:

    async def test_staff_can_edit_translations_too(self, app, category_factory, caches):
        await category_factory("Мебель")
        cat = await category("Мебель")
        async with make_client(app) as c:
            await login(c, CLERK)
            resp = await c.post(f"/admin/{CATS}/edit/{cat.id}", data={"name_ru": "Мебель", "name_ro": "Mobilă"})
            assert resp.status_code == 302
        assert (await category("Мебель")).name_ro == "Mobilă"

    @pytest.mark.parametrize("lang,title", [("en", "Translations"), ("ru", "Переводы"), ("ro", "Traduceri")])
    async def test_help_page_explains_translations(self, boss, lang, title):
        boss.cookies.set(LANG_COOKIE, lang)
        resp = await boss.get("/admin/")
        assert resp.status_code == 200 and title in resp.text
        assert {"en": "Russian", "ru": "русский", "ro": "rusă"}[lang] in resp.text  # the main language


class TestWebOptionCreation:
    """Creating a weight option from the product form: only the head and the label are needed."""

    async def test_option_needs_only_head_label_price_and_stock(self, boss, category_factory, caches):
        from bot.database.methods.create import create_item
        from bot.database.methods.read import get_item_family
        await category_factory("Furniture")
        await create_item("Sofa", "Comfy", 0, "Furniture", names={"ro": "Canapea"})
        head = await goods("Sofa")
        boss.cookies.set(LANG_COOKIE, "ro")
        resp = await boss.post(f"/admin/{GOODS}/create", data={
            "name": "", "variant_of": str(head.id), "variant_label": "200 g", "price": "300", "stock": "0",
            "category": str(head.category_id), "sale_percent": "", "sale_until": ""})
        assert resp.status_code == 302, resp.text[:600]
        fam = await get_item_family("Sofa")
        assert [(o["name"], o["variant_label"], o["name_ro"]) for o in fam["options"]] == [
            ("Sofa · 200 g", "200 g", "Canapea · 200 g")]
        assert fam["options"][0]["category_id"] == head.category_id

    async def test_label_without_a_head_is_a_visible_error(self, boss, category_factory, caches):
        await category_factory("Furniture")
        cat = await category("Furniture")
        boss.cookies.set(LANG_COOKIE, "en")
        resp = await boss.post(f"/admin/{GOODS}/create", data=product_form(cat.id, variant_label="50 g"))
        assert resp.status_code == 400 and "only be set together" in resp.text
