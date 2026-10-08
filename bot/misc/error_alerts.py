"""Error alerts: tell the owner when the bot logs an error, without flooding them.

A logging handler (ERROR and above) hands each record to :class:`ErrorAlerter`, which sends a short message to the
owner (and ``ERROR_ALERT_CHAT_ID``). The same problem is announced once per cooldown, and no more than a few alerts go
out per window; the rest are counted and summarised. Only the logger name and the first line of the message are sent,
never a traceback, so personal data from a stack frame cannot leak into a chat.
"""
import asyncio
import logging
import re
import threading
import time

from aiogram import Bot

from bot.i18n import localize, esc
from bot.misc import EnvKeys

logger = logging.getLogger("bot.error_alerts")

COOLDOWN_S = 600        # the same problem is announced at most once per this long
WINDOW_S = 600          # at most MAX_PER_WINDOW alerts per window; the rest become one summary
MAX_PER_WINDOW = 5
FLUSH_EVERY_S = 5
MAX_PENDING = 50        # distinct problems waiting for the next flush (an outage cannot grow memory)
MAX_TEXT = 300

_TOKEN = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b")
_NUMBERS = re.compile(r"\d+")


def summarize(record: logging.LogRecord) -> tuple[str, str]:
    """(dedupe key, text to show) for a log record: logger + first message line, tokens masked, no traceback."""
    try:
        message = record.getMessage()
    except Exception:
        message = str(record.msg)
    line = (message.strip().splitlines() or [""])[0]
    if record.exc_info and record.exc_info[0] is not None:
        line = f"{line} [{record.exc_info[0].__name__}]" if line else record.exc_info[0].__name__
    line = _TOKEN.sub("***", line)[:MAX_TEXT]
    key = f"{record.name}|{_NUMBERS.sub('#', line)}"
    return key, f"{record.name}: {line}"


class ErrorAlertHandler(logging.Handler):
    """Feeds ERROR+ records to an ErrorAlerter. Safe to call from any thread."""

    def __init__(self, alerter: "ErrorAlerter"):
        super().__init__(level=logging.ERROR)
        self.alerter = alerter

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.ERROR or record.name.startswith("bot.error_alerts"):      # our own failures never alert (no loops)
            return
        try:
            self.alerter.submit(*summarize(record))
        except Exception:
            pass


class ErrorAlerter:
    def __init__(self, bot: Bot, clock=time.monotonic):
        self.bot = bot
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: dict[str, list] = {}         # key -> [text, count]
        self._last_sent: dict[str, float] = {}      # key -> when it was announced
        self._repeats: dict[str, int] = {}          # key -> repeats swallowed by the cooldown
        self._window_start = clock()
        self._sent_in_window = 0
        self._suppressed = 0
        self._handler: ErrorAlertHandler | None = None
        self._task: asyncio.Task | None = None

    # --- intake (any thread) -------------------------------------------------------------------------------------
    def submit(self, key: str, text: str) -> None:
        with self._lock:
            entry = self._pending.get(key)
            if entry:
                entry[1] += 1
            elif len(self._pending) < MAX_PENDING:
                self._pending[key] = [text, 1]
            else:
                self._suppressed += 1

    # --- decisions -----------------------------------------------------------------------------------------------
    def drain(self) -> list[str]:
        """The messages to send now (already localized); updates cooldowns and the window budget."""
        now = self._clock()
        with self._lock:
            pending, self._pending = self._pending, {}
        if now - self._window_start >= WINDOW_S:
            self._window_start, self._sent_in_window = now, 0
        out: list[str] = []
        for key, (text, count) in pending.items():
            last = self._last_sent.get(key)
            if last is not None and now - last < COOLDOWN_S:
                self._repeats[key] = self._repeats.get(key, 0) + count
                continue
            if self._sent_in_window >= MAX_PER_WINDOW:
                self._suppressed += count
                continue
            repeats = self._repeats.pop(key, 0)
            self._last_sent[key] = now
            self._sent_in_window += 1
            msg = f"{localize('alert.error.title')}\n<code>{esc(text)}</code>"
            if repeats:
                msg += "\n" + localize("alert.error.repeats", n=repeats)
            out.append(msg)
        for key in [k for k, t in self._last_sent.items() if now - t >= COOLDOWN_S and k not in self._repeats]:
            del self._last_sent[key]       # forget problems that went quiet, so memory stays small
        if self._suppressed and self._sent_in_window < MAX_PER_WINDOW:
            out.append(localize("alert.error.suppressed", n=self._suppressed))
            self._suppressed = 0
            self._sent_in_window += 1
        return out

    def targets(self) -> list[int | str]:
        ids: list[int | str] = [int(EnvKeys.OWNER_ID)]
        extra = (EnvKeys.ERROR_ALERT_CHAT_ID or "").strip()
        if extra:
            ids.append(int(extra) if extra.lstrip("-").isdigit() else extra)
        return ids

    async def flush(self) -> int:
        sent = 0
        for text in self.drain():
            for chat_id in self.targets():
                try:
                    await self.bot.send_message(chat_id, text)
                    sent += 1
                except Exception as e:      # blocked bot, wrong chat id, network down: warn, never alert about it
                    logger.warning("error alert to %s failed: %s", chat_id, e)
        return sent

    # --- lifecycle -----------------------------------------------------------------------------------------------
    async def _run(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_EVERY_S)
            try:
                await self.flush()
            except Exception:
                logger.warning("error alert flush failed", exc_info=True)

    def start(self) -> None:
        self._handler = ErrorAlertHandler(self)
        for name in ("", "bot"):        # "bot" does not propagate to the root logger, so it needs its own
            logging.getLogger(name).addHandler(self._handler)
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._handler:
            for name in ("", "bot"):
                logging.getLogger(name).removeHandler(self._handler)
            self._handler = None
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        try:
            await self.flush()      # a last error from shutdown still gets out
        except Exception:
            pass


def start_error_alerts(bot: Bot) -> "ErrorAlerter | None":
    if EnvKeys.ERROR_ALERTS != "1":
        return None
    alerter = ErrorAlerter(bot)
    alerter.start()
    return alerter
