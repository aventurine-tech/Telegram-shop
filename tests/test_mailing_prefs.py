"""Mailings: opting out, the recipient log, resend to failed, and the shop timezone."""
import datetime
import re
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select

from bot.database.main import Database
from bot.database.methods import mailings as mdb
from bot.database.methods.read import check_user
from bot.database.methods.web_users import create_web_user
from bot.database.models.main import Mailings, MailingSegment, MailingStatus, User, WebRole
from bot.handlers.user.mailing_prefs import mailing_optin_handler, mailing_optout_handler, mailing_toggle_handler
from bot.keyboards.inline import profile_keyboard
from bot.misc import shop_time
from bot.misc.services.mailing_sender import MailingSender
from bot.web.admin import UserAdmin, create_admin_app
from bot.web.language import LANG_COOKIE
from bot.web.mailings import MailingAdmin
from tests.test_mailings_core import add_mailing, add_user, fake_bot

M = MailingAdmin.identity


async def set_optout(tid, value=True):
    async with Database().session() as s:
        (await s.execute(select(User).where(User.telegram_id == tid))).scalars().one().mailing_optout = value


class TestOptOut:

    async def test_people_who_opted_out_are_not_in_any_audience(self):
        for tid in (8101, 8102, 8103):
            await add_user(tid, "ro")
        await set_optout(8102)
        ids = await mdb.segment_user_ids(MailingSegment.LANG_RO)
        assert 8101 in ids and 8103 in ids and 8102 not in ids
        assert await mdb.count_segment(MailingSegment.LANG_RO) == len(ids)

    async def test_the_sender_skips_them_and_puts_a_way_out_under_every_message(self):
        await add_user(8111, "ro")
        await add_user(8112, "ru")
        await add_user(8113, "ro")
        await set_optout(8113)
        mid = await add_mailing(segment=MailingSegment.ALL, text="Hello")
        bot = fake_bot()
        await MailingSender(bot, batch_delay=0).run(mid)
        sent = {chat: kw for _k, chat, _t, kw in bot.sent if chat in (8111, 8112, 8113)}
        assert set(sent) == {8111, 8112}
        for kw in sent.values():
            button = kw["reply_markup"].inline_keyboard[0][0]
            assert button.callback_data == "mailing_optout"
        # …worded in each reader's own language
        assert sent[8111]["reply_markup"].inline_keyboard[0][0].text != sent[8112]["reply_markup"].inline_keyboard[0][0].text

    async def test_a_long_text_with_a_picture_puts_the_button_on_the_last_message_only(self):
        await add_user(8121, "ro")
        mid = await add_mailing(segment=MailingSegment.LANG_RO, text="x" * 1500, image=b"\x89PNG-fake")
        bot = fake_bot()
        await MailingSender(bot, batch_delay=0).run(mid)
        mine = [(kind, kw) for kind, chat, _t, kw in bot.sent if chat == 8121]
        assert [k for k, _ in mine] == ["photo", "msg"]
        assert mine[0][1].get("reply_markup") is None and mine[1][1]["reply_markup"] is not None

    async def test_unsubscribe_button_and_back(self, make_callback_query):
        await add_user(8131, "ro")
        call = make_callback_query(data="mailing_optout", user_id=8131)
        await mailing_optout_handler(call)
        assert (await check_user(8131))["mailing_optout"] is True
        assert call.message.edit_reply_markup.call_args[1]["reply_markup"].inline_keyboard[0][0].callback_data == "mailing_optin"

        back = make_callback_query(data="mailing_optin", user_id=8131)
        await mailing_optin_handler(back)
        assert (await check_user(8131))["mailing_optout"] is False
        assert back.message.edit_reply_markup.call_args[1]["reply_markup"].inline_keyboard[0][0].callback_data == "mailing_optout"

    async def test_profile_toggle_flips_and_redraws_the_profile(self, make_callback_query):
        await add_user(8132, "ro")
        call = make_callback_query(data="mailing_toggle", user_id=8132)
        with patch("bot.handlers.user.mailing_prefs.show_profile", new_callable=AsyncMock) as show:
            await mailing_toggle_handler(call)
            assert (await check_user(8132))["mailing_optout"] is True
            await mailing_toggle_handler(call)
            assert (await check_user(8132))["mailing_optout"] is False
            assert show.await_count == 2

    def test_profile_keyboard_shows_the_toggle_only_when_it_knows_the_state(self):
        def cbs(markup):
            return [b.callback_data for row in markup.inline_keyboard for b in row]
        assert "mailing_toggle" not in cbs(profile_keyboard(0))
        assert "mailing_toggle" in cbs(profile_keyboard(0, mailings_on=True))
        assert "mailing_toggle" in cbs(profile_keyboard(0, mailings_on=False))


class TestRecipientLogAndResend:

    async def test_every_person_gets_a_row_with_the_outcome(self):
        for tid in (8201, 8202, 8203):
            await add_user(tid, "en")
        mid = await add_mailing(segment=MailingSegment.LANG_EN)
        await MailingSender(fake_bot(forbidden={8202}, bad={8203}), batch_delay=0).run(mid)
        rows = {r["user_id"]: r["outcome"] for r in await mdb.recipient_rows(mid)}
        assert rows[8201] == "sent" and rows[8202] == "blocked" and rows[8203] == "failed"
        counts = await mdb.recipient_counts(mid)
        assert counts["sent"] == 1 and counts["blocked"] == 1 and counts["failed"] == 1
        assert [r["user_id"] for r in await mdb.recipient_rows(mid, "failed")] == [8203]

    async def test_resend_goes_only_to_the_people_who_failed(self):
        for tid in (8211, 8212, 8213):
            await add_user(tid, "en")
        mid = await add_mailing(segment=MailingSegment.LANG_EN, status=MailingStatus.SENDING)
        await MailingSender(fake_bot(bad={8212}, forbidden={8213}), batch_delay=0).run(mid)

        new_id = await mdb.create_retry_mailing(mid, "boss")
        assert new_id is not None
        retry = await mdb.get_mailing(new_id)
        assert retry["status"] == MailingStatus.DRAFT and retry["retry_of"] == mid
        assert await mdb.segment_user_ids(retry["segment"], retry["retry_of"]) == [8212]

        async with Database().session() as s:
            (await s.get(Mailings, new_id)).status = MailingStatus.SENDING
        bot = fake_bot()
        await MailingSender(bot, batch_delay=0).run(new_id)
        assert {chat for _k, chat, _t, _kw in bot.sent} == {8212}

    async def test_nothing_to_resend_when_nobody_failed_or_it_is_still_running(self):
        await add_user(8221, "en")
        done = await add_mailing(segment=MailingSegment.LANG_EN, status=MailingStatus.SENDING)
        await MailingSender(fake_bot(), batch_delay=0).run(done)
        assert await mdb.create_retry_mailing(done) is None
        running = await add_mailing(status=MailingStatus.SENDING)
        assert await mdb.create_retry_mailing(running) is None
        assert await mdb.create_retry_mailing(99999999) is None

    async def test_a_failing_log_does_not_stop_the_mailing(self):
        await add_user(8231, "en")
        mid = await add_mailing(segment=MailingSegment.LANG_EN)
        bot = fake_bot()
        with patch("bot.misc.services.mailing_sender.log_recipients", new_callable=AsyncMock, side_effect=RuntimeError):
            assert await MailingSender(bot, batch_delay=0).run(mid) == MailingStatus.SENT
        assert any(chat == 8231 for _k, chat, _t, _kw in bot.sent)


class TestShopTime:

    def test_typed_time_is_the_shop_clock_and_round_trips(self):
        typed = datetime.datetime(2026, 7, 1, 12, 0)              # summer: Chisinau is UTC+3
        moment = shop_time.from_shop(typed)
        assert moment == datetime.datetime(2026, 7, 1, 9, 0, tzinfo=datetime.timezone.utc)
        assert shop_time.to_shop(moment).replace(tzinfo=None) == typed
        winter = shop_time.from_shop(datetime.datetime(2026, 1, 15, 12, 0))
        assert winter.hour == 10                                  # UTC+2

    def test_naive_stored_values_are_utc_and_aware_ones_are_converted(self):
        assert shop_time.to_shop(datetime.datetime(2026, 7, 1, 9, 0)).hour == 12
        aware = datetime.datetime(2026, 7, 1, 12, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=3)))
        assert shop_time.from_shop(aware).hour == 9

    def test_an_unknown_zone_falls_back_to_utc(self, caplog):
        shop_time._zone.cache_clear()
        with patch("bot.misc.env.EnvKeys.SHOP_TIMEZONE", "Mars/Olympus"):
            assert shop_time.from_shop(datetime.datetime(2026, 7, 1, 12, 0)).hour == 12
        shop_time._zone.cache_clear()
        assert "Mars/Olympus" in caplog.text


@pytest.fixture
async def boss():
    assert (await create_web_user("prefboss", "prefboss-pass-1", WebRole.ADMIN))[0]
    app = create_admin_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 5000)),
                                 base_url="http://testserver") as c:
        assert (await c.post("/admin/login", data={"username": "prefboss", "password": "prefboss-pass-1"})
                ).status_code == 302
        c.cookies.set(LANG_COOKIE, "en")
        yield c, app


def form(**over):
    data = {"title": "Pref", "segment": "all", "text": "Hello", "send_mode": "draft"}
    data.update(over)
    return data


class TestPanel:

    async def test_schedule_is_typed_in_shop_time_and_shown_back_in_it(self, boss):
        client, _ = boss
        future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=2)
        typed = shop_time.to_shop(future).strftime("%Y-%m-%dT%H:%M")
        resp = await client.post(f"/admin/{M}/create", data=form(send_mode="scheduled", scheduled_at=typed))
        assert resp.status_code == 302, resp.text[:300]
        async with Database().session() as s:
            m = (await s.execute(select(Mailings).order_by(Mailings.id.desc()))).scalars().first()
        stored = m.scheduled_at if m.scheduled_at.tzinfo else m.scheduled_at.replace(tzinfo=datetime.timezone.utc)
        assert abs((stored - future).total_seconds()) < 61            # the same moment, whatever the zone offset
        edit = (await client.get(f"/admin/{M}/edit/{m.id}")).text
        assert f'value="{typed}"' in edit and "Publication date (Europe/Chisinau)" in edit
        listing = (await client.get(f"/admin/{M}/list")).text
        assert shop_time.to_shop(stored).strftime("%Y-%m-%d %H:%M") in listing

    async def test_details_list_who_was_not_reached_and_resend_makes_a_draft(self, boss):
        client, _ = boss
        for tid in (8301, 8302):
            await add_user(tid, "en")
        mid = await add_mailing(segment=MailingSegment.LANG_EN, status=MailingStatus.SENDING)
        await MailingSender(fake_bot(bad={8302}), batch_delay=0).run(mid)
        page = (await client.get(f"/admin/{M}/details/{mid}")).text
        assert "Recipients" in page and "8302" in page and "Resend to failed" in page
        assert f"/mailings/{mid}/recipients.csv" in page

        resp = await client.get(f"/admin/{M}/action/resend-failed?pks={mid}")
        assert resp.status_code == 302 and "notice=resend_created" in resp.headers["location"]
        async with Database().session() as s:
            copy = (await s.execute(select(Mailings).where(Mailings.retry_of == mid))).scalars().one()
        assert copy.status == MailingStatus.DRAFT

    async def test_csv_is_admin_only_and_lists_ids_and_outcomes(self, boss):
        client, app = boss
        await add_user(8311, "en")
        mid = await add_mailing(segment=MailingSegment.LANG_EN)
        await MailingSender(fake_bot(), batch_delay=0).run(mid)
        resp = await client.get(f"/mailings/{mid}/recipients.csv")
        assert resp.status_code == 200 and resp.text.splitlines()[0] == "user_id,outcome,time"
        assert re.search(r"^8311,sent,", resp.text, re.M)
        assert (await client.get("/mailings/99999999/recipients.csv")).status_code == 404
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as anon:
            assert (await anon.get(f"/mailings/{mid}/recipients.csv")).status_code in (401, 403)

    async def test_client_page_shows_and_edits_the_opt_out(self, boss):
        client, _ = boss
        await add_user(8321, "en")
        await set_optout(8321)
        page = (await client.get(f"/admin/{UserAdmin.identity}/details/{8321}")).text
        assert "No mailings" in page
        edit = (await client.get(f"/admin/{UserAdmin.identity}/edit/{8321}")).text
        assert 'name="mailing_optout"' in edit
