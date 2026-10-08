from decimal import Decimal
from typing import Callable, Iterable, Sequence, Tuple
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.i18n import localize, LANGUAGES
from bot.database.models import Permission
from bot.misc.localized import pick
from bot.misc import LazyPaginator, EnvKeys # noqa: F401


MENU_CATEGORY_LIMIT = 6     # category buttons on the main menu; more than this adds "All categories"


def main_menu(role: int, channel: str | None = None, helper: str | None = None,
              categories: Sequence[Tuple[int, str]] | None = None) -> InlineKeyboardMarkup:
    """
    Main menu.

    `categories` are the top-level categories as ``(id, display label)`` in the viewer's order. They
    replace the Shop button, one per row (``mcat:<id>``); past MENU_CATEGORY_LIMIT an
    "All categories" button opens the full list. Without categories the plain Shop button stays.
    """
    kb = InlineKeyboardBuilder()
    shown = list(categories or ())[:MENU_CATEGORY_LIMIT]
    for cat_id, label in shown:
        kb.button(text=label, callback_data=f"mcat:{cat_id}")
    full_rows = len(shown)
    if shown:
        if len(categories) > MENU_CATEGORY_LIMIT:
            kb.button(text=localize("btn.all_categories"), callback_data="shop")
            full_rows += 1
    else:
        kb.button(text=localize("btn.shop"), callback_data="shop")
    kb.button(text=localize("btn.rules"), callback_data="rules")
    kb.button(text=localize("btn.profile"), callback_data="profile")
    if helper:
        kb.button(text=localize("btn.support"), url=f"tg://user?id={helper}")
    if channel:
        kb.button(text=localize("btn.channel"), url=f"https://t.me/{channel.lstrip('@')}")
    if Permission.has_any_admin_perm(role):
        kb.button(text=localize("btn.admin_menu"), callback_data="console")
    kb.adjust(*([1] * full_rows), 2)
    return kb.as_markup()


def profile_keyboard(referral_percent: int, user_orders: int = 0, cart_count: int = 0,
                     mailings_on: bool | None = None) -> InlineKeyboardMarkup:
    """
    Profile keyboard: orders, cart, favorites, my details, promo code, mailings on/off, language.
    """
    kb = InlineKeyboardBuilder()
    if referral_percent != 0:
        kb.button(text=localize("btn.referral"), callback_data="referral_system")
    if user_orders != 0:
        kb.button(text=localize("btn.my_orders"), callback_data="my_orders")
    cart_text = localize("btn.cart", count=cart_count) if cart_count > 0 else localize("btn.cart_empty")
    kb.button(text=cart_text, callback_data="cart")
    kb.button(text=localize("btn.favorites"), callback_data="favorites")
    kb.button(text=localize("btn.my_details"), callback_data="my_details")
    kb.button(text=localize("btn.redeem_promo"), callback_data="redeem_promo")
    if mailings_on is not None:
        kb.button(text=localize("btn.mailings_on" if mailings_on else "btn.mailings_off"), callback_data="mailing_toggle")
    kb.button(text=localize("btn.language"), callback_data="profile_language")
    kb.button(text=localize("btn.back"), callback_data="back_to_menu")
    kb.adjust(1)
    return kb.as_markup()


def language_keyboard(payload: str | None = None, back_to: str | None = None) -> InlineKeyboardMarkup:
    """Language picker: one button per language, ``lang:<code>[:<payload>]``.

    `payload` is the /start referral id, carried so the choice does not lose it (callback data is
    capped at 64 bytes, so anything that is not a short number is dropped). `back_to` adds a back button.
    """
    kb = InlineKeyboardBuilder()
    suffix = f":{payload}" if payload and payload.isdigit() and len(payload) <= 20 else ""
    for code, label in LANGUAGES:
        kb.button(text=label, callback_data=f"lang:{code}{suffix}")
    if back_to:
        kb.button(text=localize("btn.back"), callback_data=back_to)
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


def restock_keyboard(item_id: int | None) -> InlineKeyboardMarkup:
    """Under a "back in stock" notice: open the product, or close the notice."""
    buttons = [(localize("btn.restock_open"), f"restock_open:{item_id}")] if item_id else []
    buttons.append((localize("btn.close"), "close"))
    return simple_buttons(buttons)


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
        reviews_enabled: bool = True,
        out_of_stock: bool = False, subscribed: bool = False,
        options: list[tuple[int, str, bool]] | None = None, gateway: bool = False,
        is_favorite: bool = False,
) -> InlineKeyboardMarkup:
    """
    Product card: add to cart, favorites, reviews, back.

    When `out_of_stock`, offers a restock notification toggle instead of the cart button, so the user is
    not left at a dead end. Promo codes are applied in the cart, not here.

    `options` — (goods_id, label, is_current) weight options, shown as a selector row on top
    (``opt:{goods_id}``). `gateway` — a head product with options: only the selector, favorites, reviews and
    Back are offered, never anything to buy. `is_favorite` — the product is starred (the button removes it).
    """
    rows: list[list[InlineKeyboardButton]] = []
    if options:
        buttons = [
            InlineKeyboardButton(text=f"✅ {label}" if current else label, callback_data=f"opt:{goods_id}")
            for goods_id, label, current in options
        ]
        rows += [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    if gateway:
        out_of_stock = False
    elif not out_of_stock:
        rows.append([InlineKeyboardButton(text=localize("btn.add_to_cart"), callback_data="add_to_cart")])
    rows.append([InlineKeyboardButton(
        text=localize("btn.favorite_remove" if is_favorite else "btn.favorite_add"), callback_data="fav_toggle")])
    review_row = []
    if reviews_enabled:
        if review_count > 0:
            review_row.append(InlineKeyboardButton(
                text=localize("btn.view_reviews", count=review_count), callback_data="reviews:0"))
        if has_purchased:
            review_row.append(InlineKeyboardButton(text=localize("btn.leave_review"), callback_data="review"))
    if review_row:
        rows.append(review_row)
    if out_of_stock:
        rows.append([InlineKeyboardButton(
            text=localize("btn.notify_stock_off" if subscribed else "btn.notify_stock"),
            callback_data="unsub_stock" if subscribed else "sub_stock")])
    rows.append([InlineKeyboardButton(text=localize("btn.back"), callback_data=back_data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def favorites_keyboard(items: list[dict], page: int, total: int, page_size: int) -> InlineKeyboardMarkup:
    """The favorites list: one button per product (opens its card), paging, back to the profile."""
    kb = InlineKeyboardBuilder()
    for item in items:
        kb.row(InlineKeyboardButton(text=f"⭐ {pick(item, 'name')}", callback_data=f"fav_open:{item['id']}"))
    pages = max(1, -(-total // page_size))
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"fav_page:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="dummy_button"))
        if page + 1 < pages:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"fav_page:{page + 1}"))
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text=localize("btn.back"), callback_data="profile"))
    return kb.as_markup()


def my_details_keyboard(profile: dict) -> InlineKeyboardMarkup:
    """One edit button per detail (name, phone, city, address), then Back to the profile."""
    kb = InlineKeyboardBuilder()
    for short in ("name", "phone", "city", "address"):
        kb.row(InlineKeyboardButton(text=f"✏️ {localize(f'details.label_{short}')}", callback_data=f"mydet_edit:{short}"))
    kb.row(InlineKeyboardButton(text=localize("btn.back"), callback_data="profile"))
    return kb.as_markup()


def details_edit_keyboard(short: str, can_clear: bool) -> InlineKeyboardMarkup:
    """The prompt for one detail: Clear (when it has a value) and Back to My details."""
    kb = InlineKeyboardBuilder()
    if can_clear:
        kb.row(InlineKeyboardButton(text=localize("btn.details_clear"), callback_data=f"mydet_clear:{short}"))
    kb.row(InlineKeyboardButton(text=localize("btn.back"), callback_data="my_details"))
    return kb.as_markup()


def cart_keyboard(items: list[dict]) -> InlineKeyboardMarkup:
    """
    Cart view: a quantity stepper, an optional promo-drop button and a remove button per line, then
    Checkout, Apply promo code, Clear cart and Back.
    """
    kb = InlineKeyboardBuilder()
    for item in items:
        kb.row(
            InlineKeyboardButton(text="➖", callback_data=f"cart_qty:{item['id']}:-1"),
            InlineKeyboardButton(
                text=f"{pick(item, 'name')} ×{item['quantity']}",
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
            text=localize("btn.cart_remove_item", name=pick(item, 'name')),
            callback_data=f"cart_remove:{item['id']}",
        ))
    kb.row(InlineKeyboardButton(text=localize("btn.cart_checkout"), callback_data="cart_checkout"))
    kb.row(InlineKeyboardButton(text=localize("btn.cart_promo"), callback_data="cart_promo"))
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


def checkout_shipping_keyboard(methods: list[dict], goods_total, currency: str) -> InlineKeyboardMarkup:
    """The shop's delivery methods with their price for this cart (free above a method's threshold)."""
    from bot.database.methods.shipping import delivery_fee
    from bot.misc.localized import pick
    kb = InlineKeyboardBuilder()
    for m in methods:
        fee = delivery_fee(m, goods_total)
        name = pick(m, "name")
        text = (localize("btn.checkout.ship", name=name, fee=fee, currency=currency) if fee > 0
                else localize("btn.checkout.ship_free", name=name))
        kb.button(text=text, callback_data=f"co_ship:{m['id']}")
    kb.button(text=localize("btn.checkout.cancel"), callback_data="co_cancel")
    kb.adjust(1)
    return kb.as_markup()


def checkout_name_keyboard(first_name: str | None, saved_name: str | None = None) -> InlineKeyboardMarkup:
    """Offer the saved name (My details) and the Telegram first name as the order name, plus a way out."""
    kb = InlineKeyboardBuilder()
    if saved_name:
        kb.button(text=localize("btn.checkout.use_saved_name", name=saved_name[:40]), callback_data="co_name_saved")
    if first_name and first_name != saved_name:
        kb.button(text=localize("btn.checkout.use_name", name=first_name), callback_data="co_name_tg")
    kb.button(text=localize("btn.back"), callback_data="co_cancel")
    kb.adjust(1)
    return kb.as_markup()


def checkout_address_keyboard(saved_address: str | None = None) -> InlineKeyboardMarkup:
    """The address step: the saved "city, address" as one tap (when there is one) and a way back to the cart."""
    kb = InlineKeyboardBuilder()
    if saved_address:
        shown = saved_address if len(saved_address) <= 40 else saved_address[:39] + "…"
        kb.button(text=localize("btn.checkout.use_saved_address", address=shown), callback_data="co_addr_saved")
    kb.button(text=localize("btn.checkout.cancel"), callback_data="co_cancel")
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
    """The customer's order card: payment actions while an MIA transfer is due, cancel while allowed, order again once it is over."""
    kb = InlineKeyboardBuilder()
    if order["payment_method"] == "mia" and order["status"] == "new" and order["payment_status"] == "awaiting_payment":
        kb.button(text=localize("btn.mia.details"), callback_data=f"mia_info:{order['id']}")
        kb.button(text=localize("btn.mia.paid"), callback_data=f"mia_paid:{order['id']}")
    if order["status"] == "new" and order["payment_status"] in ("unpaid", "awaiting_payment"):
        kb.button(text=localize("btn.order.cancel"), callback_data=f"my_order_cancel:{order['id']}")
    if order["status"] in ("completed", "cancelled"):
        kb.button(text=localize("btn.order.repeat"), callback_data=f"my_order_repeat:{order['id']}")
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
