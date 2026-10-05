from aiogram.filters.state import StatesGroup, State


class GoodsFSM(StatesGroup):
    """FSM for the position (product) deletion scenario."""
    waiting_item_name_delete = State()


class AddItemFSM(StatesGroup):
    """
    FSM for step-by-step creation of a product:
    1) name,
    2) description,
    3) price,
    4) category,
    5) stock quantity (units on hand).
    """
    waiting_item_name = State()
    waiting_item_description = State()
    waiting_item_price = State()
    waiting_category = State()
    waiting_stock = State()


class StockFSM(StatesGroup):
    """
    FSM for the stock screen of a product:
    1) product name,
    2) the product card is open (set / add / remove buttons),
    3) the quantity for the chosen action.
    """
    waiting_item_name = State()
    card = State()
    waiting_quantity = State()


class UpdateItemFSM(StatesGroup):
    """
    FSM for editing a product's details (stock has its own screen):
    name → new name → description → price → category.
    """
    waiting_item_name_for_update = State()
    waiting_item_new_name = State()
    waiting_item_description = State()
    waiting_item_price = State()
    waiting_item_category = State()


class SaleFSM(StatesGroup):
    """
    FSM for setting or removing a time-limited sale on an item:
    1) item name,
    2) discount percent (0 removes the sale),
    3) duration in days.
    """
    waiting_item_name = State()
    waiting_percent = State()
    waiting_days = State()

