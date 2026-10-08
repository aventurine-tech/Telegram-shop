"""Client helpers of the web panel: erase a customer's personal data (Admin accounts only)."""
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.routing import Route

from bot.database.methods.erasure import erase_client
from bot.web.session import current_web_user, session_is_admin


async def client_erase(request: Request):
    """POST /clients/{telegram_id}/erase — irreversible, so a POST from a form that asked first, never a link."""
    user = await current_web_user(request)
    if user is None:
        return PlainTextResponse("Unauthorized", status_code=401)
    if not session_is_admin(request):
        return PlainTextResponse("Forbidden", status_code=403)
    telegram_id = int(request.path_params["telegram_id"])
    ok, code, _counts = await erase_client(telegram_id, by=user.get("username"))
    back = f"/admin/user/details/{telegram_id}"
    return RedirectResponse(f"{back}?erased=1" if ok else f"{back}?erase_error={code}", status_code=303)


client_routes = [Route("/clients/{telegram_id:int}/erase", client_erase, methods=["POST"])]
