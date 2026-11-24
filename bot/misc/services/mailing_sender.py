"""Sends a mailing written in the web panel: text with placeholders, optional picture, per-batch progress."""
import asyncio
import contextlib
from typing import Awaitable, Callable

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions

from bot.database.methods.mailings import (
    add_progress, finish_mailing, get_mailing, get_mailing_image, log_recipients, mailing_status, mark_unreachable,
    reached_user_ids, recipient_profiles, segment_user_ids, set_mailing_file_id, set_total, sync_progress_from_log,
)
from bot.database.models.main import MailingStatus
from bot.i18n.main import localize, use_language
from bot.logger_mesh import logger
from bot.misc.mailing_text import CAPTION_LIMIT, has_placeholders, personalize, visible_length
from bot.misc.services.send_pacer import SendPacer, shared_pacer


def unsubscribe_markup(lang: str | None) -> InlineKeyboardMarkup:
    """The way out that every mass message carries, in the reader's own language."""
    with use_language(lang):
        button = InlineKeyboardButton(text=localize("btn.mailing.unsubscribe"), callback_data="mailing_optout")
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


class MailingSender:
    """One instance per bot; ``run`` sends one claimed mailing, ``send_test`` sends it to a single chat."""

    BATCH_SIZE = 25
    BATCH_DELAY = 1.0          # seconds between batches; inside a batch the shared pacer spaces the messages out
    RETRIES = 3

    def __init__(self, bot: Bot, *, batch_size: int | None = None, batch_delay: float | None = None,
                 pacer: SendPacer | None = None):
        self.bot = bot
        self.batch_size = batch_size or self.BATCH_SIZE
        self.batch_delay = self.BATCH_DELAY if batch_delay is None else batch_delay
        self.pacer = pacer or shared_pacer()

    # --- one message -------------------------------------------------------------------------------------------

    async def _profile(self, user_id: int) -> dict:
        """Names straight from Telegram: only for a test message to a chat we hold no record of."""
        try:
            chat = await self.bot.get_chat(user_id)
            return {"first_name": chat.first_name, "last_name": chat.last_name, "username": chat.username,
                    "telegram_id": user_id}
        except Exception:                      # names are a nicety: fall back to the placeholder defaults
            return {"telegram_id": user_id}

    _unsubscribe_markup = staticmethod(unsubscribe_markup)

    async def _send(self, mailing: dict, image: bytes | None, user_id: int, text: str,
                    lang: str | None = None) -> tuple[str, str | None]:
        """Returns (outcome, new_file_id). Outcome: sent / blocked / failed."""
        common = dict(chat_id=user_id, parse_mode="HTML", disable_notification=bool(mailing["silent"]),
                      protect_content=bool(mailing["protect_content"]))
        markup = self._unsubscribe_markup(lang)
        preview = LinkPreviewOptions(is_disabled=bool(mailing["disable_preview"]))
        photo_sent = None                       # the picture went out: a retry must not send it again
        for attempt in range(self.RETRIES):
            try:
                if image is None and not mailing.get("image_file_id"):
                    await self.pacer.wait()
                    await self.bot.send_message(text=text, link_preview_options=preview, reply_markup=markup, **common)
                    return "sent", None
                caption_fits = visible_length(text) <= CAPTION_LIMIT
                if photo_sent is None:
                    photo = mailing.get("image_file_id") or BufferedInputFile(image, filename="mailing")
                    await self.pacer.wait()
                    photo_sent = await self.bot.send_photo(photo=photo, caption=text if caption_fits else None,
                                                           reply_markup=markup if caption_fits else None, **common)
                if not caption_fits:
                    await self.pacer.wait()
                    await self.bot.send_message(text=text, link_preview_options=preview, reply_markup=markup, **common)
                file_id = photo_sent.photo[-1].file_id if getattr(photo_sent, "photo", None) else None
                return "sent", file_id
            except TelegramRetryAfter as e:
                self.pacer.pause(e.retry_after)     # Telegram asks to wait: every bulk sender pauses, not only this message
                if attempt < self.RETRIES - 1:
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

    async def _deliver(self, mailing: dict, image: bytes | None, user_id: int, profile: dict | None,
                       lang: str | None = None) -> str:
        """``profile`` fills the placeholders (None: the text has none)."""
        text = mailing["text"]
        if profile is not None:
            text = personalize(text, profile)
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
        known = (await recipient_profiles([chat_id])).get(chat_id)
        profile = None
        if has_placeholders(mailing["text"]):
            profile = known if known and known.get("first_name") else await self._profile(chat_id)
        outcome = await self._deliver(mailing, image, chat_id, profile, (known or {}).get("language"))
        return outcome == "sent", outcome

    async def _deliver_logged(self, mailing: dict, image: bytes | None, user_id: int, profile: dict | None,
                              lang: str | None) -> str:
        """Deliver to one person and write their line of the delivery log straight away, so a restart in the middle
        of a batch knows exactly who already has the message."""
        try:
            outcome = await self._deliver(mailing, image, user_id, profile, lang)
        except Exception as e:
            logger.error("mailing %s: error delivering to %s: %s", mailing["id"], user_id, e)
            outcome = "failed"
        try:                                    # the log is a report: never let it stop the mailing…
            # …but a shutdown arriving right after the send must not lose the line.
            await asyncio.shield(log_recipients(mailing["id"], [(user_id, outcome)]))
        except Exception as e:
            logger.warning("mailing %s: could not log %s: %s", mailing["id"], user_id, e)
        return outcome

    # --- the whole mailing ------------------------------------------------------------------------------------

    async def run(self, mailing_id: int,
                  on_progress: Callable[[dict], Awaitable[None]] | None = None) -> str:
        """Send a mailing that is already marked 'sending'. Returns the final status."""
        mailing = await get_mailing(mailing_id)
        if mailing is None or mailing["status"] != MailingStatus.SENDING:
            return mailing["status"] if mailing else "not_found"
        image = await get_mailing_image(mailing_id) if mailing["has_image"] else None
        user_ids = await segment_user_ids(mailing["segment"], mailing.get("retry_of"))
        # After a restart the log tells who was already reached: they are skipped, and the counters are set to what
        # the log says (the last batch before the restart may have been logged but not counted).
        reached = await reached_user_ids(mailing_id)
        if reached:
            logger.info("mailing %s resumes: %s people already reached", mailing_id, len(reached))
            user_ids = [uid for uid in user_ids if uid not in reached]
            with contextlib.suppress(Exception):
                await sync_progress_from_log(mailing_id)
        await set_total(mailing_id, len(user_ids) + len(reached))
        needs_profile = has_placeholders(mailing["text"])
        final = MailingStatus.SENT
        try:
            for start in range(0, len(user_ids), self.batch_size):
                batch = user_ids[start:start + self.batch_size]
                profiles = await recipient_profiles(batch)      # names and language from our records: no Telegram call
                results = await asyncio.gather(
                    *(self._deliver_logged(
                        mailing, image, uid,
                        (profiles.get(uid) or {"telegram_id": uid}) if needs_profile else None,
                        (profiles.get(uid) or {}).get("language")) for uid in batch),
                    return_exceptions=True)
                sent = sum(1 for r in results if r == "sent")
                blocked = sum(1 for r in results if r == "blocked")
                failed = len(results) - sent - blocked
                await add_progress(mailing_id, sent, blocked, failed)
                with contextlib.suppress(Exception):      # people Telegram refused are left alone until they come back
                    await mark_unreachable([uid for uid, r in zip(batch, results) if r == "blocked"])
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
