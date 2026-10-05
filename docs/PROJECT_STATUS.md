# Project status

_Last updated: 2026-10-05 (after PR #20). Branch of record: `development`; `main` is untouched on purpose._

## In one paragraph

A Telegram shop bot for physical goods (MIA transfer verified by staff, or cash on delivery / pickup), with a
catalog of categories → subcategories → products → weight options, order tracking, staff roles, a multi-account web
panel, and English / Russian / Romanian everywhere. Everything below is **built, merged into `development` and
covered by automated tests** (2055 passing). Nothing has been signed off in a live shop yet: the owner is testing the
deployed bot and reporting issues from screenshots.

## What exists

| Area | State |
|---|---|
| Customer flow: catalog, search, cart, promo, checkout (delivery/pickup), MIA + COD, My orders, referrals, balance, reviews, restock "notify me" | Done |
| Staff flow in chat: orders (confirm / ship / complete / cancel / MIA verification), catalog and stock, promo, users, roles, broadcast, stats | Done |
| Web panel (SQLAdmin): catalog, orders with status-aware action buttons, users, **roles as permission tags**, promo, audit, CSV export | Done |
| Web accounts: Admin and Staff levels, hashed passwords, language per account | Done |
| Languages en / ru / ro in bot and web; language asked at `/start` and remembered; per-recipient notifications | Done |
| Translated catalog: product **name is one field** in the web form; descriptions in three languages; category names in three languages | Done |
| Product pictures (original format) — bot and web upload | Done |
| Subcategories (two levels) + top categories on the main menu | Done |
| Weight options per product (own price/stock, shared picture), selector on the card, **Options rows with ＋ in the web form**, *Add option* in the bot | Done |
| Persistent bottom keyboard Catalog · Cart · Profile, carried by the welcome line | Done (see risks) |
| Clean chat: one screen per chat, user messages removed, `/start` sweep | Done |
| UMBRA catalog crawl + importer (54 products / 73 options, 3 languages, pictures) | Built; **not yet run on the live shop** |

## Pull requests (all merged into `development`)

| PR | What |
|---|---|
| #1 | Physical-goods shop: orders, MIA + COD, pictures, web accounts, EN/RU/RO, run-and-test guide, CI |
| #2 | Development workflow documented |
| #3 | Translated catalog (names, descriptions) |
| #4 | Admin forms: own-language field is plain "Name"/"Description" |
| #5 | Permanent bottom keyboard |
| #6 | Subcategories + categories on the main menu |
| #7 | Weight options (product variants) |
| #8 | Clean chat |
| #9 | Remove the visible "quick menu" text (first attempt) |
| #10 | UMBRA crawler + importer + `catalog.json` |
| #11 | Web product form: one name, localized category dropdown |
| #12 | Options inside the product (web), category paths, description order, keyboard carrier kept |
| #13 | Options as add/remove rows, own-language-first name on categories |
| #14 | **Hotfix**: `/start` crashed (Telegram rejected the blank keyboard message) |
| #15 | Role permission tags; clear, status-aware order buttons |
| #16 | Keyboard message = localized welcome line |
| #17 | Welcome line stays above the menu after a language change |
| #18 | Docs: CLAUDE.md, status, README, run-and-test |
| #19 | Web sidebar in groups (Orders, Clients, Payments, Catalog, Marketing, Settings, Log out) + "Payments to verify" |
| #20 | **Mailings** (web): editor with toolbar/placeholders/live preview, picture, audiences, schedule, delivery report, test to myself |
| #21 | Web panel fully translated (list/form/dialog chrome, validation), Romanian "Campanii" |
| #22 | Client profiles (names, @username, phone, address, order history in web) |
| #23 | Shipping methods (price, free-from threshold, chosen at checkout, fee on the order) |

## Mailings (PR #20) — how it works

- Web: **Marketing → Mailings** (Admin role only). Fields: title, group (all / ro / ru / en / with orders / without
  orders, each with its current head-count), text (B/I/U/S/link toolbar, placeholders `{first_name|friend}`,
  `{last_name}`, `{full_name}`, `{username}`, `{telegram_id}`, counter, live Telegram-style preview), one picture,
  *when* (draft / send now / schedule in UTC), options (no link previews, silent, no forwarding/saving).
- Sending: `MailingSender` (`bot/misc/services/mailing_sender.py`), batches of 25 + 1 s pause, started by the 15 s
  scheduler loop in `RecoveryManager`; picture uploaded once then reused by `file_id`; caption > 1024 = picture, then text.
  Counts delivered / blocked / failed; *Cancel mailing* works while sending. A mailing interrupted by a restart is marked
  *Interrupted* and **never resumed** (no duplicate sends).
- *Send test to me* uses the **Telegram ID** saved in **Settings → My account**.
- Tables/migration: `mailings`, `web_users.telegram_id` (`b8d4f6a2c3e5`). Code: `bot/web/mailings.py`,
  `bot/misc/mailing_text.py`, `bot/database/methods/mailings.py`.
- Not live-tested in Telegram by Claude: only unit tests, a fake bot and headless Chromium for the editor script.

## Open items (need the owner)

1. **Prices for the UMBRA import** — price per weight (50 g, 200 g) in MDL; copy
   `scripts/umbramd/prices.template.csv` → `data/prices.csv`. Then run the importer (steps in the README).
2. **Decide**: also import the site's *Puff* (e-cigarettes) and accessories sections? Currently hookah tobacco only.
3. The owner's existing test categories ("Premium hookah tobacco", "Accessories", "Electronic cigarettes") can be
   reused with `--top-category` or cleaned up.
4. Promote `development` → `main` when the owner is satisfied (manual).
5. Set real `MIA_*` details when MIA should be offered; real `PICKUP_ADDRESS` / `DELIVERY_INFO`.
6. Deployed bot must be updated: `git pull && docker compose up -d --build`, then `/start`.

## Known limitations / risks

- **Welcome line.** Telegram needs a message to hold the reply keyboard, so one short welcome message always stays at the
  top of the chat (it cannot be fully invisible). Untested on a real device since the last two changes.
- **CI on the last merges.** PRs #15–#17 were merged while CI was still running (runs show *cancelled*). The same code
  passed the full suite locally; the next PR's CI will be the first full CI run on this state — check it.
- Changing an option's **label** in the web rows = delete + create (its stock is lost). The price/stock typed on a
  product that has options are ignored. Renaming a head in the *bot* flow does not rename its options.
- The web delete of a head removes its options in a separate step first (a failure in between could leave a head
  without options).
- Descriptions are still three language fields in the web form (names are one field). Easy to collapse if wanted.
- Orders in the web panel are action-only (no free editing) by design.
- The importer clears no caches in a *running* bot's in-memory tier (it flushes Redis when available); restart the bot
  after a big import if anything looks stale.
- Not implemented on purpose: order **ownership** ("who is preparing this order") — the owner chose to skip it.

## Environment notes for a new session

- Outbound network is behind a proxy; `umbramd.com` is reachable now (owner opened full internet).
- Local PostgreSQL 16 exists in the container for migration checks (start with `pg_ctlcluster 16 main start`).
- Headless Chromium is at `/opt/pw-browsers/chromium-*/chrome-linux/chrome` (used to smoke-test the web-panel script
  via `--dump-dom`); there is no Playwright Python package.

## Where things are documented

`CLAUDE.md` (agent handoff) · `README.md` (manual: features, config, admin, import) · `docs/run-and-test.pdf`
(step-by-step test guide; source `docs/run-and-test.md`, build with `python docs/build_pdf.py`) · `.env.example`.
