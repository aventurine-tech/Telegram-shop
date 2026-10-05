# TEMPORARY (physical-goods migration): lazy so that sub-packages import independently.
def __getattr__(name):
    if name in ("register_all_handlers", "main_router"):
        from . import main as _main
        return _main.register_all_handlers if name == "register_all_handlers" else _main.router
    raise AttributeError(name)
