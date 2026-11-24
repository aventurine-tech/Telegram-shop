from aiogram import Dispatcher

from bot.handlers.admin import router as admin_router
from bot.handlers.other import router as other_router
from bot.handlers.user import router as user_router
from bot.handlers.user.language import router as language_router
from bot.handlers.user.age_gate import router as age_gate_router
from bot.handlers.user.bottom_nav import router as bottom_nav_router
from bot.handlers.user.commands import router as commands_router
from bot.handlers.user.legal import router as legal_router


def register_all_handlers(dp: Dispatcher) -> None:
    # First: whoever has not chosen a language gets the picker before any other handler (admin FSM included).
    dp.include_router(language_router)
    # Second: whoever has not confirmed they are 18 or over gets that question before the menu and the catalog (D-27).
    dp.include_router(age_gate_router)
    # The ☰ menu commands (private chats): they win over any free-text state, like the bottom keyboard.
    dp.include_router(commands_router)
    # /help, /settings, /support, /terms, /privacy and "my data": same place, so /terms works in the middle of a checkout.
    dp.include_router(legal_router)
    # Then the bottom keyboard, so a tap wins over any free-text FSM state (checkout, admin wizards).
    dp.include_router(bottom_nav_router)
    dp.include_router(admin_router)
    dp.include_router(other_router)
    dp.include_router(user_router)
