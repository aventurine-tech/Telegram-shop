"""Weight options as one block of text (``label | price | stock`` per line), for the web product form.

``parse_options_text`` / ``format_options_text`` turn that text into rows and back; ``sync_item_options``
makes a head product's options match the rows: new labels are created, known labels get the new price and
stock (their names follow the head's), labels no longer listed are deleted like any product.
"""
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from bot.database import Database
from bot.database.methods.cache_utils import safe_create_task
from bot.database.methods.delete import delete_item
from bot.database.methods.read import invalidate_category_cache, invalidate_item_cache
from bot.database.models import Categories, Goods
from bot.misc.localized import LANGS, MAX_NAME_LEN, clean_name

MAX_LABEL_LEN = 32
SEPARATOR = "·"


class OptionsError(ValueError):
    """A bad options line; ``code`` is a ``web.form.options_*`` suffix and ``params`` its placeholders."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


def parse_options_text(text: str | None) -> list[tuple[str, Decimal, int]]:
    """Rows ``(label, price, stock)`` from lines like ``50 g | 150 | 200`` (stock optional, default 0)."""
    rows, seen = [], set()
    for number, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) not in (2, 3):
            raise OptionsError("line_bad", line=number)
        label = clean_name(parts[0])
        if not label or SEPARATOR in label or len(label) > MAX_LABEL_LEN:
            raise OptionsError("label_bad", line=number, limit=MAX_LABEL_LEN)
        if label.casefold() in seen:
            raise OptionsError("label_dup", line=number, label=label)
        seen.add(label.casefold())
        try:
            price = Decimal(parts[1].replace(",", "."))
            if price < 0 or price != price.quantize(Decimal("0.01")):
                raise InvalidOperation
        except InvalidOperation:
            raise OptionsError("price_bad", line=number)
        try:
            stock = int(parts[2]) if len(parts) == 3 and parts[2] else 0
            if stock < 0:
                raise ValueError
        except ValueError:
            raise OptionsError("stock_bad", line=number)
        rows.append((label, price, stock))
    return rows


def plain_price(price) -> str:
    """150 -> "150", 255.5 -> "255.50" (never scientific notation)."""
    price = Decimal(price).quantize(Decimal("0.01"))
    return str(int(price)) if price == price.to_integral() else f"{price:.2f}"


def format_options_text(options: list) -> str:
    """The inverse of parse_options_text for existing option rows (objects or dicts), in creation order."""
    def value(o, key):
        return o.get(key) if isinstance(o, dict) else getattr(o, key)
    lines = []
    for o in sorted(options, key=lambda o: value(o, "id")):
        lines.append(f"{value(o, 'variant_label')} | {plain_price(value(o, 'price'))} | {value(o, 'stock')}")
    return "\n".join(lines)


def _composite(head: Goods, label: str) -> tuple[str, dict[str, str | None]]:
    name = f"{head.name} {SEPARATOR} {label}"
    translated = {}
    for lang in LANGS:
        base = getattr(head, f"name_{lang}", None)
        translated[f"name_{lang}"] = f"{base} {SEPARATOR} {label}"[:MAX_NAME_LEN] if base else None
    return name, translated


async def check_option_names_free(head_name: str, head_id: int | None, rows) -> None:
    """Every ``"<head> · <label>"`` must be free (or already be one of this head's own options)."""
    async with Database().session() as s:
        for label, _price, _stock in rows:
            name = f"{head_name} {SEPARATOR} {label}"
            if len(name) > MAX_NAME_LEN:
                raise OptionsError("name_too_long", name=name, limit=MAX_NAME_LEN)
            clash = select(Goods.id).where(Goods.name == name)
            if head_id is not None:
                clash = clash.where(Goods.variant_of.is_(None) | (Goods.variant_of != head_id))
            if (await s.execute(clash.limit(1))).first() is not None:
                raise OptionsError("name_taken", name=name)


async def sync_item_options(head_id: int, rows: list[tuple[str, Decimal, int]]) -> dict:
    """Make the head's options equal ``rows``. Returns ``{"restocked": [names], "touched": [names]}``."""
    restocked, touched, removed = [], [], []
    async with Database().session() as s:
        head = (await s.execute(select(Goods).where(Goods.id == head_id).with_for_update())).scalars().one()
        if head.variant_of is not None:
            return {"restocked": [], "touched": []}
        category = (await s.execute(select(Categories.name).where(Categories.id == head.category_id))).scalar()
        existing = {o.variant_label.casefold(): o for o in (await s.execute(
            select(Goods).where(Goods.variant_of == head.id).order_by(Goods.id))).scalars().all()}
        wanted = {label.casefold() for label, _p, _s in rows}
        for label, price, stock in rows:
            name, translated = _composite(head, label)
            option = existing.get(label.casefold())
            if option is None:
                s.add(Goods(name=name, description="", price=price, category_id=head.category_id, stock=stock,
                            variant_of=head.id, variant_label=label, **translated))
            else:
                if (option.stock or 0) == 0 and stock > 0:
                    restocked.append(name)
                touched.append(option.name)
                option.price, option.stock = price, stock
                option.category_id = head.category_id
                option.name = name
                for key, text in translated.items():
                    setattr(option, key, text)
            touched.append(name)
        removed = [o.name for key, o in existing.items() if key not in wanted]
    for name in removed:
        await delete_item(name)
    for name in set(touched):
        safe_create_task(invalidate_item_cache(name))
    if category:
        safe_create_task(invalidate_category_cache(category))
    return {"restocked": restocked, "touched": touched}
