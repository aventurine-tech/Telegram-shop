# Decision log

Architecture and product decisions with the reasoning, newest information last in each entry. Format: **Context → Decision →
Consequences**. Add an entry when a choice would otherwise be re-litigated later; never rewrite history — mark an entry
*Superseded by D-xx* instead. (Owner requirements themselves live in `PROJECT_PRINCIPLES.md` §4.)

---

### D-01 One process, one event loop
**Context** small shop, small team, simple deploy (`docker compose up`). **Decision** the bot, the web panel (Starlette/SQLAdmin)
and the background services (`recovery`, `cleanup`, mailing scheduler) run in one asyncio process; no broker, no worker pool.
**Consequences** simple ops; long jobs must be chunked and cancel-aware (mailings send in batches); a restart interrupts running
jobs, so jobs must be restart-safe (D-12).

### D-02 Tests on SQLite, migrations on PostgreSQL
**Context** fast, hermetic unit tests vs. production PostgreSQL behaviour. **Decision** the suite runs against in-memory async
SQLite; CI adds a separate job that runs `alembic upgrade → downgrade -1 → upgrade` on PostgreSQL 16. **Consequences** SQL that
only PostgreSQL understands is verified by the migration job and by hand locally; text comparison of non-ASCII must be done in
Python (SQLite `lower()` is ASCII-only).

### D-03 Canonical name vs translations
**Context** names must be unique lookup keys and shown in three languages. **Decision** `name`/`description` hold the main
language (`BOT_LOCALE`) and are the keys; `name_en/ru/ro` are display-only with fallback to canonical (`pick`). Admin input
in any language is resolved to the canonical row. **Consequences** renames must keep the canonical key stable; the web product
form has **one** name (owner request R-21) and sets all three equal.

### D-04 Weight options are separate product rows
**Context** UMBRA sells 50 g / 200 g with different prices and stock. **Decision** each option is its own `Goods` row
(`variant_of` → head, `variant_label`, name `"<head> · <label>"`); lists/search show heads only; a head with options is a
gateway (not addable to the cart); reviews and picture/description belong to the head. **Consequences** stock, price, sale, cart
and order lines work unchanged per option; renaming a head in the bot does not rename options (web rows do).

### D-05 Two category levels
A category holds subcategories **or** products, never both; parents are always top-level. Keeps navigation simple and the main
menu (top categories) predictable. Promo codes bound to a parent also cover its subcategories.

### D-06 Clean chat
**Context** owner: "I only want the current menu, no history". **Decision** a middleware tracks one *screen* message per private
chat; a bot send during an update deletes the previous screen; the user's own message is deleted after handling; background sends
and sends to other chats are untouched; `CLEAN_CHAT=0` disables. **Consequences** Telegram only lets bots delete messages younger
than 48 h; `/start` sweeps the 100 ids before it; handlers use `outside_screen()` for messages that must stay.

### D-07 The welcome line carries the bottom keyboard
**Context** a reply keyboard needs a message to live on; deleting that message drops the keyboard; Telegram rejects blank,
zero-width and Braille-blank text ("text must be non-empty"); the owner does not want helper text or odd symbols. **Decision**
the carrier is a localized welcome line (*Bun venit la UMBRA / Welcome to UMBRA / Добро пожаловать в UMBRA*); it is excluded from
clean-chat tracking, a new one is sent *before* the screen and replaces the old after it is delivered; on language change the
picker is removed, the welcome line is sent first, then the profile. **Consequences** exactly one short line stays at the top of
the chat (cannot be invisible); history: #9 → #14 (hotfix) → #16 → #17.

### D-08 Stock reservation and MIA timeout
Stock is reserved when the order is created (not at payment) so two buyers cannot take the last unit; an unpaid MIA order is
cancelled and its stock/balance returned after `MIA_PAY_TIMEOUT_MIN`. All of it runs in `orders.py` transactions under row
locks; the web actions reuse them.

### D-09 Orders in the web panel are action-only
Orders are not freely editable (no create/edit/delete); the details page offers only the status moves valid for the order's
state, which call `apply_order_action`. This keeps stock, balance and referral rules impossible to bypass from the panel.

### D-10 Keep SQLAdmin, own its templates
**Context** SQLAdmin 0.16.1 gives CRUD quickly but is English-only and has quirks. **Decision** keep it pinned, override templates
in `bot/web/templates/` (layout, macros, list/create/edit/details/modals, details pages), route every string through `localize()`
(`web.*`), wrap forms with `LocalizedForm`. **Consequences** a SQLAdmin upgrade needs a template diff review; quirks are recorded
in `CLAUDE.md`.

### D-11 Roles are a permission bitmask, shown as tags
11 permission bits; a role may only grant what the grantor has; the web form shows checkbox tags and stores their sum
(owner R-40).

### D-12 Mailings are never resumed after a restart
**Context** a restart in the middle of a send could otherwise re-send to people who already got the message. **Decision** on
startup mailings in *sending* become *Interrupted* and are not resumed; the owner can duplicate and send to the remainder.
**Consequences** no duplicate sends; the per-recipient log (4.6) lets staff *Resend to failed* as a new draft; resuming (6.2) is still on the roadmap.

### D-13 Mailing design
Text is sanitised to Telegram's tag set (b, i, u, s, code, pre, spoiler, safe links); placeholders `{first_name|default}` are
resolved per recipient from `bot.get_chat`; batches of 25 with a 1 s pause (well inside ~30 msg/s); caption ≤ 1024 else picture
then text; picture uploaded once and reused by `file_id`; blocked users are skipped and counted; scheduling is stored in UTC and
polled every 15 s by `RecoveryManager`; audiences are computed (language / has orders), NULL language counts as the main language.
Admin-role only (D-19).

### D-14 No client import tool
The owner showed a Botobot export (1,380 clients) but asked for the **functionality** — profiles with username, phone, address and
order history — and explicitly **not** an import. Profiles fill from Telegram (middleware) and from orders (transaction);
the migration back-fills phone/address from existing orders. Clients imported into the Botobot-era bot would also only be
mailable if they had started the *active* bot token.

### D-15 Shipping fee is part of the order total
**Decision** the fee is added to `orders.total` (and stored in `delivery_fee` with the method name) so payment, balance and
referral code needn't change; computed server-side and included in `expected_total`. With **no active shipping method delivery is
free and unpriced** (previous behaviour), so enabling is just adding a method. **Consequences** referral commission is currently
computed on the paid total including the fee (roadmap 6.1); the order stores the method's canonical name only (roadmap 4.10).

### D-16 Profile freshness without write amplification
`ProfileMiddleware` runs after the handler (a new user is created by `/start` itself) and writes only when username/name changed
or the last write is older than 5 minutes (in-memory throttle); failures are swallowed. Phone/address are written by the order
transaction (latest order wins; pickup does not erase the address).

### D-17 Order ownership skipped
"Who is preparing this order" was offered and declined by the owner.

### D-18 Merge strategy
Squash merge into `development` (one PR = one commit = one revert). Dependent PRs merge `development` into themselves
(merge commits, no rebase/force-push). Merge with the **full** head SHA as `expectedHeadSha`. Translation files conflict at the same
anchor when two PRs add keys: keep both sides and drop exact duplicate keys, then run the i18n tests.

### D-19 Mailings are Admin-only
Mass messaging is the riskiest action in the panel; the *Mailings* view and the image route require the Admin web role. Staff
see Orders/Clients/Catalog etc. as before.

### D-20 UMBRA catalog import — superseded by D-21
A crawler/importer for umbramd.com was built (#10); it was never run on the live shop and has been removed (D-21).

### D-21 Catalog is entered by staff
**Context** the owner cancelled the open items *prices per weight* and *Puff/accessories import*. **Decision** products, options, prices and stock are created in the bot or the web panel by staff; the crawler, importer, scraped data and price template were deleted. **Consequences** no import code path to maintain; bulk import may return as a web-panel feature (roadmap 4.1) if the owner asks.

### D-23 Two-step sign-in is optional (owner, 2026-10-08)
**Context** the owner asked for 2FA on panel accounts, "optional, not forced for users". **Decision** time-based codes (RFC 6238, any authenticator app) plus 8 one-time backup codes, switched on by each person under *My account*; never required by the shop. The second step is a field on the normal login form (no half-signed-in state). The secret is stored encrypted with a key derived from `SECRET_KEY`; used codes cannot be replayed; an Admin can reset an account. **Consequences** no new dependency and no QR code (people type the setup key); rotating `SECRET_KEY` locks 2FA accounts out until reset; the login limiter stays per-process.
