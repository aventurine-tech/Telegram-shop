# Changelog

All notable changes to this project. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project is
not versioned with releases yet, so entries are grouped by merged pull request (newest first) under **Unreleased** — the state
of the `development` branch. `main` still holds the original upstream code and is promoted manually by the owner.

**How to maintain this file** (see `docs/GIT_WORKFLOW.md`): every PR adds its entry here in the same PR — *Added / Changed /
Fixed / Removed / Database / Security*, one line per user-visible change, with the PR number. A hotfix gets its own entry.
When `development` is promoted to `main`, the Unreleased block becomes a dated release heading.

## [Unreleased] — `development`

### Light / dark theme (2026-10-06)
- **Added** a light/dark switch in the web panel (sidebar and login page): follows the system preference on first visit, remembers the choice
  in the browser, applied before the first paint (no white flash). Dark palette for cards, tables, forms, dialogs, pagination, Select2 and
  the date picker; the mailing preview bubble and permission tags are themed too. Labels in en/ru/ro.
- **Changed** own `base.html`; inline light-only colours replaced by themed classes (`shop-pill`, `tg-bubble`).

### #25 — CI runs once per change (2026-10-06)
- **Changed** the workflow no longer triggers on both `push` and `pull_request` (which ran every check twice per PR update): PRs are tested by
  the `pull_request` event, pushes only on `development`/`main`.

### Documentation set (2026-10-06)
- **Added** `AGENTS.md` (canonical rulebook), rewritten `CLAUDE.md`, this `CHANGELOG.md`, `ROADMAP.md`, and `docs/`: `PROJECT_PRINCIPLES`
  (with the owner's requirements register), `DECISIONS`, `GIT_WORKFLOW`, `NAMING_STANDARDS`, `TESTING`, `SECURITY`,
  `ENTERPRISE_STANDARDS`, `MODULE_GUIDE`, `MODULE_STATUS`.
- **Changed** `docs/PROJECT_STATUS.md` → `docs/PROJECT_STATE.md` (current state, open items, risks, resume checklist); README documentation
  index, architecture notes (profile middleware, mailing scheduler, new tables); run-and-test guide covers the back office.

### #23 — Shipping methods (2026-10-06)
- **Added** Catalog → **Shipping** in the web panel: delivery methods with a name in en/ru/ro, price, optional *free from*
  amount, active flag and position.
- **Added** checkout step *choose a delivery method* (after the address; a single method is taken automatically); the price is
  added to the order total and shown in the confirmation, the order card (customer and staff) and the web order page.
- **Changed** `create_order_transaction` validates the method (`shipping_required`, `invalid_shipping`), computes the fee on the
  server and checks `expected_total` including it. With no active method delivery stays free and unpriced (unchanged behaviour).
- **Database** migration `d1f6b8c4e5a7`: table `shipping_methods`; `orders.shipping_name`, `orders.delivery_fee`.

### #22 — Client profiles (2026-10-06)
- **Added** customer profile: first/last name and @username (from Telegram, refreshed by `ProfileMiddleware` at most every
  5 minutes), phone and delivery address (from the latest order), staff notes, last activity.
- **Added** web **Clients → Customers**: list with names, @username link, phone, address, language, balance, first contact,
  last activity; search by id/name/username/phone/address; edit form with notes; details page with full order history and total;
  CSV export with the new columns.
- **Changed** `create_order_transaction` saves phone (and, for delivery, the address) into the profile.
- **Database** migration `c9e5a7b3d4f6`: nine profile columns on `users`; phone/address back-filled from existing orders.
- **Decision** no client import tool (the owner asked for the functionality, not for importing the Botobot export).

### #21 — Whole web panel translated (2026-10-06)
- **Changed** SQLAdmin's English-only chrome (list, create, edit, details, delete/confirm dialogs, pagination, search, buttons,
  Yes/No selects) now follows the panel language via our own template copies and `web.sa.*` keys.
- **Changed** WTForms validation messages follow the panel language.
- **Changed** Romanian wording of Mailings → **Campanii / Campanie**; "variabile", "Trimite un test pentru mine"; Russian
  audience names (Румыноязычные / Русскоязычные / Англоязычные клиенты).

### #20 — Mailings (2026-10-06)
- **Added** web **Marketing → Mailings** (Admin role): title, audience (all / ro / ru / en / with orders / without orders, with
  head-counts), rich text editor (bold / italic / underline / strike / link, placeholders `{first_name|friend}`, `{last_name}`,
  `{full_name}`, `{username}`, `{telegram_id}`), live Telegram-style preview, character counter (1024 with picture / 4096),
  one picture, options (no link previews, silent, forbid forwarding/saving), draft / send now / schedule (UTC).
- **Added** list with status and **Delivered N out of M**; details page with progress bar, *Send test to me*, *Cancel mailing*,
  *Duplicate*.
- **Added** `MailingSender` (batches of 25, 1 s pause, blocked users counted, cancel honoured, picture cached by `file_id`) and a
  15-second scheduler in `RecoveryManager`; a mailing interrupted by a restart is marked *Interrupted* and never resumed.
- **Added** Settings → My account → **Telegram ID** (target of test messages).
- **Database** migration `b8d4f6a2c3e5`: table `mailings`; `web_users.telegram_id`.

### #19 — Grouped web sidebar (2026-10-06)
- **Changed** sidebar into collapsible groups: Orders · Clients · Payments · Catalog · Marketing · Settings · Log out (Botobot-
  inspired); open group follows the current page; Order lines are reached from an order.
- **Added** *Payments to verify* (MIA orders waiting for a staff check) next to *Balance operations*.

### #18 — Documentation handoff (2026-10-06)
- **Added** `CLAUDE.md`, `docs/PROJECT_STATUS.md` (now `PROJECT_STATE.md`), refreshed README, run-and-test guide source + PDF builder.

### #17 — Welcome line above the menu after language change (2026-10-05)
- **Fixed** after changing the language the new welcome line appeared below the profile; it is now sent first.

### #16 — Localized welcome line (2026-10-05)
- **Changed** the message that carries the bottom keyboard is the welcome line *Bun venit la UMBRA / Welcome to UMBRA /
  Добро пожаловать в UMBRA* (owner's wording) instead of a symbol.

### #15 — Role tags and order buttons (2026-10-05)
- **Changed** role permissions in the web form are **checkbox tags**, not a binary number.
- **Changed** order details show clear, status-aware action buttons (only the moves that fit the order's state).

### #14 — Hotfix: `/start` crashed (2026-10-05)
- **Fixed** Telegram rejected the blank keyboard-carrier message ("text must be non-empty"); the carrier is now a visible
  character and a keyboard failure never blocks the menu.

### #13 — Options as rows, categories (2026-10-05)
- **Changed** product *Options* are add/remove rows with a **＋** button (option name, price, stock); category form shows the
  own-language name first.

### #12 — Options inside the product form (2026-10-05)
- **Changed** web product form manages weight options inline; category paths; description order; keyboard carrier kept.

### #11 — Web product form clean-up (2026-10-05)
- **Changed** the product has **one name** (descriptions stay per language); category dropdown shows localized names.

### #10 — UMBRA catalog crawler and importer (2026-10-05)
- **Added** `scripts/crawl_umbramd.py` (54 products / 73 options, 3 languages, pictures → `scripts/umbramd/`),
  `scripts/import_catalog.py` (idempotent, `--dry-run`, prices CSV, pictures). Not yet run on the live shop (prices pending).

### #9 — No visible "quick menu" text (2026-10-05)
- **Changed** first attempt at hiding the keyboard-carrier message (superseded by #14/#16).

### #8 — Clean chat (2026-10-05)
- **Added** one screen per private chat (`CLEAN_CHAT=1`): bot screens replace each other, the user's messages are removed,
  `/start` sweeps ~100 earlier messages.

### #7 — Weight options (2026-10-05)
- **Added** product options (e.g. 50 g / 200 g), each with its own price, stock and sale, sharing picture and description;
  selector on the card; lists show heads only; *Add option* in the bot.
- **Database** migration `a7c3e5f1b2d4` (`goods.variant_of`, `goods.variant_label`).

### #6 — Subcategories (2026-10-05)
- **Added** two category levels; top-level categories appear on the main menu.
- **Database** `categories.parent_id`.

### #5 — Permanent bottom keyboard (2026-10-05)
- **Added** Catalog · Cart · Profile keyboard on every screen.

### #4 — Own-language field first (2026-10-05)
- **Changed** admin forms: the field for the admin's own language is plain "Name"/"Description"; wizards ask in that language first.

### #3 — Translated catalog (2026-10-05)
- **Added** category names and product names/descriptions in en/ru/ro with fallback to the canonical (main-language) text.
- **Database** `name_en/ru/ro`, `description_en/ru/ro` columns.

### #2 — Development workflow (2026-10-05)
- **Added** documented branch/PR/CI workflow.

### #1 — Physical-goods shop (2026-10-05)
- **Added** orders with stock reservation, MIA (staff-verified) and cash on delivery/pickup, delivery or pickup,
  product pictures, web accounts (Admin / Staff), EN/RU/RO bot and web, run-and-test guide, CI (tests + PostgreSQL migrations).
- **Removed** digital delivery, Telegram Stars, CryptoPay, Telegram Payments and balance top-ups from the upstream project.

## Before the fork (upstream `interlumpen/Telegram-shop`, 2026-03 … 2026-07)

Digital-goods shop this project was derived from (kept for context): async migration to asyncpg, role/permission system
(11-bit mask), promo codes, cart, reviews, operation history, CSV export, audit log, optional Redis, webhook mode, rate
limiting, sales, catalog search, restock notifications, multiple security and performance audits, SQLAlchemy 2.0 typed models.
