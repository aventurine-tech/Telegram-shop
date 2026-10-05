"""The panel's own pages (lists, forms, dialogs, validation messages) speak the chosen language."""
import httpx
import pytest

from bot.database.methods.web_users import create_web_user
from bot.database.models.main import WebRole
from bot.web.admin import PromoCodeAdmin, RoleAdmin, create_admin_app
from bot.web.language import LANG_COOKIE
from bot.web.mailings import MailingAdmin

BOSS = ("i18nboss", "boss-pass-1")
ENGLISH_CHROME = ["Actions", "Search", "Export", "Showing", " / Page", "Delete selected", "Please confirm",
                  "Save and continue", "Save and add another", "prev\n", "Cancel\n"]


@pytest.fixture
async def boss():
    await create_web_user(*BOSS, WebRole.ADMIN)
    app = create_admin_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 5000)),
                                 base_url="http://testserver") as c:
        assert (await c.post("/admin/login", data={"username": BOSS[0], "password": BOSS[1]})).status_code == 302
        yield c


def test_every_sidebar_page_string_exists_in_every_language():
    from bot.i18n.strings import TRANSLATIONS
    keys = {k for k in TRANSLATIONS["en"] if k.startswith("web.sa.")}
    assert len(keys) > 20
    for lang in ("ru", "ro"):
        assert keys == {k for k in TRANSLATIONS[lang] if k.startswith("web.sa.")}, lang


@pytest.mark.parametrize("lang,words", [("ru", ["Действия", "Найти", "Экспорт", "Создать:"]),
                                         ("ro", ["Acțiuni", "Caută", "Export", "Adaugă:"]),
                                         ("en", ["Actions", "Search", "Export", "New:"])])
async def test_list_page_chrome_is_translated(boss, lang, words):
    boss.cookies.set(LANG_COOKIE, lang)
    page = (await boss.get(f"/admin/{MailingAdmin.identity}/list")).text
    for w in words:
        assert w in page, (lang, w)
    if lang != "en":
        for w in [w for w in ENGLISH_CHROME[:6] if w != "Export" or lang == "ru"]:
            assert w not in page, (lang, w)


@pytest.mark.parametrize("lang", ["ru", "ro"])
async def test_forms_and_dialogs_are_translated(boss, lang):
    boss.cookies.set(LANG_COOKIE, lang)
    create = (await boss.get(f"/admin/{PromoCodeAdmin.identity}/create")).text
    for w in (">Save and continue editing<", ">Save and add another<", ">Cancel<", ">Save<"):
        assert w not in create, (lang, w)
    listing = (await boss.get(f"/admin/{PromoCodeAdmin.identity}/list")).text
    assert "Please confirm" not in listing and "permanently" not in listing


async def test_save_buttons_still_post_the_values_sqladmin_expects(boss):
    boss.cookies.set(LANG_COOKIE, "ru")
    page = (await boss.get(f"/admin/{RoleAdmin.identity}/create")).text
    assert 'value="Save and continue editing"' in page and "Сохранить и продолжить редактирование" in page


async def test_validation_messages_follow_the_language(boss):
    data = {"code": "X1", "discount_type": "percent", "scope": "global", "discount_value": "abc"}
    boss.cookies.set(LANG_COOKIE, "en")
    en = (await boss.post(f"/admin/{PromoCodeAdmin.identity}/create", data=data)).text
    assert "Not a valid" in en
    for lang in ("ru", "ro"):
        boss.cookies.set(LANG_COOKIE, lang)
        page = (await boss.post(f"/admin/{PromoCodeAdmin.identity}/create", data=data)).text
        assert "Not a valid" not in page and "invalid-feedback" in page, lang
