"""A customer's profile: Telegram names and @username, refreshed as they use the bot (the phone and address are
saved by the order transaction)."""
import datetime
import logging

from sqlalchemy import update

from bot.database import Database
from bot.database.models.main import User

logger = logging.getLogger(__name__)

NAME_MAX = 128
USERNAME_MAX = 64


def _clean(value: str | None, limit: int) -> str | None:
    value = (value or "").strip()
    return value[:limit] or None


async def refresh_profile(user_id: int, username: str | None, first_name: str | None, last_name: str | None) -> bool:
    """Store what Telegram says about the person and stamp ``last_seen_at``. False when there is no such user yet."""
    values = {
        "username": _clean(username, USERNAME_MAX), "first_name": _clean(first_name, NAME_MAX),
        "last_name": _clean(last_name, NAME_MAX), "last_seen_at": datetime.datetime.now(datetime.timezone.utc),
    }
    async with Database().session() as s:
        result = await s.execute(update(User).where(User.telegram_id == user_id).values(**values))
        return result.rowcount == 1


DETAIL_FIELDS = ("contact_name", "phone", "city", "address")
_LIMITS = {"contact_name": 100, "phone": 32, "city": 100}


async def save_details(user_id: int, **values) -> bool:
    """Set (or clear, with ``None`` / empty text) the profile details the customer edits themselves:
    ``contact_name``, ``phone``, ``city``, ``address``. Returns False if there is no such user."""
    clean = {}
    for key, value in values.items():
        if key not in DETAIL_FIELDS:
            raise ValueError(f"not a profile detail: {key}")
        text = (value or "").strip()
        clean[key] = (text[:_LIMITS[key]] if key in _LIMITS else text) or None
    if not clean:
        return True
    async with Database().session() as s:
        result = await s.execute(update(User).where(User.telegram_id == user_id).values(**clean))
        return result.rowcount == 1


def saved_address(profile: dict | None) -> str:
    """The delivery address as a customer would write it: ``city, address`` (whichever parts exist)."""
    profile = profile or {}
    return ", ".join(p for p in ((profile.get("city") or "").strip(), (profile.get("address") or "").strip()) if p)
