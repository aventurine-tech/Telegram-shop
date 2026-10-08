# Module guide

How the code is organised and how a request flows through it. For the product-level view see the README; for what is built vs.
planned see [`MODULE_STATUS.md`](MODULE_STATUS.md).

## 1. Runtime picture
One process, one asyncio loop (D-01): the aiogram dispatcher (long polling or webhook), the Starlette/SQLAdmin web panel (uvicorn) and
background tasks (`RecoveryManager`, `CleanupManager`, `CacheScheduler`). PostgreSQL is the source of truth; Redis is optional.

**Update path** (registration order in `bot/main.py`; first registered = outermost):
`CleanChat` → rate limit (Redis-atomic or in-process) → analytics → **auth** (role cache, blocked users) → **language** (per-update
ContextVar) → **profile** (`ProfileMiddleware`, after the handler) → **security** (audit, maintenance gate, 1 h replay guard) →
routers: `language` → `bottom_nav` → `admin` → `other` → `user`.

## 2. Package map

### `bot/` entry and infrastructure
| Path | Responsibility |
|---|---|
| `main.py` | startup: DB, cache, middlewares, routers, web app, services, graceful shutdown |
| `logger_mesh.py` | logging setup (stdout/file/audit) |
| `misc/env.py` | all configuration (`EnvKeys`), startup safety checks |
| `misc/localized.py` | `LANGS`, `pick`, `derive_canonical`, `clean_name/description`, name-length limits |
| `misc/images.py` | picture validation (type, size, pixels) |
| `misc/mailing_text.py` | mailing HTML sanitiser, visible length, placeholders (`personalize`) |
| `misc/validators.py` | phone/name/address validators |
| `misc/caching/` | cache manager (Redis + in-process), scheduler, stats cache |
| `misc/metrics.py` | counters, funnels, `/metrics` data |
| `misc/services/` | long-running/domain services (see §3) |

### `bot/database/`
| Path | Responsibility |
|---|---|
| `main.py`, `dsn.py` | async engine, `Database().session()`, declarative base |
| `models/main.py` | **all ORM models** and status/enum classes (`OrderStatus`, `PaymentMethod`, `Fulfillment`, `MailingStatus`, `MailingSegment`, `Permission`, `WebRole`) |
| `methods/orders.py` | **order transactions**: create (stock reservation, promo, balance, shipping fee), cancel, MIA verify, status changes, expiry, referral commission |
| `methods/dashboard.py` | numbers for the panel home page (`dashboard_data`: per-day orders/revenue/clients in the shop timezone, top products, attention box) |
| `methods/shipping.py` | active shipping methods, `delivery_fee` |
| `methods/mailings.py` | audiences, claim/progress/finish/cancel, restart handling |
| `methods/profiles.py` | `refresh_profile` (Telegram names/username/last seen) |
| `methods/item_options.py` | weight options sync (`sync_item_options`) |
| `methods/translations.py` | name resolution in any language, translated labels |
| `methods/product_images.py`, `web_users.py`, `audit.py`, `pricing.py`, `transactions.py` | pictures · web accounts · audit log · prices/promos · balance ops |
| `methods/create/read/update/delete.py` | generic CRUD helpers with cache invalidation |
| `methods/lazy_queries.py` | paginated queries (heads-only product lists, order lists) |

### `bot/handlers/`
| Path | Responsibility |
|---|---|
| `user/main.py` | `/start`, welcome line, profile, referral entry, registration |
| `user/bottom_nav.py` | the persistent keyboard actions |
| `user/shop_and_goods.py`, `cart.py`, `checkout.py` | catalog, cart, checkout FSM (fulfilment → name → phone → address → **shipping** → comment → payment → summary), MIA "I've paid" |
| `user/language.py`, `referral_system.py`, `_screen.py` | language picker, referrals, screen helpers |
| `admin/*` | staff flows in chat: orders, goods + options, categories, translations, promo, sales, roles, users, shop settings, broadcast (text) |
| `other.py` | misc commands/fallbacks (stale buttons) |

### `bot/keyboards/`, `bot/states/`, `bot/filters/`, `bot/i18n/`
Inline/reply keyboards (`inline.py` includes `checkout_shipping_keyboard`), FSM state groups, permission filters, and translation
dictionaries (`strings*.py` en/ru, `strings_ro_*.py` ro; `localize()` reads the per-update language).

### `bot/middleware/`
`clean_chat.py` (one screen per chat, carrier tracking, `/start` sweep), `language.py`, `profile.py`, `rate_limit.py`, `security.py`.

### `bot/web/` (the panel)
| Path | Responsibility |
|---|---|
| `admin.py` | app factory `create_admin_app`, auth backend, `LocalizedModelView`/`AuditModelView`/`TranslatedModelView`, all ModelViews (orders, payments, clients, catalog, shipping, promo, reviews, roles, audit…), health/metrics routes |
| `mailings.py` | `MailingAdmin`, the rich editor widget, image route |
| `accounts.py` | `WebUserAdmin`, **My account** (password, language, Telegram ID) |
| `export.py` | CSV exports (users, orders, order items, operations) |
| `language.py`, `session.py`, `passwords.py` | panel language middleware (`LazyText`, `Localized`), signed-in user lookup, password hashing |
| `templates/` | `layout.html`, `_macros.html` (grouped sidebar), own copies of SQLAdmin `list/create/edit/details` + `modals/`, `order_details.html`, `client_details.html`, `mailing_details.html`, `my_account.html`, `login.html`, `index.html` (cheat-sheet), `error.html` |

### `migrations/`, `tests/`, `docs/`
Alembic revisions (single head), the suite (`TESTING.md`), documentation.

## 3. Background services (`bot/misc/services/`)
| Service | Does | Cadence |
|---|---|---|
| `recovery.RecoveryManager` | expires unpaid MIA orders (releases stock), health check, **dispatches due mailings** (claims one, runs `MailingSender`), marks interrupted mailings at startup | 60 s / 60 s / 15 s |
| `mailing_sender.MailingSender` | batches of 25 + 1 s, placeholders, photo reuse, cancel checks, test send | per mailing |
| `cleanup.CleanupManager` | retention of audit rows etc. | daily |
| `restock_notifier` | tells subscribers when a sold-out product returns | event-driven |
| `order_view` | order card text (customer/staff), staff alerts per language, delivery lines | on demand |
| `broadcast_system`, `recipients` | the bot-side text broadcast | on demand |

## 4. Key flows

**Checkout:** cart → fulfilment (delivery/pickup) → name → phone → [address → **shipping method** if active methods exist] → comment →
payment (balance toggle, MIA/COD) → summary (total incl. fee, recomputed from the live cart) → `create_order_transaction` (locks user + goods,
validates promo/shipping, checks `expected_total`, reserves stock, writes order + lines, saves phone/address to the profile) → staff alerts.

**Order lifecycle:** `new` → (MIA: staff verify payment) → `confirmed` → `shipped` → `completed` | `cancelled` (stock released). Web and bot both call
the same functions; completing pays the referral commission once.

**Mailing:** draft/scheduled row → `claim_due_mailing` (atomic scheduled→sending) → `MailingSender.run` (audience at that moment, batches, progress
counters, cancel checks) → `sent` | `cancelled` | `failed`. Restart: *sending* started < 24 h ago → *scheduled* again and resumed (the sender skips people in the delivery log); older → *Interrupted*.

**Language:** per update `LanguageMiddleware` sets the ContextVar from the user row; `localize()` formats with it; staff alerts are built once per
recipient language; the panel resolves language from the account/cookie (`LanguageMiddleware` in `bot/web/language.py`).

**Welcome line / clean chat:** see `DECISIONS.md` D-06/D-07 and `CLAUDE.md` quirks.

## 5. Where to add things
| I want to… | Touch |
|---|---|
| a new admin list/page | a `ModelView` in `bot/web/admin.py` (+ `category`, `web.model.<x>.one/many`, `web.col.*`), register in `create_admin_app`, tests |
| a new customer button/flow | keyboard in `keyboards/inline.py`, handler in `handlers/user/`, FSM state if it waits for text, strings en/ru/ro, tests with the handler doubles |
| a new table/column | model → migration (guarded, reversible) → `db_cleanup` if tests write to it → tests |
| a new setting | `EnvKeys` in `misc/env.py`, `.env.example`, README table |
| a new background job | a service in `misc/services/`, started/stopped by `main.py`/`RecoveryManager`, restart-safe, tested with a fake bot |
