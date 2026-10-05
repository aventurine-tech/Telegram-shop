"""Taps on the persistent bottom keyboard (Catalog / Cart / Profile)."""
from aiogram import Router, F
from aiogram.enums.chat_type import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.handlers.user.cart import _show_cart
from bot.handlers.user.main import show_profile, _delete_quietly
from bot.handlers.user.shop_and_goods import _show_categories_page
from bot.keyboards.reply import all_nav_labels
from bot.misc.metrics import get_metrics
from bot.states import ShopStates

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)

# Resolved once: every locale's labels are static.
_NAV_LABELS = all_nav_labels()


@router.message(F.text.in_(_NAV_LABELS))
async def bottom_nav_tap(message: Message, state: FSMContext):
    """Open the tapped screen as a new message, abandoning whatever flow was in progress."""
    target = _NAV_LABELS[message.text]
    await state.clear()
    try:
        await _delete_quietly(message)
    except Exception:  # the tap message is cosmetic; never let it block the screen
        pass

    if target == "catalog":
        metrics = get_metrics()
        if metrics:
            metrics.track_conversion("purchase_funnel", "view_shop", message.from_user.id)
        await _show_categories_page(message, state, 0)
        await state.set_state(ShopStates.viewing_categories)
    elif target == "cart":
        await _show_cart(message)
    else:
        await show_profile(message)
