"""Web panel. Names are imported lazily: bot.database.methods imports bot.web.passwords, and loading the
panel (which needs the database methods) at that moment would be a circular import."""


def __getattr__(name):
    if name == "create_admin_app":
        from bot.web.admin import create_admin_app
        return create_admin_app
    if name == "export_routes":
        from bot.web.export import export_routes
        return export_routes
    raise AttributeError(f"module 'bot.web' has no attribute {name!r}")
