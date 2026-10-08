"""Web panel accounts (Admin / Staff), sign-in, language and "My account", end to end through SQLAdmin."""
import re
from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy import select

from bot.database.main import Database
from bot.database.methods.web_users import (
    bootstrap_web_admin, create_web_user, get_web_user, get_web_user_auth,
)
from bot.database.models.main import AuditLog, WebRole, WebUsers
from bot.web import admin as web_admin
from bot.web.accounts import WebUserAdmin
from bot.web.admin import AdminAuth, PromoCodeAdmin, create_admin_app
from bot.web.language import LANG_COOKIE, request_language
from bot.web.passwords import DUMMY_HASH, hash_password, verify_password

BOSS = ("boss", "boss-pass-1")
CLERK = ("clerk", "clerk-pass-1")
ACCOUNTS = WebUserAdmin.identity


@pytest.fixture(autouse=True)
def fresh_limiter():
    web_admin._login_limiter._attempts.clear()
    yield
    web_admin._login_limiter._attempts.clear()


@pytest.fixture
async def accounts():
    """One Admin and one Staff account."""
    assert (await create_web_user(*BOSS, WebRole.ADMIN))[0]
    assert (await create_web_user(*CLERK, WebRole.STAFF))[0]


def make_client(app, host="127.0.0.1"):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(host, 5000)),
                             base_url="http://testserver")


@pytest.fixture
async def app(accounts):
    return create_admin_app()


@pytest.fixture
async def client(app):
    async with make_client(app) as c:
        yield c


async def login(c, creds, expect=302):
    resp = await c.post("/admin/login", data={"username": creds[0], "password": creds[1]})
    assert resp.status_code == expect, resp.text[:300]
    return resp


@pytest.fixture
async def boss(client):
    await login(client, BOSS)
    return client


@pytest.fixture
async def clerk(app):
    async with make_client(app) as c:
        await login(c, CLERK)
        yield c


async def audit_rows(action=None):
    async with Database().session() as s:
        q = select(AuditLog)
        if action:
            q = q.where(AuditLog.action == action)
        return (await s.execute(q)).scalars().all()


async def row(username):
    return await get_web_user_auth(username)


def new_account(username="newbie", password="newbie-pass-1", role="staff", **extra):
    form = {"username": username, "password": password, "role": role, "language": "", "is_active": "y"}
    form.update(extra)
    return form


class TestLogin:

    async def test_valid_login_opens_the_panel(self, client):
        resp = await login(client, BOSS)
        assert resp.headers["location"].endswith("/admin/")
        page = await client.get("/admin/")
        assert page.status_code == 200
        assert any(r.details and "user=boss" in r.details for r in await audit_rows("web_login"))
        assert (await row("boss"))["last_login_at"] is not None

    async def test_panel_requires_login(self, client):
        resp = await client.get("/admin/")
        assert resp.status_code == 302 and resp.headers["location"].endswith("/admin/login")

    async def test_session_carries_uid_role_and_no_legacy_flag(self, app):
        seen = {}
        original = AdminAuth.authenticate

        async def spy(self, request):
            seen.update(request.session)
            return await original(self, request)

        with patch.object(AdminAuth, "authenticate", spy):
            async with make_client(app) as c:
                await login(c, BOSS)
                await c.get("/admin/")
        boss = await row("boss")
        assert seen["uid"] == boss["id"] and seen["role"] == "admin"
        assert "authenticated" not in seen

    async def test_wrong_password_is_rejected_and_audited_without_the_password(self, client):
        resp = await login(client, (BOSS[0], "totally-wrong"), expect=400)
        assert "Invalid" in resp.text or "Неверный" in resp.text
        rows = await audit_rows("web_login_failed")
        assert rows and "user=boss" in rows[0].details
        assert all("totally-wrong" not in (r.details or "") for r in await audit_rows())

    async def test_unknown_user_costs_a_hash_and_is_rejected(self, client):
        calls = []
        real = web_admin.verify_password

        def spy(password, stored):
            calls.append(stored)
            return real(password, stored)

        with patch.object(web_admin, "verify_password", spy):
            await login(client, ("nobody", "whatever-123"), expect=400)
        assert calls == [DUMMY_HASH]
        assert any("user=nobody" in (r.details or "") for r in await audit_rows("web_login_failed"))

    async def test_inactive_account_cannot_sign_in(self, client):
        async with Database().session() as s:
            (await s.execute(select(WebUsers).where(WebUsers.username == "clerk"))).scalar_one().is_active = False
        await login(client, CLERK, expect=400)
        rows = await audit_rows("web_login_failed")
        assert any("reason=inactive" in r.details for r in rows)
        assert (await client.get("/admin/")).status_code == 302

    async def test_rate_limit_blocks_even_the_right_password(self, client):
        for _ in range(5):
            await login(client, (BOSS[0], "nope-nope-1"), expect=400)
        await login(client, BOSS, expect=400)
        assert await audit_rows("web_login_blocked")

    async def test_a_remote_account_with_the_password_admin_is_refused(self, app):
        async with Database().session() as s:
            s.add(WebUsers(username="legacy", password_hash=hash_password("admin"), role="staff"))
        async with make_client(app, host="203.0.113.7") as remote:
            await login(remote, ("legacy", "admin"), expect=400)
        assert await audit_rows("web_login_blocked_default_creds")
        async with make_client(app, host="127.0.0.1") as local:
            await login(local, ("legacy", "admin"))

    async def test_logout_ends_the_session(self, boss):
        await boss.get("/admin/logout")
        assert (await boss.get("/admin/")).status_code == 302


class TestSessionIsRecheckedEveryRequest:

    async def _set(self, username, **fields):
        async with Database().session() as s:
            u = (await s.execute(select(WebUsers).where(WebUsers.username == username))).scalar_one()
            for k, v in fields.items():
                setattr(u, k, v)

    async def test_disabling_takes_effect_at_once(self, clerk):
        assert (await clerk.get("/admin/")).status_code == 200
        await self._set("clerk", is_active=False)
        assert (await clerk.get("/admin/")).status_code == 302
        assert (await clerk.get("/export/users")).status_code == 401

    async def test_demotion_ends_the_old_session(self, boss):
        assert (await boss.get(f"/admin/{ACCOUNTS}/list")).status_code == 200
        await self._set("boss", role="staff")
        assert (await boss.get(f"/admin/{ACCOUNTS}/list")).status_code == 302

    async def test_deleting_the_account_ends_the_session(self, clerk):
        async with Database().session() as s:
            await s.delete((await s.execute(select(WebUsers).where(WebUsers.username == "clerk"))).scalar_one())
        assert (await clerk.get("/admin/")).status_code == 302

    async def test_health_and_metrics_follow_the_account(self, clerk):
        with patch.object(web_admin, "get_cache_manager", return_value=None):
            assert "checks" in (await clerk.get("/health")).json()
        assert (await clerk.get("/metrics")).status_code in (200, 503)
        await self._set("clerk", is_active=False)
        with patch.object(web_admin, "get_cache_manager", return_value=None):
            assert "checks" not in (await clerk.get("/health")).json()
        assert (await clerk.get("/metrics")).status_code == 401
        assert (await clerk.get("/metrics/prometheus")).status_code == 401

    async def test_staff_can_still_export(self, clerk):
        assert (await clerk.get("/export/users")).status_code == 200


class TestAccountsAreAdminOnly:

    async def test_staff_gets_403_on_every_accounts_route(self, clerk):
        boss = await row("boss")
        assert (await clerk.get(f"/admin/{ACCOUNTS}/list")).status_code == 403
        assert (await clerk.get(f"/admin/{ACCOUNTS}/create")).status_code == 403
        assert (await clerk.post(f"/admin/{ACCOUNTS}/create", data=new_account())).status_code == 403
        assert (await clerk.get(f"/admin/{ACCOUNTS}/details/{boss['id']}")).status_code == 403
        assert (await clerk.get(f"/admin/{ACCOUNTS}/edit/{boss['id']}")).status_code == 403
        assert (await clerk.post(f"/admin/{ACCOUNTS}/edit/{boss['id']}", data=new_account("boss"))).status_code == 403
        assert (await clerk.delete(f"/admin/{ACCOUNTS}/delete?pks={boss['id']}")).status_code == 403
        assert (await clerk.get(f"/admin/{ACCOUNTS}/export/csv")).status_code == 403
        assert await row("newbie") is None and (await row("boss")) is not None

    async def test_staff_keeps_every_other_view_but_does_not_see_the_menu_entry(self, clerk):
        for identity in ("goods", "orders", "user", "audit-log", PromoCodeAdmin.identity):
            assert (await clerk.get(f"/admin/{identity}/list")).status_code == 200, identity
        assert f"/admin/{ACCOUNTS}/list" not in (await clerk.get("/admin/")).text

    async def test_admin_sees_the_menu_entry_and_the_list(self, boss):
        page = await boss.get("/admin/")
        assert f"/admin/{ACCOUNTS}/list" in page.text and "/admin/my-account" in page.text
        listing = await boss.get(f"/admin/{ACCOUNTS}/list")
        assert listing.status_code == 200 and "boss" in listing.text and "clerk" in listing.text

    async def test_direct_calls_on_the_view_refuse_staff_too(self):
        request = MagicMock()
        request.session = {"uid": 1, "role": "staff"}
        view = WebUserAdmin()
        from starlette.exceptions import HTTPException
        for call in (view.list(request), view.on_model_change({}, MagicMock(), True, request),
                     view.delete_model(request, "1"), view.insert_model(request, {}),
                     view.update_model(request, "1", {}), view.on_model_delete(MagicMock(), request)):
            with pytest.raises(HTTPException) as e:
                await call
            assert e.value.status_code == 403


class TestManagingAccounts:

    async def test_admin_creates_a_staff_account_who_can_then_sign_in(self, boss, app):
        resp = await boss.post(f"/admin/{ACCOUNTS}/create", data=new_account())
        assert resp.status_code == 302, resp.text[:400]
        created = await row("newbie")
        assert created["role"] == "staff" and created["is_active"] and created["language"] is None
        async with make_client(app) as other:
            await login(other, ("newbie", "newbie-pass-1"))
            assert (await other.get(f"/admin/{ACCOUNTS}/list")).status_code == 403

    async def test_password_is_hashed_and_never_stored_shown_or_audited(self, boss):
        await boss.post(f"/admin/{ACCOUNTS}/create", data=new_account(password="s3cret-Passw0rd"))
        stored = await row("newbie")
        assert stored["password_hash"].startswith("scrypt$") and "s3cret-Passw0rd" not in stored["password_hash"]
        assert verify_password("s3cret-Passw0rd", stored["password_hash"])
        pages = [await boss.get(f"/admin/{ACCOUNTS}/list"),
                 await boss.get(f"/admin/{ACCOUNTS}/details/{stored['id']}"),
                 await boss.get(f"/admin/{ACCOUNTS}/edit/{stored['id']}"),
                 await boss.get(f"/admin/{ACCOUNTS}/create")]
        for page in pages:
            assert page.status_code == 200
            assert "s3cret-Passw0rd" not in page.text and "scrypt$" not in page.text
            assert "password_hash" not in page.text
        for entry in await audit_rows():
            blob = f"{entry.action} {entry.details} {entry.resource_id}"
            assert "s3cret-Passw0rd" not in blob and "scrypt$" not in blob
        actions = {r.action for r in await audit_rows()}
        assert {"sqladmin_create", "sqladmin_web_user_password_set"} <= actions

    async def test_username_must_be_unique_ignoring_case(self, boss):
        resp = await boss.post(f"/admin/{ACCOUNTS}/create", data=new_account("BOSS"))
        assert resp.status_code == 400
        async with Database().session() as s:
            assert len((await s.execute(select(WebUsers))).scalars().all()) == 2

    @pytest.mark.parametrize("fields", [{"password": "short"}, {"password": ""}, {"username": "has space"},
                                        {"username": ""}])
    async def test_invalid_new_accounts_are_refused(self, boss, fields):
        resp = await boss.post(f"/admin/{ACCOUNTS}/create", data=new_account(**fields))
        assert resp.status_code == 400
        assert await row("newbie") is None

    async def test_editing_without_a_password_keeps_it_and_with_one_replaces_it(self, boss, app):
        before = (await row("clerk"))
        form = new_account("clerk", password="", role="staff")
        assert (await boss.post(f"/admin/{ACCOUNTS}/edit/{before['id']}", data=form)).status_code == 302
        assert (await row("clerk"))["password_hash"] == before["password_hash"]

        form["password"] = "brand-new-pass-9"
        assert (await boss.post(f"/admin/{ACCOUNTS}/edit/{before['id']}", data=form)).status_code == 302
        async with make_client(app) as c:
            await login(c, (CLERK[0], CLERK[1]), expect=400)
            await login(c, (CLERK[0], "brand-new-pass-9"))

    async def test_editing_role_and_language(self, boss):
        clerk = await row("clerk")
        form = new_account("clerk", password="", role="admin", language="ro")
        assert (await boss.post(f"/admin/{ACCOUNTS}/edit/{clerk['id']}", data=form)).status_code == 302
        after = await row("clerk")
        assert after["role"] == "admin" and after["language"] == "ro"
        updates = [r for r in await audit_rows("sqladmin_update")]
        assert updates and all("password" not in (r.details or "").lower() for r in updates)

    async def test_admin_can_delete_another_account_and_it_is_audited(self, boss):
        clerk = await row("clerk")
        resp = await boss.delete(f"/admin/{ACCOUNTS}/delete?pks={clerk['id']}")
        assert resp.status_code == 200
        assert await row("clerk") is None
        assert await audit_rows("sqladmin_delete")

    async def test_cannot_delete_deactivate_or_demote_yourself(self, boss):
        me = await row("boss")
        assert (await boss.delete(f"/admin/{ACCOUNTS}/delete?pks={me['id']}")).status_code == 400
        off = new_account("boss", password="", role="admin")
        del off["is_active"]
        assert (await boss.post(f"/admin/{ACCOUNTS}/edit/{me['id']}", data=off)).status_code == 400
        demote = new_account("boss", password="", role="staff")
        assert (await boss.post(f"/admin/{ACCOUNTS}/edit/{me['id']}", data=demote)).status_code == 400
        after = await row("boss")
        assert after["role"] == "admin" and after["is_active"]

    async def test_the_last_active_admin_is_protected(self):
        """Reached only by a stale/forged session (a real Admin session is never the only one), so drive the view."""
        request = MagicMock()
        request.session = {"uid": 424242, "role": "admin"}
        view = WebUserAdmin()
        async with Database().session() as s:
            s.add(WebUsers(username="solo", password_hash=hash_password("solo-pass-1"), role="admin"))
        solo = await get_web_user_auth("solo")
        model = MagicMock(id=solo["id"], role="admin", is_active=True)

        for change in ({"role": "staff", "is_active": True}, {"role": "admin", "is_active": False}):
            with pytest.raises(ValueError):
                await view.on_model_change({"username": "solo", **change}, model, False, request)
        from starlette.exceptions import HTTPException
        with pytest.raises(HTTPException) as e:
            await view.delete_model(request, str(solo["id"]))
        assert e.value.status_code == 400
        assert await row("solo") is not None

    async def test_an_admin_can_disable_another_admin_while_two_remain_active(self, boss):
        assert (await create_web_user("second", "second-pass-1", WebRole.ADMIN))[0]
        second = await row("second")
        form = new_account("second", password="", role="admin")
        del form["is_active"]
        assert (await boss.post(f"/admin/{ACCOUNTS}/edit/{second['id']}", data=form)).status_code == 302
        assert not (await row("second"))["is_active"]


class TestMyAccount:

    async def test_page_is_open_to_staff_and_admin(self, clerk, boss):
        for c in (clerk, boss):
            page = await c.get("/admin/my-account")
            assert page.status_code == 200 and 'name="current_password"' in page.text

    async def _change(self, c, current, new, again=None):
        return await c.post("/admin/my-account", data={
            "form": "password", "current_password": current, "new_password": new,
            "confirm_password": new if again is None else again})

    async def test_changing_the_password_needs_the_current_one(self, clerk, app):
        resp = await self._change(clerk, "not-my-password", "another-pass-77")
        assert resp.status_code == 400
        assert verify_password(CLERK[1], (await row("clerk"))["password_hash"])
        assert await audit_rows("web_password_change_failed")

    @pytest.mark.parametrize("new,again", [("another-pass-77", "different-pass-1"), ("short", "short"),
                                           (CLERK[1], CLERK[1])])
    async def test_new_password_is_checked(self, clerk, new, again):
        assert (await self._change(clerk, CLERK[1], new, again)).status_code == 400
        assert verify_password(CLERK[1], (await row("clerk"))["password_hash"])

    async def test_password_change_works_and_is_audited_without_the_password(self, clerk, app):
        resp = await self._change(clerk, CLERK[1], "another-pass-77")
        assert resp.status_code == 200
        assert (await clerk.get("/admin/")).status_code == 200      # still signed in
        async with make_client(app) as c:
            await login(c, CLERK, expect=400)
            await login(c, (CLERK[0], "another-pass-77"))
        rows = await audit_rows("web_password_changed")
        assert rows and all("another-pass-77" not in (r.details or "") for r in await audit_rows())

    async def test_wrong_current_passwords_are_rate_limited(self, clerk):
        for _ in range(5):
            await self._change(clerk, "guess-guess-1", "another-pass-77")
        resp = await self._change(clerk, CLERK[1], "another-pass-77")
        assert resp.status_code == 400
        assert verify_password(CLERK[1], (await row("clerk"))["password_hash"])


class TestLanguage:

    async def test_login_page_is_the_language_picker(self, client):
        page = await client.get("/admin/login")
        for code in ("en", "ru", "ro"):
            assert f"?lang={code}" in page.text

    async def test_picking_a_language_sets_a_strict_cookie_and_translates_the_page(self, client):
        resp = await client.get("/admin/login?lang=ro")
        assert "Autentificare" in resp.text
        cookie = resp.headers["set-cookie"]
        assert cookie.startswith(f"{LANG_COOKIE}=ro") and "SameSite=strict" in cookie and "HttpOnly" in cookie
        assert "Autentificare" in (await client.get("/admin/login")).text       # remembered by the cookie

    async def test_other_languages_and_unknown_codes(self, client):
        assert "Войти" in (await client.get("/admin/login?lang=ru")).text
        assert "Sign in" in (await client.get("/admin/login?lang=en")).text
        bad = await client.get("/admin/login?lang=xx")
        assert "set-cookie" not in bad.headers

    async def test_error_message_is_translated(self, client):
        await client.get("/admin/login?lang=ro")
        resp = await login(client, (BOSS[0], "bad-bad-bad"), expect=400)
        assert "Utilizator, parolă sau cod incorect" in resp.text

    async def test_cookie_choice_is_saved_on_first_login_then_the_account_wins(self, app):
        async with make_client(app) as c:
            await c.get("/admin/login?lang=ro")
            await login(c, BOSS)
            assert (await row("boss"))["language"] == "ro"
            assert "Ghid rapid" in (await c.get("/admin/")).text
            await c.get("/admin/logout")
            # A different choice on the login page no longer matters: the account has a language.
            await c.get("/admin/login?lang=ru")
            await login(c, BOSS)
            assert (await row("boss"))["language"] == "ro"
            page = await c.get("/admin/")
            assert "Ghid rapid" in page.text and "Краткая справка" not in page.text

    async def test_signed_in_query_parameter_does_not_override_the_account(self, app):
        async with make_client(app) as c:
            await c.get("/admin/login?lang=ru")
            await login(c, BOSS)
            page = await c.get("/admin/?lang=en")
            assert "Краткая справка" in page.text
            assert LANG_COOKIE not in page.headers.get("set-cookie", "")

    async def test_my_account_changes_the_language(self, app):
        async with make_client(app) as c:
            await c.get("/admin/login?lang=en")
            await login(c, BOSS)
            resp = await c.post("/admin/my-account", data={"form": "language", "language": "ru"})
            assert resp.status_code == 200 and "Язык сохранён" in resp.text
            assert (await row("boss"))["language"] == "ru"
            assert "Краткая справка" in (await c.get("/admin/")).text
            bad = await c.post("/admin/my-account", data={"form": "language", "language": "xx"})
            assert bad.status_code == 400 and (await row("boss"))["language"] == "ru"

    async def test_account_language_set_by_an_admin_applies_at_once(self, boss, app):
        async with make_client(app) as c:
            await login(c, CLERK)
            assert "Ghid rapid" not in (await c.get("/admin/")).text
            clerk = await row("clerk")
            form = new_account("clerk", password="", role="staff", language="ro")
            assert (await boss.post(f"/admin/{ACCOUNTS}/edit/{clerk['id']}", data=form)).status_code == 302
            assert "Ghid rapid" in (await c.get("/admin/")).text

    async def test_help_page_in_russian_keeps_the_content(self, app):
        async with make_client(app) as c:
            await c.get("/admin/login?lang=ru")
            await login(c, BOSS)
            page = (await c.get("/admin/")).text
        assert "Продажа товаров" in page and "/export/orders" in page and "145" in page and "10&nbsp;МБ" in page

    async def test_sidebar_columns_and_actions_follow_the_language(self, app):
        async with make_client(app) as c:
            await c.get("/admin/login?lang=ro")
            await login(c, BOSS)
            goods = (await c.get("/admin/goods/list")).text
            orders = (await c.get("/admin/orders/list")).text
            sidebar = (await c.get("/admin/")).text
        assert "Produse" in goods and "Preț" in goods and "Stoc" in goods
        assert "Confirmă comanda" in orders and "Anulează comanda" in orders
        assert "Conturi de panou" in sidebar and "Contul meu" in sidebar and "Ieșire" in sidebar

    async def test_validation_errors_are_translated(self, app):
        async with make_client(app) as c:
            await c.get("/admin/login?lang=ro")
            await login(c, BOSS)
            resp = await c.post(f"/admin/{ACCOUNTS}/create", data=new_account("BOSS"))
        assert resp.status_code == 400 and "există deja" in resp.text

    async def test_audit_resource_type_stays_stable_whatever_the_language(self, app):
        async with make_client(app) as c:
            await c.get("/admin/login?lang=ro")
            await login(c, BOSS)
            await c.post(f"/admin/{ACCOUNTS}/create", data=new_account())
        entry = (await audit_rows("sqladmin_create"))[-1]
        assert entry.resource_type == "Web Account"

    def test_request_language_resolution_order(self):
        def scope(session=None, cookie=None):
            headers = [(b"cookie", f"{LANG_COOKIE}={cookie}".encode())] if cookie else []
            return {"session": session or {}, "headers": headers}
        assert request_language(scope({"lang": "ru"}, cookie="ro")) == "ru"
        assert request_language(scope({}, cookie="ro")) == "ro"
        assert request_language(scope({"lang": "xx"}, cookie="ro")) == "ro"
        assert request_language(scope({}, cookie="xx")) is None
        assert request_language(scope()) is None


class TestBootstrap:

    async def test_creates_exactly_one_admin_while_the_table_is_empty(self):
        assert await bootstrap_web_admin("owner", "owner-pass-12") is True
        assert await bootstrap_web_admin("owner", "owner-pass-12") is False
        assert await bootstrap_web_admin("someone-else", "other-pass-12") is False
        async with Database().session() as s:
            users = (await s.execute(select(WebUsers))).scalars().all()
        assert [(u.username, u.role) for u in users] == [("owner", "admin")]
        assert verify_password("owner-pass-12", users[0].password_hash)

    async def test_the_bootstrapped_admin_can_sign_in(self):
        await bootstrap_web_admin("owner", "owner-pass-12")
        async with make_client(create_admin_app()) as c:
            await login(c, ("owner", "owner-pass-12"))
            assert (await c.get(f"/admin/{ACCOUNTS}/list")).status_code == 200

    async def test_nothing_is_created_when_an_account_already_exists(self, accounts):
        assert await bootstrap_web_admin("owner", "owner-pass-12") is False
        assert await row("owner") is None
