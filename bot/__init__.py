# TEMPORARY (physical-goods migration): lazy so that sub-packages import independently.
def __getattr__(name):
    if name == "start_bot":
        from .main import start_bot
        return start_bot
    raise AttributeError(name)
