import asyncio
from typing import List, Optional, Callable, Awaitable, Union
from dataclasses import dataclass
from datetime import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest

from bot.logger_mesh import logger
from bot.misc.services.send_pacer import SendPacer, shared_pacer

# One keyboard for everyone, or a function that builds it per person (e.g. a button in their language).
Markup = Union[InlineKeyboardMarkup, Callable[[int], Optional[InlineKeyboardMarkup]], None]


@dataclass
class BroadcastStats:
    """Broadcast statistics"""
    total: int = 0
    sent: int = 0
    failed: int = 0
    blocked: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0
        return (self.sent / self.total) * 100

    @property
    def duration(self) -> Optional[float]:
        if not self.start_time or not self.end_time:
            return None
        return (self.end_time - self.start_time).total_seconds()


class BroadcastManager:
    """Manager for mass mailing with optimization"""

    DEFAULT_BATCH_SIZE = 25
    DEFAULT_BATCH_DELAY = 1.0

    def __init__(
            self,
            bot: Bot,
            batch_size: int = DEFAULT_BATCH_SIZE,
            batch_delay: float = DEFAULT_BATCH_DELAY,
            retry_count: int = 3,
            pacer: Optional[SendPacer] = None,
    ):
        """
        Args:
            bot: Bot instance
            batch_size: Number of messages in a batch
            batch_delay: Delay between batches (sec)
            retry_count: Number of retries on error
            pacer: Shared send pace (defaults to the one every bulk sender uses)
        """
        self.bot = bot
        self.batch_size = batch_size
        self.batch_delay = batch_delay
        self.retry_count = retry_count
        self.pacer = pacer or shared_pacer()
        self._cancelled = False

    async def _send_message_safe(
            self,
            user_id: int,
            text: str,
            reply_markup: Optional[InlineKeyboardMarkup] = None,
            parse_mode: str = "HTML"
    ) -> str:
        """
        Securely sending a message with error handling.

        Returns one of: "sent", "blocked" (user blocked the bot), or "failed"
        (bad request / retries exhausted / unknown).
        """
        for attempt in range(self.retry_count):
            await self.pacer.wait()
            try:
                await self.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                    disable_notification=True  # Don't spam notifications
                )
                return "sent"

            except TelegramRetryAfter as e:
                # Telegram asks to wait: every bulk sender pauses, not only this message
                self.pacer.pause(e.retry_after)
                if attempt < self.retry_count - 1:
                    continue
                return "failed"

            except TelegramForbiddenError:
                # The person blocked the bot or deleted their account
                logger.debug(f"Bot blocked by user {user_id}")
                return "blocked"

            except TelegramBadRequest as e:
                # Invalid message parameters
                logger.error(f"Bad request for user {user_id}: {e}")
                return "failed"

            except Exception as e:
                # Unknown error
                logger.error(f"Unknown error sending to {user_id}: {e}")
                if attempt < self.retry_count - 1:
                    await asyncio.sleep(1)
                    continue
                return "failed"

        return "failed"

    async def broadcast(
            self,
            user_ids: List[int],
            text: str,
            reply_markup: Markup = None,
            parse_mode: str = "HTML",
            progress_callback: Optional[Union[
                Callable[[BroadcastStats], None],
                Callable[[BroadcastStats], Awaitable[None]]
            ]] = None
    ) -> BroadcastStats:
        """
        Perform broadcast to a list of users

        Args:
            user_ids: List of user IDs
            text: Message text
            reply_markup: Keyboard, or a function ``user_id -> keyboard``
            parse_mode: Parsing mode
            progress_callback: Callback for tracking progress (can be async or sync)

        Returns:
            Broadcast statistics
        """
        stats = BroadcastStats(
            total=len(user_ids),
            start_time=datetime.now()
        )

        self._cancelled = False

        # Split into batches
        for i in range(0, len(user_ids), self.batch_size):
            if self._cancelled:
                logger.info("Broadcast cancelled")
                break

            batch = user_ids[i:i + self.batch_size]

            # Create tasks for the batch
            tasks = [
                self._send_message_safe(
                    user_id, text, reply_markup(user_id) if callable(reply_markup) else reply_markup, parse_mode)
                for user_id in batch
            ]

            # Execute the patch in parallel
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Update the statistics
            for result in results:
                if result == "sent":
                    stats.sent += 1
                elif result == "blocked":
                    stats.blocked += 1
                else:
                    # "failed" or an unexpected Exception from gather
                    stats.failed += 1

            # People Telegram refused are not written to again until they come back to the bot.
            await self._remember_unreachable([uid for uid, r in zip(batch, results) if r == "blocked"])

            if (i // self.batch_size) % 20 == 0:
                logger.info(
                    "Broadcast progress: %s/%s (sent=%s failed=%s blocked=%s)",
                    min(i + self.batch_size, stats.total), stats.total,
                    stats.sent, stats.failed, stats.blocked,
                )

            # Calling a progress collback
            if progress_callback:
                try:
                    # Check if the callback is asynchronous
                    if asyncio.iscoroutinefunction(progress_callback):
                        await progress_callback(stats)
                    else:
                        progress_callback(stats)
                except Exception as e:
                    logger.error(f"Progress callback error: {e}")

            # Delay between batches
            if i + self.batch_size < len(user_ids):
                await asyncio.sleep(self.batch_delay)

        stats.end_time = datetime.now()
        return stats

    @staticmethod
    async def _remember_unreachable(user_ids: List[int]) -> None:
        if not user_ids:
            return
        try:
            from bot.database.methods.mailings import mark_unreachable
            await mark_unreachable(user_ids)
        except Exception as e:                  # bookkeeping: never let it stop the send
            logger.warning("could not mark %s people as unreachable: %s", len(user_ids), e)

    def cancel(self):
        """Cancel the current mailing"""
        self._cancelled = True
