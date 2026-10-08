"""The shop's clock. Times are stored in UTC; people read and type them in ``SHOP_TIMEZONE``."""
import datetime
import logging
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bot.misc import EnvKeys

logger = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def _zone(name: str) -> datetime.tzinfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        logger.warning("SHOP_TIMEZONE=%r is not a known timezone; using UTC", name)
        return datetime.timezone.utc


def shop_tz() -> datetime.tzinfo:
    return _zone((EnvKeys.SHOP_TIMEZONE or "UTC").strip())


def _utc(value: datetime.datetime) -> datetime.datetime:
    """Naive datetimes (SQLite) are UTC."""
    return value.replace(tzinfo=datetime.timezone.utc) if value.tzinfo is None else value.astimezone(datetime.timezone.utc)


def to_shop(value: datetime.datetime) -> datetime.datetime:
    """A stored (UTC) moment as the shop's wall clock."""
    return _utc(value).astimezone(shop_tz())


def from_shop(value: datetime.datetime) -> datetime.datetime:
    """A wall-clock time typed in the shop's timezone (naive) as a UTC moment. Aware values are just converted."""
    if value.tzinfo is not None:
        return value.astimezone(datetime.timezone.utc)
    return value.replace(tzinfo=shop_tz()).astimezone(datetime.timezone.utc)


def zone_label(value: datetime.datetime | None = None) -> str:
    """Short name of the shop's zone at ``value`` (default now), e.g. ``EEST`` or ``UTC+03:00``."""
    moment = to_shop(value) if value else datetime.datetime.now(datetime.timezone.utc).astimezone(shop_tz())
    return moment.tzname() or "UTC"
