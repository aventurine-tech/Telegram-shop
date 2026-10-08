"""Optional two-step sign-in for panel accounts: the codes, setting it up, signing in, backup codes, reset."""
import re
import time

import httpx
import pytest
from sqlalchemy import select

from bot.database.main import Database
from bot.database.methods.web_users import create_web_user, get_totp, get_web_user_auth
from bot.database.models.main import AuditLog, WebRole, WebUsers
from bot.web import admin as web_admin
from bot.web import totp
from bot.web.accounts import WebUserAdmin
from bot.web.admin import create_admin_app
from bot.web.language import LANG_COOKIE

BOSS = ("boss", "boss-pass-1")
CLERK = ("clerk", "clerk-pass-1")
ACCOUNTS = WebUserAdmin.identity


@pytest.fixture(autouse=True)
def fresh_limiter():
    web_admin._login_limiter._attempts.clear()
    yield
    web_admin._login_limiter._attempts.clear()


@pytest.fixture
async def app():
    assert (await create_web_user(*BOSS, WebRole.ADMIN))[0]
    assert (await create_web_user(*CLERK, WebRole.STAFF))[0]
    return create_admin_app()


def make_client(app):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 5000)),
                               base_url="http://testserver")
    client.cookies.set(LANG_COOKIE, "en")
    return client


async def sign_in(c, creds, code=None):
    data = {"username": creds[0], "password": creds[1]}
    if code is not None:
        data["code"] = code
    return await c.post("/admin/login", data=data)


async def secret_of(creds) -> str:
    user = await get_web_user_auth(creds[0])
    return totp.unseal((await get_totp(user["id"]))["secret"])


async def turn_on(app, creds):
    """Sign in, set up two-step through the page; returns (secret, backup codes)."""
    async with make_client(app) as c:
        assert (await sign_in(c, creds)).status_code == 302
        await c.post("/admin/my-account", data={"form": "totp_start"})
        secret = await secret_of(creds)
        resp = await c.post("/admin/my-account", data={"form": "totp_confirm", "code": totp.code_at(secret, totp.current_step())})
        assert resp.status_code == 200
        codes = re.findall(r"<li>([a-z0-9]{4}-[a-z0-9]{4})</li>", resp.text)
    return secret, codes


class TestCodes:

    def test_matches_the_rfc_6238_test_vector(self):
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"          # "12345678901234567890"
        assert totp.code_at(secret, 59 // 30) == "287082"
        assert totp.match_step(secret, "287082", now=59) == 1
        assert totp.code_at(secret, 1111111109 // 30) == "081804"

    def test_a_neighbouring_step_is_accepted_but_not_a_distant_one(self):
        secret = totp.new_secret()
        now = 1_700_000_000
        step = totp.current_step(now)
        assert totp.match_step(secret, totp.code_at(secret, step - 1), now) == step - 1
        assert totp.match_step(secret, totp.code_at(secret, step + 1), now) == step + 1
        assert totp.match_step(secret, totp.code_at(secret, step + 3), now) is None
        assert totp.match_step(secret, "12345", now) is None and totp.match_step(secret, "", now) is None

    def test_spaces_in_a_typed_code_are_ignored(self):
        secret = totp.new_secret()
        code = totp.code_at(secret, totp.current_step())
        assert totp.match_step(secret, f"{code[:3]} {code[3:]}") is not None

    def test_secret_is_sealed_and_not_readable_with_another_key(self, monkeypatch):
        secret = totp.new_secret()
        sealed = totp.seal(secret)
        assert secret not in sealed and totp.unseal(sealed) == secret
        monkeypatch.setattr("bot.misc.EnvKeys.SECRET_KEY", "another-key-entirely-0123456789")
        assert totp.unseal(sealed) is None

    def test_backup_codes_are_unique_and_compared_loosely(self):
        codes = totp.new_backup_codes()
        assert len(set(codes)) == totp.BACKUP_COUNT and all(len(c) == 8 for c in codes)
        shown = totp.show_backup(codes[0])
        assert totp.backup_hash(shown.upper()) == totp.backup_hash(codes[0])
        assert totp.backup_hash(codes[0]) != totp.backup_hash(codes[1])

    def test_provisioning_uri(self):
        uri = totp.provisioning_uri("ABCDEFGH", "ana pop", "Telegram Shop")
        assert uri.startswith("otpauth://totp/Telegram%20Shop%3Aana%20pop?secret=ABCDEFGH&issuer=Telegram%20Shop")

    def test_qr_svg_is_an_inline_svg_without_an_xml_header(self):
        svg = totp.qr_svg(totp.provisioning_uri("ABCDEFGH", "ana", "Telegram Shop"))
        assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>") and "<?xml" not in svg

    def test_qr_svg_is_empty_when_segno_is_missing(self, monkeypatch):
        import builtins
        real_import = builtins.__import__

        def no_segno(name, *args, **kwargs):
            if name == "segno":
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_segno)
        assert totp.qr_svg("otpauth://totp/x?secret=ABCDEFGH") == ""


class TestSetUp:

    async def test_off_by_default_and_signing_in_needs_no_code(self, app):
        async with make_client(app) as c:
            assert (await sign_in(c, BOSS)).status_code == 302
            page = (await c.get("/admin/my-account")).text
        assert 'id="two-step"' in page and "Set up" in page

    async def test_start_shows_the_key_and_it_is_stored_sealed(self, app):
        async with make_client(app) as c:
            await sign_in(c, BOSS)
            resp = await c.post("/admin/my-account", data={"form": "totp_start"})
        secret = await secret_of(BOSS)
        assert totp.group(secret) in resp.text
        state = await get_totp((await get_web_user_auth(BOSS[0]))["id"])
        assert state["enabled"] is False and secret not in state["secret"]

    async def test_start_shows_a_qr_code_next_to_the_typed_key(self, app):
        async with make_client(app) as c:
            await sign_in(c, BOSS)
            resp = await c.post("/admin/my-account", data={"form": "totp_start"})
        assert 'id="two-step-qr"' in resp.text and "<svg" in resp.text.split('id="two-step-qr"', 1)[1][:200]
        assert 'id="two-step-key"' in resp.text

    async def test_a_wrong_first_code_does_not_turn_it_on(self, app):
        async with make_client(app) as c:
            await sign_in(c, BOSS)
            await c.post("/admin/my-account", data={"form": "totp_start"})
            resp = await c.post("/admin/my-account", data={"form": "totp_confirm", "code": "000000"})
        assert resp.status_code == 400 and "That code is not correct" in resp.text
        assert (await get_totp((await get_web_user_auth(BOSS[0]))["id"]))["enabled"] is False

    async def test_confirming_turns_it_on_and_shows_backup_codes_once(self, app):
        secret, codes = await turn_on(app, BOSS)
        assert len(codes) == totp.BACKUP_COUNT
        user = await get_web_user_auth(BOSS[0])
        assert user["totp_enabled"] is True
        async with make_client(app) as c:
            await sign_in(c, BOSS, totp.code_at(secret, totp.current_step() + 1))
            page = (await c.get("/admin/my-account")).text
        assert 'id="backup-codes"' not in page and "Backup codes left: 8" in page

    async def test_panel_language(self, app):
        async with make_client(app) as c:
            await sign_in(c, BOSS)
            c.cookies.set(LANG_COOKIE, "ro")
            await c.post("/admin/my-account", data={"form": "language", "language": "ro"})
            page = (await c.get("/admin/my-account")).text
        assert "Autentificare în doi pași" in page


class TestSigningIn:

    async def test_password_alone_is_not_enough_once_it_is_on(self, app):
        secret, _ = await turn_on(app, BOSS)
        async with make_client(app) as c:
            resp = await sign_in(c, BOSS)
            assert resp.status_code == 400 and "Invalid username, password or code" in resp.text
            assert (await c.get("/admin/", follow_redirects=False)).status_code in (302, 303)
            assert (await sign_in(c, BOSS, "123456")).status_code == 400
            ok = await sign_in(c, BOSS, totp.code_at(secret, totp.current_step() + 1))
            assert ok.status_code == 302
            assert (await c.get("/admin/")).status_code == 200

    async def test_a_code_cannot_be_used_twice(self, app):
        secret, _ = await turn_on(app, BOSS)
        code = totp.code_at(secret, totp.current_step() + 1)
        async with make_client(app) as c:
            assert (await sign_in(c, BOSS, code)).status_code == 302
        async with make_client(app) as c:
            assert (await sign_in(c, BOSS, code)).status_code == 400

    async def test_the_code_from_setting_it_up_cannot_sign_in_either(self, app):
        secret, _ = await turn_on(app, BOSS)
        async with make_client(app) as c:
            assert (await sign_in(c, BOSS, totp.code_at(secret, totp.current_step()))).status_code == 400

    async def test_a_backup_code_works_once(self, app):
        _, codes = await turn_on(app, BOSS)
        async with make_client(app) as c:
            assert (await sign_in(c, BOSS, codes[0])).status_code == 302
        async with make_client(app) as c:
            assert (await sign_in(c, BOSS, codes[0])).status_code == 400
        async with make_client(app) as c:
            assert (await sign_in(c, BOSS, codes[1].upper())).status_code == 302
        state = await get_totp((await get_web_user_auth(BOSS[0]))["id"])
        assert len(state["backup"]) == totp.BACKUP_COUNT - 2

    async def test_other_accounts_are_not_affected(self, app):
        await turn_on(app, BOSS)
        async with make_client(app) as c:
            assert (await sign_in(c, CLERK)).status_code == 302

    async def test_wrong_codes_count_towards_the_lockout(self, app):
        await turn_on(app, BOSS)
        async with make_client(app) as c:
            for _ in range(5):
                assert (await sign_in(c, BOSS, "000000")).status_code == 400
            assert (await sign_in(c, BOSS, "000000")).status_code == 400
            assert web_admin._login_limiter.is_blocked("127.0.0.1")

    async def test_an_unreadable_secret_locks_the_account_out_instead_of_letting_it_in(self, app, monkeypatch):
        secret, _ = await turn_on(app, BOSS)
        monkeypatch.setattr("bot.misc.EnvKeys.SECRET_KEY", "another-key-entirely-0123456789")
        async with make_client(app) as c:
            assert (await sign_in(c, BOSS, totp.code_at(secret, totp.current_step() + 1))).status_code == 400


class TestTurningOff:

    async def test_needs_the_password(self, app):
        await turn_on(app, BOSS)
        secret = await secret_of(BOSS)
        async with make_client(app) as c:
            await sign_in(c, BOSS, totp.code_at(secret, totp.current_step() + 1))
            bad = await c.post("/admin/my-account", data={"form": "totp_disable", "current_password": "nope-nope-1"})
            assert bad.status_code == 400
            assert (await get_web_user_auth(BOSS[0]))["totp_enabled"] is True
            ok = await c.post("/admin/my-account", data={"form": "totp_disable", "current_password": BOSS[1]})
            assert ok.status_code == 200 and "Two-step sign-in is off" in ok.text
        assert (await get_web_user_auth(BOSS[0]))["totp_enabled"] is False
        async with make_client(app) as c:
            assert (await sign_in(c, BOSS)).status_code == 302

    async def test_new_backup_codes_replace_the_old_ones(self, app):
        secret, old = await turn_on(app, BOSS)
        async with make_client(app) as c:
            await sign_in(c, BOSS, totp.code_at(secret, totp.current_step() + 1))
            resp = await c.post("/admin/my-account", data={"form": "totp_backup_new", "current_password": BOSS[1]})
            fresh = re.findall(r"<li>([a-z0-9]{4}-[a-z0-9]{4})</li>", resp.text)
        assert len(fresh) == totp.BACKUP_COUNT and not set(fresh) & set(old)
        async with make_client(app) as c:
            assert (await sign_in(c, BOSS, old[0])).status_code == 400
        async with make_client(app) as c:
            assert (await sign_in(c, BOSS, fresh[0])).status_code == 302

    async def test_an_admin_can_reset_a_lost_phone_and_staff_cannot(self, app):
        await turn_on(app, CLERK)
        clerk_id = (await get_web_user_auth(CLERK[0]))["id"]
        async with make_client(app) as c:
            await sign_in(c, CLERK, None)         # fails: 2FA is on and no code
        async with make_client(app) as c:
            await sign_in(c, BOSS)
            resp = await c.get(f"/admin/{ACCOUNTS}/action/reset-two-step?pks={clerk_id}", follow_redirects=False)
            assert resp.status_code in (302, 303)
        assert (await get_web_user_auth(CLERK[0]))["totp_enabled"] is False
        async with make_client(app) as c:
            assert (await sign_in(c, CLERK)).status_code == 302
            resp = await c.get(f"/admin/{ACCOUNTS}/action/reset-two-step?pks={clerk_id}", follow_redirects=False)
            assert resp.status_code in (403, 302, 303)
        async with Database().session() as s:
            events = [a.action for a in (await s.execute(select(AuditLog))).scalars().all()]
        assert "web_two_step_reset" in events and "web_two_step_enabled" in events

    async def test_the_account_list_shows_who_uses_it(self, app):
        await turn_on(app, CLERK)
        async with make_client(app) as c:
            await sign_in(c, BOSS)
            page = (await c.get(f"/admin/{ACCOUNTS}/list")).text
        assert "Two-step sign-in" in page


def test_time_is_not_frozen_in_these_tests():
    assert abs(totp.current_step() - int(time.time() // 30)) <= 1
