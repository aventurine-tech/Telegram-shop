from aiogram.filters.state import StatesGroup, State


class OrdersAdminFSM(StatesGroup):
    """FSM for the orders console: look an order up by its number."""
    waiting_order_id = State()
