import csv
import io
from datetime import datetime, timezone

from starlette.requests import Request
from starlette.responses import StreamingResponse, JSONResponse
from starlette.routing import Route
from sqlalchemy import select

from bot.database.main import Database
from bot.database.models.main import User, Orders, OrderItems, Operations
from bot.web.session import current_web_user


BATCH_SIZE = 1000

# Leading characters that spreadsheet apps interpret as the start of a formula.
_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_cell(value) -> str:
    """Neutralize CSV/Excel formula injection by quoting risky leading chars."""
    if value is None:
        return ""
    s = str(value)
    if s and s[0] in _INJECTION_PREFIXES:
        return "'" + s
    return s


async def _stream_csv(query, columns, session_maker, keyset_column):
    """Generic CSV streamer using keyset pagination on ``keyset_column``.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(columns)
    yield output.getvalue()
    output.seek(0)
    output.truncate(0)

    last_key = None
    while True:
        batch_query = query
        if last_key is not None:
            batch_query = batch_query.where(keyset_column > last_key)
        batch_query = batch_query.limit(BATCH_SIZE)

        async with session_maker() as s:
            result = await s.execute(batch_query)
            rows = result.all()

        if not rows:
            break

        for row in rows:
            values = [getattr(row, c, row[i]) if hasattr(row, c) else row[i] for i, c in enumerate(columns)]
            writer.writerow([_sanitize_cell(v) for v in values])

        last_key = rows[-1][0]
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        if len(rows) < BATCH_SIZE:
            break


def _parse_date_params(request: Request):
    """Parse from/to date query params."""
    from_str = request.query_params.get("from")
    to_str = request.query_params.get("to")
    from_date = None
    to_date = None
    if from_str:
        try:
            from_date = datetime.strptime(from_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    if to_str:
        try:
            to_date = datetime.strptime(to_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return from_date, to_date


async def _check_auth(request: Request) -> bool:
    """Any signed-in, still-active account (Admin or Staff) may export."""
    return await current_web_user(request) is not None


async def export_users(request: Request):
    if not await _check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    from_date, to_date = _parse_date_params(request)
    query = select(
        User.telegram_id, User.first_name, User.last_name, User.username, User.contact_name, User.phone, User.city,
        User.address,
        User.language, User.balance, User.role_id, User.referral_id, User.registration_date, User.last_seen_at,
        User.is_blocked
    ).order_by(User.telegram_id)

    if from_date:
        query = query.where(User.registration_date >= from_date)
    if to_date:
        query = query.where(User.registration_date < to_date)

    columns = ["telegram_id", "first_name", "last_name", "username", "contact_name", "phone", "city", "address", "language", "balance",
               "role_id", "referral_id", "registration_date", "last_seen_at", "is_blocked"]

    return StreamingResponse(
        _stream_csv(query, columns, Database().session, User.telegram_id),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"},
    )


async def export_orders(request: Request):
    if not await _check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    from_date, to_date = _parse_date_params(request)
    query = select(
        Orders.id, Orders.user_id, Orders.status, Orders.payment_method, Orders.payment_status,
        Orders.fulfillment, Orders.customer_name, Orders.phone, Orders.address,
        Orders.total, Orders.balance_used, Orders.created_at
    ).order_by(Orders.id)

    if from_date:
        query = query.where(Orders.created_at >= from_date)
    if to_date:
        query = query.where(Orders.created_at < to_date)

    columns = ["id", "user_id", "status", "payment_method", "payment_status", "fulfillment",
               "customer_name", "phone", "address", "total", "balance_used", "created_at"]

    return StreamingResponse(
        _stream_csv(query, columns, Database().session, Orders.id),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=orders.csv"},
    )


async def export_order_items(request: Request):
    if not await _check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    from_date, to_date = _parse_date_params(request)
    # The date window is the order's, so the lines of one order always travel together.
    query = select(
        OrderItems.id, OrderItems.order_id, OrderItems.item_name, OrderItems.quantity,
        OrderItems.unit_price, OrderItems.line_total
    ).join(Orders, Orders.id == OrderItems.order_id).order_by(OrderItems.id)

    if from_date:
        query = query.where(Orders.created_at >= from_date)
    if to_date:
        query = query.where(Orders.created_at < to_date)

    columns = ["id", "order_id", "item_name", "quantity", "unit_price", "line_total"]

    return StreamingResponse(
        _stream_csv(query, columns, Database().session, OrderItems.id),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=order_items.csv"},
    )


async def export_operations(request: Request):
    if not await _check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    from_date, to_date = _parse_date_params(request)
    query = select(
        Operations.id, Operations.user_id, Operations.operation_value,
        Operations.operation_time
    ).order_by(Operations.id)

    if from_date:
        query = query.where(Operations.operation_time >= from_date)
    if to_date:
        query = query.where(Operations.operation_time < to_date)

    columns = ["id", "user_id", "operation_value", "operation_time"]

    return StreamingResponse(
        _stream_csv(query, columns, Database().session, Operations.id),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=operations.csv"},
    )


export_routes = [
    Route("/export/users", export_users),
    Route("/export/orders", export_orders),
    Route("/export/order_items", export_order_items),
    Route("/export/operations", export_operations),
]
