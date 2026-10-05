"""Mailings: audience queries, status transitions and counters (the sending itself is bot/misc/services/mailing_sender)."""
import datetime

from sqlalchemy import select, update, func, exists, or_

from bot.database import Database
from bot.database.models import User
from bot.database.models.main import Mailings, MailingSegment, MailingStatus, Orders
from bot.i18n import main as i18n_main

# Mailings fields that are plain data (no picture bytes) — what the sender and the pages read.
_FIELDS = ("id", "title", "text", "image_file_id", "segment", "status", "scheduled_at", "started_at", "finished_at",
           "disable_preview", "silent", "protect_content", "total", "sent", "blocked", "failed", "created_by")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _audience(segment: str):
    """WHERE clauses for a segment (people blocked by an admin are never mailed)."""
    clauses = [or_(User.is_blocked.is_(False), User.is_blocked.is_(None))]
    if segment in (MailingSegment.LANG_RO, MailingSegment.LANG_RU, MailingSegment.LANG_EN):
        code = segment.split("_", 1)[1]
        if code == i18n_main.get_locale():      # people who never picked a language use the shop's main one
            clauses.append(or_(User.language == code, User.language.is_(None)))
        else:
            clauses.append(User.language == code)
    elif segment == MailingSegment.WITH_ORDERS:
        clauses.append(exists().where(Orders.user_id == User.telegram_id))
    elif segment == MailingSegment.WITHOUT_ORDERS:
        clauses.append(~exists().where(Orders.user_id == User.telegram_id))
    return clauses


async def segment_user_ids(segment: str) -> list[int]:
    async with Database().session() as s:
        rows = await s.execute(select(User.telegram_id).where(*_audience(segment)).order_by(User.telegram_id))
        return [int(r[0]) for r in rows.all()]


async def count_segment(segment: str) -> int:
    async with Database().session() as s:
        return (await s.execute(select(func.count()).select_from(User).where(*_audience(segment)))).scalar() or 0


async def segment_counts() -> dict[str, int]:
    return {seg: await count_segment(seg) for seg in MailingSegment.CHOICES}


def _as_dict(m: Mailings) -> dict:
    d = {f: getattr(m, f) for f in _FIELDS}
    d["has_image"] = m.image is not None
    return d


async def get_mailing(mailing_id: int) -> dict | None:
    async with Database().session() as s:
        m = await s.get(Mailings, mailing_id)
        return _as_dict(m) if m else None


async def get_mailing_image(mailing_id: int) -> bytes | None:
    async with Database().session() as s:
        return (await s.execute(select(Mailings.image).where(Mailings.id == mailing_id))).scalar()


async def set_mailing_file_id(mailing_id: int, file_id: str | None) -> None:
    async with Database().session() as s:
        await s.execute(update(Mailings).where(Mailings.id == mailing_id).values(image_file_id=file_id))


async def claim_due_mailing() -> dict | None:
    """Atomically take one scheduled mailing whose time has come (scheduled -> sending); None if there is none."""
    now = _now()
    async with Database().session() as s:
        candidate = (await s.execute(
            select(Mailings.id).where(Mailings.status == MailingStatus.SCHEDULED, Mailings.scheduled_at <= now)
            .order_by(Mailings.scheduled_at, Mailings.id).limit(1))).scalar()
        if candidate is None:
            return None
        claimed = await s.execute(
            update(Mailings).where(Mailings.id == candidate, Mailings.status == MailingStatus.SCHEDULED)
            .values(status=MailingStatus.SENDING, started_at=now))
        if claimed.rowcount != 1:
            return None
    return await get_mailing(candidate)


async def set_total(mailing_id: int, total: int) -> None:
    async with Database().session() as s:
        await s.execute(update(Mailings).where(Mailings.id == mailing_id).values(total=total))


async def add_progress(mailing_id: int, sent: int, blocked: int, failed: int) -> str:
    """Add a batch's counters; returns the mailing's current status (so the sender can stop when cancelled)."""
    async with Database().session() as s:
        await s.execute(update(Mailings).where(Mailings.id == mailing_id).values(
            sent=Mailings.sent + sent, blocked=Mailings.blocked + blocked, failed=Mailings.failed + failed))
        return (await s.execute(select(Mailings.status).where(Mailings.id == mailing_id))).scalar() or ""


async def mailing_status(mailing_id: int) -> str:
    async with Database().session() as s:
        return (await s.execute(select(Mailings.status).where(Mailings.id == mailing_id))).scalar() or ""


async def finish_mailing(mailing_id: int, status: str) -> None:
    """sending -> sent / cancelled / failed (a cancelled mailing stays cancelled)."""
    async with Database().session() as s:
        current = (await s.execute(select(Mailings.status).where(Mailings.id == mailing_id))).scalar()
        if current == MailingStatus.CANCELLED:
            status = MailingStatus.CANCELLED
        await s.execute(update(Mailings).where(Mailings.id == mailing_id).values(status=status, finished_at=_now()))


async def cancel_mailing(mailing_id: int) -> bool:
    """Cancel a scheduled or sending mailing. True if something was cancelled."""
    async with Database().session() as s:
        result = await s.execute(
            update(Mailings).where(Mailings.id == mailing_id,
                                   Mailings.status.in_((MailingStatus.SCHEDULED, MailingStatus.SENDING)))
            .values(status=MailingStatus.CANCELLED, finished_at=_now()))
        return result.rowcount == 1


async def fail_interrupted_mailings() -> int:
    """At startup: a mailing still 'sending' lost its sender with the old process; mark it failed (never resumed,
    so nobody gets the message twice)."""
    async with Database().session() as s:
        result = await s.execute(
            update(Mailings).where(Mailings.status == MailingStatus.SENDING)
            .values(status=MailingStatus.FAILED, finished_at=_now()))
        return result.rowcount or 0
