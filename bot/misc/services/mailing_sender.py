"""Sends a mailing written in the web panel: text with placeholders, optional picture, per-batch progress."""
import asyncio
import contextlib
from typing import Awaitable, Callable

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions

from bot.database.methods.mailings import (
    add_progress, finish_mailing, get_mailing, get_mailing_image, log_recipients, mailing_status, segment_user_ids,
    set_mailing_file_id, set_total,
)
from bot.database.methods.read import get_user_languages
from bot.database.models.main import MailingStatus
from bot.i18n.main import localize, use_language
from bot.logger_mesh import logger
from bot.misc.mailing_text import CAPTION_LIMIT, has_placeholders, personalize, visible_length


class MailingSender:
    """One instance per bot; ``run`` sends one claimed mailing, ``send_test`` sends it to a single chat."""

    BATCH_SIZE = 25
    BATCH_DELAY = 1.0          # seconds between batches: stays well inside Telegram's ~30 messages / second
    RETRIES = 3

    def __init__(self, bot: Bot, *, batch_size: int | None = None, batch_delay: float | None = None):
        self.bot = bot
        self.batch_size = batch_size or self.BATCH_SIZE
        self.batch_delay = self.BATCH_DELAY if batch_delay is None else batch_delay

    # --- one message -------------------------------------------------------------------------------------------

    async def _profile(self, user_id: int) -> dict:
        try:
            chat = await self.bot.get_chat(user_id)
            return {"first_name": chat.first_name, "last_name": chat.last_name, "username": chat.username,
                    "telegram_id": user_id}
        except Exception:                      # names are a nicety: fall back to the placeholder defaults
            return {"telegram_id": user_id}

    @staticmethod
    def _unsubscribe_markup(lang: str | None) -> InlineKeyboardMarkup:
        """Every mailing carries a way out, in the reader's own language."""
        with use_language(lang):
            button = InlineKeyboardButton(text=localize("btn.mailing.unsubscribe"), callback_data="mailing_optout")
        return InlineKeyboardMarkup(inline_keyboard=[[button]])

    async def _send(self, mailing: dict, image: bytes | None, user_id: int, text: str,
                    lang: str | None = None) -> tuple[str, str | None]:
        """Returns (outcome, new_file_id). Outcome: sent / blocked / failed."""
        common = dict(chat_id=user_id, parse_mode="HTML", disable_notification=bool(mailing["silent"]),
                      protect_content=bool(mailing["protect_content"]))
        markup = self._unsubscribe_markup(lang)
        preview = LinkPreviewOptions(is_disabled=bool(mailing["disable_preview"]))
        for attempt in range(self.RETRIES):
            try:
                if image is None and not mailing.get("image_file_id"):
                    await self.bot.send_message(text=text, link_preview_options=preview, reply_markup=markup, **common)
                    return "sent", None
                photo = mailing.get("image_file_id") or BufferedInputFile(image, filename="mailing")
                caption_fits = visible_length(text) <= CAPTION_LIMIT
                message = await self.bot.send_photo(photo=photo, caption=text if caption_fits else None,
                                                    reply_markup=markup if caption_fits else None, **common)
                if not caption_fits:
                    await self.bot.send_message(text=text, link_preview_options=preview, reply_markup=markup, **common)
                file_id = message.photo[-1].file_id if getattr(message, "photo", None) else None
                return "sent", file_id
            except TelegramRetryAfter as e:
                if attempt < self.RETRIES - 1:
                    await asyncio.sleep(e.retry_after)
                    continue
                return "failed", None
            except TelegramForbiddenError:
                return "blocked", None
            except TelegramBadRequest as e:
                logger.warning("mailing %s: bad request for %s: %s", mailing["id"], user_id, e)
                return "failed", None
            except Exception as e:
                logger.error("mailing %s: error sending to %s: %s", mailing["id"], user_id, e)
                if attempt < self.RETRIES - 1:
                    await asyncio.sleep(1)
                    continue
                return "failed", None
        return "failed", None

    async def _deliver(self, mailing: dict, image: bytes | None, user_id: int, needs_profile: bool,
                       lang: str | None = None) -> str:
        text = mailing["text"]
        if needs_profile:
            text = personalize(text, await self._profile(user_id))
        outcome, file_id = await self._send(mailing, image, user_id, text, lang)
        if file_id and not mailing.get("image_file_id"):
            mailing["image_file_id"] = file_id          # later messages reuse the uploaded picture
            with contextlib.suppress(Exception):
                await set_mailing_file_id(mailing["id"], file_id)
        return outcome

    async def send_test(self, mailing_id: int, chat_id: int) -> tuple[bool, str]:
        """Send the mailing to one chat (placeholders filled from that chat). Returns (ok, code)."""
        mailing = await get_mailing(mailing_id)
        if mailing is None:
            return False, "not_found"
        image = await get_mailing_image(mailing_id) if mailing["has_image"] else None
        lang = (await get_user_languages([chat_id])).get(chat_id)
        outcome = await self._deliver(mailing, image, chat_id, has_placeholders(mailing["text"]), lang)
        return outcome == "sent", outcome

    # --- the whole mailing ------------------------------------------------------------------------------------

    async def run(self, mailing_id: int,
                  on_progress: Callable[[dict], Awaitable[None]] | None = None) -> str:
        """Send a mailing that is already marked 'sending'. Returns the final status."""
        mailing = await get_mailing(mailing_id)
        if mailing is None or mailing["status"] != MailingStatus.SENDING:
            return mailing["status"] if mailing else "not_found"
        image = await get_mailing_image(mailing_id) if mailing["has_image"] else None
        user_ids = await segment_user_ids(mailing["segment"], mailing.get("retry_of"))
        await set_total(mailing_id, len(user_ids))
        needs_profile = has_placeholders(mailing["text"])
        final = MailingStatus.SENT
        try:
            for start in range(0, len(user_ids), self.batch_size):
                batch = user_ids[start:start + self.batch_size]
                languages = await get_user_languages(batch)
                results = await asyncio.gather(
                    *(self._deliver(mailing, image, uid, needs_profile, languages.get(uid)) for uid in batch),
                    return_exceptions=True)
                sent = sum(1 for r in results if r == "sent")
                blocked = sum(1 for r in results if r == "blocked")
                failed = len(results) - sent - blocked
                await add_progress(mailing_id, sent, blocked, failed)
                with contextlib.suppress(Exception):      # the log is a report: never let it stop the mailing
                    await log_recipients(mailing_id, [
                        (uid, r if r in ("sent", "blocked") else "failed") for uid, r in zip(batch, results)])
                if on_progress:
                    with contextlib.suppress(Exception):
                        await on_progress({"id": mailing_id, "sent": sent, "blocked": blocked, "failed": failed})
                if await mailing_status(mailing_id) == MailingStatus.CANCELLED:
                    logger.info("mailing %s cancelled after %s recipients", mailing_id, start + len(batch))
                    final = MailingStatus.CANCELLED
                    break
                if start + self.batch_size < len(user_ids):
                    await asyncio.sleep(self.batch_delay)
                    if await mailing_status(mailing_id) == MailingStatus.CANCELLED:   # cancelled during the pause
                        final = MailingStatus.CANCELLED
                        break
        except asyncio.CancelledError:
            await finish_mailing(mailing_id, MailingStatus.FAILED)
            raise
        except Exception as e:
            logger.error("mailing %s failed: %s", mailing_id, e, exc_info=True)
            final = MailingStatus.FAILED
        await finish_mailing(mailing_id, final)
        return final
