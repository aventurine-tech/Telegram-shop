"""Order helpers of the web panel: list filters, the printable packing slip and the tracking note form."""
import datetime
import os
from decimal import Decimal

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route

from bot.database.methods.audit import log_audit
from bot.database.methods.orders import get_order, set_tracking_note
from bot.database.models.main import Fulfillment, Orders, OrderStatus, PaymentMethod, PaymentStatus
from bot.i18n.main import current_language, localize
from bot.misc import EnvKeys
from bot.misc.localized import pick
from bot.misc.services.order_view import method_label, notify_customer
from bot.web.session import current_web_user

_TEMPLATES = os.path.join(os.path.dirname(__file__), "templates")
_env = Environment(loader=FileSystemLoader(_TEMPLATES), autoescape=select_autoescape(["html"]))
_env.globals["_"] = localize

_PARAMS = ("status", "method", "pay", "date_from", "date_to")


# --------------------------------------------------------------------------- #
# List filters
# --------------------------------------------------------------------------- #

def _day(value: str | None) -> datetime.datetime | None:
    try:
        return datetime.datetime.strptime(value or "", "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def filter_values(request: Request) -> dict:
    """The filters in the query string, each reduced to a known choice (anything else is ignored)."""
    q = request.query_params
    return {
        "status": q.get("status") if q.get("status") in OrderStatus.ALL else "",
        "method": q.get("method") if q.get("method") in PaymentMethod.CHOICES else "",
        "pay": q.get("pay") if q.get("pay") in (
            PaymentStatus.UNPAID, PaymentStatus.AWAITING_PAYMENT, PaymentStatus.AWAITING_CONFIRMATION,
            PaymentStatus.PAID, PaymentStatus.REFUNDED) else "",
        "date_from": q.get("date_from", "") if _day(q.get("date_from")) else "",
        "date_to": q.get("date_to", "") if _day(q.get("date_to")) else "",
    }


def filter_clauses(request: Request) -> list:
    """SQL conditions for the active filters. Dates are whole days in UTC, ``date_to`` included."""
    v = filter_values(request)
    clauses = []
    if v["status"]:
        clauses.append(Orders.status == v["status"])
    if v["method"]:
        clauses.append(Orders.payment_method == v["method"])
    if v["pay"]:
        clauses.append(Orders.payment_status == v["pay"])
    if v["date_from"]:
        clauses.append(Orders.created_at >= _day(v["date_from"]))
    if v["date_to"]:
        clauses.append(Orders.created_at < _day(v["date_to"]) + datetime.timedelta(days=1))
    return clauses


def filter_context(request: Request) -> dict:
    """What the filter bar template needs: the current values and the localized choices."""
    return {
        "values": filter_values(request),
        "statuses": [(s, localize(f"order.status.{s}")) for s in OrderStatus.ALL],
        "methods": [(m, localize(f"order.method.{m}" if m != PaymentMethod.COD else "web.filter.method_cod"))
                    for m in PaymentMethod.CHOICES],
        "payments": [(p, localize(f"order.paystatus.{p}")) for p in (
            PaymentStatus.UNPAID, PaymentStatus.AWAITING_PAYMENT, PaymentStatus.AWAITING_CONFIRMATION,
            PaymentStatus.PAID, PaymentStatus.REFUNDED)],
    }


# --------------------------------------------------------------------------- #
# Packing slip
# --------------------------------------------------------------------------- #

async def order_slip(request: Request):
    if await current_web_user(request) is None:
        return PlainTextResponse("Unauthorized", status_code=401)
    order = await get_order(int(request.path_params["order_id"]))
    if not order:
        return PlainTextResponse("Not found", status_code=404)
    cur = EnvKeys.PAY_CURRENCY
    fee = Decimal(str(order["delivery_fee"] or 0))
    total = Decimal(str(order["total"]))
    balance = Decimal(str(order["balance_used"] or 0))
    html = _env.get_template("order_slip.html").render(
        order=order, lang=current_language(), currency=cur,
        items=[{"name": pick(i, "name"), "qty": i["quantity"], "price": i["unit_price"], "total": i["line_total"]}
               for i in order["items"]],
        goods_total=total - fee, fee=fee, total=total, balance=balance, due=total - balance,
        shipping=pick(order, "shipping_name"),
        status=localize(f"order.status.{order['status']}"),
        method=method_label(order),
        pay_status=localize(f"order.paystatus.{order['payment_status']}"),
        fulfillment=localize(f"order.fulfillment.{order['fulfillment']}"),
        created=order["created_at"].strftime("%Y-%m-%d %H:%M") if order.get("created_at") else "",
        pickup=order["fulfillment"] == Fulfillment.PICKUP,
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


# --------------------------------------------------------------------------- #
# Tracking note
# --------------------------------------------------------------------------- #

async def order_tracking(request: Request):
    """Save the note from the order page; a shipped order's customer is told right away."""
    if request.method != "POST":
        return PlainTextResponse("Method not allowed", status_code=405)
    user = await current_web_user(request)
    if user is None:
        return PlainTextResponse("Unauthorized", status_code=401)
    order_id = int(request.path_params["order_id"])
    form = await request.form()
    ok, code, order = await set_tracking_note(order_id, str(form.get("tracking_note") or ""))
    back = f"/admin/orders/details/{order_id}"
    if not ok:
        return RedirectResponse(f"{back}?tracking_error={code}", status_code=303)
    if order["note_changed"]:
        await log_audit("sqladmin_order_tracking", resource_type="Order", resource_id=str(order_id),
                        details=f"by={user.get('username', '')}, cleared={not order['tracking_note']}")
        from bot.web import admin as panel          # the notifier bot lives there
        if panel._notifier_bot is not None and order["tracking_note"] and order["status"] in (
                OrderStatus.SHIPPED, OrderStatus.COMPLETED):
            await notify_customer(panel._notifier_bot, order, "tracking")
    return RedirectResponse(f"{back}?tracking_saved=1", status_code=303)


order_routes = [
    Route("/orders/{order_id:int}/slip", order_slip),
    Route("/orders/{order_id:int}/tracking", order_tracking, methods=["POST"]),
]
