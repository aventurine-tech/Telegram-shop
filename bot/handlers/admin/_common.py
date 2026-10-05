from html import escape as _esc

from bot.i18n import localize
from bot.logger_mesh import logger
from bot.misc import EnvKeys

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
