"""Import the crawled UMBRA catalog (``catalog.json``) into the shop.

    docker compose exec bot python -m scripts.import_catalog scripts/umbramd/catalog.json \\
        --prices data/prices.csv [--dry-run] [--top-category NAME] [--no-images]

* Structure: top category (``--top-category`` to reuse an existing empty one) -> Classic / Intense
  subcategories -> one head product per flavour with a weight option per size (``SOLO 11 · 50 g``).
  Intense products are named ``<NAME> Intense`` so the same flavour can exist in both strengths.
* Prices come from the CSV (``strength,name,weight,price``; ``*`` matches anything, the most specific
  row wins). An option without a price is skipped and listed; stock is always 0.
* Idempotent: anything that already exists is left untouched (names, prices, stock, pictures), so a
  second run changes nothing. ``--dry-run`` reports what would happen and writes nothing.
* A failing product (bad picture, name clash) is reported and the run goes on.
"""
import argparse
import asyncio
import csv
import json
import sys
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

from bot.database.methods.create import create_category, create_item, create_item_option, create_subcategory
from bot.database.methods.product_images import has_item_image, set_item_image
from bot.database.methods.read import check_category, get_item_info
from bot.misc import EnvKeys
from bot.misc.images import MAX_IMAGE_BYTES

LANGS = ("ro", "en", "ru")
KIND_LABEL = {"solo": "Solo", "mix": "Mix"}
STRENGTH_LABEL = {"classic": "Classic", "intense": "Intense"}


@dataclass
class Summary:
    created: dict = field(default_factory=lambda: {"categories": 0, "products": 0, "options": 0, "images": 0})
    existing: dict = field(default_factory=lambda: {"categories": 0, "products": 0, "options": 0, "images": 0})
    no_price: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def lines(self, dry_run: bool) -> list[str]:
        verb = "would create" if dry_run else "created"
        out = [f"{verb}: " + ", ".join(f"{n} {k}" for k, n in self.created.items()),
               "already there: " + ", ".join(f"{n} {k}" for k, n in self.existing.items())]
        if self.no_price:
            out.append(f"skipped, no price ({len(self.no_price)}): " + ", ".join(self.no_price))
        out += [f"note: {n}" for n in self.notes]
        out += [f"ERROR: {e}" for e in self.errors]
        return out


def load_prices(path: str | Path | None) -> list[tuple[str, str, int, Decimal]]:
    """Rows ``(strength, NAME, grams, price)`` with ``*`` wildcards; blank prices are ignored."""
    rows = []
    if not path:
        return rows
    with open(path, newline="", encoding="utf-8") as fh:
        for n, row in enumerate(csv.DictReader(fh), start=2):
            raw = (row.get("price") or "").strip()
            if not raw:
                continue
            try:
                price = Decimal(raw.replace(",", "."))
                grams = int(str(row.get("weight", "")).strip().lower().rstrip("g").strip())
            except (InvalidOperation, ValueError):
                raise SystemExit(f"{path}:{n}: bad weight/price in {row}")
            if price < 0:
                raise SystemExit(f"{path}:{n}: negative price")
            rows.append(((row.get("strength") or "*").strip().lower(), (row.get("name") or "*").strip().upper(),
                         grams, price))
    return rows


def price_for(rows, strength: str, name: str, grams: int) -> Decimal | None:
    best, best_score = None, -1
    for r_strength, r_name, r_grams, price in rows:
        if r_grams != grams or r_strength not in ("*", strength) or r_name not in ("*", name.upper()):
            continue
        score = (r_strength != "*") * 2 + (r_name != "*")
        if score > best_score:
            best, best_score = price, score
    return best


def validate_catalog(catalog: dict) -> None:
    try:
        assert isinstance(catalog["products"], list) and catalog["products"]
        for key in ("top", "sub"):
            assert catalog["categories"][key]
        for p in catalog["products"]:
            assert p["name"] and p["strength"] in STRENGTH_LABEL and p["options"]
            for o in p["options"]:
                assert o["label"] and isinstance(o["grams"], int)
    except (KeyError, TypeError, AssertionError):
        raise SystemExit("catalog.json is not a valid catalog (run the crawler again)")


def _text(texts: dict, lang: str, main: str) -> str:
    return texts.get(lang) or texts.get(main) or texts.get("ro") or next(iter(texts.values()), "")


def product_names(product: dict) -> str:
    return product["name"] if product["strength"] == "classic" else f"{product['name']} Intense"


def descriptions(product: dict) -> dict[str, str]:
    facts = f"UMBRA · {KIND_LABEL.get(product['kind'], '')} · {STRENGTH_LABEL[product['strength']]}".replace(" ·  ·", " ·")
    return {lang: f"{flavour}\n\n{facts}" for lang, flavour in product["flavour"].items() if flavour}


async def _fetch(base: Path, file: str | None, url: str | None, client) -> bytes | None:
    """A picture from the local cache, else downloaded (and cached) from ``url``."""
    if file and (base / file).exists():
        return (base / file).read_bytes()
    if client and url:
        response = await client.get(url)
        response.raise_for_status()
        if file:
            (base / file).parent.mkdir(parents=True, exist_ok=True)
            (base / file).write_bytes(response.content)
        return response.content
    return None


async def _image_bytes(base: Path, option: dict, client: httpx.AsyncClient | None,
                       summary: Summary | None = None, name: str = "") -> bytes | None:
    """The original picture; when it is too large to store (a few site originals are 14 MB), the
    site's 450x450 version instead."""
    data = await _fetch(base, option.get("image_file"), option.get("image_url"), client)
    if data is not None and len(data) > MAX_IMAGE_BYTES and option.get("thumbnail_url"):
        thumb_file = f"images/thumb_{Path(option['image_file'] or 'x.png').name}"
        data = await _fetch(base, thumb_file, option["thumbnail_url"], client)
        if summary is not None:
            summary.notes.append(f"{name}: original too large, used the site's 450x450 picture")
    return data


async def run_import(catalog: dict, prices: list, *, base: Path, dry_run: bool = False,
                     top_category: str | None = None, images: bool = True,
                     client: httpx.AsyncClient | None = None) -> Summary:
    validate_catalog(catalog)
    summary = Summary()
    main = EnvKeys.BOT_LOCALE if EnvKeys.BOT_LOCALE in LANGS else "ro"
    top_names = catalog["categories"]["top"]
    top = top_category or _text(top_names, main, main)
    top_translations = None if top_category else {l: t for l, t in top_names.items() if t}

    # Categories -------------------------------------------------------------------------------
    existing_top = await check_category(top)
    if existing_top is None:
        summary.created["categories"] += 1
        if not dry_run:
            await create_category(top, names=top_translations)
    elif existing_top.get("parent_id") is not None:
        summary.errors.append(f"category {top!r} is itself a subcategory; choose another --top-category")
        return summary
    else:
        summary.existing["categories"] += 1

    sub_name = {}
    for strength, texts in catalog["categories"]["sub"].items():
        name = _text(texts, main, main)
        sub_name[strength] = name
        found = await check_category(name)
        if found is None:
            summary.created["categories"] += 1
            if not dry_run:
                ok, code = await create_subcategory(name, top, names={l: t for l, t in texts.items() if t})
                if not ok:
                    summary.errors.append(f"subcategory {name!r}: {code}")
        elif found.get("parent_id") is None or (existing_top and found.get("parent_id") != existing_top["id"]):
            summary.errors.append(f"category {name!r} exists but is not under {top!r}; rename or remove it first")
        else:
            summary.existing["categories"] += 1
    if summary.errors:
        return summary

    # Products ---------------------------------------------------------------------------------
    for product in catalog["products"]:
        head = product_names(product)
        priced = []
        for option in product["options"]:
            price = price_for(prices, product["strength"], product["name"], option["grams"])
            if price is None:
                summary.no_price.append(f"{head} · {option['label']}")
            else:
                priced.append((option, price))
        if not priced:
            continue
        try:
            await _import_product(product, head, priced, sub_name[product["strength"]], summary,
                                  base=base, dry_run=dry_run, images=images, client=client)
        except Exception as e:  # one bad product must not stop the run
            summary.errors.append(f"{head}: {type(e).__name__}: {e}")
    return summary


async def _import_product(product, head, priced, category, summary, *, base, dry_run, images, client):
    names = {lang: head for lang in LANGS}
    descs = descriptions(product)
    main = EnvKeys.BOT_LOCALE if EnvKeys.BOT_LOCALE in LANGS else "ro"
    head_exists = await get_item_info(head) is not None
    if head_exists:
        summary.existing["products"] += 1
    else:
        summary.created["products"] += 1
        if not dry_run:
            await create_item(head, descs.get(main) or descs.get("ro", ""), 0, category, stock=0,
                              names=names, descriptions=descs)
            if await get_item_info(head) is None:
                raise RuntimeError("the product was not created (name clash or wrong category)")

    first_image = None
    for option, price in priced:
        option_name = f"{head} · {option['label']}"
        if await get_item_info(option_name) is not None:
            summary.existing["options"] += 1
        else:
            summary.created["options"] += 1
            if not dry_run:
                ok, code = await create_item_option(head, option["label"], price, 0)
                if not ok:
                    raise RuntimeError(f"option {option['label']}: {code}")
        if images:
            data = None
            try:
                data = await _image_bytes(base, option, client, summary, option_name)
            except Exception as e:
                summary.errors.append(f"{option_name}: picture not available ({e})")
            if data is not None:
                first_image = first_image or data
                await _attach_image(option_name, data, summary, dry_run)
    if images and first_image is not None:
        await _attach_image(head, first_image, summary, dry_run)


async def _attach_image(item_name: str, data: bytes, summary: Summary, dry_run: bool) -> None:
    """Give a product its picture unless it already has one (never replaces)."""
    if await get_item_info(item_name) is not None and await has_item_image(item_name):
        summary.existing["images"] += 1
        return
    summary.created["images"] += 1
    if not dry_run:
        ok, code = await set_item_image(item_name, data)
        if not ok:
            summary.created["images"] -= 1
            summary.errors.append(f"{item_name}: picture rejected ({code})")


async def _main(args) -> int:
    from bot.database import Database
    from bot.misc.caching import init_cache_manager
    from bot.misc.caching.storage import get_redis_storage

    catalog_path = Path(args.catalog)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    prices = load_prices(args.prices)
    if not args.dry_run:
        storage = await get_redis_storage()          # so cache invalidation reaches the bot's Redis
        if storage is not None:
            await init_cache_manager(storage.redis)
    async with httpx.AsyncClient(follow_redirects=True, timeout=30,
                                 headers={"User-Agent": "UmbraShopCatalogImport/1.0"}) as client:
        summary = await run_import(catalog, prices, base=catalog_path.parent, dry_run=args.dry_run,
                                   top_category=args.top_category, images=not args.no_images, client=client)
    await asyncio.sleep(0.5)                         # let fire-and-forget cache invalidations finish
    print("\n".join(summary.lines(args.dry_run)))
    return 1 if summary.errors else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("catalog", help="path to catalog.json")
    ap.add_argument("--prices", help="CSV with columns strength,name,weight,price ('*' = any)")
    ap.add_argument("--dry-run", action="store_true", help="show what would be created, write nothing")
    ap.add_argument("--top-category", help="reuse this existing top-level category instead of creating one")
    ap.add_argument("--no-images", action="store_true")
    return asyncio.run(_main(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
