"""Clean chat: one screen per private chat."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage, SendPhoto, EditMessageText, AnswerCallbackQuery
from aiogram.types import Message, CallbackQuery

from bot.middleware import clean_chat as cc


@pytest.fixture(autouse=True)
def fresh_tracker(monkeypatch):
    monkeypatch.setattr(cc, "tracker", cc.ScreenTracker())


def sent(chat_id, message_id):
    return MagicMock(message_id=message_id, chat=MagicMock(id=chat_id))


def bot_mock():
    bot = MagicMock()
    bot.delete_message = AsyncMock()
    bot.delete_messages = AsyncMock()
    return bot


async def run_send(method, result, chat_serving):
    mw = cc.CleanChatRequestMiddleware()
    bot = bot_mock()
    make_request = AsyncMock(return_value=result)
    token = cc._serving_chat.set(chat_serving)
    try:
        out = await mw(make_request, bot, method)
    finally:
        cc._serving_chat.reset(token)
    return out, bot


class TestTracker:

    def test_set_get_and_bound(self):
        t = cc.ScreenTracker(limit=2)
        t.set(1, 10); t.set(2, 20); t.set(3, 30)
        assert t.get(1) is None and t.get(2) == 20 and t.get(3) == 30


class TestRequestMiddleware:

    async def test_second_send_deletes_the_first(self):
        _, bot = await run_send(SendMessage(chat_id=5, text="a"), sent(5, 100), 5)
        assert cc.tracker.get(5) == 100 and not bot.delete_message.await_count
        _, bot = await run_send(SendMessage(chat_id=5, text="b"), sent(5, 101), 5)
        bot.delete_message.assert_awaited_once_with(chat_id=5, message_id=100)
        assert cc.tracker.get(5) == 101

    async def test_photo_sends_count_too(self):
        cc.tracker.set(5, 7)
        _, bot = await run_send(SendPhoto(chat_id=5, photo="x"), sent(5, 8), 5)
        bot.delete_message.assert_awaited_once_with(chat_id=5, message_id=7)

    async def test_other_chat_and_no_context_untouched(self):
        cc.tracker.set(5, 7)
        _, bot = await run_send(SendMessage(chat_id=9, text="notify"), sent(9, 1), 5)
        assert not bot.delete_message.await_count and cc.tracker.get(9) is None
        _, bot = await run_send(SendMessage(chat_id=5, text="bg"), sent(5, 2), None)
        assert not bot.delete_message.await_count and cc.tracker.get(5) == 7

    async def test_edits_and_answers_pass_through(self):
        cc.tracker.set(5, 7)
        for m in (EditMessageText(chat_id=5, message_id=7, text="x"), AnswerCallbackQuery(callback_query_id="1")):
            out, bot = await run_send(m, True, 5)
            assert out is True and not bot.delete_message.await_count
        assert cc.tracker.get(5) == 7

    async def test_delete_failure_is_swallowed(self):
        cc.tracker.set(5, 7)
        mw = cc.CleanChatRequestMiddleware()
        bot = bot_mock()
        bot.delete_message.side_effect = TelegramBadRequest(method=MagicMock(), message="gone")
        token = cc._serving_chat.set(5)
        try:
            await mw(AsyncMock(return_value=sent(5, 8)), bot, SendMessage(chat_id=5, text="x"))
        finally:
            cc._serving_chat.reset(token)
        assert cc.tracker.get(5) == 8


def make_message(chat_type="private", text="hi", chat_id=5, mid=50):
    msg = MagicMock(spec=Message)
    msg.text = text
    msg.message_id = mid
    msg.chat = MagicMock(id=chat_id, type=chat_type)
    msg.delete = AsyncMock()
    msg.bot = bot_mock()
    return msg


class TestUpdateMiddleware:

    async def test_user_message_deleted_after_handler(self):
        msg = make_message()
        order = []
        handler = AsyncMock(side_effect=lambda *a: order.append("handler") or "ok")
        msg.delete.side_effect = lambda: order.append("delete")
        assert await cc.CleanChatMiddleware()(handler, msg, {}) == "ok"
        assert order == ["handler", "delete"]
        assert cc._serving_chat.get() is None

    async def test_group_chat_ignored(self):
        msg = make_message(chat_type="group")
        await cc.CleanChatMiddleware()(AsyncMock(), msg, {})
        msg.delete.assert_not_awaited()

    async def test_handler_error_propagates_and_still_tidies(self):
        msg = make_message()
        with pytest.raises(RuntimeError):
            await cc.CleanChatMiddleware()(AsyncMock(side_effect=RuntimeError("x")), msg, {})
        msg.delete.assert_awaited_once()
        assert cc._serving_chat.get() is None

    async def test_callback_marks_its_message_as_the_screen(self):
        call = MagicMock(spec=CallbackQuery)
        call.message = make_message(mid=77)
        await cc.CleanChatMiddleware()(AsyncMock(), call, {})
        assert cc.tracker.get(5) == 77
        call.message.delete.assert_not_awaited()

    async def test_start_sweeps_the_ids_before_it(self):
        msg = make_message(text="/start", mid=250)
        await cc.CleanChatMiddleware()(AsyncMock(), msg, {})
        ids = msg.bot.delete_messages.await_args.kwargs["message_ids"]
        assert ids == list(range(150, 250))

    async def test_start_near_the_beginning_of_a_chat(self):
        msg = make_message(text="/start", mid=3)
        await cc.CleanChatMiddleware()(AsyncMock(), msg, {})
        assert msg.bot.delete_messages.await_args.kwargs["message_ids"] == [1, 2]

    async def test_toggle(self, monkeypatch):
        monkeypatch.setenv("CLEAN_CHAT", "0")
        assert cc.clean_chat_enabled() is False
        monkeypatch.setenv("CLEAN_CHAT", "1")
        assert cc.clean_chat_enabled() is True


class TestOutsideScreen:

    async def test_sends_inside_the_block_are_not_tracked_and_replace_nothing(self):
        cc.tracker.set(5, 7)
        mw = cc.CleanChatRequestMiddleware()
        bot = bot_mock()
        token = cc._serving_chat.set(5)
        try:
            with cc.outside_screen():
                await mw(AsyncMock(return_value=sent(5, 8)), bot, SendMessage(chat_id=5, text="👇"))
            assert cc._serving_chat.get() == 5          # restored afterwards
        finally:
            cc._serving_chat.reset(token)
        assert not bot.delete_message.await_count and cc.tracker.get(5) == 7


class TestStaffAlertsInTheServedChat:
    """The owner placing an order is both customer and staff: the staff alert goes into the chat being served and
    must not become that chat's screen (it used to delete the confirm screen, so the next edit failed)."""

    async def _alert_while_serving(self, send):
        cc.tracker.set(5, 7)
        mw = cc.CleanChatRequestMiddleware()
        bot = bot_mock()

        async def send_message(chat_id, text, reply_markup=None):
            return await mw(AsyncMock(return_value=sent(chat_id, 8)), bot, SendMessage(chat_id=chat_id, text=text))

        bot.send_message = send_message
        token = cc._serving_chat.set(5)
        try:
            await send(bot)
        finally:
            cc._serving_chat.reset(token)
        return bot

    async def test_new_order_alert_keeps_the_screen(self, user_factory):
        from bot.misc.services.order_view import notify_new_order
        from tests.test_language_picker import _order
        await user_factory(telegram_id=5, role_id=3)
        bot = await self._alert_while_serving(lambda b: notify_new_order(b, _order(5)))
        assert not bot.delete_message.await_count and cc.tracker.get(5) == 7

    async def test_customer_notice_keeps_the_screen(self, user_factory):
        from bot.misc.services.order_view import notify_customer
        from tests.test_language_picker import _order
        await user_factory(telegram_id=5, role_id=3)
        bot = await self._alert_while_serving(lambda b: notify_customer(b, _order(5), "confirmed"))
        assert not bot.delete_message.await_count and cc.tracker.get(5) == 7
