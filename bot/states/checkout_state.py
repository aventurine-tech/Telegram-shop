from aiogram.filters.state import StatesGroup, State


class CheckoutFSM(StatesGroup):
    """FSM states for placing an order and for sending an MIA payment screenshot."""
    choosing_fulfillment = State()
    waiting_name = State()
    waiting_phone = State()
    waiting_address = State()
    waiting_comment = State()
    choosing_payment = State()
    confirming = State()
    waiting_proof = State()
