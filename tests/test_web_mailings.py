"""Mailings in the web panel: the form, scheduling, editing limits, actions, the picture route, My account ID."""
import datetime
import io
import re
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

from bot.database.main import Database
from bot.database.methods.web_users import create_web_user, get_web_user_auth
from bot.database.models.main import Mailings, MailingStatus, WebRole
from bot.web import admin as admin_module
from bot.web.admin import create_admin_app
from bot.web.language import LANG_COOKIE
from bot.web.mailings import MailingAdmin

BOSS = ("mboss", "boss-pass-1")
CLERK = ("mclerk", "clerk-pass-1")
M = MailingAdmin.identity


def make_client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 5000)),
                             base_url="http://testserver")


def png(size=(8, 8)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def when(**delta) -> str:
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(**delta)).strftime("%Y-%m-%dT%H:%M")


@pytest.fixture
async def boss():
    await create_web_user(*BOSS, WebRole.ADMIN)
    app = create_admin_app()
    async with make_client(app) as c:
        assert (await c.post("/admin/login", data={"username": BOSS[0], "password": BOSS[1]})).status_code == 302
        c.cookies.set(LANG_COOKIE, "en")
        yield c


async def all_mailings():
    async with Database().session() as s:
        return (await s.execute(select(Mailings).order_by(Mailings.id))).scalars().all()


async def clear():
    async with Database().session() as s:
        for m in (await s.execute(select(Mailings))).scalars().all():
            await s.delete(m)


@pytest.fixture(autouse=True)
async def _clean():
    await clear()
    yield
    await clear()


def form(**over):
    base = {"title": "Spring", "segment": "all", "text": "Hello <b>{first_name|friend}</b>", "send_mode": "draft"}
    base.update(over)
    return base


class TestForm:

    async def test_create_page_has_the_editor_and_audience_counts(self, boss):
        page = (await boss.get(f"/admin/{M}/create")).text
        assert "mailing-editor" in page and "contentEditable" in page
        assert "name=\"text\"" in page and "name=\"picture\"" in page and "name=\"scheduled_at\"" in page
        assert "All customers (" in page and "Customers with orders (" in page
        assert "Prohibit forwarding and saving" in page

    async def test_a_draft_is_saved_with_clean_html(self, boss):
        resp = await boss.post(f"/admin/{M}/create", data=form(
            text='<script>x()</script><b>Hi</b> <a href="javascript:evil()">l</a> {first_name}'))
        assert resp.status_code == 302, resp.text[:400]
        (m,) = await all_mailings()
        assert m.status == MailingStatus.DRAFT and m.created_by == BOSS[0]
        assert "<script" not in m.text and "javascript:" not in m.text and "<b>Hi</b>" in m.text

    async def test_title_and_content_are_required(self, boss):
        assert (await boss.post(f"/admin/{M}/create", data=form(title="  "))).status_code == 400
        assert (await boss.post(f"/admin/{M}/create", data=form(text=""))).status_code == 400
        assert await all_mailings() == []

    async def test_text_over_the_telegram_limit_is_refused(self, boss):
        resp = await boss.post(f"/admin/{M}/create", data=form(text="x" * 4097))
        assert resp.status_code == 400 and "too long" in resp.text
        assert (await boss.post(f"/admin/{M}/create", data=form(text="x" * 4096))).status_code == 302

    async def test_a_picture_alone_is_enough_and_is_stored_as_uploaded(self, boss):
        data = png()
        resp = await boss.post(f"/admin/{M}/create", data=form(text=""),
                               files={"picture": ("a.png", data, "image/png")})
        assert resp.status_code == 302, resp.text[:400]
        (m,) = await all_mailings()
        assert m.image == data and m.image_file_id is None

    async def test_a_bad_picture_is_refused(self, boss):
        resp = await boss.post(f"/admin/{M}/create", data=form(), files={"picture": ("a.png", b"nope", "image/png")})
        assert resp.status_code == 400 and await all_mailings() == []

    async def test_send_now_schedules_it_for_this_moment(self, boss):
        assert (await boss.post(f"/admin/{M}/create", data=form(send_mode="now"))).status_code == 302
        (m,) = await all_mailings()
        assert m.status == MailingStatus.SCHEDULED and m.scheduled_at is not None

    async def test_scheduling_needs_a_future_date(self, boss):
        assert (await boss.post(f"/admin/{M}/create", data=form(send_mode="scheduled"))).status_code == 400
        past = await boss.post(f"/admin/{M}/create", data=form(send_mode="scheduled", scheduled_at=when(days=-1)))
        assert past.status_code == 400 and "in the past" in past.text
        ok = await boss.post(f"/admin/{M}/create", data=form(send_mode="scheduled", scheduled_at=when(hours=3)))
        assert ok.status_code == 302
        (m,) = await all_mailings()
        assert m.status == MailingStatus.SCHEDULED

    async def test_options_are_saved(self, boss):
        await boss.post(f"/admin/{M}/create", data=form(disable_preview="y", silent="y", protect_content="y"))
        (m,) = await all_mailings()
        assert (m.disable_preview, m.silent, m.protect_content) == (True, True, True)


class TestEditing:

    async def _make(self, boss, **over):
        await boss.post(f"/admin/{M}/create", data=form(**over))
        return (await all_mailings())[-1]

    async def test_a_draft_can_be_edited_and_prefilled(self, boss):
        m = await self._make(boss)
        page = (await boss.get(f"/admin/{M}/edit/{m.id}")).text
        assert "Spring" in page and "{first_name|friend}" in page
        resp = await boss.post(f"/admin/{M}/edit/{m.id}", data=form(title="Summer", send_mode="draft"))
        assert resp.status_code == 302
        assert (await all_mailings())[0].title == "Summer"

    async def test_a_sent_mailing_cannot_be_changed(self, boss):
        m = await self._make(boss)
        async with Database().session() as s:
            (await s.get(Mailings, m.id)).status = MailingStatus.SENT
        resp = await boss.post(f"/admin/{M}/edit/{m.id}", data=form(title="Hack"))
        assert resp.status_code == 400 and "cannot be changed" in resp.text
        assert (await all_mailings())[0].title == "Spring"

    async def test_removing_the_picture_and_keeping_it(self, boss):
        await boss.post(f"/admin/{M}/create", data=form(), files={"picture": ("a.png", png(), "image/png")})
        m = (await all_mailings())[0]
        await boss.post(f"/admin/{M}/edit/{m.id}", data=form(title="Same"))
        assert (await all_mailings())[0].image is not None
        await boss.post(f"/admin/{M}/edit/{m.id}", data=form(title="Same", remove_picture="y"))
        assert (await all_mailings())[0].image is None

    async def test_a_running_mailing_cannot_be_deleted(self, boss):
        m = await self._make(boss)
        async with Database().session() as s:
            (await s.get(Mailings, m.id)).status = MailingStatus.SENDING
        await boss.post(f"/admin/{M}/delete?pks={m.id}")
        assert len(await all_mailings()) == 1


class TestListAndDetails:

    async def test_list_shows_status_group_and_delivered(self, boss):
        await boss.post(f"/admin/{M}/create", data=form(segment="lang_ru"))
        async with Database().session() as s:
            m = (await s.execute(select(Mailings))).scalars().first()
            m.status, m.total, m.sent = MailingStatus.SENT, 1188, 534
        page = (await boss.get(f"/admin/{M}/list")).text
        assert "Sent" in page and "Russian speakers" in page and "534 out of 1188" in page

    async def test_details_show_message_progress_and_actions(self, boss):
        await boss.post(f"/admin/{M}/create", data=form(send_mode="scheduled", scheduled_at=when(hours=2)))
        m = (await all_mailings())[0]
        page = (await boss.get(f"/admin/{M}/details/{m.id}")).text
        assert "<b>Anna</b>" in page                      # placeholders previewed with sample values
        assert "Send test to me" in page and "Cancel mailing" in page and "progress-bar" in page

    async def test_details_in_every_language(self, boss):
        await boss.post(f"/admin/{M}/create", data=form())
        m = (await all_mailings())[0]
        for lang, word in (("ru", "Отправить тест мне"), ("ro", "Trimite test mie")):
            boss.cookies.set(LANG_COOKIE, lang)
            assert word in (await boss.get(f"/admin/{M}/details/{m.id}")).text


class TestActions:

    async def _draft(self, boss):
        await boss.post(f"/admin/{M}/create", data=form())
        return (await all_mailings())[0]

    async def test_test_message_needs_a_telegram_id(self, boss):
        m = await self._draft(boss)
        resp = await boss.get(f"/admin/{M}/action/send-test?pks={m.id}", follow_redirects=True)
        assert "Set your Telegram ID" in resp.text

    async def test_test_message_goes_to_my_chat(self, boss):
        m = await self._draft(boss)
        await boss.post("/admin/my-account", data={"form": "telegram", "telegram_id": "4242"})
        bot = MagicMock()
        bot.get_chat = AsyncMock(return_value=MagicMock(first_name="Boss", last_name=None, username=None))
        bot.send_message = AsyncMock()
        old = admin_module._notifier_bot
        admin_module.set_notifier_bot(bot)
        try:
            resp = await boss.get(f"/admin/{M}/action/send-test?pks={m.id}", follow_redirects=True)
        finally:
            admin_module.set_notifier_bot(old)
        assert "Test message sent" in resp.text
        assert bot.send_message.await_args.kwargs["chat_id"] == 4242
        assert "<b>Boss</b>" in bot.send_message.await_args.kwargs["text"]

    async def test_cancel_a_scheduled_mailing(self, boss):
        await boss.post(f"/admin/{M}/create", data=form(send_mode="scheduled", scheduled_at=when(hours=5)))
        m = (await all_mailings())[0]
        resp = await boss.get(f"/admin/{M}/action/cancel-mailing?pks={m.id}", follow_redirects=True)
        assert "Mailing cancelled" in resp.text
        assert (await all_mailings())[0].status == MailingStatus.CANCELLED
        again = await boss.get(f"/admin/{M}/action/cancel-mailing?pks={m.id}", follow_redirects=True)
        assert "Only a scheduled or running" in again.text

    async def test_duplicate_makes_a_draft_copy_with_the_picture(self, boss):
        await boss.post(f"/admin/{M}/create", data=form(send_mode="now"), files={"picture": ("a.png", png(), "image/png")})
        m = (await all_mailings())[0]
        await boss.get(f"/admin/{M}/action/duplicate?pks={m.id}", follow_redirects=True)
        copy = (await all_mailings())[1]
        assert copy.status == MailingStatus.DRAFT and copy.image == m.image and copy.title.startswith("Spring")


class TestPictureAndAccess:

    async def test_picture_route_serves_the_bytes_to_admins_only(self, boss):
        data = png()
        await boss.post(f"/admin/{M}/create", data=form(), files={"picture": ("a.png", data, "image/png")})
        m = (await all_mailings())[0]
        ok = await boss.get(f"/mailing-image/{m.id}")
        assert ok.status_code == 200 and ok.content == data and ok.headers["content-type"] == "image/png"
        assert (await boss.get("/mailing-image/99999")).status_code == 404
        async with make_client(create_admin_app()) as anon:
            assert (await anon.get(f"/mailing-image/{m.id}")).status_code == 403

    async def test_staff_do_not_see_or_reach_mailings(self, boss):
        await create_web_user(*CLERK, WebRole.STAFF)
        async with make_client(create_admin_app()) as c:
            await c.post("/admin/login", data={"username": CLERK[0], "password": CLERK[1]})
            c.cookies.set(LANG_COOKIE, "en")
            assert (await c.get(f"/admin/{M}/list")).status_code in (302, 401, 403)
            assert "Mailings" not in (await c.get("/admin/")).text


class TestMyAccountTelegramId:

    async def test_save_and_clear(self, boss):
        resp = await boss.post("/admin/my-account", data={"form": "telegram", "telegram_id": "777"})
        assert "Telegram ID saved" in resp.text
        assert (await get_web_user_auth(BOSS[0]))["telegram_id"] == 777
        await boss.post("/admin/my-account", data={"form": "telegram", "telegram_id": ""})
        assert (await get_web_user_auth(BOSS[0]))["telegram_id"] is None

    @pytest.mark.parametrize("bad", ["abc", "-5", "0", "12.5", str(2 ** 63)])
    async def test_bad_values_are_refused(self, boss, bad):
        resp = await boss.post("/admin/my-account", data={"form": "telegram", "telegram_id": bad})
        assert "positive whole number" in resp.text
        assert (await get_web_user_auth(BOSS[0]))["telegram_id"] is None
