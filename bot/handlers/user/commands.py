"""The ☰ menu commands: each opens the same screen as the matching button, as a new message."""
from aiogram import Router
from aiogram.enums.chat_type import ChatType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram import F

from bot.handlers.user._screen import edit_screen
from bot.handlers.user.cart import _show_cart
from bot.handlers.user.main import show_profile, _delete_quietly
from bot.handlers.user.shop_and_goods import _show_categories_page, _show_orders_page, show_favorites
from bot.i18n import localize
from bot.keyboards.inline import language_keyboard
from bot.misc.metrics import get_metrics
from bot.states import ShopStates

router = Router()
router.message.filter(F.chat.type == ChatType.PRIVATE)


async def _open(message: Message, state: FSMContext) -> None:
    """Common start of every command: drop any flow in progress and the typed command (clean chat)."""
    await state.clear()
    try:
        await _delete_quietly(message)
    except Exception:           # cosmetic
        pass


@router.message(Command("catalog"))
async def catalog_command(message: Message, state: FSMContext):
    await _open(message, state)
    metrics = get_metrics()
    if metrics:
        metrics.track_conversion("purchase_funnel", "view_shop", message.from_user.id)
    await _show_categories_page(message, state, 0)
    await state.set_state(ShopStates.viewing_categories)


@router.message(Command("cart"))
async def cart_command(message: Message, state: FSMContext):
    await _open(message, state)
    await _show_cart(message)


@router.message(Command("orders"))
async def orders_command(message: Message, state: FSMContext):
    await _open(message, state)
    await _show_orders_page(message, message.from_user.id, 0)


@router.message(Command("favorites"))
async def favorites_command(message: Message, state: FSMContext):
    await _open(message, state)
    await show_favorites(message, message.from_user.id)


@router.message(Command("profile"))
async def profile_command(message: Message, state: FSMContext):
    await _open(message, state)
    await show_profile(message)


@router.message(Command("language"))
async def language_command(message: Message, state: FSMContext):
    await _open(message, state)
    await edit_screen(message, localize("language.picker.title"), reply_markup=language_keyboard(back_to="profile"))
