"""Error alerts: dedupe, rate cap, no traceback, no loops."""
import logging
from unittest.mock import AsyncMock

import pytest

from bot.misc import error_alerts as ea
from bot.misc.error_alerts import ErrorAlerter, ErrorAlertHandler, summarize


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(clock=None):
    bot = AsyncMock()
    return ErrorAlerter(bot, clock=clock or Clock()), bot


def record(msg, name="bot.x", exc=None, *args):
    return logging.LogRecord(name, logging.ERROR, __file__, 1, msg, args, exc)


def test_summarize_masks_token_and_drops_traceback():
    try:
        raise ValueError("secret customer phone +37360000000")
    except ValueError:
        import sys
        rec = record("boom 1:23 token 123456789:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789ab\nTraceback line", exc=sys.exc_info())
    key, text = summarize(rec)
    assert "123456789:ABC" not in text
    assert "Traceback" not in text and "+3736" not in text
    assert "[ValueError]" in text and text.startswith("bot.x: ")


def test_same_problem_with_different_numbers_shares_a_key():
    assert summarize(record("order 5 failed"))[0] == summarize(record("order 77 failed"))[0]
    assert summarize(record("order 5 failed", name="bot.a"))[0] != summarize(record("order 5 failed", name="bot.b"))[0]


def test_long_message_is_cut():
    assert len(summarize(record("x" * 5000))[1]) < 400


async def test_first_error_is_sent_to_the_owner():
    a, bot = make()
    a.submit(*summarize(record("db down")))
    assert await a.flush() == 1
    chat, text = bot.send_message.await_args.args
    assert chat == 999999 and "alert.error.title" in text and "db down" in text


async def test_extra_chat_also_gets_it(monkeypatch):
    from bot.misc import EnvKeys
    monkeypatch.setattr(EnvKeys, "ERROR_ALERT_CHAT_ID", "-100500", raising=False)
    a, bot = make()
    a.submit(*summarize(record("db down")))
    assert await a.flush() == 2
    assert [c.args[0] for c in bot.send_message.await_args_list] == [999999, -100500]


async def test_repeat_within_cooldown_is_swallowed_then_counted():
    clock = Clock()
    a, bot = make(clock)
    a.submit(*summarize(record("db down")))
    await a.flush()
    for _ in range(3):
        a.submit(*summarize(record("db down")))
    clock.t += 30
    assert await a.flush() == 0
    clock.t += ea.COOLDOWN_S
    a.submit(*summarize(record("db down")))
    assert await a.flush() == 1
    assert "alert.error.repeats" in bot.send_message.await_args.args[1]


async def test_burst_is_capped_and_summarised_next_window():
    clock = Clock()
    a, bot = make(clock)
    for i in range(ea.MAX_PER_WINDOW + 4):
        a.submit(*summarize(record(f"problem-{chr(97 + i)}")))
    assert await a.flush() == ea.MAX_PER_WINDOW
    clock.t += ea.WINDOW_S
    assert await a.flush() == 1
    assert "alert.error.suppressed" in bot.send_message.await_args.args[1]


async def test_pending_is_bounded():
    a, _ = make()
    for i in range(ea.MAX_PENDING + 20):
        a.submit(f"k{i}", "t")
    assert len(a._pending) == ea.MAX_PENDING


async def test_send_failure_is_swallowed():
    a, bot = make()
    bot.send_message.side_effect = RuntimeError("blocked")
    a.submit(*summarize(record("db down")))
    assert await a.flush() == 0


def test_handler_ignores_its_own_logger_and_low_levels():
    a, _ = make()
    h = ErrorAlertHandler(a)
    h.handle(record("x", name="bot.error_alerts"))
    low = record("y")
    low.levelno = logging.WARNING
    h.handle(low)
    assert not a._pending
    h.handle(record("real", name="bot.orders"))
    assert len(a._pending) == 1


async def test_start_attaches_and_stop_detaches():
    a, bot = make()
    a.start()
    logging.getLogger("bot.something").error("kaboom")
    logging.getLogger("other.lib").error("kaboom2")
    assert len(a._pending) == 2
    await a.stop()
    assert a._handler is None
    logging.getLogger("bot.something").error("after")
    assert bot.send_message.await_count >= 1     # stop() flushes what was waiting


def test_switch_off(monkeypatch):
    from bot.misc import EnvKeys
    monkeypatch.setattr(EnvKeys, "ERROR_ALERTS", "0", raising=False)
    assert ea.start_error_alerts(AsyncMock()) is None
