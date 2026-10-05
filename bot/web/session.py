"""Who is signed in to the panel, re-checked against the database on every request."""
from starlette.requests import Request

from bot.database.methods.web_users import get_web_user
from bot.database.models.main import WebRole


async def current_web_user(request: Request) -> dict | None:
    """The signed-in account, or None.

    The session only carries ``uid`` and ``role``; the account must still exist, be active and have
    the same role, so disabling, demoting or deleting someone takes effect on their next request.
    """
    session = request.session
    uid = session.get("uid")
    if not isinstance(uid, int) or isinstance(uid, bool):
        return None
    cached = getattr(request.state, "web_user", None) if hasattr(request, "state") else None
    if isinstance(cached, dict) and cached.get("id") == uid:
        return cached
    user = await get_web_user(uid)
    if not user or not user["is_active"] or user["role"] != session.get("role"):
        return None
    try:
        request.state.web_user = user
    except Exception:
        pass
    return user


def session_is_admin(request: Request) -> bool:
    """Cheap, synchronous check for view access hooks (``authenticate`` has already verified the role)."""
    return request.session.get("role") == WebRole.ADMIN
