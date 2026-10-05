from aiogram import Dispatcher

from bot.handlers.admin import router as admin_router
from bot.handlers.other import router as other_router
from bot.handlers.user import router as user_router
from bot.handlers.user.language import router as language_router
from bot.handlers.user.bottom_nav import router as bottom_nav_router


def register_all_handlers(dp: Dispatcher) -> None:
    # First: whoever has not chosen a language gets the picker before any other handler (admin FSM included).
    dp.include_router(language_router)
    # Then the bottom keyboard, so a tap wins over any free-text FSM state (checkout, admin wizards).
    dp.include_router(bottom_nav_router)
    dp.include_router(admin_router)
    dp.include_router(other_router)
    dp.include_router(user_router)
