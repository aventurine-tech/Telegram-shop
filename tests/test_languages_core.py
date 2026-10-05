"""Per-user language plumbing and web account storage (the pieces the UI layers build on)."""
import asyncio

import pytest
from sqlalchemy import select

from bot.database.main import Database
from bot.database.methods.read import get_user_languages, check_user
from bot.database.methods.update import set_user_language
from bot.database.methods.web_users import (
    create_web_user, get_web_user_auth, get_web_user, count_active_admins, record_web_login,
    set_web_user_language, set_web_user_password, bootstrap_web_admin,
)
from bot.database.models.main import WebUsers, WebRole
from bot.i18n import main as i18n
from bot.web.passwords import hash_password, verify_password, DUMMY_HASH, check_password_strength


class TestLanguageContext:
    """Uses the real `localize` (the autouse fixture only replaces it by name in handler modules)."""

    @pytest.fixture(autouse=True)
    def _default_ru(self):
        i18n.get_locale.cache_clear()
        yield
        i18n.get_locale.cache_clear()

    def test_default_applies_without_a_chosen_language(self):
        assert i18n.current_language() == i18n.get_locale()

    @pytest.mark.parametrize("lang", ["en", "ru", "ro"])
    def test_use_language_switches_and_restores(self, lang):
        before = i18n.current_language()
        with i18n.use_language(lang):
            assert i18n.current_language() == lang
        assert i18n.current_language() == before

    def test_the_three_languages_really_differ(self):
        texts = {lang: i18n.localize_in(lang, "btn.shop") for lang in ("en", "ru", "ro")}
        assert len(set(texts.values())) == 3

    def test_unknown_language_falls_back_to_default(self):
        with i18n.use_language("xx"):
            assert i18n.current_language() == i18n.get_locale()
        assert i18n.localize_in(None, "btn.shop") == i18n.localize_in(i18n.get_locale(), "btn.shop")

    def test_formatting_uses_the_recipient_language(self):
        ro = i18n.localize_in("ro", "notify.customer.confirmed", id=5)
        en = i18n.localize_in("en", "notify.customer.confirmed", id=5)
        assert "#5" in ro and "#5" in en and ro != en

    async def test_concurrent_updates_do_not_leak_languages(self):
        async def handle(lang):
            with i18n.use_language(lang):
                await asyncio.sleep(0)
                first = i18n.localize("btn.shop")
                await asyncio.sleep(0)
                return lang, first, i18n.localize("btn.shop")

        results = await asyncio.gather(*(handle(l) for l in ["en", "ro", "ru", "ro", "en"]))
        for lang, a, b in results:
            assert a == b == i18n.localize_in(lang, "btn.shop")


class TestUserLanguageStorage:

    async def test_new_user_has_no_language(self, user_factory):
        user = await user_factory(telegram_id=950001)
        assert user["language"] is None

    async def test_set_and_read_back(self, user_factory):
        await user_factory(telegram_id=950002)
        assert await set_user_language(950002, "ro") is True
        assert (await check_user(950002))["language"] == "ro"

    @pytest.mark.parametrize("bad", ["", "de", "RO", None])
    async def test_rejects_unknown_language(self, user_factory, bad):
        await user_factory(telegram_id=950003)
        assert await set_user_language(950003, bad) is False
        assert (await check_user(950003))["language"] is None

    async def test_unknown_user(self):
        assert await set_user_language(1, "en") is False

    async def test_languages_for_many_users_in_one_call(self, user_factory):
        await user_factory(telegram_id=950010)
        await user_factory(telegram_id=950011)
        await set_user_language(950011, "ru")
        assert await get_user_languages([950010, 950011, 950012, 950011]) == {950010: None, 950011: "ru"}
        assert await get_user_languages([]) == {}


class TestPasswords:

    def test_hash_is_salted_and_not_plain(self):
        a, b = hash_password("correct horse"), hash_password("correct horse")
        assert a != b and "correct horse" not in a
        assert a.startswith("scrypt$")

    def test_verify(self):
        h = hash_password("s3cret-pass")
        assert verify_password("s3cret-pass", h)
        assert not verify_password("s3cret-pasS", h)
        assert not verify_password("", h)

    @pytest.mark.parametrize("stored", [None, "", "plain", "md5$a$b", "scrypt$x$y$z$q$w", "scrypt$1$1$1$zz$zz"])
    def test_garbage_hash_never_verifies(self, stored):
        assert verify_password("anything", stored) is False

    def test_dummy_hash_is_a_real_hash(self):
        assert verify_password("not it", DUMMY_HASH) is False

    def test_strength(self):
        assert check_password_strength("short") == "password_too_short"
        assert check_password_strength("x" * 200) == "password_too_long"
        assert check_password_strength("long-enough") is None


class TestWebUserStorage:

    async def test_create_stores_only_a_hash(self):
        assert await create_web_user("alice", "password-1", WebRole.ADMIN, "ro") == (True, "success")
        auth = await get_web_user_auth("alice")
        assert auth["role"] == "admin" and auth["language"] == "ro" and auth["is_active"]
        assert auth["password_hash"] != "password-1" and verify_password("password-1", auth["password_hash"])
        assert "password_hash" not in await get_web_user(auth["id"])

    @pytest.mark.parametrize("kwargs,code", [
        (dict(username="", password="password-1"), "invalid_username"),
        (dict(username="has space", password="password-1"), "invalid_username"),
        (dict(username="x" * 65, password="password-1"), "invalid_username"),
        (dict(username="bob", password="password-1", role="root"), "invalid_role"),
        (dict(username="bob", password="password-1", language="de"), "invalid_language"),
        (dict(username="bob", password="short"), "password_too_short"),
    ])
    async def test_validation(self, kwargs, code):
        assert await create_web_user(**kwargs) == (False, code)

    async def test_username_is_unique_case_insensitively(self):
        await create_web_user("Carol", "password-1")
        assert await create_web_user("carol", "password-2") == (False, "username_taken")

    async def test_login_lookup_ignores_case(self):
        await create_web_user("Boss", "password-1")
        assert (await get_web_user_auth("boss"))["username"] == "Boss"
        assert (await get_web_user_auth(" BOSS "))["username"] == "Boss"
        assert await get_web_user_auth("nobody") is None

    async def test_active_admin_count(self):
        await create_web_user("a1", "password-1", WebRole.ADMIN)
        await create_web_user("a2", "password-1", WebRole.ADMIN, is_active=False)
        await create_web_user("s1", "password-1", WebRole.STAFF)
        assert await count_active_admins() == 1

    async def test_login_stamp_and_language_remembered_once(self):
        await create_web_user("dave", "password-1")
        uid = (await get_web_user_auth("dave"))["id"]
        await record_web_login(uid, "ru")
        u = await get_web_user(uid)
        assert u["last_login_at"] is not None and u["language"] == "ru"
        await record_web_login(uid, "en")                 # an existing choice is not overwritten at login
        assert (await get_web_user(uid))["language"] == "ru"

    async def test_change_language_and_password(self):
        await create_web_user("erin", "password-1")
        uid = (await get_web_user_auth("erin"))["id"]
        assert await set_web_user_language(uid, "ro") and (await get_web_user(uid))["language"] == "ro"
        assert not await set_web_user_language(uid, "de")
        assert await set_web_user_password(uid, "short") == (False, "password_too_short")
        assert await set_web_user_password(uid, "brand-new-pass") == (True, "success")
        assert verify_password("brand-new-pass", (await get_web_user_auth("erin"))["password_hash"])
        assert await set_web_user_password(999, "brand-new-pass") == (False, "not_found")

    async def test_bootstrap_creates_the_first_admin_only_once(self):
        assert await bootstrap_web_admin("owner", "owner-password") is True
        assert await bootstrap_web_admin("someone", "another-password") is False
        auth = await get_web_user_auth("owner")
        assert auth["role"] == "admin" and verify_password("owner-password", auth["password_hash"])
        assert await get_web_user_auth("someone") is None

    async def test_bootstrap_accepts_a_short_configured_password(self):
        assert await bootstrap_web_admin("admin", "adm") is True
        assert verify_password("adm", (await get_web_user_auth("admin"))["password_hash"])
