# CLAUDE.md — start here in a new session

Telegram shop bot for **physical goods** (aiogram 3, async SQLAlchemy + PostgreSQL, optional Redis, SQLAdmin web
panel). Two payment methods only: **MIA** (manual instant transfer, verified by staff) and **cash on delivery /
pickup**. Languages: **English, Russian, Romanian** in the bot *and* the web panel. Currency MDL. Integer stock.
First real catalog: **UMBRA hookah tobacco** (umbramd.com).

Read [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) next: what exists, what is open, known risks.
[`README.md`](README.md) is the user-facing manual; [`docs/run-and-test.pdf`](docs/run-and-test.pdf) the step-by-step test guide.

## Working agreements (from the owner — follow them)

- **Branch + PR per change.** Cut `claude/<topic>` from `origin/development`, open a PR **into `development`**, merge
  (squash, `expectedHeadSha` = the real full SHA from `git rev-parse HEAD`) when CI is green. **Never touch `main`**
  (it still holds the original upstream code; promotion is the owner's manual decision).
- The owner sometimes merges PRs themselves, even before CI finishes. After a merge, re-check `origin/development`; if a
  commit missed the merge, **re-apply it on a fresh branch from `development`** (never stack on a merged PR).
- **Never edit or overwrite the owner's `.env`** (only `.env.example`); tell them what to add by hand.
- Report honestly: say what was and was not tried on a real device. Nothing has been verified in a live Telegram chat
  by Claude — only by tests (and a headless Chromium for the web-panel script).
- Owner's language is English/Russian; they send screenshots of the live bot and the web panel — fix what they show.
- The GitHub MCP tools can disconnect; reload them with ToolSearch (`select:mcp__github__...`). No `gh` CLI.

## Commands

```bash
export TOKEN=1:x OWNER_ID=1 POSTGRES_DB=x POSTGRES_USER=x POSTGRES_PASSWORD=x
python -m pytest -q -p no:cacheprovider            # ~95 s, 2009 passed / 6 skipped at last count
```
Tests use in-memory SQLite (shared across tests in a session: never assume a table is empty), `FakeCache`, and a
key-echo `localize` mock (`conftest.py`; modules that localize are listed in `_LOCALIZING_MODULES` — a new one must be
added there). CI (`.github/workflows/tests.yml`): "Unit tests" + "Migrations on PostgreSQL" (upgrade → downgrade -1 →
upgrade on PG16). To test a migration locally: `pg_ctlcluster 16 main start`, create a DB, `alembic upgrade head`,
`alembic downgrade -1`, `alembic upgrade head` (env `POSTGRES_HOST=localhost`). Alembic head: `c9e5a7b3d4f6`
(client profiles; before it `b8d4f6a2c3e5` = mailings, before that `a7c3e5f1b2d4` = product options); chain files in `migrations/versions/`.

Deploy (owner): `git pull && docker compose up -d --build`, then `/start` once in the bot (migrations run on start).

## Map of the code

| Area | Where |
|---|---|
| Entry, middleware order | `bot/main.py` (CleanChat outermost → analytics → auth → language → security; rate limit separately) |
| Models | `bot/database/models/main.py` (Goods has `variant_of`/`variant_label`; Categories `parent_id`; translations `name_en/ru/ro`) |
| DB methods | `bot/database/methods/` — `create/read/update/delete`, `orders.py` (all stock/money transactions), `item_options.py`, `translations.py`, `product_images.py`, `web_users.py`, `lazy_queries.py` (paginated, heads-only lists) |
| Customer bot | `bot/handlers/user/` — `main.py` (/start, profile, welcome line), `bottom_nav.py`, `shop_and_goods.py`, `cart.py`, `checkout.py`, `language.py` |
| Admin bot | `bot/handlers/admin/` (orders, goods + options, categories, translations, roles, promo, broadcast…) |
| Web panel | `bot/web/admin.py` (all ModelViews), `bot/web/templates/` (layout, login, `order_details.html`, …), `accounts.py`, `passwords.py` |
| i18n | `bot/i18n/` — keys in `strings*.py` (en/ru) and `strings_ro_*.py`; `localize()` uses a per-update ContextVar language |
| Localized names | `bot/misc/localized.py` — `pick`, `derive_canonical`, `clean_name`, `LANGS` |
| Clean chat | `bot/middleware/clean_chat.py` |
| UMBRA import | `scripts/crawl_umbramd.py`, `scripts/import_catalog.py`, `scripts/umbramd/` |

## Design rules that are easy to break

- **Canonical vs translated names.** `name`/`description` (shop main language = `BOT_LOCALE`) are the unique lookup
  keys; `name_xx`/`description_xx` are display-only; `pick(row, field, lang)` falls back to canonical. Anything that
  accepts a name from an admin resolves it in any language (`resolve_item_name`, `resolve_category_name`, casefolded in
  Python — SQLite `lower()` is ASCII-only).
- **Catalog shape.** Two category levels max; a category holds subcategories *or* products. A product may have
  **weight options**: each option is its own `Goods` row (own price/stock/sale) named `"<head> · <label>"`
  (`variant_of` → head). Lists/search show **heads only**; the card shows a selector; a head with options is a
  gateway (cannot be added to the cart); reviews live on the head; options show the head's picture/description.
  An option's category follows its head. Flavours sold in both strengths are two products (`SOLO 11` / `SOLO 11 Intense`).
- **Orders**: stock is reserved at creation, released on cancel; statuses new → confirmed → shipped → completed /
  cancelled; MIA needs staff verification before progressing; all in `orders.py` under row locks. The web panel's order
  actions call the same functions (`apply_order_action`).
- **Web panel (SQLAdmin 0.16.1) quirks learned the hard way**: action names are normalised (`confirm_payment` →
  `confirm-payment`); a class defining `get_list_value` twice silently keeps the last; relationship select labels are
  `str(obj)` computed by sqladmin (so `Categories.__str__` is viewer-language aware) — a replaced `category` field
  must keep the original's `creation_counter`; field order = WTForms creation counters (`_own_language_first`);
  templates do not print field `description`, so hints are also placeholders; ValueError in `on_model_change` →
  400 page with the message.
- **Telegram quirks learned the hard way**: the persistent Catalog/Cart/Profile keyboard rides on a message — the
  **welcome line** ("Bun venit la UMBRA" / "Welcome to UMBRA" / "Добро пожаловать в UMBRA"). Telegram rejects
  whitespace / zero-width / Braille-blank text ("text must be non-empty") and **drops the keyboard if that message is
  deleted**, so it stays, is excluded from clean-chat tracking (`outside_screen()`), and a new one replaces the old
  after being sent. It must always be *above* the menu (send it first, then the screen). Bots can delete messages only
  within 48 h. `/start` also sweeps the 100 message ids before it.
- **Clean chat** (`CLEAN_CHAT=1`): one screen per private chat — a bot send during an update deletes the previous
  tracked screen, the user's own message is deleted after handling; sends to other chats / background sends are untouched.
- **Weight-option names** are composed once at creation/sync; renaming a head in the *bot* flow does not rename its
  options (the web form's options rows do).

## Conventions

- Match surrounding code style; comments only for the non-obvious. New user-facing strings need en + ru (`strings*.py`)
  and ro (`strings_ro_*.py`) — `tests/test_i18n.py` checks parity and placeholders. Romanian uses comma-below ș/ț.
- Every PR: tests for the change, README line if user-visible, full suite green locally before pushing.
- Pictures are stored unchanged (JPEG/PNG/WEBP ≤ 10 MB) in `product_images`; the bot caches Telegram `file_id`.
