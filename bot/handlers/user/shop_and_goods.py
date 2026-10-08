import asyncio
import contextlib
from decimal import Decimal
from functools import partial

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from pydantic import ValidationError

from bot.database.methods import (
    query_categories, get_item_info_cached, select_item_stock_cached, effective_price
)
from bot.database.methods.read import (
    get_category_by_id, category_children_count, check_category_cached,
    get_item_avg_rating, has_purchased_item,
    get_user_review, invalidate_rating_cache, is_subscribed_to_stock,
    get_item_family, get_option_by_id, get_head_name,
)
from bot.database.methods.favorites import (
    PAGE_SIZE as FAVORITES_PAGE_SIZE, is_favorite, item_name_by_id, list_favorites, toggle_favorite,
)
from bot.database.methods.orders import get_order, cancel_order_transaction, reorder_to_cart
from bot.database.methods.create import create_review, subscribe_to_stock
from bot.database.methods.delete import unsubscribe_from_stock
from bot.database.methods.lazy_queries import (
    query_item_reviews, query_goods_search, query_items_in_category, query_user_orders,
    query_subcategories,
)
from bot.database.methods.transactions import redeem_balance_promo
from bot.database.methods.audit import log_audit_bg
from bot.database.methods.cache_utils import safe_create_task
from bot.database.methods.product_images import (
    get_item_image_ref, get_item_image_bytes, store_image_file_id,
)
from bot.keyboards import item_info, back, lazy_paginated_keyboard, order_keyboard
from bot.keyboards.inline import simple_buttons, rating_keyboard, favorites_keyboard
from aiogram.types import InlineKeyboardButton
from bot.i18n import localize, esc
from bot.database.methods.translations import category_labels, item_labels
from bot.misc.localized import pick
from bot.handlers.user._screen import edit_screen, is_photo_message
from bot.misc import EnvKeys, LazyPaginator, ReviewRequest
from bot.misc.metrics import get_metrics
from bot.misc.services.order_view import format_order
from bot.misc.services.restock_notifier import notify_restock
from bot.states import ShopStates
from bot.states.review_state import ReviewFSM
from bot.states.promo_state import PromoFSM

router = Router()

CAPTION_LIMIT = 1024    # Telegram's cap on a photo caption


def _browsing_state_for(back_data: str):
    """The FSM state the item card's Back button needs, or None if it needs none."""
    if back_data.startswith('gp_'):
        return ShopStates.viewing_goods
    if back_data.startswith('sp_'):
        return ShopStates.viewing_search_results
    return None


def _page_arg(raw: str) -> int | None:
    """Parse a page number out of callback_data. None if it is not a valid page."""
    try:
        page = int(raw)
    except (TypeError, ValueError):
        return None
    return page if page >= 0 else None


# --- Shared helper: render item page ---

async def _render_item_page(target, state: FSMContext, item_name: str, back_data: str = None,
                            user_id: int = None, replace: bool = False):
    """
    Render the item detail page with optional promo discount.
    `target` can be CallbackQuery or Message. With a picture the card is a photo message with the
    text as caption; `replace` forces a fresh message instead of editing the caption in place.
    """
    data = await state.get_data()
    if not back_data:
        back_data = data.get('item_back_data', 'gp_0')

    item_info_data = await get_item_info_cached(item_name)
    if not item_info_data:
        if isinstance(target, CallbackQuery):
            await target.answer(localize("shop.item.not_found"), show_alert=True)
        else:
            await target.answer(localize("shop.item.not_found"))
        return

    required_state = _browsing_state_for(back_data)
    if required_state is not None:
        await state.set_state(required_state)

    # Weight options: reviews and the fallback picture/description live on the head; a head that has
    # options is only a gateway to them (nothing to buy on its own card).
    family = await get_item_family(item_name)
    head = family["head"] if family else item_info_data
    family_options = family["options"] if family else []
    is_option = item_info_data.get("variant_of") is not None
    gateway = bool(family_options) and not is_option
    # A sold-out option is marked in the selector, so customers see which ones they can only wait for.
    selector = [(o["id"], o["variant_label"] if (o["stock"] or 0) > 0 else f"{o['variant_label']} ✕",
                 o["id"] == item_info_data["id"]) for o in family_options]
    review_name = head["name"]

    reviews_enabled = EnvKeys.REVIEWS_ENABLED == "1"

    reads = [select_item_stock_cached(item_name), is_favorite(user_id, item_name) if user_id else asyncio.sleep(0, False)]
    if reviews_enabled:
        reads.append(get_item_avg_rating(review_name))
        reads.append(query_item_reviews(review_name, count_only=True))
        if user_id:
            reads.append(has_purchased_item(user_id, review_name))
    results = await asyncio.gather(*reads)

    stock = results[0]
    favorite = bool(results[1])
    avg_rating = results[2] if reviews_enabled else None
    review_count_val = results[3] if reviews_enabled else 0
    purchased = results[4] if (reviews_enabled and user_id) else False

    out_of_stock = stock <= 0
    quantity_line = localize("shop.item.out_of_stock") if out_of_stock else localize("shop.item.in_stock", count=stock)
    subscribed = bool(
        out_of_stock and user_id and await is_subscribed_to_stock(user_id, item_name)
    )

    # Price line: the sale price (if any) is the base; promo codes are applied in the cart.
    sale_price, on_sale, original_price = effective_price(item_info_data)
    price = sale_price

    if on_sale:
        percent = (Decimal(str(item_info_data.get("sale_percent") or 0))).quantize(Decimal("1"))
        price_line = localize(
            "shop.item.price_sale",
            original=original_price, sale=sale_price,
            currency=EnvKeys.PAY_CURRENCY, percent=percent,
        )
    else:
        price_line = localize("shop.item.price", amount=price, currency=EnvKeys.PAY_CURRENCY)

    markup = item_info(
        back_data,
        avg_rating=avg_rating, review_count=review_count_val,
        has_purchased=purchased,
        reviews_enabled=reviews_enabled,
        out_of_stock=out_of_stock, subscribed=subscribed,
        options=selector, gateway=gateway, is_favorite=favorite,
    )

    # Shown in the viewer's language; every lookup below keeps using the canonical `item_name`.
    display_name = pick(item_info_data, "name")
    description = pick(item_info_data, "description")
    if not description.strip() and head is not item_info_data:
        description = pick(head, "description")     # an option without its own text shows the head's

    def build_text(desc: str) -> str:
        lines = [
            localize("shop.item.title", name=esc(display_name)),
            localize("shop.item.description", description=esc(desc)),
        ]
        if gateway:
            lines.append(localize("shop.item.choose_option"))
        else:
            lines += [price_line, quantity_line]
        if reviews_enabled and avg_rating is not None:
            lines.append(localize("review.avg_rating", rating=avg_rating, count=review_count_val))
        return "\n".join(lines)

    text = build_text(description)

    image_name = item_name
    image_ref = await get_item_image_ref(item_name)
    if image_ref is None and head is not item_info_data:
        image_name = head["name"]                   # an option without its own picture shows the head's
        image_ref = await get_item_image_ref(image_name)
    message = target.message if hasattr(target, 'message') else None
    on_photo = is_photo_message(message)

    if image_ref is not None:
        caption = _fit_caption(build_text, description)
        try:
            if on_photo and not replace:
                # Same card, same picture: only the caption and keyboard change.
                await message.edit_caption(caption=caption, reply_markup=markup)
                return
            sent = await _send_card_photo(message or target, image_name, image_ref, caption, markup)
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return
            raise
        if sent:
            if message is not None:
                with contextlib.suppress(TelegramAPIError):
                    await message.delete()
            return
        # The picture is gone: show the plain text card instead.

    try:
        if message is not None:
            await edit_screen(target, text, reply_markup=markup)
        else:
            await target.answer(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


def _fit_caption(build_text, description: str) -> str:
    """The card text, with the description trimmed (ellipsis) so it fits a photo caption."""
    text = build_text(description)
    if len(text) <= CAPTION_LIMIT:
        return text
    lo, hi = 0, len(description)
    while lo < hi:                                  # longest description prefix that still fits
        mid = (lo + hi + 1) // 2
        if len(build_text(description[:mid].rstrip() + "…")) <= CAPTION_LIMIT:
            lo = mid
        else:
            hi = mid - 1
    return build_text(description[:lo].rstrip() + "…")[:CAPTION_LIMIT]


async def _send_card_photo(target, item_name: str, ref: dict, caption: str, markup):
    """Send the item card as a photo. True on success, False if the picture is gone.

    A cached `file_id` is tried first; if Telegram refuses it, the stale id is cleared and the
    stored bytes are uploaded instead, and the new id is remembered.
    """
    file_id = ref.get("file_id")
    if file_id:
        try:
            await target.answer_photo(file_id, caption=caption, reply_markup=markup)
            return True
        except TelegramBadRequest:
            await store_image_file_id(item_name, None)

    data = await get_item_image_bytes(item_name)
    if not data:
        return False
    sent = await target.answer_photo(
        BufferedInputFile(data, filename="item.jpg"), caption=caption, reply_markup=markup,
    )
    photos = getattr(sent, 'photo', None)
    if isinstance(photos, list) and photos:
        await store_image_file_id(item_name, photos[-1].file_id)
    return True


# --- Shop / categories / items ---

async def _show_categories_page(call: CallbackQuery | Message, state: FSMContext, page: int):
    """Render one page of the category list (shared by the shop entry, paginate handlers and the bottom keyboard)."""
    paginator = LazyPaginator(query_categories, per_page=10)

    # Pre-fetch page items to build the index map used by the item_callback.
    page_items = await paginator.get_page(page)
    items_index = {cat: idx for idx, cat in enumerate(page_items)}
    labels = await category_labels(page_items)     # display text only; callbacks stay canonical

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda cat: labels.get(cat, cat),
        item_callback=lambda cat: f"cat:{items_index[cat]}:{page}",
        page=page,
        back_cb="back_to_menu",
        nav_cb_prefix="categories-page_",
        extra_rows=[[InlineKeyboardButton(
            text=localize("btn.search"), callback_data="shop_search",
        )]],
    )

    await edit_screen(call, localize("shop.categories.title"), reply_markup=markup)
    await state.update_data(
        category_page_items=list(page_items),
        category_page_num=page,
        current_parent=None,        # back at the top level: no parent, not opened from the menu
        shop_origin=None,
    )


@router.callback_query(F.data == "shop")
async def shop_callback_handler(call: CallbackQuery, state: FSMContext):
    """Show list of shop categories with lazy loading."""
    metrics = get_metrics()
    if metrics:
        metrics.track_conversion("purchase_funnel", "view_shop", call.from_user.id)

    await _show_categories_page(call, state, 0)
    await state.set_state(ShopStates.viewing_categories)


@router.callback_query(F.data.startswith('categories-page_'))
async def navigate_categories(call: CallbackQuery, state: FSMContext):
    """Pagination across shop categories with cache."""
    parts = call.data.split('_', 1)
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    await _show_categories_page(call, state, page)


async def _show_goods_page(call: CallbackQuery, state: FSMContext,
                           category_name: str, cat_page: int, page: int):
    """Render one page of goods inside a category (shared by category-open + paginate).

    `cat_page` is the page of the list Back returns to: the subcategory list when the category was
    opened through a parent (FSM `current_parent`), the main menu when it was opened from there
    (`shop_origin`), else the top-level list.
    """
    from bot.database.methods.lazy_queries import query_items_in_category

    data = await state.get_data()
    if data.get('current_parent'):
        back_cb = f"subcat-page_{cat_page}"
    elif data.get('shop_origin') == "menu":
        back_cb = "back_to_menu"
    else:
        back_cb = f"categories-page_{cat_page}"

    paginator = LazyPaginator(partial(query_items_in_category, category_name), per_page=10)

    page_items = await paginator.get_page(page)
    items_index = {item: i for i, item in enumerate(page_items)}
    labels = await item_labels(page_items)

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda item: labels.get(item, item),
        item_callback=lambda item: f"itm:{items_index[item]}:{page}",
        page=page,
        back_cb=back_cb,
        nav_cb_prefix="gp_",
    )

    await edit_screen(call, localize("shop.goods.choose"), reply_markup=markup)
    await state.update_data(
        current_category=category_name,
        goods_page_items=list(page_items),
        goods_page_num=page,
        categories_last_viewed_page=cat_page,
    )
    await state.set_state(ShopStates.viewing_goods)


async def _show_subcategories_page(call: CallbackQuery, state: FSMContext, parent_name: str, page: int):
    """Render one page of a category's subcategories (parent = FSM `current_parent`)."""
    data = await state.get_data()
    paginator = LazyPaginator(partial(query_subcategories, parent_name), per_page=10)

    page_items = await paginator.get_page(page)
    items_index = {cat: idx for idx, cat in enumerate(page_items)}
    labels = await category_labels(page_items + [parent_name])

    # Back leaves the drill-down: to the menu it was opened from, else to the top-level list.
    if data.get('shop_origin') == "menu":
        back_cb = "back_to_menu"
    else:
        back_cb = f"categories-page_{data.get('parent_cat_page', 0)}"

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda cat: labels.get(cat, cat),
        item_callback=lambda cat: f"subcat:{items_index[cat]}:{page}",
        page=page,
        back_cb=back_cb,
        nav_cb_prefix="subcat-page_",
    )

    title = localize("shop.subcategories.title", name=esc(labels.get(parent_name, parent_name)))
    await edit_screen(call, title, reply_markup=markup)
    await state.update_data(
        subcategory_page_items=list(page_items),
        subcategory_page_num=page,
        current_parent=parent_name,
    )
    await state.set_state(ShopStates.viewing_categories)


async def _open_category(call: CallbackQuery, state: FSMContext, category_name: str,
                         cat_page: int, origin: str | None = None):
    """Open a top-level category: its subcategory list if it has any, else its products.

    `origin` ("menu") is where Back should finally lead; `cat_page` the top-level list page it came from.
    """
    cat = await check_category_cached(category_name)
    if not cat:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return
    if await category_children_count(cat['id']):
        await state.update_data(shop_origin=origin, parent_cat_page=cat_page)
        await _show_subcategories_page(call, state, category_name, 0)
        return
    # A leaf: forget any earlier parent so Back does not return to a stale subcategory list.
    await state.update_data(current_parent=None, shop_origin=origin)
    await _show_goods_page(call, state, category_name, cat_page, 0)


@router.callback_query(F.data.startswith('cat:'))
async def items_list_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Show items (or subcategories) of selected category.
    Parse index and page from cat:{index}:{page}, look up category name from state.
    """
    try:
        parts = call.data.split(':')
        idx = int(parts[1])
        cat_page = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    category = await _page_item_from_state(state, 'category_page_items', 'category_page_num', cat_page, idx)
    if category is None:
        category = await _page_item_at(query_categories, cat_page, idx)
    if category is None:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    await _open_category(call, state, category, cat_page)


@router.callback_query(F.data.startswith('mcat:'))
async def menu_category_handler(call: CallbackQuery, state: FSMContext):
    """A category button of the main menu (mcat:{category_id}); Back returns to the menu."""
    try:
        cat_id = int(call.data.split(':', 1)[1])
    except (ValueError, IndexError):
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return
    cat = await get_category_by_id(cat_id)
    if not cat or cat.get('parent_id') is not None:     # gone since the menu was drawn
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return
    metrics = get_metrics()
    if metrics:
        metrics.track_conversion("purchase_funnel", "view_shop", call.from_user.id)
    await _open_category(call, state, cat['name'], 0, origin="menu")


@router.callback_query(F.data.startswith('subcat-page_'))
async def navigate_subcategories(call: CallbackQuery, state: FSMContext):
    """Pagination across a parent's subcategories (also where Back from its products lands)."""
    page = _page_arg(call.data.split('_', 1)[1])
    parent = (await state.get_data()).get('current_parent')
    if page is None or not parent:
        # State is gone (restart / stale keyboard): the top-level list is the safe place.
        await _show_categories_page(call, state, 0)
        return
    await _show_subcategories_page(call, state, parent, page)


@router.callback_query(F.data.startswith('subcat:'))
async def subcategory_callback_handler(call: CallbackQuery, state: FSMContext):
    """Show the products of a subcategory. Format: subcat:{index}:{page}"""
    try:
        parts = call.data.split(':')
        idx = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return
    parent = (await state.get_data()).get('current_parent')
    if not parent:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    sub = await _page_item_from_state(state, 'subcategory_page_items', 'subcategory_page_num', page, idx)
    if sub is None:
        sub = await _page_item_at(partial(query_subcategories, parent), page, idx)
    if sub is None:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return
    await _show_goods_page(call, state, sub, page, 0)


@router.callback_query(F.data.startswith('gp_'), ShopStates.viewing_goods)
async def navigate_goods(call: CallbackQuery, state: FSMContext):
    """
    Pagination for items inside selected category.
    Format: gp_{page}
    """
    page = _page_arg(call.data[3:])
    if page is None:
        await call.answer(localize("errors.pagination_invalid"), show_alert=True)
        return
    data = await state.get_data()
    await _show_goods_page(
        call, state,
        data.get('current_category', ''),
        data.get('categories_last_viewed_page', 0),
        page,
    )


async def _page_item_at(query_func, page: int, idx: int):
    """Return the item at ``idx`` on ``page`` of ``query_func``, or None."""
    paginator = LazyPaginator(query_func, per_page=10)
    page_items = await paginator.get_page(page)
    if idx < 0 or idx >= len(page_items):
        return None
    return page_items[idx]


async def _page_item_from_state(state: FSMContext, list_key: str, page_key: str,
                                page: int, idx: int):
    """Resolve idx->name from the page list saved by the last render.

    Avoids re-running the list query the user just saw. Returns None when the
    state doesn't cover this page (restart, stale keyboard) — the caller then
    falls back to _page_item_at.
    """
    data = await state.get_data()
    if data.get(page_key) != page:
        return None
    items = data.get(list_key)
    if not items or idx < 0 or idx >= len(items):
        return None
    return items[idx]


async def _preselect_option(item_name: str) -> str:
    """A head with weight options opens on its first option that is in stock (else the first)."""
    family = await get_item_family(item_name)
    if not family or not family["options"] or family["current"]["variant_of"] is not None:
        return item_name
    options = family["options"]
    return next((o for o in options if (o["stock"] or 0) > 0), options[0])["name"]


async def _open_item(call: CallbackQuery, state: FSMContext, item_name: str, back_data: str):
    """Open an item card and record it for the on-screen (csrf) item context."""
    metrics = get_metrics()
    if metrics:
        metrics.track_conversion("purchase_funnel", "view_item", call.from_user.id)

    item_name = await _preselect_option(item_name)

    # Save item name and back_data in state
    updates = {"csrf_item": item_name, "item_back_data": back_data}
    switched = (await state.get_data()).get('csrf_item') != item_name
    await state.update_data(**updates)

    # A photo card of another item cannot have its caption reused: send a fresh message.
    await _render_item_page(call, state, item_name, back_data, user_id=call.from_user.id, replace=switched)


@router.callback_query(F.data.startswith('itm:'))
async def item_info_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Show detailed information about the item.
    Format: itm:{index}:{page}
    """
    try:
        parts = call.data.split(':')
        idx = int(parts[1])
        goods_page = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    item_name = await _page_item_from_state(state, 'goods_page_items', 'goods_page_num', goods_page, idx)
    if not item_name:
        category = (await state.get_data()).get('current_category', '')
        item_name = await _page_item_at(partial(query_items_in_category, category), goods_page, idx)
    if not item_name:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return
    await _open_item(call, state, item_name, f"gp_{goods_page}")


@router.callback_query(F.data.startswith('opt:'))
async def option_callback_handler(call: CallbackQuery, state: FSMContext):
    """
    Switch the card to another weight option of the same product.
    Format: opt:{goods_id}. Back keeps going where the head's card went (the list it was opened from).
    """
    try:
        goods_id = int(call.data.split(':')[1])
    except (ValueError, IndexError):
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    option = await get_option_by_id(goods_id)
    data = await state.get_data()
    family = await get_item_family(data['csrf_item']) if data.get('csrf_item') else None
    if not option or not family or option["variant_of"] != family["head"]["id"]:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return
    await _open_item(call, state, option["name"], data.get('item_back_data', 'gp_0'))


# --- Catalog search ---

async def _show_search_page(target, state: FSMContext, query: str, page: int):
    """Render one page of search results. `target` is a CallbackQuery or Message."""
    paginator = LazyPaginator(
        partial(query_goods_search, query), per_page=10,
    )

    page_items = await paginator.get_page(page)
    safe_query = esc(query)

    async def _render(text, markup):
        if isinstance(target, CallbackQuery):
            await edit_screen(target, text, reply_markup=markup, parse_mode="HTML")
        else:
            await target.answer(text, reply_markup=markup, parse_mode="HTML")

    if not page_items and page == 0:
        await _render(localize("shop.search.empty", query=safe_query), back("shop"))
        await state.set_state(None)
        return

    items_index = {item: i for i, item in enumerate(page_items)}
    labels = await item_labels(page_items)
    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda item: labels.get(item, item),
        item_callback=lambda item: f"sitm:{items_index[item]}:{page}",
        page=page,
        back_cb="shop",
        nav_cb_prefix="sp_",
    )

    total = await paginator.get_total_count()
    await _render(localize("shop.search.results", query=safe_query, count=total), markup)

    await state.update_data(
        search_query=query,
        search_page_items=list(page_items),
        search_page_num=page,
    )
    await state.set_state(ShopStates.viewing_search_results)


@router.callback_query(F.data == "shop_search")
async def shop_search_handler(call: CallbackQuery, state: FSMContext):
    """Prompt for a search query."""
    await edit_screen(call, localize("shop.search.prompt"), reply_markup=back("shop"))
    await state.set_state(ShopStates.waiting_search_query)


@router.message(ShopStates.waiting_search_query, F.text)
async def receive_search_query_handler(message: Message, state: FSMContext):
    query = (message.text or "").strip()

    if len(query) < 2 or len(query) > 64:
        # Stay in the state so the user can just retype.
        await message.answer(localize("shop.search.too_short"), reply_markup=back("shop"))
        return

    await _show_search_page(message, state, query, 0)


@router.callback_query(F.data.startswith('sp_'), ShopStates.viewing_search_results)
async def navigate_search(call: CallbackQuery, state: FSMContext):
    """Pagination across search results. Format: sp_{page}"""
    page = _page_arg(call.data[3:])
    if page is None:
        await call.answer(localize("errors.pagination_invalid"), show_alert=True)
        return
    data = await state.get_data()
    await _show_search_page(call, state, data.get('search_query', ''), page)


@router.callback_query(F.data.startswith('sitm:'))
async def search_item_info_handler(call: CallbackQuery, state: FSMContext):
    """
    Open an item from the search results.
    Format: sitm:{index}:{page}

    A separate namespace from itm:/gp_ because navigate_goods re-derives its page
    from current_category, which search results do not have.
    """
    try:
        parts = call.data.split(':')
        idx = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    item_name = await _page_item_from_state(state, 'search_page_items', 'search_page_num', page, idx)
    if not item_name:
        query = (await state.get_data()).get('search_query', '')
        item_name = await _page_item_at(partial(query_goods_search, query), page, idx)
    if not item_name:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return
    await _open_item(call, state, item_name, f"sp_{page}")


# --- Restock notifications ---

@router.callback_query(F.data == "sub_stock")
async def subscribe_stock_handler(call: CallbackQuery, state: FSMContext):
    """Subscribe to the restock notification for the item on screen."""
    item_name = (await state.get_data()).get('csrf_item')
    if not item_name:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    ok, _code = await subscribe_to_stock(call.from_user.id, item_name)
    await call.answer(localize("stock.subscribed" if ok else "errors.something_wrong"))
    await _render_item_page(call, state, item_name, user_id=call.from_user.id)


@router.callback_query(F.data == "unsub_stock")
async def unsubscribe_stock_handler(call: CallbackQuery, state: FSMContext):
    """Cancel the restock notification for the item on screen."""
    item_name = (await state.get_data()).get('csrf_item')
    if not item_name:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    await unsubscribe_from_stock(call.from_user.id, item_name)
    await call.answer(localize("stock.unsubscribed"))
    await _render_item_page(call, state, item_name, user_id=call.from_user.id)


# --- Favorites ---

@router.callback_query(F.data == "fav_toggle")
async def favorite_toggle_handler(call: CallbackQuery, state: FSMContext):
    """Star / un-star the product on screen (an option stars its head product)."""
    item_name = (await state.get_data()).get('csrf_item')
    if not item_name:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return
    now = await toggle_favorite(call.from_user.id, item_name)
    if now is None:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return
    await call.answer(localize("favorites.added" if now else "favorites.removed"))
    await _render_item_page(call, state, item_name, user_id=call.from_user.id)


async def show_favorites(target, user_id: int, page: int = 0) -> None:
    """The favorites list (a page of product buttons)."""
    total_probe = await list_favorites(user_id, 0, 1)
    pages = max(1, -(-total_probe[1] // FAVORITES_PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    items, total = await list_favorites(user_id, page, FAVORITES_PAGE_SIZE)
    title = localize("favorites.title")
    if not items:
        await edit_screen(target, title + "\n\n" + localize("favorites.empty"), reply_markup=back("profile"))
        return
    await edit_screen(target, title, reply_markup=favorites_keyboard(items, page, total, FAVORITES_PAGE_SIZE))


@router.callback_query(F.data == "favorites")
async def favorites_handler(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await show_favorites(call, call.from_user.id)


@router.callback_query(F.data.startswith("fav_page:"))
async def favorites_page_handler(call: CallbackQuery, state: FSMContext):
    page = _page_arg(call.data.split(":", 1)[1])
    if page is None:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    await call.answer()
    await show_favorites(call, call.from_user.id, page)


@router.callback_query(F.data.startswith("fav_open:"))
async def favorites_open_handler(call: CallbackQuery, state: FSMContext):
    try:
        item_id = int(call.data.split(":", 1)[1])
    except ValueError:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    name = await item_name_by_id(item_id)
    if not name:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        await show_favorites(call, call.from_user.id)
        return
    await call.answer()
    await _open_item(call, state, name, "favorites")


@router.callback_query(F.data.startswith("restock_open:"))
async def restock_open_handler(call: CallbackQuery, state: FSMContext):
    """The product from a "back in stock" notice (it may be an option)."""
    try:
        item_id = int(call.data.split(":", 1)[1])
    except ValueError:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    name = await item_name_by_id(item_id)
    if not name:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return
    await call.answer()
    await _open_item(call, state, name, "shop")


@router.callback_query(F.data == "back_to_item")
async def back_to_item_handler(call: CallbackQuery, state: FSMContext):
    """Return to item page, preserving promo state."""
    data = await state.get_data()
    item_name = data.get('csrf_item')
    if not item_name:
        # Fallback
        await edit_screen(
            call,
            localize("shop.item.not_found"),
            reply_markup=back("back_to_menu"),
        )
        return
    await _render_item_page(call, state, item_name, user_id=call.from_user.id)


# --- Balance Promo Redemption (from profile) ---

@router.callback_query(F.data == "redeem_promo")
async def redeem_promo_handler(call: CallbackQuery, state: FSMContext):
    await edit_screen(call, localize("promo.enter_redeem_code"), reply_markup=back("profile"))
    await state.set_state(PromoFSM.waiting_redeem_code)


@router.message(PromoFSM.waiting_redeem_code, F.text)
async def redeem_promo_code_handler(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()
    success, error_key, amount = await redeem_balance_promo(code, message.from_user.id)

    if success:
        await message.answer(
            localize("promo.balance_redeemed", code=code, amount=amount, currency=EnvKeys.PAY_CURRENCY),
            reply_markup=back("profile"),
        )
        log_audit_bg(
            "promo_redeem", user_id=message.from_user.id,
            resource_type="PromoCode", resource_id=code,
        )
    else:
        await message.answer(localize(error_key), reply_markup=back("profile"))

    await state.clear()


# --- Review Handlers ---

async def _display_name(item_name: str) -> str:
    """The product's name in the viewer's language (the canonical name if it has no translation)."""
    return (await item_labels([item_name])).get(item_name, item_name)


@router.callback_query(F.data == "review")
async def start_review_handler(call: CallbackQuery, state: FSMContext):
    if EnvKeys.REVIEWS_ENABLED != "1":
        await call.answer(localize("review.disabled"), show_alert=True)
        return

    item_name = (await state.get_data()).get('csrf_item')
    if not item_name:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    # Check if user purchased the item
    purchased = await has_purchased_item(call.from_user.id, await get_head_name(item_name))
    if not purchased:
        await call.answer(localize("review.not_purchased"), show_alert=True)
        return

    # Check if already reviewed
    existing = await get_user_review(call.from_user.id, item_name)
    if existing:
        await call.answer(localize("review.already_exists"), show_alert=True)
        return

    await state.update_data(review_item_name=item_name)
    await edit_screen(
        call,
        localize("review.prompt_rating", name=esc(await _display_name(await get_head_name(item_name)))),
        reply_markup=rating_keyboard(),
    )
    await state.set_state(ReviewFSM.waiting_rating)


@router.callback_query(F.data.startswith("rating:"), ReviewFSM.waiting_rating)
async def receive_rating_handler(call: CallbackQuery, state: FSMContext):
    try:
        rating = ReviewRequest(rating=int(call.data.split(":")[1])).rating
    except (ValueError, IndexError, ValidationError):
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return

    await state.update_data(review_rating=rating)

    buttons = [
        (localize("btn.skip_review_text"), "skip_review_text"),
        (localize("btn.back"), "back_to_menu"),
    ]
    await edit_screen(
        call,
        localize("review.prompt_text"),
        reply_markup=simple_buttons(buttons),
    )
    await state.set_state(ReviewFSM.waiting_text)


async def _submit_review(user_id: int, state: FSMContext, text: str | None) -> bool:
    """Persist the review accumulated in the FSM. False if it could not be saved.

    The item name and rating come out of state, which an expired session can
    leave empty — create_review also re-validates, so a bad pair is refused
    rather than raised.
    """
    data = await state.get_data()
    item_name = data.get('review_item_name')
    rating = data.get('review_rating')
    if not item_name or rating is None:
        return False

    if await create_review(user_id, item_name, rating, text) is None:
        return False

    await invalidate_rating_cache(item_name)
    return True


@router.callback_query(F.data == "skip_review_text", ReviewFSM.waiting_text)
async def skip_review_text_handler(call: CallbackQuery, state: FSMContext):
    ok = await _submit_review(call.from_user.id, state, None)
    await edit_screen(
        call,
        localize("review.created" if ok else "errors.something_wrong"),
        reply_markup=back("back_to_menu"),
    )
    await state.clear()


@router.message(ReviewFSM.waiting_text, F.text)
async def receive_review_text_handler(message: Message, state: FSMContext):
    text = (message.text or "")[:500].strip()

    ok = await _submit_review(message.from_user.id, state, text)
    await message.answer(
        localize("review.created" if ok else "errors.something_wrong"),
        reply_markup=back("back_to_menu"),
    )
    await state.clear()


# --- View Reviews ---

@router.callback_query(F.data.startswith("reviews:"))
async def view_reviews_handler(call: CallbackQuery, state: FSMContext):
    """List an item's reviews. Format: reviews:{page}"""
    if EnvKeys.REVIEWS_ENABLED != "1":
        await call.answer(localize("review.disabled"), show_alert=True)
        return

    try:
        page = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        page = 0

    item_name = (await state.get_data()).get('csrf_item')
    if not item_name:
        await call.answer(localize("shop.item.not_found"), show_alert=True)
        return

    paginator = LazyPaginator(partial(query_item_reviews, item_name), per_page=5)

    reviews = await paginator.get_page(page)
    total_pages = await paginator.get_total_pages()

    if not reviews:
        await edit_screen(
            call,
            localize("review.list_empty"),
            reply_markup=back("back_to_item"),
        )
        return

    lines = [localize("review.list_title", name=esc(await _display_name(item_name))), ""]
    for r in reviews:
        if r.get('text'):
            lines.append(localize(
                "review.item", rating=r['rating'],
                text=esc(r['text'][:100]),
            ))
        else:
            lines.append(localize("review.item_no_text", rating=r['rating']))

    # Navigation
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    kb = InlineKeyboardBuilder()
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"reviews:{page - 1}"))
    if total_pages > 1:
        nav_buttons.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="dummy_button"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"reviews:{page + 1}"))
    if nav_buttons:
        kb.row(*nav_buttons)
    kb.row(InlineKeyboardButton(text=localize("btn.back"), callback_data="back_to_item"))

    await edit_screen(call, "\n".join(lines), reply_markup=kb.as_markup())


# --- My orders ---

def _orders_back(page: int) -> str:
    return f"my-orders-page_{page}"


async def _show_orders_page(call: CallbackQuery | Message, user_id: int, page: int):
    """Render one page of the customer's orders, newest first (into the pressed message, or as a new message)."""
    paginator = LazyPaginator(partial(query_user_orders, user_id), per_page=10)
    if not await paginator.get_total_count():
        await edit_screen(call, localize("orders.title") + "\n\n" + localize("orders.empty"),
                          reply_markup=back("profile"))
        return

    markup = await lazy_paginated_keyboard(
        paginator=paginator,
        item_text=lambda o: localize(
            "orders.item", id=o.id, status=localize(f"order.status.{o.status}"),
            total=o.total, currency=EnvKeys.PAY_CURRENCY,
        ),
        item_callback=lambda o: f"my_order:{o.id}:{page}",
        page=page,
        back_cb="profile",
        nav_cb_prefix="my-orders-page_",
    )
    await edit_screen(call, localize("orders.title"), reply_markup=markup)


@router.callback_query(F.data == "my_orders")
async def my_orders_handler(call: CallbackQuery, state: FSMContext):
    """The customer's order list. First page."""
    await _show_orders_page(call, call.from_user.id, 0)


@router.callback_query(F.data.startswith("my-orders-page_"))
async def navigate_my_orders(call: CallbackQuery, state: FSMContext):
    """Pagination for the order list. Format: my-orders-page_{page}"""
    page = _page_arg(call.data.split("_", 1)[1])
    if page is None:
        await call.answer(localize("errors.pagination_invalid"), show_alert=True)
        return
    await _show_orders_page(call, call.from_user.id, page)


def _order_ref(data: str) -> tuple[int, int] | None:
    """Parse ``prefix:{order_id}[:{page}]`` into (order_id, page)."""
    parts = data.split(":")
    try:
        order_id = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        return None
    return (order_id, page) if page >= 0 else None


async def _show_order(call: CallbackQuery, order_id: int, page: int):
    """The order card, only ever for the caller's own order."""
    order = await get_order(order_id, user_id=call.from_user.id)
    if not order:
        await call.answer(localize("orders.not_found"), show_alert=True)
        return
    try:
        await call.message.edit_text(
            format_order(order), reply_markup=order_keyboard(order, back_cb=_orders_back(page)),
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


@router.callback_query(F.data.startswith("my_order:"))
async def my_order_handler(call: CallbackQuery, state: FSMContext):
    """Order detail. Format: my_order:{id}[:{page}] (the bare form comes from status notices)."""
    ref = _order_ref(call.data)
    if ref is None:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    await _show_order(call, *ref)


@router.callback_query(F.data.startswith("my_order_repeat:"))
async def my_order_repeat_handler(call: CallbackQuery, state: FSMContext):
    """Order again: refill the cart from a finished order. Format: my_order_repeat:{id}"""
    ref = _order_ref(call.data)
    if ref is None:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    ok, _code, result = await reorder_to_cart(call.from_user.id, ref[0])
    if not ok:
        await call.answer(localize("orders.not_found"), show_alert=True)
        return
    if not result["added"]:
        await call.answer(localize("orders.repeat_none"), show_alert=True)
        return
    text = localize("orders.repeat_done", added=result["added"])
    if result["skipped"]:
        text += "\n" + localize("orders.repeat_skipped", skipped=result["skipped"])
    await call.message.edit_text(text, reply_markup=simple_buttons([
        (localize("btn.cart_empty"), "cart"),
        (localize("btn.order.open"), f"my_order:{ref[0]}"),
    ]))


@router.callback_query(F.data.startswith("my_order_cancel:"))
async def my_order_cancel_ask_handler(call: CallbackQuery, state: FSMContext):
    """Ask before cancelling. Format: my_order_cancel:{id}[:{page}]"""
    ref = _order_ref(call.data)
    if ref is None:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    order_id, page = ref
    await call.message.edit_text(
        localize("orders.cancel_confirm", id=order_id),
        reply_markup=simple_buttons([
            (localize("btn.yes"), f"my_order_cancel_yes:{order_id}:{page}"),
            (localize("btn.no"), f"my_order:{order_id}:{page}"),
        ]),
    )


@router.callback_query(F.data.startswith("my_order_cancel_yes:"))
async def my_order_cancel_handler(call: CallbackQuery, state: FSMContext):
    """Cancel the caller's own order and put its stock back. Format: my_order_cancel_yes:{id}[:{page}]"""
    ref = _order_ref(call.data)
    if ref is None:
        await call.answer(localize("errors.invalid_data"), show_alert=True)
        return
    order_id, page = ref

    ok, code, order = await cancel_order_transaction(order_id, by_customer_id=call.from_user.id, reason="customer")
    if not ok:
        error_map = {
            "order_not_found": localize("orders.not_found"),
            "not_cancellable": localize("orders.not_cancellable"),
        }
        await call.answer(error_map.get(code, localize("errors.something_wrong")), show_alert=True)
        await _show_order(call, order_id, page)
        return

    await call.answer(localize("orders.cancelled", id=order_id))
    for name in order.get("restocked", []):
        # Waiting customers learn the item is back; don't hold up this reply for the broadcast.
        safe_create_task(notify_restock(call.bot, name))
    await _show_order(call, order_id, page)
