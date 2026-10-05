"""Web panel: per-language names/descriptions of categories and products, end to end through SQLAdmin."""
import re
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
    form = {"name": "Chair", "description": "A chair", "price": "10", "category": str(category_id),
            "stock": "1", "sale_percent": "", "sale_until": ""}
    form.update(extra)
    return form


class TestForms:

    async def test_category_form_lists_translation_fields_with_hints(self, boss):
        boss.cookies.set(LANG_COOKIE, "en")
        page = (await boss.get(f"/admin/{CATS}/create")).text
        for lang in ("en", "ru", "ro"):
            assert f'name="name_{lang}"' in page
        assert "main-language name" in page and "Romanian" in page
        assert page.index('name="name"') < page.index('name="name_en"') < page.index('name="name_ro"')

    async def test_product_form_has_textareas_for_descriptions(self, boss, category_factory):
        await category_factory("Furniture")
        page = (await boss.get(f"/admin/{GOODS}/create")).text
        for lang in ("en", "ru", "ro"):
            assert f'name="name_{lang}"' in page
            assert re.search(rf'<textarea[^>]*name="description_{lang}"', page)
        assert page.index('name="price"') < page.index('name="name_en"')
        assert page.index('name="description"') < page.index('name="description_en"')
        assert 'name="picture"' in page and 'name="remove_picture"' in page


class TestCategories:

    async def test_create_and_edit_with_translations_and_blank_clears_to_null(self, boss, caches):
        resp = await boss.post(f"/admin/{CATS}/create",
                               data={"name": "Furniture", "name_en": " Furniture ", "name_ru": "Мебель", "name_ro": ""})
        assert resp.status_code == 302, resp.text[:400]
        cat = await category("Furniture")
        assert (cat.name_en, cat.name_ru, cat.name_ro) == ("Furniture", "Мебель", None)

        resp = await boss.post(f"/admin/{CATS}/edit/{cat.id}",
                               data={"name": "Furniture", "name_en": "", "name_ru": "   ", "name_ro": "Mobilă"})
        assert resp.status_code == 302, resp.text[:400]
        cat = await category("Furniture")
        assert (cat.name_en, cat.name_ru, cat.name_ro) == (None, None, "Mobilă")

    async def test_too_long_name_is_rejected_with_a_translated_error(self, boss, caches):
        resp = await boss.post(f"/admin/{CATS}/create",
                               data={"name": "Long", "name_ro": "x" * (MAX_NAME_LEN + 1)})
        assert resp.status_code == 400
        assert await category("Long") is None
        boss.cookies.set(LANG_COOKIE, "ro")
        resp = await boss.post(f"/admin/{CATS}/create",
                               data={"name": "Long", "name_ro": "x" * (MAX_NAME_LEN + 1)})
        assert resp.status_code == 400 and "prea lungă" in resp.text

    async def test_edit_invalidates_the_cache_and_a_rename_both_names(self, boss, caches):
        item, cat_cache = caches
        await boss.post(f"/admin/{CATS}/create", data={"name": "Old"})
        cat_cache.reset_mock()
        cat = await category("Old")

        await boss.post(f"/admin/{CATS}/edit/{cat.id}", data={"name": "Old", "name_ro": "Vechi"})
        assert {c.args[0] for c in cat_cache.call_args_list} == {"Old"}

        cat_cache.reset_mock()
        await boss.post(f"/admin/{CATS}/edit/{cat.id}", data={"name": "New"})
        assert {c.args[0] for c in cat_cache.call_args_list} == {"Old", "New"}

        cat_cache.reset_mock()
        await boss.delete(f"/admin/{CATS}/delete?pks={cat.id}")
        assert await category("New") is None
        assert {c.args[0] for c in cat_cache.call_args_list} == {"New"}

    async def test_search_finds_translated_names(self, boss, caches):
        await boss.post(f"/admin/{CATS}/create", data={"name": "Furniture", "name_ro": "Mobilă"})
        await boss.post(f"/admin/{CATS}/create", data={"name": "Toys", "name_ru": "Игрушки"})
        found = (await boss.get(f"/admin/{CATS}/list?search=Mobil")).text
        assert "Furniture" in found and "Toys" not in found
        found = (await boss.get(f"/admin/{CATS}/list?search=Игруш")).text
        assert "Toys" in found and "Furniture" not in found


class TestProducts:

    async def test_create_and_edit_with_translations_and_blank_clears_to_null(self, boss, category_factory, caches):
        await category_factory("Furniture")
        cat = await category("Furniture")
        resp = await boss.post(f"/admin/{GOODS}/create", data=product_form(
            cat.id, name_en="Chair", name_ro="Scaun", description_ru="Стул\n\nудобный", description_ro="  Confortabil "))
        assert resp.status_code == 302, resp.text[:400]
        item = await goods("Chair")
        assert (item.name_en, item.name_ru, item.name_ro) == ("Chair", None, "Scaun")
        assert (item.description_en, item.description_ru, item.description_ro) == (None, "Стул\n\nудобный", "Confortabil")

        resp = await boss.post(f"/admin/{GOODS}/edit/{item.id}", data=product_form(
            cat.id, name_en="", name_ro="Scaun nou", description_ru="", description_ro=""))
        assert resp.status_code == 302, resp.text[:400]
        item = await goods("Chair")
        assert (item.name_en, item.name_ro, item.description_ru, item.description_ro) == (None, "Scaun nou", None, None)

    @pytest.mark.parametrize("field,limit", [("name_ru", MAX_NAME_LEN), ("description_en", MAX_DESCRIPTION_LEN)])
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

        await boss.post(f"/admin/{GOODS}/edit/{item.id}", data=product_form(cat_id, name_ro="Scaun"))
        assert {c.args[0] for c in item_cache.call_args_list} == {"Chair"}

        item_cache.reset_mock()
        resp = await boss.post(f"/admin/{GOODS}/edit/{item.id}", data=product_form(cat_id, name="Armchair"))
        assert resp.status_code == 302, resp.text[:400]
        assert {c.args[0] for c in item_cache.call_args_list} == {"Chair", "Armchair"}

    async def test_search_finds_translated_names(self, boss, item_factory, caches):
        await item_factory(name="Chair", price=10, stock=1)
        await item_factory(name="Table", price=10, stock=1)
        item = await goods("Chair")
        await boss.post(f"/admin/{GOODS}/edit/{item.id}", data=product_form(item.category_id, name_ro="Scaun"))
        found = (await boss.get(f"/admin/{GOODS}/list?search=Scaun")).text
        assert "Chair" in found
        assert "Table" not in found


class TestAccountsAndLabels:

    async def test_staff_can_edit_translations_too(self, app, category_factory, caches):
        await category_factory("Furniture")
        cat = await category("Furniture")
        async with make_client(app) as c:
            await login(c, CLERK)
            resp = await c.post(f"/admin/{CATS}/edit/{cat.id}", data={"name": "Furniture", "name_ro": "Mobilă"})
            assert resp.status_code == 302
        assert (await category("Furniture")).name_ro == "Mobilă"

    @pytest.mark.parametrize("lang,name_label,descr_label", [
        ("en", "Name (Romanian)", "Description (Romanian)"),
        ("ru", "Название (румынский)", "Описание (румынский)"),
        ("ro", "Denumire (română)", "Descriere (română)"),
    ])
    async def test_labels_render_in_each_language(self, boss, category_factory, lang, name_label, descr_label):
        await category_factory("Furniture")
        boss.cookies.set(LANG_COOKIE, lang)
        assert name_label in (await boss.get(f"/admin/{CATS}/create")).text
        assert descr_label in (await boss.get(f"/admin/{GOODS}/create")).text

    @pytest.mark.parametrize("lang,title", [("en", "Translations"), ("ru", "Переводы"), ("ro", "Traduceri")])
    async def test_help_page_explains_translations(self, boss, lang, title):
        boss.cookies.set(LANG_COOKIE, lang)
        resp = await boss.get("/admin/")
        assert resp.status_code == 200 and title in resp.text
