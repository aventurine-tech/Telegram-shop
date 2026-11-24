"""One pace for everything the bot sends in bulk (mailings, the in-bot broadcast, back-in-stock notices).

Telegram allows roughly 30 messages a second to different people and answers faster senders with "retry after N
seconds". Every bulk sender takes its turn here, so several mailings running together still add up to one steady
stream, and when Telegram asks to wait, all of them wait.
"""
import asyncio
import time


class SendPacer:
    RATE = 20.0                # messages a second, all bulk senders together

    def __init__(self, rate: float | None = None):
        self.interval = 1.0 / (rate or self.RATE)
        self._next = 0.0
        self._paused_until = 0.0

    async def wait(self) -> None:
        """Return when it is this caller's turn to make one Telegram request."""
        while True:
            now = time.monotonic()
            turn = max(now, self._next, self._paused_until)
            self._next = turn + self.interval
            if turn <= now:
                return
            await asyncio.sleep(turn - now)
            if time.monotonic() >= self._paused_until:      # not paused while we slept: go
                return

    def pause(self, seconds: float) -> None:
        """Telegram said "retry after": nobody sends until then."""
        self._paused_until = max(self._paused_until, time.monotonic() + max(0.0, float(seconds)))


_shared = SendPacer()


def shared_pacer() -> SendPacer:
    return _shared
