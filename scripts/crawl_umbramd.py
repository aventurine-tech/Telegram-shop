"""One-time crawl of the UMBRA hookah-tobacco catalog on umbramd.com.

Reads the public product cards of the three language pages (ro / en / ru) — one request per page,
at most one request per second, plus the original product pictures — and writes
``catalog.json`` and ``REPORT.md`` for review before anything is imported.

    python -m scripts.crawl_umbramd [--out scripts/umbramd] [--no-images]

The cards are in the page HTML (the age prompt on the site is a client-side overlay); nothing here
bypasses any access control.
"""
import argparse
import html
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

BASE = "https://umbramd.com"
LANGS = ("ro", "en", "ru")
USER_AGENT = "Mozilla/5.0 (compatible; UmbraShopCatalogImport/1.0; one-time import for the shop owner)"

_CARD = re.compile(r'<div class="card grid-item ([^"]*)">(.*?)</div>\s*</div>', re.S)
_IMG = re.compile(r'<img src="([^"]+)" alt="([^"]*)"')
_TITLE = re.compile(r'<p class="title">(.*?)</p>', re.S)
_DESC = re.compile(r'<p class="description">(.*?)</p>', re.S)
_WEIGHT = re.compile(r'<p class="option-1">\s*(\d+)\s*g\s*</p>', re.I)
_UUID = re.compile(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})')


def original_image_url(src: str) -> str:
    """``/media/filer_public_thumbnails/filer_public/b2/3e/<uuid>.png__450x450_...`` -> the original file."""
    m = re.match(r'(/media/)filer_public_thumbnails/(filer_public/.+?\.\w+)__.*$', src)
    return BASE + (m.group(1) + m.group(2) if m else src)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text))).strip()


def parse_cards(page: str) -> list[dict]:
    """The hookah-tobacco cards of one language page."""
    start = page.find("grid-cards2 hookah")
    end = page.find("</li>", start)
    if start < 0 or end < 0:
        raise ValueError("hookah grid not found: the page layout changed")
    cards = []
    for classes, body in _CARD.findall(page[start:end]):
        flags = set(classes.split())
        img = _IMG.search(body)
        title = _TITLE.search(body)
        weight = _WEIGHT.search(body)
        if not (img and title and weight):
            raise ValueError(f"unparsable card: {clean(body)[:80]!r}")
        uuid = _UUID.search(img.group(1))
        cards.append({
            "title": clean(title.group(1)),
            "flavour": clean(_DESC.search(body).group(1)) if _DESC.search(body) else "",
            "grams": int(weight.group(1)),
            "strength": "intense" if "intense" in flags else "classic" if "classic" in flags else None,
            "kind": "mix" if "mix" in flags else "solo" if "solo" in flags else None,
            "image_src": img.group(1),
            "image_id": uuid.group(1) if uuid else None,
        })
    return cards


def product_key(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip().upper()


def build_catalog(pages: dict[str, list[dict]]) -> tuple[dict, list[str]]:
    """Merge the per-language cards into products with weight options. Returns (catalog, warnings).

    A flavour can be sold in both strengths (e.g. SOLO 11: Classic 50 g / 200 g and Intense 200 g), so a
    product is identified by (strength, name); the Romanian page is the master list."""
    warnings: list[str] = []
    main = pages["ro"]
    by_image = {lang: {c["image_id"]: c for c in cards if c["image_id"]} for lang, cards in pages.items()}
    by_title = {lang: {(product_key(c["title"]), c["grams"], c["strength"]): c for c in cards}
                for lang, cards in pages.items()}

    products: dict[tuple, dict] = {}
    for card in main:
        name = product_key(card["title"])
        key = (card["strength"], name)
        product = products.setdefault(key, {
            "name": name, "kind": card["kind"], "strength": card["strength"],
            "flavour": {}, "options": [],
        })
        label = f"{name} ({card['strength']})"
        if product["kind"] != card["kind"]:
            warnings.append(f"{label}: solo/mix differs between weights")
        if any(o["grams"] == card["grams"] for o in product["options"]):
            warnings.append(f"{label}: duplicate {card['grams']} g card skipped")
            continue
        for lang in LANGS:
            other = by_title[lang].get((name, card["grams"], card["strength"])) or by_image[lang].get(card["image_id"])
            if other is None:
                warnings.append(f"{label} {card['grams']} g: no {lang} card on the site")
                continue
            if lang != "ro" and other["strength"] != card["strength"]:
                warnings.append(f"{label} {card['grams']} g: the {lang} page lists it as {other['strength']}")
            if other["flavour"]:
                previous = product["flavour"].get(lang)
                if previous and previous != other["flavour"]:
                    warnings.append(f"{label}: {lang} flavour differs between weights "
                                    f"({previous!r} vs {other['flavour']!r}); first kept")
                else:
                    product["flavour"][lang] = other["flavour"]
        product["options"].append({
            "label": f"{card['grams']} g", "grams": card["grams"],
            "image_url": original_image_url(card["image_src"]),
            "thumbnail_url": BASE + card["image_src"],     # 450x450 fallback when an original is too big to store
        })
    for p in products.values():
        p["options"].sort(key=lambda o: o["grams"])
        for lang in LANGS:
            if not p["flavour"].get(lang):
                warnings.append(f"{p['name']} ({p['strength']}): no {lang} flavour text")
    catalog = {
        "source": BASE, "main_language": "ro",
        "categories": {"top": {"ro": "Tutun pentru narghilea", "en": "Hookah tobacco", "ru": "Табак для кальяна"},
                       "sub": {"classic": {"ro": "Classic", "en": "Classic", "ru": "Classic"},
                               "intense": {"ro": "Intense", "en": "Intense", "ru": "Intense"}}},
        "products": sorted(products.values(), key=lambda p: (p["strength"] or "", p["kind"] or "", p["name"])),
    }
    return catalog, warnings


def report(catalog: dict, warnings: list[str], cards_per_lang: dict[str, int]) -> str:
    products = catalog["products"]
    count = defaultdict(int)
    for p in products:
        count[(p["strength"], p["kind"])] += 1
    options = sum(len(p["options"]) for p in products)
    only_one = [f"{p['name']} ({p['strength']})" for p in products if len(p["options"]) == 1]
    lines = [
        "# UMBRA catalog crawl", "",
        f"Source: {catalog['source']} (hookah tobacco only; the site's Puff and accessories sections are not included).", "",
        f"- Cards per language page: " + ", ".join(f"{l}: {n}" for l, n in cards_per_lang.items()),
        f"- Products: **{len(products)}**, weight options: **{options}**",
    ]
    for (strength, kind), n in sorted(count.items(), key=lambda kv: str(kv[0])):
        lines.append(f"  - {strength} / {kind}: {n}")
    lines += ["", f"Products with a single weight: {len(only_one)}" + (f" ({', '.join(only_one)})" if only_one else ""), "",
              "## Warnings", ""]
    lines += [f"- {w}" for w in warnings] or ["- none"]
    lines += ["", "## Products", "", "| Name | Strength | Type | Weights | Flavour (ro) |", "|---|---|---|---|---|"]
    for p in products:
        lines.append(f"| {p['name']} | {p['strength']} | {p['kind']} | "
                     f"{', '.join(o['label'] for o in p['options'])} | {p['flavour'].get('ro', '')} |")
    return "\n".join(lines) + "\n"


def polite_get(client: httpx.Client, url: str, last: list[float]) -> httpx.Response:
    wait = 1.0 - (time.monotonic() - last[0])
    if wait > 0:
        time.sleep(wait)
    response = client.get(url)
    last[0] = time.monotonic()
    response.raise_for_status()
    return response


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="scripts/umbramd")
    ap.add_argument("--no-images", action="store_true", help="skip downloading pictures (catalog + report only)")
    args = ap.parse_args(argv)
    out = Path(args.out)
    (out / "images").mkdir(parents=True, exist_ok=True)

    last = [0.0]
    pages = {}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30) as client:
        for lang in LANGS:
            pages[lang] = parse_cards(polite_get(client, f"{BASE}/{lang}/", last).text)
            print(f"{lang}: {len(pages[lang])} cards")
        catalog, warnings = build_catalog(pages)
        if not args.no_images:
            for p in catalog["products"]:
                for o in p["options"]:
                    name = o["image_url"].rsplit("/", 1)[-1]
                    target = out / "images" / name
                    o["image_file"] = f"images/{name}"
                    if not target.exists():
                        target.write_bytes(polite_get(client, o["image_url"], last).content)
            print("pictures downloaded")
    (out / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "REPORT.md").write_text(report(catalog, warnings, {l: len(c) for l, c in pages.items()}), encoding="utf-8")
    weights = sorted({o["grams"] for p in catalog["products"] for o in p["options"]})
    template = out / "prices.template.csv"
    template.write_text("strength,name,weight,price\n" + "".join(f"*,*,{g},\n" for g in weights), encoding="utf-8")
    print(f"{len(catalog['products'])} products; {len(warnings)} warnings -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
