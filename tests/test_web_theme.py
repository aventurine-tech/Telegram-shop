"""Light / dark theme of the web panel."""
import re

import httpx
import pytest

from bot.database.methods.web_users import create_web_user
from bot.database.models.main import WebRole
from bot.web.admin import RoleAdmin, create_admin_app
from bot.web.language import LANG_COOKIE

BOSS = ("themeboss", "boss-pass-1")


@pytest.fixture
async def client():
    await create_web_user(*BOSS, WebRole.ADMIN)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_admin_app(), client=("127.0.0.1", 5000)),
                                 base_url="http://testserver") as c:
        yield c


async def signed_in(c):
    assert (await c.post("/admin/login", data={"username": BOSS[0], "password": BOSS[1]})).status_code == 302
    return c


class TestTheme:

    async def test_login_page_has_the_switch_and_the_early_theme_script(self, client):
        page = (await client.get("/admin/login")).text
        assert '<html lang="' in page and 'data-bs-theme="light"' in page
        assert "localStorage.getItem('shop-theme')" in page and "prefers-color-scheme: dark" in page
        assert "data-theme-toggle" in page
        # the theme is applied in <head>, before the stylesheets load (no white flash)
        assert page.index("shop-theme") < page.index("tabler.min.css")

    async def test_every_panel_page_has_the_switch(self, client):
        await signed_in(client)
        for url in ("/admin/", f"/admin/{RoleAdmin.identity}/list", f"/admin/{RoleAdmin.identity}/create", "/admin/my-account"):
            assert "data-theme-toggle" in (await client.get(url)).text, url

    @pytest.mark.parametrize("lang,words", [("en", ("Dark theme", "Light theme")), ("ru", ("Тёмная тема", "Светлая тема")),
                                             ("ro", ("Temă întunecată", "Temă luminoasă"))])
    async def test_switch_labels_follow_the_language(self, client, lang, words):
        client.cookies.set(LANG_COOKIE, lang)
        page = (await client.get("/admin/login")).text
        for w in words:
            assert w in page, (lang, w)
        assert f'<html lang="{lang}"' in page

    async def test_no_hard_coded_light_colours_left_in_our_markup(self, client):
        await signed_in(client)
        page = (await client.get(f"/admin/{RoleAdmin.identity}/list")).text
        assert "background:#e2e8f0" not in page and "color:#999" not in page
        assert ".shop-pill" in page and "[data-bs-theme=\"dark\"]" in page

    async def test_permission_tags_use_the_themed_class(self, client):
        await signed_in(client)
        await client.post(f"/admin/{RoleAdmin.identity}/create", data={"name": "Themed", "permissions": ["1", "1024"]})
        page = (await client.get(f"/admin/{RoleAdmin.identity}/list")).text
        assert re.search(r'<span class="shop-pill">', page)
