from aiogram.filters.state import StatesGroup, State


class TranslationFSM(StatesGroup):
    """
    FSM for the translations editor of a category or a product:
    1) the category name (products are opened from their stock card),
    2) the editor screen (what is set in every language),
    3) the text for the chosen language and field.
    The target (kind + canonical name) and the chosen language/field live in the FSM data.
    """
    waiting_category_name = State()
    card = State()
    waiting_text = State()
