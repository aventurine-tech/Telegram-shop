"""One-time catalog import: structure, prices, idempotency, dry run, bad pictures (no network)."""
import io
import json
from decimal import Decimal

import pytest
from PIL import Image
from sqlalchemy import select, func

from bot.database.main import Database
from bot.database.methods.read import check_category, get_item_info, get_item_family
from bot.database.methods.product_images import has_item_image
from bot.database.models.main import Categories, Goods, ProductImages
from scripts import crawl_umbramd as crawl
from scripts import import_catalog as imp


def png(color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "PNG")
    return buf.getvalue()


def catalog(tmp_path, *, bad_image=False):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "a50.png").write_bytes(png())
    (tmp_path / "images" / "a200.png").write_bytes(png((1, 2, 3)))
    (tmp_path / "images" / "bad.png").write_bytes(b"not an image" if bad_image else png())
    (tmp_path / "images" / "i200.png").write_bytes(png((9, 9, 9)))
    return {
        "source": "x", "main_language": "ro",
        "categories": {"top": {"ro": "Tutun UMB", "en": "Hookah UMB", "ru": "Кальян UMB"},
                       "sub": {"classic": {"ro": "Classic", "en": "Classic", "ru": "Classic"},
                               "intense": {"ro": "Intense", "en": "Intense", "ru": "Intense"}}},
        "products": [
            {"name": "SOLO 11", "kind": "solo", "strength": "classic",
             "flavour": {"ro": "Mangosteen", "en": "Mangosteen EN", "ru": "Мангостин"},
             "options": [{"label": "50 g", "grams": 50, "image_file": "images/a50.png"},
                         {"label": "200 g", "grams": 200, "image_file": "images/a200.png"}]},
            {"name": "SOLO 11", "kind": "solo", "strength": "intense", "flavour": {"ro": "Mangosteen"},
             "options": [{"label": "200 g", "grams": 200, "image_file": "images/i200.png"}]},
            {"name": "MIX 325", "kind": "mix", "strength": "classic", "flavour": {"ro": "Tiramisu"},
             "options": [{"label": "50 g", "grams": 50, "image_file": "images/bad.png"}]},
        ],
    }


PRICES = [("*", "*", 50, Decimal("90")), ("*", "*", 200, Decimal("300")), ("intense", "SOLO 11", 200, Decimal("320"))]


@pytest.fixture
def main_ro(monkeypatch):
    monkeypatch.setattr(imp.EnvKeys, "BOT_LOCALE", "ro", raising=False)


async def count(model):
    async with Database().session() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar()


class TestPrices:

    def test_most_specific_row_wins(self):
        assert imp.price_for(PRICES, "intense", "SOLO 11", 200) == Decimal("320")
        assert imp.price_for(PRICES, "classic", "SOLO 11", 200) == Decimal("300")
        assert imp.price_for(PRICES, "classic", "X", 100) is None

    def test_csv_blank_prices_ignored_and_bad_rows_rejected(self, tmp_path):
        f = tmp_path / "p.csv"
        f.write_text("strength,name,weight,price\n*,*,50,\n*,*,200,\"310,5\"\n", encoding="utf-8")
        assert imp.load_prices(f) == [("*", "*", 200, Decimal("310.5"))]
        f.write_text("strength,name,weight,price\n*,*,abc,10\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            imp.load_prices(f)

    def test_invalid_catalog_rejected(self):
        with pytest.raises(SystemExit):
            imp.validate_catalog({"products": []})


class TestImport:

    async def test_creates_structure_prices_stock_and_pictures(self, tmp_path, main_ro):
        summary = await imp.run_import(catalog(tmp_path), PRICES, base=tmp_path)
        top, classic = await check_category("Tutun UMB"), await check_category("Classic")
        assert classic["parent_id"] == top["id"] and top["parent_id"] is None
        fam = await get_item_family("SOLO 11")
        assert [(o["name"], o["price"], o["stock"]) for o in fam["options"]] == [
            ("SOLO 11 · 50 g", 90, 0), ("SOLO 11 · 200 g", 300, 0)]
        assert fam["head"]["category_id"] == classic["id"]
        assert fam["head"]["description"].startswith("Mangosteen") and "Solo · Classic" in fam["head"]["description"]
        assert fam["head"]["description_en"].startswith("Mangosteen EN") and fam["head"]["name_ru"] == "SOLO 11"
        intense = await get_item_family("SOLO 11 Intense")
        assert intense["options"][0]["name"] == "SOLO 11 Intense · 200 g" and intense["options"][0]["price"] == 320
        assert await has_item_image("SOLO 11") and await has_item_image("SOLO 11 · 200 g")
        assert await has_item_image("SOLO 11 Intense · 200 g")
        assert not summary.errors

    async def test_second_run_changes_nothing(self, tmp_path, main_ro):
        cat = catalog(tmp_path)
        await imp.run_import(cat, PRICES, base=tmp_path)
        before = (await count(Goods), await count(Categories), await count(ProductImages))
        again = await imp.run_import(cat, PRICES, base=tmp_path)
        assert (await count(Goods), await count(Categories), await count(ProductImages)) == before
        assert not any(again.created.values()) and not again.errors

    async def test_existing_values_are_never_overwritten(self, tmp_path, main_ro):
        cat = catalog(tmp_path)
        await imp.run_import(cat, PRICES, base=tmp_path)
        async with Database().session() as s:
            g = (await s.execute(select(Goods).where(Goods.name == "SOLO 11 · 50 g"))).scalars().one()
            g.price, g.stock = Decimal("123"), 7
        await imp.run_import(cat, PRICES, base=tmp_path)
        info = await get_item_info("SOLO 11 · 50 g")
        assert info["price"] == 123 and info["stock"] == 7

    async def test_dry_run_writes_nothing(self, tmp_path, main_ro):
        summary = await imp.run_import(catalog(tmp_path), PRICES, base=tmp_path, dry_run=True)
        assert await check_category("Tutun UMB") is None and await get_item_info("SOLO 11") is None
        assert summary.created["products"] == 3 and summary.created["options"] == 4

    async def test_missing_price_skips_the_option_and_lists_it(self, tmp_path, main_ro):
        summary = await imp.run_import(catalog(tmp_path), [("*", "*", 50, Decimal("90"))], base=tmp_path)
        assert "SOLO 11 · 200 g" in summary.no_price and "SOLO 11 Intense · 200 g" in summary.no_price
        assert await get_item_info("SOLO 11 Intense") is None          # nothing priced -> no empty head
        assert [o["name"] for o in (await get_item_family("SOLO 11"))["options"]] == ["SOLO 11 · 50 g"]

    async def test_bad_picture_is_reported_but_the_product_is_created(self, tmp_path, main_ro):
        summary = await imp.run_import(catalog(tmp_path, bad_image=True), PRICES, base=tmp_path)
        assert await get_item_info("MIX 325 · 50 g") is not None
        assert not await has_item_image("MIX 325 · 50 g")
        assert any("picture rejected" in e for e in summary.errors)

    async def test_no_images_option(self, tmp_path, main_ro):
        await imp.run_import(catalog(tmp_path), PRICES, base=tmp_path, images=False)
        assert await count(ProductImages) == 0 and await get_item_info("SOLO 11") is not None

    async def test_reuses_an_existing_top_category(self, tmp_path, main_ro):
        from bot.database.methods.create import create_category
        await create_category("Premium hookah tobacco")
        await imp.run_import(catalog(tmp_path), PRICES, base=tmp_path, top_category="Premium hookah tobacco")
        top = await check_category("Premium hookah tobacco")
        assert (await check_category("Classic"))["parent_id"] == top["id"]
        assert await check_category("Tutun UMB") is None

    async def test_clashing_subcategory_is_reported(self, tmp_path, main_ro):
        from bot.database.methods.create import create_category
        await create_category("Classic")                                # top-level, not under ours
        summary = await imp.run_import(catalog(tmp_path), PRICES, base=tmp_path)
        assert any("not under" in e for e in summary.errors)
        assert await get_item_info("SOLO 11") is None


class TestCrawlParsing:

    PAGE = '''<ul><li><div class="grid-cards2 hookah container">
<div class="card grid-item solo classic 50 ">
    <div class="card-img"><span class="option-2">classic</span>
      <img src="/media/filer_public_thumbnails/filer_public/b2/3e/b23e4ec7-ebcf-404f-a225-24c9e58e91d9/umbra_50_11.png__450x450_subsampling-2_upscale.png" alt="solo 11" />
    </div>
    <div class="card-body"><p class="title">solo 11</p><p class="description">Mangosteen</p><p class="option-1">50g</p></div>
</div>
<div class="card grid-item solo intense 200 ">
    <div class="card-img"><span class="option-2">intense</span>
      <img src="/media/filer_public_thumbnails/filer_public/aa/bb/aabbccdd-ebcf-404f-a225-24c9e58e91d9/x.png__450x450_subsampling-2_upscale.png" alt="solo 11" />
    </div>
    <div class="card-body"><p class="title">solo  11</p><p class="description">Mangosteen</p><p class="option-1">200g</p></div>
</div>
</div></li></ul>'''

    def test_cards_and_original_picture_url(self):
        cards = crawl.parse_cards(self.PAGE)
        assert [(c["title"], c["grams"], c["strength"], c["kind"]) for c in cards] == [
            ("solo 11", 50, "classic", "solo"), ("solo 11", 200, "intense", "solo")]
        assert crawl.original_image_url(cards[0]["image_src"]) == (
            "https://umbramd.com/media/filer_public/b2/3e/b23e4ec7-ebcf-404f-a225-24c9e58e91d9/umbra_50_11.png")

    def test_same_flavour_in_both_strengths_stays_two_products(self):
        cards = crawl.parse_cards(self.PAGE)
        cat, warnings = crawl.build_catalog({"ro": cards, "en": cards, "ru": cards})
        assert sorted((p["strength"], p["name"], len(p["options"])) for p in cat["products"]) == [
            ("classic", "SOLO 11", 1), ("intense", "SOLO 11", 1)]
        assert not warnings

    def test_layout_change_is_detected(self):
        with pytest.raises(ValueError):
            crawl.parse_cards("<html></html>")


class TestOversizedOriginal:

    async def test_falls_back_to_the_site_thumbnail(self, tmp_path, main_ro, monkeypatch):
        cat = catalog(tmp_path)
        monkeypatch.setattr(imp, "MAX_IMAGE_BYTES", 100)                 # every 8x8 png is "too large"... except the thumb
        small = png()
        monkeypatch.setattr(imp, "MAX_IMAGE_BYTES", len(small) - 1)
        (tmp_path / "images" / "thumb_a50.png").write_bytes(b"x" * (len(small) - 5))   # stands in for the thumbnail
        cat["products"][0]["options"][0]["thumbnail_url"] = "https://example.invalid/t.png"
        summary = await imp.run_import(cat, PRICES, base=tmp_path)
        assert any("used the site's 450x450 picture" in n for n in summary.notes)
