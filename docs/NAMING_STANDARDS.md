# Naming standards

Consistency over taste: follow what is already there; when in doubt, grep for the nearest sibling.

## Git
| Thing | Rule | Example |
|---|---|---|
| Branch | `claude/<topic>`, lowercase-hyphen | `claude/client-profiles` |
| Commit subject | Imperative/descriptive sentence, what the user gets | `Shipping methods: price, free-from threshold, …` |
| PR title | One line, same style as the squash commit | `Web panel fully translated (EN/RU/RO); professional mailing wording` |

## Python
| Thing | Rule | Example |
|---|---|---|
| Modules | `snake_case.py`, named for their responsibility | `mailing_sender.py`, `item_options.py` |
| Functions / variables | `snake_case`; async functions are not suffixed | `create_order_transaction`, `active_methods` |
| Classes | `PascalCase`; ORM models plural for tables of many (`Orders`, `Goods`, `ShippingMethods`) except legacy `User`, `Role` | `Mailings` |
| Web views | `<Model>Admin` (SQLAdmin `ModelView`), `identity` derived from the model | `MailingAdmin`, `ShippingAdmin` |
| Constants / enums-as-classes | `UPPER_SNAKE` members on a plain class | `MailingStatus.SENDING`, `Fulfillment.DELIVERY` |
| Private helpers | leading underscore; module-level only when shared in-module | `_apply_shipping` |
| Failure codes returned by transactions | lowercase snake strings, documented in the docstring | `shipping_required`, `price_changed` |

## Database
| Thing | Rule | Example |
|---|---|---|
| Tables | plural snake_case | `shipping_methods`, `web_users` |
| Columns | snake_case; money `Numeric(12, 2)`; booleans `is_…` or a plain adjective; timestamps `…_at` (timezone-aware) | `is_active`, `scheduled_at`, `delivery_fee` |
| Translations | `<field>_<lang>` with `lang ∈ {en, ru, ro}` | `name_ru`, `description_ro` |
| Constraints / indexes | `ck_<table>_<what>`, `ix_<table>_<column>` | `ck_shipping_price_nonneg`, `ix_users_username` |
| Migration file | `<12-hex revision>_<slug>.py`; revision id is the 12-hex string; **one head** | `d1f6b8c4e5a7_shipping_methods.py` |
| Migration style | additive, guarded with `inspect(...)`, `downgrade` mirrors `upgrade` | |

## i18n keys (`bot/i18n/strings*.py`, Romanian in `strings_ro_*.py`)
Dotted, lowercase, namespaced from general to specific; placeholders in `{braces}` identical in every language.

| Namespace | Use |
|---|---|
| `btn.*` | button labels (`btn.checkout.ship`) |
| `checkout.*`, `cart.*`, `shop.*`, `profile.*`, `menu.*` | customer screens and messages |
| `order.*` | order card, statuses, methods (`order.status.new`, `order.line.delivery`) |
| `admin.*` (bot admin) | staff screens in chat |
| `web.menu.<group>` | sidebar group titles |
| `web.model.<name>.one` / `.many` | singular / plural model names (menu + page titles) |
| `web.col.<column>` | column labels (shared by lists, forms, details) |
| `web.sa.*` | SQLAdmin chrome (buttons, pagination, dialogs) |
| `web.<feature>.*` | feature text: `web.mailing.*`, `web.shipping.*`, `web.client.*`, `web.promo.*`, `web.account.*`, `web.my.*` |
| `web.<feature>.err.*` / `.notice.*` / `.action.*` | validation errors / banners / action labels |
| `web.perm.*`, `web.help.*` | permission labels, the panel's cheat-sheet page |

Wording: natural, professional, consistent terminology per language (see §Glossary). Romanian uses **ș ț** (comma below), never ş ţ.

## Telegram callbacks and states
- `callback_data` is a short snake_case verb or `prefix:argument`; prefixes by flow: `co_` (checkout: `co_ful:`, `co_ship:`, `co_pay:`),
  `cart_`, `shop`, `profile`… Max 64 bytes. Handlers match on the exact string/prefix; stale buttons are answered by a catch-all.
- FSM: `<Flow>FSM` classes in `bot/states/`, state names are gerunds/`waiting_*` (`choosing_shipping`, `waiting_address`); FSM data keys
  are prefixed per flow (`co_total`, `co_ship`).

## Web panel
- Templates `snake_case.html` in `bot/web/templates/`; override a SQLAdmin template by using its exact name.
- Sidebar groups are the `category` of a view: `clients`, `payments`, `catalog`, `marketing`, `settings`; DOM ids `menu-group-<category>`.
- Routes outside SQLAdmin: lowercase-hyphen paths (`/mailing-image/{id}`, `/export/users`) and always check `current_web_user`.

## Config
Env vars `UPPER_SNAKE`; booleans are `"1"`/`"0"`; every variable is documented in `.env.example` (comment above it) and in the README table.

## Tests
`tests/test_<area>.py`; classes `Test<Behaviour>`; functions `test_<what_happens>` in plain sentences
(`test_a_method_switched_off_meanwhile_is_refused`). Fixtures named for what they yield (`boss`, `shop`).

## Glossary (use these words consistently)
| EN | RU | RO |
|---|---|---|
| Customer / Client | Клиент | Client |
| Order | Заказ | Comandă |
| Cart | Корзина | Coș |
| Catalog | Каталог | Catalog |
| Shipping / Delivery | Доставка | Livrare |
| Pickup | Самовывоз | Ridicare |
| Mailing | Рассылка | Campanie |
| Audience / Group | Группа | Grup |
| Promo code | Промокод | Cod promoțional |
| Balance | Баланс | Sold |
| Settings | Настройки | Setări |
