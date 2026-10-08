"""Mailings: audience queries, status transitions and counters (the sending itself is bot/misc/services/mailing_sender)."""
import datetime

from sqlalchemy import select, update, func, exists, or_

from bot.database import Database
from bot.database.models import User
from bot.database.models.main import MailingRecipients, Mailings, MailingSegment, MailingStatus, Orders
from bot.i18n import main as i18n_main

# Mailings fields that are plain data (no picture bytes) — what the sender and the pages read.
_FIELDS = ("id", "title", "text", "image_file_id", "segment", "status", "scheduled_at", "started_at", "finished_at",
           "disable_preview", "silent", "protect_content", "total", "sent", "blocked", "failed", "created_by",
           "retry_of")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _audience(segment: str):
    """WHERE clauses for a segment (people blocked by an admin, or who opted out of mailings, are never mailed)."""
    clauses = [or_(User.is_blocked.is_(False), User.is_blocked.is_(None)), User.mailing_optout.is_(False)]
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


async def segment_user_ids(segment: str, retry_of: int | None = None) -> list[int]:
    """Who a mailing goes to. A "resend to failed" mailing (``retry_of``) goes to the people the earlier mailing failed to
    reach, minus anyone blocked or opted out since."""
    async with Database().session() as s:
        stmt = select(User.telegram_id).where(*_audience(segment))
        if retry_of is not None:
            stmt = stmt.where(User.telegram_id.in_(
                select(MailingRecipients.user_id).where(
                    MailingRecipients.mailing_id == retry_of, MailingRecipients.outcome == "failed")))
        rows = await s.execute(stmt.order_by(User.telegram_id))
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
            .values(status=MailingStatus.SENDING, started_at=func.coalesce(Mailings.started_at, now)))
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


RESUME_WINDOW = datetime.timedelta(hours=24)


async def resume_interrupted_mailings() -> tuple[int, int]:
    """At startup: a mailing still 'sending' lost its sender with the old process. One that started within the last
    24 hours goes back to 'scheduled' (due now) and carries on with the people its delivery log does not list; an older
    one is marked failed. Returns ``(resumed, failed)``."""
    now = _now()
    async with Database().session() as s:
        rows = (await s.execute(select(Mailings.id, Mailings.started_at).where(
            Mailings.status == MailingStatus.SENDING))).all()
        resumed = failed = 0
        for mailing_id, started in rows:
            fresh = started is None or now - (started if started.tzinfo else started.replace(
                tzinfo=datetime.timezone.utc)) <= RESUME_WINDOW
            if fresh:
                await s.execute(update(Mailings).where(Mailings.id == mailing_id).values(
                    status=MailingStatus.SCHEDULED, scheduled_at=now))
                resumed += 1
            else:
                await s.execute(update(Mailings).where(Mailings.id == mailing_id).values(
                    status=MailingStatus.FAILED, finished_at=now))
                failed += 1
        return resumed, failed


async def reached_user_ids(mailing_id: int) -> set[int]:
    """Everyone the delivery log lists for this mailing (sent, blocked or failed): they are not tried again."""
    async with Database().session() as s:
        rows = await s.execute(select(MailingRecipients.user_id).where(MailingRecipients.mailing_id == mailing_id))
        return {int(r[0]) for r in rows.all()}


# --- who got what ----------------------------------------------------------------------------------------------------

async def log_recipients(mailing_id: int, results: list[tuple[int, str]]) -> None:
    """Record the outcome (sent / blocked / failed) for each person of a batch, in one insert."""
    if not results:
        return
    async with Database().session() as s:
        s.add_all([MailingRecipients(mailing_id=mailing_id, user_id=uid, outcome=outcome) for uid, outcome in results])


async def recipient_counts(mailing_id: int) -> dict[str, int]:
    async with Database().session() as s:
        rows = await s.execute(select(MailingRecipients.outcome, func.count()).where(
            MailingRecipients.mailing_id == mailing_id).group_by(MailingRecipients.outcome))
        counts = {"sent": 0, "blocked": 0, "failed": 0}
        counts.update({outcome: int(n) for outcome, n in rows.all()})
        return counts


async def recipient_rows(mailing_id: int, outcome: str | None = None, limit: int | None = None) -> list[dict]:
    """The log, oldest first, optionally only one outcome."""
    async with Database().session() as s:
        stmt = select(MailingRecipients.user_id, MailingRecipients.outcome, MailingRecipients.created_at).where(
            MailingRecipients.mailing_id == mailing_id)
        if outcome:
            stmt = stmt.where(MailingRecipients.outcome == outcome)
        stmt = stmt.order_by(MailingRecipients.id)
        if limit:
            stmt = stmt.limit(limit)
        return [{"user_id": int(r[0]), "outcome": r[1], "created_at": r[2]} for r in (await s.execute(stmt)).all()]


async def create_retry_mailing(mailing_id: int, created_by: str | None = None) -> int | None:
    """A draft copy of a finished mailing that targets only the people it failed to reach. None when there is no such
    mailing, it is still running, or nobody failed."""
    async with Database().session() as s:
        original = await s.get(Mailings, mailing_id)
        if original is None or original.status not in (MailingStatus.SENT, MailingStatus.CANCELLED, MailingStatus.FAILED):
            return None
        failed = (await s.execute(select(func.count()).select_from(MailingRecipients).where(
            MailingRecipients.mailing_id == mailing_id, MailingRecipients.outcome == "failed"))).scalar() or 0
        if not failed:
            return None
        copy = Mailings(
            title=f"{original.title} (resend)"[:200], text=original.text, image=original.image,
            image_file_id=original.image_file_id, segment=original.segment, status=MailingStatus.DRAFT,
            disable_preview=original.disable_preview, silent=original.silent, protect_content=original.protect_content,
            created_by=created_by, retry_of=original.id)
        s.add(copy)
        await s.flush()
        return copy.id


# --- opting out ------------------------------------------------------------------------------------------------------

async def set_mailing_optout(user_id: int, optout: bool) -> bool:
    """Turn mailings off / on for a person. False when there is no such user."""
    async with Database().session() as s:
        result = await s.execute(update(User).where(User.telegram_id == user_id).values(mailing_optout=optout))
        return (result.rowcount or 0) == 1
