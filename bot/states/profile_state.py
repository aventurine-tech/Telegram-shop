from aiogram.fsm.state import StatesGroup, State


class ProfileFSM(StatesGroup):
    """Editing one of the customer's own details; the field name is kept in the FSM data (``pd_field``)."""
    editing = State()
