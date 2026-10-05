from aiogram.filters.state import StatesGroup, State


class CategoryFSM(StatesGroup):
    """
    FSM states for category management:
    - add (name, then the name in the other two languages, then the optional parent category),
    - delete,
    - rename.
    """
    waiting_add_category = State()
    waiting_delete_category = State()
    waiting_update_category = State()
    waiting_update_category_name = State()
    waiting_add_category_translation = State()
    waiting_add_category_parent = State()
