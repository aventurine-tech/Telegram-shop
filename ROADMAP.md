# Roadmap

Planning document. **The owner sets priorities**; items below are proposals unless marked *requested*. Status legend:
✅ done · 🟡 in progress / waiting on the owner · ⬜ planned · 💡 idea (not committed) · ⛔ declined.
History of what was delivered lives in [`CHANGELOG.md`](CHANGELOG.md); the current state in [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md).

## Phase 0 — Foundation ✅ (PR #1–#4)
Physical-goods shop from the digital-goods upstream: orders with stock reservation, MIA + cash on delivery/pickup, delivery or
pickup, web accounts, EN/RU/RO, translated catalog, CI with PostgreSQL migration check.

## Phase 1 — Catalog shape & chat experience ✅ (PR #5–#17)
Bottom keyboard, subcategories, weight options, clean chat, welcome line, role tags, status-aware order buttons.

## Phase 2 — Botobot-style back office ✅ (PR #19–#23)
Grouped sidebar · Mailings (editor, audiences, schedule, delivery report) · fully translated panel · client profiles with order
history · shipping methods with prices.

## Phase 2b — Customer polish ✅ (PR #27–#31)
Light/dark panel theme · ⭐ Favorites and promo code in the cart · Profile → My details with checkout "use saved" · ☰ bot command
menu · UMBRA crawler/importer removed (catalog is entered by staff, D-21).

## Phase 3 — Go live 🟡 (blocked on the owner)
| # | Item | Status | Needs |
|---|---|---|---|
| 3.3 | Real `MIA_*`, `PICKUP_ADDRESS`, `DELIVERY_INFO`; add the first **shipping methods** | 🟡 | owner: data |
| 3.4 | Live acceptance pass of the whole flow on a real phone (order → MIA → staff verify → shipped → completed; mailing test; language switch; clean chat) | 🟡 | owner + Claude fixes from screenshots |
| 3.5 | Promote `development` → `main` | ⬜ | owner's decision |
| 3.6 | Production hardening checklist: strong `SECRET_KEY`/`ADMIN_PASSWORD`, HTTPS in front of the panel, DB backups, log rotation | ⬜ | owner/ops (see `docs/SECURITY.md`) |

## Phase 4 — Back-office parity with Botobot (proposals)
| # | Item | Notes |
|---|---|---|
| 4.1 | **Import page in the web panel** (CSV/XLSX price list: dry-run preview, apply, history) | Botobot's *Catalog → Import*. The old UMBRA crawler/importer was removed (#31, D-21); only comes back if the owner asks. |
| 4.2 | ✅ **Print order / packing slip** (printable order page) | Button on the order page |
| 4.3 | **Customer groups** (manual tags like "VIP", used as mailing audiences) | Botobot's *Group*; today audiences are computed (language / has orders) |
| 4.4 | ✅ **Unsubscribe / "mailing: yes/no"** per customer + opt-out button under every mailing and a profile toggle | |
| 4.5 | ✅ Mailing **scheduling in the shop timezone** (`SHOP_TIMEZONE`, default Europe/Chisinau) | |
| 4.6 | ✅ Mailing **per-recipient log** and a "resend to failed" action | |
| 4.7 | ✅ Orders list: localized statuses/payment labels, filters by status/date/payment | |
| 4.8 | ✅ Dashboard on the panel home: orders/revenue/new clients per day, top products, what needs attention | 7 / 30 / 90 days |
| 4.9 | Shipping zones / cities, per-method delivery notes and time estimates | Builds on shipping methods |
| 4.10 | ✅ Localized **shipping name on orders** (per-language snapshot) | Old orders back-filled from the method |

## Phase 5 — Customer experience (proposals)
| # | Item |
|---|---|
| 5.1 | ✅ Prefill checkout name/phone/address from the saved profile — delivered in #29 |
| 5.2 | ✅ Re-order from *My orders* (completed / cancelled orders) |
| 5.3 | ✅ Order status notifications with tracking text (note on the order page, sent with *shipped*) |
| 5.4 | ✅ "Notify me" for sold-out options: already worked per option; sold-out marks in the selector and an *Open product* button on the notice added (the wishlist is ⭐ favorites) |
| 5.5 | ✅ Product search by the words describing a product (name, flavour, strength, option, category) | All words must match |

## Phase 6 — Platform & quality (proposals)
| # | Item |
|---|---|
| 6.1 | ✅ Referral commission **excluding the delivery fee** |
| 6.2 | ✅ Resumable mailings after a restart (uses the delivery log; ≤ 24 h; `MAILING_RESUME=0` = old behaviour) | A crash mid-batch can repeat up to 25 messages |
| 6.3a | ✅ Payment reminders for customers and stale-order alerts for staff (MIA / cash) |
| 6.3b | ✅ Error alerts to the owner / a staff chat (deduplicated, rate-limited) and a secret scan in CI |
| 6.2b | ✅ Optional two-step sign-in (authenticator app + backup codes) for panel accounts — never forced |
| 6.3 | Structured JSON logging; metrics dashboard for the existing `/metrics` |
| 6.4 | ✅ Automated DB backup/restore script + guide (`docs/BACKUP_AND_RESTORE.md`); "erase a client" action. Still open: a retention policy that deletes old personal data automatically |
| 6.5 | Browser-level tests for the web panel scripts (Playwright) in CI; coverage gate |
| 6.6 | Split `bot/web/admin.py` (≈1,700 lines) into per-area modules |
| 6.7 | Release process: version numbers, dated CHANGELOG releases, tagged `main` promotions |

## Declined / out of scope ⛔
- Order **ownership** ("who is preparing this order") — owner chose to skip.
- Online card payments, Telegram Stars, crypto — removed on purpose; exactly two payments (MIA, cash).
- Importing the Botobot client export — the owner wants the *functionality* (profiles), not the import.

## How the roadmap is maintained
Review at the start of each working session and after each merged PR: move delivered items to ✅ (and into the changelog),
add owner requests with *requested*, date the change in the PR. New ideas go to the table as 💡 until the owner picks them.
