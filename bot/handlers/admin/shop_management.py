import asyncio
from typing import Optional

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.types import FSInputFile

from pathlib import Path
import datetime

from bot.database.models import Permission
from bot.database.models.main import OrderStatus
from bot.database.methods import (
    select_today_users, get_user_count, select_today_orders,
    select_all_orders, select_today_operations, select_users_balance, select_all_operations,
    select_count_items, select_count_goods, select_count_categories, select_count_bought_items,
    query_all_users, check_user_cached
)
from bot.database.methods.lazy_queries import query_orders
from bot.database.methods.read import (
    get_roles_with_user_counts, select_unique_buyers, select_avg_order,
    select_today_orders_count, select_blocked_users_count, get_user_profile_aggregates,
)
from bot.keyboards import back, simple_buttons, lazy_paginated_keyboard
from bot.filters import HasPermissionFilter, HasAnyPermissionFilter
from bot.handlers.admin._common import user_profile_lines
from bot.handlers.other import display_name
from bot.database.methods.cache_utils import safe_create_task
from bot.misc import EnvKeys, LazyPaginator, StatsCache, get_cache_manager
from bot.i18n import localize

router = Router()

# Telegram's upload ceiling for send_document.
MAX_LOG_UPLOAD_BYTES = 50 * 1024 * 1024

# Initialize StatsCache as a global variable
stats_cache: Optional[StatsCache] = None


def init_stats_cache():
    """Initializing the statistics cache"""
    global stats_cache
    cache_manager = get_cache_manager()
    if cache_manager:
        stats_cache = StatsCache(cache_manager)
        safe_create_task(stats_cache.warm_up_cache())


@router.callback_query(F.data == "shop_management", HasAnyPermissionFilter(
    permissions=Permission.CATALOG_MANAGE | Permission.STATS_VIEW
))


async def shop_callback_handler(call: CallbackQuery):
    """
    Open shop-management main menu.
    Shows only items the caller has permissions for.
    """
    from bot.database.methods import check_role_cached
    role = await check_role_cached(call.from_user.id) or 0

    actions = []
    if role & Permission.STATS_VIEW:
        actions.append((localize("admin.shop.menu.statistics"), "statistics"))
        actions.append((localize("admin.shop.menu.logs"), "show_logs"))
    if role & Permission.USERS_MANAGE:
        actions.append((localize("admin.shop.menu.users"), "users_list"))
    actions.append((localize("btn.back"), "console"))

    markup = simple_buttons(actions, per_row=1)
    await call.message.edit_text(localize("admin.shop.menu.title"), reply_markup=markup)


@router.callback_query(F.data == "show_logs", HasPermissionFilter(Permission.STATS_VIEW))
async def logs_callback_handler(call: CallbackQuery):
    """
    Send bot logs (audit and bot) files if they exist and are not empty.
    """
    files_to_send = []
    oversized = []

    for log_type, raw_path in (('audit', EnvKeys.BOT_AUDITFILE), ('bot', EnvKeys.BOT_LOGFILE)):
        path = Path(raw_path)
        if not path.exists():
            continue
        size = path.stat().st_size
        if size == 0:
            continue
        # send_document rejects anything past Telegram's 50 MB limit; say so instead of letting the upload fail with an opaque API error.
        if size > MAX_LOG_UPLOAD_BYTES:
            oversized.append(path.name)
            continue
        files_to_send.append((log_type, path))

    if oversized:
        await call.answer(
            localize("admin.shop.logs.too_large", files=", ".join(oversized)),
            show_alert=True,
        )

    if files_to_send:
        for log_type, file_path in files_to_send:
            doc = FSInputFile(file_path, filename=file_path.name)
            caption = localize("admin.shop.logs.caption") if log_type == 'audit' else f"{log_type.title()} log file"
            await call.message.bot.send_document(
                chat_id=call.message.chat.id,
                document=doc,
                caption=caption,
            )
    else:
        await call.answer(localize("admin.shop.logs.empty"))


@router.callback_query(F.data == "statistics", HasPermissionFilter(Permission.STATS_VIEW))
async def statistics_callback_handler(call: CallbackQuery):
    """
    Show key shop statistics.
    """
    today_str = datetime.date.today().isoformat()

    if stats_cache:
        roles, daily, glob, dash = await asyncio.gather(
            get_roles_with_user_counts(),
            stats_cache.get_daily_stats(today_str),
            stats_cache.get_global_stats(),
            stats_cache.get_dashboard_stats(),
        )
        today_users, today_orders = daily['users'], daily['orders']
        today_topups, today_sold_count = daily['operations'], daily['orders_count']

        users, all_orders = glob['total_users'], glob['total_revenue']
        items, goods = glob['total_items'], glob['total_goods']

        unique_buyers, avg_order = dash['unique_buyers'], dash['avg_order']
        sold_count, blocked_count = dash['sold_count'], dash['blocked_users']
        new_orders = dash['new_orders']
        system_balance, all_topups = dash['users_balance'], dash['all_operations']
        categories = dash['categories']
    else:
        # Redis is off — no cache to populate, so fall back to individual reads.
        (
            roles,
            today_users, today_orders, today_topups, today_sold_count,
            users, all_orders, items, goods,
            unique_buyers, avg_order, sold_count, blocked_count,
            system_balance, all_topups, categories, new_orders,
        ) = await asyncio.gather(
            get_roles_with_user_counts(),
            select_today_users(today_str),
            select_today_orders(today_str),
            select_today_operations(today_str),
            select_today_orders_count(today_str),
            get_user_count(),
            select_all_orders(),
            select_count_items(),
            select_count_goods(),
            select_unique_buyers(),
            select_avg_order(),
            select_count_bought_items(),
            select_blocked_users_count(),
            select_users_balance(),
            select_all_operations(),
            select_count_categories(),
            query_orders(status=OrderStatus.NEW, count_only=True),
        )

    text = localize(
        "admin.shop.stats.template",
        today_users=today_users,
        users=users,
        buyers=unique_buyers,
        blocked=blocked_count,
        today_orders=today_orders,
        today_sold_count=today_sold_count,
        all_orders=all_orders,
        avg_order=f"{avg_order:.2f}",
        today_topups=today_topups,
        system_balance=system_balance,
        all_topups=all_topups,
        items=items,
        goods=goods,
        categories=categories,
        sold_count=sold_count,
        new_orders=new_orders,
        currency=EnvKeys.PAY_CURRENCY
    )

    # Append role breakdown
    if roles:
        text += "\n" + localize("admin.shop.stats.roles_header")
        for r in roles:
            perms_list = [label for bit, label in _PERM_LABELS.items() if r['permissions'] & bit]
            perms_str = ", ".join(perms_list) if perms_list else "—"
            text += f"\n◾<b>{r['name']}</b> ({perms_str}): {r['user_count']}"

    await call.message.edit_text(text, reply_markup=back("shop_management"), parse_mode="HTML")


_PERM_LABELS = {
    Permission.USE: "USE",
    Permission.BROADCAST: "BROADCAST",
    Permission.SETTINGS_MANAGE: "SETTINGS",
    Permission.USERS_MANAGE: "USERS",
    Permission.CATALOG_MANAGE: "CATALOG",
    Permission.ADMINS_MANAGE: "ADMINS",
    Permission.OWN: "OWNER",
    Permission.STATS_VIEW: "STATS",
    Permission.BALANCE_MANAGE: "BALANCE",
    Permission.PROMO_MANAGE: "PROMOS",
    Permission.ORDERS_MANAGE: "ORDERS",
}


async def _show_users_page(call: CallbackQuery, state: FSMContext, page: int):
    """Render one page of the all-users list (shared by the view and paginate handlers)."""
    paginator = LazyPaginator(query_all_users, per_page=10)

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda user_id: str(user_id),
        item_callback=lambda user_id: f"show-user_user-{user_id}",
        page=page,
        back_cb="shop_management",
        nav_cb_prefix="users-page_",
    )

    await call.message.edit_text(localize("admin.shop.users.title"), reply_markup=markup)


@router.callback_query(F.data == "users_list", HasPermissionFilter(Permission.USERS_MANAGE))
async def users_callback_handler(call: CallbackQuery, state: FSMContext):
    """Show list of all users with lazy loading pagination."""
    await _show_users_page(call, state, 0)


@router.callback_query(F.data.startswith("users-page_"), HasPermissionFilter(Permission.USERS_MANAGE))
async def navigate_users(call: CallbackQuery, state: FSMContext):
    """Pagination for users list with lazy loading."""
    try:
        page = int(call.data.split("_")[1])
    except Exception:
        page = 0
    await _show_users_page(call, state, page)


@router.callback_query(F.data.startswith("show-user_"), HasPermissionFilter(permission=Permission.USERS_MANAGE))
async def show_user_info(call: CallbackQuery):
    """
    Show detailed info for selected user.
    Callback data format: show-user_user-{user_id}
    """
    try:
        user_id = int(call.data[len("show-user_"):].split("-", 1)[1])
    except (ValueError, IndexError):
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return

    user = await check_user_cached(user_id)
    if not user:
        await call.answer(localize("admin.users.not_found"), show_alert=True)
        return

    first_name, agg = await asyncio.gather(
        display_name(call.message.bot, user_id),
        get_user_profile_aggregates(user_id, user.get('role_id')),
    )

    text = '\n'.join(user_profile_lines(
        user, first_name, user_id,
        overall_balance=agg['operations_total'], orders_count=agg['items_count'],
        role=agg['role_name'], referrals=agg['referrals'], include_referral_id=True,
    )) + '\n'

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=back("users_list"))
