import io
from html import escape as _esc

from aiogram import F

from bot.i18n import localize, LANGUAGES
from bot.i18n import main as _i18n_main
from bot.logger_mesh import logger
from bot.misc import EnvKeys
from bot.misc.images import ImageError, MAX_IMAGE_BYTES
from bot.misc.localized import (
    LANGS, MAX_NAME_LEN, MAX_DESCRIPTION_LEN, clean_name, clean_description,
)

# Numeric(12, 2) leaves 10 integer digits; anything larger is a DB error. Shared by the add and the update flows so they cannot drift.
MAX_ITEM_PRICE = 99_999_999


# A sane ceiling for units on hand (Integer column; typo guard for "1000000000").
MAX_STOCK = 1_000_000


def parse_price(text: str) -> int | None:
    """Parse an item price from admin input. None if it is not a usable price.
    """
    price_text = (text or "").strip()
    if not (price_text.isascii() and price_text.isdigit()):
        return None
    price = int(price_text)
    if price < 1 or price > MAX_ITEM_PRICE:
        return None
    return price


def parse_quantity(text: str, *, minimum: int = 0) -> int | None:
    """Parse a unit count from admin input. None if it is not a whole number in range.

    ``minimum`` is 0 for an absolute stock and 1 for "add N" / "remove N".
    """
    qty_text = (text or "").strip()
    if not (qty_text.isascii() and qty_text.isdigit()):
        return None
    qty = int(qty_text)
    if qty < minimum or qty > MAX_STOCK:
        return None
    return qty


async def announce_arrival(bot, item_name: str, quantity: int) -> None:
    """Tell the shop channel (if configured) that a product has arrived.

    Best effort: a missing channel or a bot without rights must not break the stock change.
    """
    from bot.handlers.other import _parse_channel_username
    channel_username = _parse_channel_username()
    if not channel_username:
        return
    try:
        chat_id = int(EnvKeys.CHANNEL_ID) if EnvKeys.CHANNEL_ID else f"@{channel_username}"
        await bot.send_message(
            chat_id=chat_id,
            text=localize('admin.goods.channel.arrival', name=_esc(item_name), qty=quantity),
            parse_mode='HTML',
        )
    except Exception as e:
        logger.warning("channel arrival post for %r failed: %s", item_name, e)


async def _notify_restock_safe(bot, item_name: str) -> None:
    """Fire restock notifications, never letting a failure break the stock add."""
    from bot.misc.services.restock_notifier import notify_restock
    try:
        await notify_restock(bot, item_name)
    except Exception:
        logger.exception("restock notification failed for %r", item_name)


def user_profile_lines(user, first_name, target_id, *, overall_balance,
                       orders_count, role, referrals, include_referral_id):
    """Build the common user-profile text lines shared by the admin profile views.

    Returns a list of lines (join with ``"\n"``). ``include_referral_id`` inserts
    the referral_id line — the read-only show-user view includes it, the
    action-panel view does not. Callers append their own extra lines afterward
    (blocked status, earnings stats).
    """
    lines = [
        localize('profile.caption', name=_esc(str(first_name or '')), id=target_id),
        '',
        localize('profile.id', id=target_id),
        localize('profile.balance', amount=user.get('balance'), currency=EnvKeys.PAY_CURRENCY),
        localize('profile.total_topup', amount=overall_balance, currency=EnvKeys.PAY_CURRENCY),
        localize('admin.users.orders_count', count=orders_count),
        '',
    ]
    if include_referral_id:
        lines.append(localize('profile.referral_id', id=user.get('referral_id')))
    lines += [
        localize('admin.users.referrals', count=referrals),
        localize('admin.users.role', role=role),
        localize('profile.registration_date', dt=user.get('registration_date')),
    ]
    return lines


# Messages the photo steps accept: a regular photo, or an image sent as a file (keeps the original quality).
IMAGE_MESSAGE = F.photo | (F.document & F.document.mime_type.startswith("image/"))

_IMAGE_ERROR_KEYS = {
    "too_large": "admin.goods.photo.too_large",
    "invalid_image": "admin.goods.photo.invalid",
    "unsupported_format": "admin.goods.photo.unsupported",
    "download_failed": "admin.goods.photo.download_failed",
    "item_not_found": "admin.goods.position.not_found",
}


def image_error_text(code: str) -> str:
    """Localized text for a ``set_item_image`` / ``validate_image`` error code."""
    return localize(_IMAGE_ERROR_KEYS.get(code, "admin.goods.photo.invalid"))


async def download_message_image(message) -> bytes | None:
    """Download the photo (largest size) or image document of ``message``; None if there is none.

    Raises ``ImageError`` ("too_large" before downloading when Telegram already reports an oversize file, or "download_failed").
    """
    if getattr(message, "photo", None):
        media = message.photo[-1]
    elif getattr(message, "document", None):
        media = message.document
    else:
        return None
    if (getattr(media, "file_size", None) or 0) > MAX_IMAGE_BYTES:
        raise ImageError("too_large")
    buf = io.BytesIO()
    try:
        await message.bot.download(media, destination=buf)
    except Exception as e:
        logger.warning("downloading a product picture failed: %s", e)
        raise ImageError("download_failed")
    return buf.getvalue()


# --- Catalog translations (names / descriptions in en, ru, ro) ---

def main_language() -> str:
    """The language the canonical (lookup-key) name/description is written in: BOT_LOCALE."""
    lang = _i18n_main.get_locale()
    return lang if lang in LANGS else LANGS[0]


def other_languages() -> list[str]:
    """The languages besides the main one, in picker order."""
    main = main_language()
    return [code for code, _ in LANGUAGES if code in LANGS and code != main]


def language_label(code: str) -> str:
    """Picker label of a language ("🇷🇴 Română")."""
    return dict(LANGUAGES).get(code, code)


def check_translation(field: str, text: str | None) -> tuple[str | None, str | None]:
    """Clean and validate admin input for a translated ``field`` ("name" / "description").

    Returns ``(value, None)`` or ``(None, i18n key of the error)``: blank after cleaning
    -> ``admin.translations.invalid``, over the limit -> ``admin.translations.too_long``.
    """
    cleaner, limit = (clean_name, MAX_NAME_LEN) if field == "name" else (clean_description, MAX_DESCRIPTION_LEN)
    value = cleaner(text)
    if value is None:
        return None, "admin.translations.invalid"
    if len(value) > limit:
        return None, "admin.translations.too_long"
    return value, None


def translation_limit(field: str) -> int:
    return MAX_NAME_LEN if field == "name" else MAX_DESCRIPTION_LEN
