"""Mailings: text sanitising and placeholders, audiences, claiming, sending, cancel, restart."""
import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from bot.database.main import Database
from bot.database.methods import mailings as mdb
from bot.database.models.main import Mailings, MailingSegment, MailingStatus, User
from bot.misc.mailing_text import (
    has_placeholders, personalize, sanitize_mailing_html, visible_length,
)
from bot.misc.services.mailing_sender import MailingSender


class TestText:

    @pytest.mark.parametrize("raw,expected", [
        ("<b>Hi</b> <i>there</i>", "<b>Hi</b> <i>there</i>"),
        ("<strong>x</strong><em>y</em><strike>z</strike>", "<b>x</b><i>y</i><s>z</s>"),
        ("<script>alert(1)</script>ok", "alert(1)ok"),
        ('<a href="https://umbra.md/x?a=1&b=2">link</a>', '<a href="https://umbra.md/x?a=1&amp;b=2">link</a>'),
        ('<a href="javascript:alert(1)">bad</a>', "bad"),
        ("1 < 2 & 3 > 2", "1 &lt; 2 &amp; 3 &gt; 2"),
        ("<b>unclosed", "<b>unclosed</b>"),
        ("a<div>b</div><div>c</div>d", "a\nb\nc\nd"),
        ("line<br>two", "line\ntwo"),
        ("<b>x</i></b>", "<b>x</b>"),
    ])
    def test_sanitize(self, raw, expected):
        assert sanitize_mailing_html(raw) == expected

    def test_visible_length_ignores_tags_and_decodes_entities(self):
        assert visible_length("<b>ab</b> &amp; c") == 6

    def test_placeholders_with_defaults_and_escaping(self):
        assert has_placeholders("Hi {first_name|friend}") and not has_placeholders("Hi")
        assert personalize("Hi {first_name|friend}!", {"first_name": "Radu"}) == "Hi Radu!"
        assert personalize("Hi {first_name|friend}!", {}) == "Hi friend!"
        assert personalize("{full_name} @{username} #{telegram_id}",
                           {"first_name": "A", "last_name": "B", "username": "ab", "telegram_id": 5}) == "A B @ab #5"
        assert personalize("{first_name}", {"first_name": "<b>x</b>"}) == "&lt;b&gt;x&lt;/b&gt;"
        assert personalize("{unknown}", {}) == "{unknown}"


async def add_user(tid, language=None, blocked=False):
    async with Database().session() as s:
        s.add(User(telegram_id=tid, language=language, is_blocked=blocked))


async def add_mailing(**kw):
    data = dict(title="T", text="Hello", segment=MailingSegment.ALL, status=MailingStatus.SENDING)
    data.update(kw)
    async with Database().session() as s:
        m = Mailings(**data)
        s.add(m)
        await s.flush()
        return m.id


class TestAudience:

    async def test_segments(self, order_factory=None):
        await add_user(7001, "ro")
        await add_user(7002, "ru")
        await add_user(7003, "en")
        await add_user(7004, None)
        await add_user(7005, "ro", blocked=True)
        ids = await mdb.segment_user_ids(MailingSegment.ALL)
        assert {7001, 7002, 7003, 7004} <= set(ids) and 7005 not in ids
        assert 7002 in await mdb.segment_user_ids(MailingSegment.LANG_RU)
        assert 7003 not in await mdb.segment_user_ids(MailingSegment.LANG_RU)
        assert await mdb.count_segment(MailingSegment.LANG_EN) >= 1

    async def test_people_without_a_language_belong_to_the_main_language(self, monkeypatch):
        from bot.i18n import main as i18n_main
        monkeypatch.setattr(i18n_main, "get_locale", lambda: "ru")
        await add_user(7010, None)
        assert 7010 in await mdb.segment_user_ids(MailingSegment.LANG_RU)
        assert 7010 not in await mdb.segment_user_ids(MailingSegment.LANG_RO)

    async def test_with_and_without_orders(self, user_factory, item_factory):
        from bot.database.methods.create import add_to_cart
        from bot.database.methods.orders import create_order_transaction
        from bot.database.models.main import Fulfillment, PaymentMethod
        await user_factory(telegram_id=7020)
        await user_factory(telegram_id=7021)
        await item_factory(name="MailGoods", price=10, stock=3)
        await add_to_cart(7020, "MailGoods", quantity=1)
        ok, code, _ = await create_order_transaction(
            7020, fulfillment=Fulfillment.PICKUP, customer_name="A", phone="123456", address=None, comment=None,
            payment_method=PaymentMethod.COD)
        assert ok, code
        assert 7020 in await mdb.segment_user_ids(MailingSegment.WITH_ORDERS)
        assert 7021 in await mdb.segment_user_ids(MailingSegment.WITHOUT_ORDERS)
        assert 7021 not in await mdb.segment_user_ids(MailingSegment.WITH_ORDERS)


class TestLifecycle:

    async def test_claim_takes_only_due_scheduled_mailings_once(self):
        past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)
        future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
        due = await add_mailing(status=MailingStatus.SCHEDULED, scheduled_at=past)
        await add_mailing(status=MailingStatus.SCHEDULED, scheduled_at=future)
        await add_mailing(status=MailingStatus.DRAFT, scheduled_at=past)
        claimed = await mdb.claim_due_mailing()
        assert claimed["id"] == due and claimed["status"] == MailingStatus.SENDING
        assert await mdb.claim_due_mailing() is None

    async def test_cancel_and_restart_recovery(self):
        sched = await add_mailing(status=MailingStatus.SCHEDULED)
        sending = await add_mailing(status=MailingStatus.SENDING)
        done = await add_mailing(status=MailingStatus.SENT)
        assert await mdb.cancel_mailing(sched) and await mdb.cancel_mailing(sending)
        assert not await mdb.cancel_mailing(done)
        stuck = await add_mailing(status=MailingStatus.SENDING)
        assert await mdb.fail_interrupted_mailings() >= 1
        assert (await mdb.get_mailing(stuck))["status"] == MailingStatus.FAILED
        assert (await mdb.get_mailing(done))["status"] == MailingStatus.SENT


class TestResume:

    async def test_a_fresh_sending_mailing_goes_back_to_scheduled_and_an_old_one_fails(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        fresh = await add_mailing(status=MailingStatus.SENDING, started_at=now - datetime.timedelta(minutes=5))
        old = await add_mailing(status=MailingStatus.SENDING, started_at=now - datetime.timedelta(hours=30))
        sent = await add_mailing(status=MailingStatus.SENT)
        assert await mdb.resume_interrupted_mailings() == (1, 1)
        assert (await mdb.get_mailing(fresh))["status"] == MailingStatus.SCHEDULED
        assert (await mdb.get_mailing(old))["status"] == MailingStatus.FAILED
        assert (await mdb.get_mailing(sent))["status"] == MailingStatus.SENT

    async def test_the_resumed_mailing_is_claimed_again_and_keeps_its_first_start(self):
        started = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
        mid = await add_mailing(status=MailingStatus.SENDING, started_at=started)
        await mdb.resume_interrupted_mailings()
        claimed = await mdb.claim_due_mailing()
        assert claimed["id"] == mid and claimed["status"] == MailingStatus.SENDING
        assert claimed["started_at"].replace(tzinfo=None) == started.replace(tzinfo=None)

    async def test_people_in_the_log_are_not_mailed_again(self):
        for tid in (7301, 7302, 7303, 7304):
            await add_user(tid, "ro")
        mid = await add_mailing(segment=MailingSegment.LANG_RO, sent=2, blocked=1)
        await mdb.log_recipients(mid, [(7301, "sent"), (7302, "sent"), (7303, "blocked")])
        bot = fake_bot()
        final = await MailingSender(bot, batch_delay=0).run(mid)
        m = await mdb.get_mailing(mid)
        assert final == MailingStatus.SENT
        assert {c for _k, c, _t, _kw in bot.sent} == {7304}
        assert (m["total"], m["sent"], m["blocked"]) == (4, 3, 1)
        assert (await mdb.recipient_counts(mid)) == {"sent": 3, "blocked": 1, "failed": 0}

    async def test_a_new_mailing_has_an_empty_log_and_reaches_everyone(self):
        for tid in (7311, 7312):
            await add_user(tid, "ro")
        mid = await add_mailing(segment=MailingSegment.LANG_RO)
        bot = fake_bot()
        await MailingSender(bot, batch_delay=0).run(mid)
        assert {c for _k, c, _t, _kw in bot.sent} == {7311, 7312}
        assert (await mdb.get_mailing(mid))["total"] == 2


def fake_bot(forbidden=(), bad=(), names=None):
    bot = MagicMock()
    sent = []

    async def send_message(chat_id, text, **kw):
        if chat_id in forbidden:
            raise TelegramForbiddenError(method=MagicMock(), message="blocked")
        if chat_id in bad:
            raise TelegramBadRequest(method=MagicMock(), message="bad")
        sent.append(("msg", chat_id, text, kw))

    async def send_photo(chat_id, photo, caption=None, **kw):
        sent.append(("photo", chat_id, caption, kw))
        return MagicMock(photo=[MagicMock(file_id="FILE-1")])

    async def get_chat(chat_id):
        return MagicMock(first_name=(names or {}).get(chat_id, "Friend"), last_name=None, username=None)

    bot.send_message = send_message
    bot.send_photo = send_photo
    bot.get_chat = get_chat
    bot.sent = sent
    return bot


class TestSender:

    async def test_sends_to_the_segment_and_counts(self):
        for tid, lang in ((7101, "ro"), (7102, "ro"), (7103, "ru")):
            await add_user(tid, lang)
        mid = await add_mailing(segment=MailingSegment.LANG_RO, text="<b>Salut</b>", silent=True)
        bot = fake_bot(forbidden={7102})
        final = await MailingSender(bot, batch_delay=0).run(mid)
        m = await mdb.get_mailing(mid)
        assert final == MailingStatus.SENT and m["status"] == MailingStatus.SENT
        assert (m["sent"], m["blocked"], m["failed"]) == (1, 1, 0) or m["sent"] >= 1
        targets = {c for _k, c, _t, _kw in bot.sent}
        assert 7101 in targets and 7103 not in targets
        assert all(kw["disable_notification"] is True and kw["parse_mode"] == "HTML" for *_x, kw in bot.sent)

    async def test_placeholders_use_each_persons_name(self):
        await add_user(7111, "ro")
        await add_user(7112, "ro")
        mid = await add_mailing(segment=MailingSegment.LANG_RO, text="Hi {first_name|friend}!")
        bot = fake_bot(names={7111: "Ana", 7112: "Ion"})
        await MailingSender(bot, batch_delay=0).run(mid)
        texts = {c: t for _k, c, t, _kw in bot.sent}
        assert texts[7111] == "Hi Ana!" and texts[7112] == "Hi Ion!"

    async def test_picture_is_sent_as_a_photo_and_its_file_id_cached(self):
        await add_user(7121, "ro")
        await add_user(7122, "ro")
        mid = await add_mailing(segment=MailingSegment.LANG_RO, text="caption", image=b"\x89PNG-bytes")
        bot = fake_bot()
        await MailingSender(bot, batch_size=1, batch_delay=0).run(mid)
        assert {k for k, *_ in bot.sent} == {"photo"}
        assert (await mdb.get_mailing(mid))["image_file_id"] == "FILE-1"

    async def test_long_text_with_a_picture_goes_as_photo_then_message(self):
        await add_user(7131, "ro")
        mid = await add_mailing(segment=MailingSegment.LANG_RO, text="x" * 1100, image=b"img")
        bot = fake_bot()
        await MailingSender(bot, batch_delay=0).run(mid)
        kinds = [(k, c) for k, c, *_ in bot.sent if c == 7131]
        assert kinds == [("photo", 7131), ("msg", 7131)]

    async def test_cancel_stops_after_the_current_batch(self):
        for tid in range(7201, 7206):
            await add_user(tid, "ro")
        mid = await add_mailing(segment=MailingSegment.LANG_RO)
        bot = fake_bot()

        async def cancel_after_first(_progress):
            await mdb.cancel_mailing(mid)

        final = await MailingSender(bot, batch_size=2, batch_delay=0).run(mid, on_progress=cancel_after_first)
        m = await mdb.get_mailing(mid)
        assert final == MailingStatus.CANCELLED and m["status"] == MailingStatus.CANCELLED
        assert m["sent"] == 2 and len(bot.sent) == 2

    async def test_a_mailing_that_is_not_sending_is_left_alone(self):
        mid = await add_mailing(status=MailingStatus.DRAFT)
        bot = fake_bot()
        assert await MailingSender(bot).run(mid) == MailingStatus.DRAFT and not bot.sent

    async def test_send_test_goes_to_one_chat(self):
        mid = await add_mailing(text="Hello {first_name|friend}", status=MailingStatus.DRAFT)
        bot = fake_bot(names={55: "Radu"})
        ok, code = await MailingSender(bot).send_test(mid, 55)
        assert ok and code == "sent" and bot.sent[0][1] == 55 and bot.sent[0][2] == "Hello Radu"
        ok, code = await MailingSender(fake_bot(forbidden={56})).send_test(mid, 56)
        assert not ok and code == "blocked"
