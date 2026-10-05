from html import escape as html_escape

from aiogram import Bot

from bot.database.methods.delete import pop_stock_subscribers
from bot.database.methods.read import get_user_languages
from bot.i18n import localize, use_language
from bot.keyboards.inline import close
from bot.logger_mesh import logger
from bot.misc.services.broadcast_system import BroadcastManager


async def notify_restock(bot: Bot, item_name: str) -> int:
    """Tell everyone waiting on `item_name` that it is back, and unsubscribe them.

    Returns the number of messages actually delivered.
    """
    user_ids = await pop_stock_subscribers(item_name)
    if not user_ids:
        return 0

    # Everyone is told in their own language: one broadcast per language group.
    languages = await get_user_languages(user_ids)
    groups: dict[str | None, list[int]] = {}
    for uid in user_ids:
        groups.setdefault(languages.get(uid), []).append(uid)

    manager = BroadcastManager(bot)
    sent = failed = 0
    for lang, ids in groups.items():
        with use_language(lang):
            text = localize("stock.back_in_stock", name=html_escape(item_name, quote=False))
        stats = await manager.broadcast(
            user_ids=ids,
            text=text,
            reply_markup=close(),
            parse_mode="HTML",
        )
        sent += stats.sent
        failed += stats.failed

    logger.info(
        "restock notify %r: subscribers=%s sent=%s failed=%s",
        item_name, len(user_ids), sent, failed,
    )
    return sent
