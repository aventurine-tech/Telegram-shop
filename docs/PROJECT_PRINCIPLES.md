# Project principles and the owner's requirements register

## 1. What we are building

A Telegram shop for **physical goods**, run by a small team from chat and from a web panel, replacing an older bot that ran on
Botobot. First catalog: UMBRA hookah tobacco (umbramd.com). The owner is the product owner and tester; work is delivered in
small pull requests that the owner can review, merge and roll back one by one.

## 2. Product principles

1. **Two payments only** — **MIA** (instant transfer, *verified by a human*; the bot never treats "I've paid" as proof) and
   **cash on delivery / pickup**. No card gateways, Stars or crypto.
2. **Physical goods, real stock.** Integer stock, reserved when an order is placed, released on cancel; overselling is
   impossible by construction (database transaction with row locks).
3. **Three languages, everywhere.** English, Russian, Romanian in the bot *and* in the web panel; each person gets their own
   language (asked at `/start`, remembered; per-recipient notifications). Wording must be natural and professional, not literal.
4. **Customer sees one clean screen.** Clean chat: the current screen only; a permanent bottom menu (Catalog · Cart · Profile)
   carried by a localized welcome line that always stays *above* the menu. No stray helper messages.
5. **Staff can do everything from either place** — chat or web — with the same rules (the web order actions call the same code
   as the bot). Roles/permissions control who sees what; web accounts have Admin and Staff levels.
6. **Currency MDL**, prices as decimals with two places.
7. **Botobot as the benchmark for the back office** — grouped menu, mailings with a rich editor, client records with order
   history, shipping, import — "replicate it for our needs, and make it better".
8. **No personal-data imports; profiles fill themselves** from Telegram and from orders.

## 3. Engineering principles

1. **The database enforces the invariants** (constraints, transactions, locks) — never the UI alone.
2. **Small, reversible changes.** One branch and one PR per change; one squash commit per PR; migrations additive and
   reversible; rollback = revert the squash commit (+ `alembic downgrade -1`).
3. **Test what you change; verify honestly.** Unit/integration tests for every change; migrations on a real PostgreSQL; panel
   scripts in a real (headless) browser; and say plainly what was *not* verified (live Telegram).
4. **Documentation is part of the product.** README (manual), CHANGELOG, ROADMAP, module status and the rulebooks are updated in
   the same PR as the code.
5. **Secure by default.** Least privilege, parameterised queries, escaped output, rate limits, audit log, no secrets in git
   (`docs/SECURITY.md`).
6. **Simple over clever.** Match the surrounding style, avoid new dependencies, no speculative abstractions, no dead code.
7. **Fail soft for customers, loud for staff.** A failed nicety (profile refresh, keyboard message) never blocks an order or
   the menu; real failures are logged and visible.

## 4. Owner's requirements register

Everything the owner asked for or ruled on, with where it lives. IDs are stable — refer to them in PRs.
(Reasoning for the larger decisions: [`DECISIONS.md`](DECISIONS.md).)

### Process
| ID | Requirement | Where enforced |
|---|---|---|
| R-01 | Every change = its own branch `claude/<topic>` from `development` + PR **into `development`**; merge when CI is green | `GIT_WORKFLOW.md` |
| R-02 | **`main` is never touched**; promotion is manual | `AGENTS.md` §1 |
| R-03 | Never touch the owner's `.env`; tell them what to add by hand | `AGENTS.md` §1 |
| R-04 | Report honestly what was and was not verified (nothing live in Telegram by Claude) | `AGENTS.md` §1 |
| R-05 | The owner may merge early; re-check `development`, re-apply missed commits on a fresh branch | `GIT_WORKFLOW.md` |
| R-06 | Keep documentation current so a new chat session can continue (CLAUDE.md, AGENTS.md, status, roadmap, changelog) | `AGENTS.md` §10 |

### Shop behaviour
| ID | Requirement | Since |
|---|---|---|
| R-10 | Physical goods, integer stock reserved at order and released on cancel | #1 |
| R-11 | Payments: MIA (staff-verified) and cash on delivery/pickup only | #1 |
| R-12 | Delivery or pickup at checkout; delivery can be priced by shipping methods (price, free-from threshold) | #1, #23 |
| R-13 | Orders: new → confirmed → shipped → completed / cancelled; staff act from chat or web; clear, status-aware buttons | #1, #15 |
| R-14 | Subcategories (two levels); top categories on the main menu; "Premium hookah tobacco → Classic" shown as real navigation, not only a dropdown | #6, #12 |
| R-15 | Products with weight options (50 g / 200 g…) each with own price and stock, shared picture/description; **variants never appear as separate products** in lists | #7 |
| R-16 | Product pictures stored as uploaded; shown on the card | #1 |
| R-17 | Customer data: name, @username, phone, address (if given), order history visible to staff — **no import** | #22 |

### Languages and wording
| ID | Requirement | Since |
|---|---|---|
| R-20 | EN/RU/RO in bot and web, per-user language remembered | #1 |
| R-21 | Catalog names/descriptions in three languages; **product name is a single field** in the web form (descriptions per language); name under "Name of category", then other languages; own language first | #3, #4, #11, #13 |
| R-22 | Welcome line text: *Romanian: Bun venit la UMBRA · English: Welcome to UMBRA · Russian: Добро пожаловать в UMBRA*, **always above the menu, never below** | #16, #17 |
| R-23 | **Everything in the web portal translated** (including list/form/dialog chrome, validation) with professional wording; Romanian mailings are **Campanii**, not "Mesaj în masă" | #21 |

### Chat experience
| ID | Requirement | Since |
|---|---|---|
| R-30 | Customer sees only the current menu, no chat history; `/start` clears the clutter | #8 |
| R-31 | Permanent bottom menu on every screen (sticky) | #5 |
| R-32 | **No "quick menu is always at the bottom" notice** and no one-character helper message visible — only the shop menu and the sticky bottom menu | #9, #14, #16 |

### Web panel
| ID | Requirement | Since |
|---|---|---|
| R-40 | Multi-account panel; roles shown as **tags**, not a binary number | #1, #15 |
| R-41 | Grouped dropdown sidebar: Orders · Clients · Payments · Catalog · Marketing · Settings · Log out (Botobot-like) | #19 |
| R-42 | **Mailings** like Botobot, better: image, rich text (bold/italic/link), placeholders with defaults, segments, schedule, live preview + counter, test to myself, message options, delivered N out of M | #20 |
| R-43 | Options of a product inside the product form as rows with a **＋** button ("Option 1, Option 2") | #13 |
| R-44 | Shipping functionality (delivery methods with prices) managed in the panel, off until configured | #23 |
| R-46 | Profile: **no Operation History**; the customer keeps **Name and Surname, Phone, City, Address** (Profile → My details) and checkout offers them | profile-details PR |
| R-45 | Product card: **⭐ Favorites** under each product; **no "Order now"** under the product; **Apply promo code lives in the Cart** between Checkout and Clear cart | favorites PR |

### Catalog source
| ID | Requirement | Status |
|---|---|---|
| R-50 | First catalog = UMBRA (umbramd.com), crawled with its 18+ prompt bypassed; a flavour sold in two strengths = two products; originals ≤ 14 MB fall back to the thumbnail | built (#10) |
| R-51 | Prices per weight supplied by the owner (`data/prices.csv`) before the live import | **open** |
| R-52 | Puff/accessories sections: owner to decide | **open** |

## 5. Changing a requirement
Requirements change only when the owner says so. Record the change here (new ID or a *superseded by* note), in
`DECISIONS.md` if there is reasoning worth keeping, and in `CHANGELOG.md` when code changes.
