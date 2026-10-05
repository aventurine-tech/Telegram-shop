from decimal import Decimal
from typing import Callable, Iterable, Tuple
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.i18n import localize
from bot.database.models import Permission
from bot.misc import LazyPaginator, EnvKeys # noqa: F401


def main_menu(role: int, channel: str | None = None, helper: str | None = None) -> InlineKeyboardMarkup:
    """
    Main menu.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text=localize("btn.shop"), callback_data="shop")
    kb.button(text=localize("btn.rules"), callback_data="rules")
    kb.button(text=localize("btn.profile"), callback_data="profile")
    if helper:
        kb.button(text=localize("btn.support"), url=f"tg://user?id={helper}")
    if channel:
        kb.button(text=localize("btn.channel"), url=f"https://t.me/{channel.lstrip('@')}")
    if Permission.has_any_admin_perm(role):
        kb.button(text=localize("btn.admin_menu"), callback_data="console")
    kb.adjust(2)
    return kb.as_markup()


def profile_keyboard(referral_percent: int, user_orders: int = 0, cart_count: int = 0) -> InlineKeyboardMarkup:
    """
    Profile keyboard with orders, cart, history, promo codes.
    """
    kb = InlineKeyboardBuilder()
    if referral_percent != 0:
        kb.button(text=localize("btn.referral"), callback_data="referral_system")
    if user_orders != 0:
        kb.button(text=localize("btn.my_orders"), callback_data="my_orders")
    cart_text = localize("btn.cart", count=cart_count) if cart_count > 0 else localize("btn.cart_empty")
    kb.button(text=cart_text, callback_data="cart")
    kb.button(text=localize("btn.operation_history"), callback_data="operation_history")
    kb.button(text=localize("btn.redeem_promo"), callback_data="redeem_promo")
    kb.button(text=localize("btn.back"), callback_data="back_to_menu")
    kb.adjust(1)
    return kb.as_markup()


def admin_console_keyboard(maintenance_mode: bool = False, role: int = 127,
                           new_orders: int = 0) -> InlineKeyboardMarkup:
    """
    Admin panel — shows only buttons the user has permissions for.
    `new_orders` is the number of orders waiting for a decision, shown as a badge on "Orders".
    """
    kb = InlineKeyboardBuilder()
    if role & Permission.ORDERS_MANAGE:
        orders_text = localize("admin.menu.orders")
        kb.button(text=f"{orders_text} ({new_orders})" if new_orders else orders_text,
                  callback_data="orders_mgmt")
    if role & Permission.CATALOG_MANAGE:
        kb.button(text=localize("admin.menu.shop"), callback_data="shop_management")
        kb.button(text=localize("admin.menu.goods"), callback_data="goods_management")
        kb.button(text=localize("admin.menu.categories"), callback_data="categories_management")
    if role & Permission.PROMO_MANAGE:
        kb.button(text=localize("admin.menu.promo"), callback_data="promo_mgmt")
    if role & Permission.USERS_MANAGE:
        kb.button(text=localize("admin.menu.users"), callback_data="user_management")
    if role & Permission.ADMINS_MANAGE:
        kb.button(text=localize("admin.menu.roles"), callback_data="role_mgmt")
    if role & Permission.BROADCAST:
        kb.button(text=localize("admin.menu.broadcast"), callback_data="send_message")
    if role & Permission.SETTINGS_MANAGE:
        maintenance_key = "admin.menu.maintenance_on" if maintenance_mode else "admin.menu.maintenance_off"
        kb.button(text=localize(maintenance_key), callback_data="toggle_maintenance")
    kb.button(text=localize("btn.back"), callback_data="back_to_menu")
    kb.adjust(1)
    return kb.as_markup()


def simple_buttons(buttons: Iterable[Tuple[str, str]], per_row: int = 1) -> InlineKeyboardMarkup:
    """
    Universal button assembly from (text, callback_data)
    """
    kb = InlineKeyboardBuilder()
    for text, cb in buttons:
        kb.button(text=text, callback_data=cb)
    kb.adjust(per_row)
    return kb.as_markup()


def back(cb: str = "menu", text: str | None = None) -> InlineKeyboardMarkup:
    """
    One 'Back' button.
    """
    return simple_buttons([(text or localize("btn.back"), cb)])


def close() -> InlineKeyboardMarkup:
    """
    One button 'Close'.
    """
    return simple_buttons([(localize("btn.close"), "close")])


async def lazy_paginated_keyboard(
        paginator: 'LazyPaginator',
        item_text: Callable[[object], str],
        item_callback: Callable[[object], str],
        page: int = 0,
        back_cb: str | None = None,
        nav_cb_prefix: str = "",
        back_text: str | None = None,
        extra_rows: list[list[InlineKeyboardButton]] | None = None,
) -> InlineKeyboardMarkup:
    """
    Lazy pagination keyboard with data loading on demand.

    `extra_rows` are inserted between the item buttons and the navigation row.
    """
    kb = InlineKeyboardBuilder()

    # Get items for current page
    items = await paginator.get_page(page)

    for item in items:
        kb.button(text=item_text(item), callback_data=item_callback(item))
    kb.adjust(1)

    for row in (extra_rows or []):
        kb.row(*row)

    # Navigation
    total_pages = await paginator.get_total_pages()
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"{nav_cb_prefix}{page - 1}"))
        nav_buttons.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="dummy_button"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"{nav_cb_prefix}{page + 1}"))
        kb.row(*nav_buttons)

    if back_cb:
        kb.row(InlineKeyboardButton(text=back_text or localize("btn.back"), callback_data=back_cb))

    return kb.as_markup()


def item_info(
        back_data: str, avg_rating: float = None,
        review_count: int = 0, has_purchased: bool = False,
        applied_promo: str = None, reviews_enabled: bool = True,
        out_of_stock: bool = False, subscribed: bool = False,
) -> InlineKeyboardMarkup:
    """
    Product card with order, cart, promo, review buttons.

    When `out_of_stock`, offers a restock notification toggle instead of
    the order buttons, so the user is not left at a dead end.
    """
    kb = InlineKeyboardBuilder()
    if not out_of_stock:
        kb.button(text=localize("btn.buy"), callback_data="buy_item")
        kb.button(text=localize("btn.add_to_cart"), callback_data="add_to_cart")
    if applied_promo:
        kb.button(text=localize("btn.remove_promo"), callback_data="remove_promo")
    else:
        kb.button(text=localize("btn.apply_promo"), callback_data="apply_promo")
    if reviews_enabled:
        if review_count > 0:
            kb.button(text=localize("btn.view_reviews", count=review_count), callback_data="reviews:0")
        if has_purchased:
            kb.button(text=localize("btn.leave_review"), callback_data="review")
    if out_of_stock:
        if subscribed:
            kb.button(text=localize("btn.notify_stock_off"), callback_data="unsub_stock")
        else:
            kb.button(text=localize("btn.notify_stock"), callback_data="sub_stock")
    kb.button(text=localize("btn.back"), callback_data=back_data)
    kb.adjust(2)
    return kb.as_markup()


def cart_keyboard(items: list[dict]) -> InlineKeyboardMarkup:
    """
    Cart view: a quantity stepper, an optional promo-drop button, and a remove
    button per line.
    """
    kb = InlineKeyboardBuilder()
    for item in items:
        kb.row(
            InlineKeyboardButton(text="➖", callback_data=f"cart_qty:{item['id']}:-1"),
            InlineKeyboardButton(
                text=f"{item['item_name']} ×{item['quantity']}",
                callback_data="dummy_button",
            ),
            InlineKeyboardButton(text="➕", callback_data=f"cart_qty:{item['id']}:1"),
        )
        if item.get('promo_code'):
            kb.row(InlineKeyboardButton(
                text=localize("btn.cart_remove_promo", code=item['promo_code']),
                callback_data=f"cart_unpromo:{item['id']}",
            ))
        kb.row(InlineKeyboardButton(
            text=localize("btn.cart_remove_item", name=item['item_name']),
            callback_data=f"cart_remove:{item['id']}",
        ))
    kb.row(InlineKeyboardButton(text=localize("btn.cart_checkout"), callback_data="cart_checkout"))
    kb.row(InlineKeyboardButton(text=localize("btn.cart_clear"), callback_data="cart_clear"))
    kb.row(InlineKeyboardButton(text=localize("btn.back"), callback_data="profile"))
    return kb.as_markup()


def checkout_fulfillment_keyboard(kinds: Iterable[str]) -> InlineKeyboardMarkup:
    """Delivery / pickup choice, limited to what the shop offers."""
    kb = InlineKeyboardBuilder()
    for kind in kinds:
        kb.button(text=localize(f"btn.checkout.{kind}"), callback_data=f"co_ful:{kind}")
    kb.button(text=localize("btn.back"), callback_data="co_cancel")
    kb.adjust(1)
    return kb.as_markup()


def checkout_name_keyboard(first_name: str | None) -> InlineKeyboardMarkup:
    """Offer the Telegram first name as the order name, plus a way out."""
    kb = InlineKeyboardBuilder()
    if first_name:
        kb.button(text=localize("btn.checkout.use_name", name=first_name), callback_data="co_name_tg")
    kb.button(text=localize("btn.back"), callback_data="co_cancel")
    kb.adjust(1)
    return kb.as_markup()


def checkout_cancel_keyboard() -> InlineKeyboardMarkup:
    """Just a way back to the cart, for steps that wait for typed text."""
    return simple_buttons([(localize("btn.checkout.cancel"), "co_cancel")])


def checkout_comment_keyboard() -> InlineKeyboardMarkup:
    return simple_buttons([
        (localize("btn.checkout.skip"), "co_skip_comment"),
        (localize("btn.checkout.cancel"), "co_cancel"),
    ])


def checkout_payment_keyboard(
        methods: Iterable[str], fulfillment: str | None, balance: Decimal | None = None,
        use_balance: bool = False, covered: bool = False,
) -> InlineKeyboardMarkup:
    """Payment methods, the "use balance" toggle (only with a balance), or "continue" when the balance covers it all."""
    kb = InlineKeyboardBuilder()
    if covered:
        kb.button(text=localize("btn.checkout.pay_balance"), callback_data="co_pay:balance")
    for method in methods:
        if method == "cod":
            key = "btn.checkout.pay_cod_pickup" if fulfillment == "pickup" else "btn.checkout.pay_cod_delivery"
        else:
            key = f"btn.checkout.pay_{method}"
        kb.button(text=localize(key), callback_data=f"co_pay:{method}")
    if balance is not None and balance > 0:
        kb.button(
            text=localize(
                "btn.checkout.balance_on" if use_balance else "btn.checkout.balance_off",
                balance=balance, currency=EnvKeys.PAY_CURRENCY,
            ),
            callback_data="co_balance",
        )
    kb.button(text=localize("btn.checkout.cancel"), callback_data="co_cancel")
    kb.adjust(1)
    return kb.as_markup()


def checkout_confirm_keyboard() -> InlineKeyboardMarkup:
    return simple_buttons([
        (localize("btn.checkout.confirm"), "co_confirm"),
        (localize("btn.checkout.change_payment"), "co_to_payment"),
        (localize("btn.checkout.cancel"), "co_cancel"),
    ])


def mia_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Under the MIA payment details: claim the payment, or go look at the order."""
    return simple_buttons([
        (localize("btn.mia.paid"), f"mia_paid:{order_id}"),
        (localize("btn.order.open"), f"my_order:{order_id}"),
        (localize("btn.my_orders"), "my_orders"),
    ])


def order_keyboard(order: dict, back_cb: str = "my_orders") -> InlineKeyboardMarkup:
    """The customer's order card: payment actions while an MIA transfer is due, cancel while allowed."""
    kb = InlineKeyboardBuilder()
    if order["payment_method"] == "mia" and order["status"] == "new" and order["payment_status"] == "awaiting_payment":
        kb.button(text=localize("btn.mia.details"), callback_data=f"mia_info:{order['id']}")
        kb.button(text=localize("btn.mia.paid"), callback_data=f"mia_paid:{order['id']}")
    if order["status"] == "new" and order["payment_status"] in ("unpaid", "awaiting_payment"):
        kb.button(text=localize("btn.order.cancel"), callback_data=f"my_order_cancel:{order['id']}")
    kb.button(text=localize("btn.back"), callback_data=back_cb)
    kb.adjust(1)
    return kb.as_markup()


def question_buttons(question: str, back_data: str) -> InlineKeyboardMarkup:
    """
    Universal yes/no + Back.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text=localize("btn.yes"), callback_data=f"{question}_yes")
    kb.button(text=localize("btn.no"), callback_data=f"{question}_no")
    kb.button(text=localize("btn.back"), callback_data=back_data)
    kb.adjust(2)
    return kb.as_markup()


def check_sub(channel_username: str) -> InlineKeyboardMarkup:
    """
    checks the channel subscription.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text=localize("btn.channel"), url=f"https://t.me/{channel_username}")
    kb.button(text=localize("btn.check_subscription"), callback_data="sub_channel_done")
    kb.adjust(1)
    return kb.as_markup()


def rating_keyboard() -> InlineKeyboardMarkup:
    """Rating selection keyboard (1-5 stars)."""
    kb = InlineKeyboardBuilder()
    for i in range(1, 6):
        kb.button(text="⭐" * i, callback_data=f"rating:{i}")
    kb.button(text=localize("btn.back"), callback_data="back_to_menu")
    kb.adjust(5)
    return kb.as_markup()


def referral_system_keyboard(has_referrals: bool = False, has_earnings: bool = False) -> InlineKeyboardMarkup:
    """
    Referral system keyboard with additional buttons.
    """
    kb = InlineKeyboardBuilder()

    if has_referrals:
        kb.button(text=localize("btn.view_referrals"), callback_data="view_referrals")

    if has_earnings:
        kb.button(text=localize("btn.view_earnings"), callback_data="view_all_earnings")

    kb.button(text=localize("btn.back"), callback_data="profile")
    kb.adjust(1)
    return kb.as_markup()
