# Project state

_Last updated: 2026-10-07, after PR #31. Branch of record: `development`; `main` is untouched on purpose._
History: [`../CHANGELOG.md`](../CHANGELOG.md) · plans: [`../ROADMAP.md`](../ROADMAP.md) · per-module detail: [`MODULE_STATUS.md`](MODULE_STATUS.md).

## In one paragraph
A Telegram shop bot for physical goods (MIA transfer verified by staff, or cash on delivery / pickup) with a catalog of categories →
subcategories → products → weight options, order tracking, staff roles, a Botobot-style multi-account web panel (grouped menu, mailings,
client profiles with order history, shipping methods, payments to verify) and English / Russian / Romanian everywhere. Everything is
**built, merged into `development` and covered by automated tests** (last full count 2055 passed; not re-counted after #27–#31). Nothing has been signed off in a live shop yet:
the owner is testing the deployed bot and reporting issues from screenshots.

## What exists (all merged)
| Area | State |
|---|---|
| Customer flow: catalog, search, cart, promo, checkout (delivery/pickup, **shipping choice**), MIA + COD, My orders, referrals, balance, reviews, restock "notify me" | Done |
| Staff flow in chat: orders, catalog and stock, promo, users, roles, broadcast, stats | Done |
| Web panel groups: **Orders · Clients · Payments · Catalog (Products, Categories, Shipping) · Marketing (Mailings, Promo codes, Reviews) · Settings (Web accounts, Roles, Audit log, My account) · Log out** | Done |
| Mailings (editor, audiences, schedule, delivery report, test to me) | Done — not yet tried live |
| Client profiles (name, @username, phone, address, notes, order history) | Done |
| Shipping methods (price, free-from, active, position; fee on the order) | Done — add the first method to use it |
| Whole panel translated (chrome, forms, validation) | Done |
| Languages en/ru/ro in bot and web; per-user language remembered | Done |
| Weight options, subcategories, pictures, translated catalog | Done |
| Bottom keyboard + welcome line, clean chat | Done (see risks) |
| ☰ command menu (`/start /catalog /cart /orders /favorites /profile /language`), ⭐ Favorites, Profile → My details with checkout "use saved" | Done (#28–#30) |
| Web panel light/dark theme | Done (#27) |

## Open items (need the owner)
1. Add real `MIA_*` details, `PICKUP_ADDRESS` / `DELIVERY_INFO` to the server `.env`, and create the first **shipping method(s)**.
2. Send yourself a **mailing test** (Settings → My account → Telegram ID; Marketing → Mailings → *Send test to me*) before the first real campaign.
3. Deploy the latest code: `git pull && docker compose up -d --build`, then `/start` (migrations run on start).
4. Promote `development` → `main` when satisfied (manual, owner only).
5. Priorities for the next phase — see `ROADMAP.md` Phase 4–6 (customer groups, unsubscribe, …).

## Known limitations / risks
- **Welcome line.** Telegram needs a message to hold the reply keyboard, so one short welcome line always stays at the top of the chat.
  Not re-verified on a real device since #16/#17.
- **Unverified live:** nothing (clean chat, mailings, shipping, profiles) has been seen working in real Telegram by Claude.
- Mailings: interrupted by a restart ⇒ marked *Interrupted*, never resumed.
- Option label change in the web rows = delete + create (stock of that option is lost); renaming a head in the bot does not rename options.
- Web login limiter is per-process. Two-step sign-in is optional per account (authenticator app; Admin can reset); losing `SECRET_KEY` locks those accounts out until an Admin resets them.
- Not built on purpose: order **ownership**; client **import**; catalog crawler/importer (removed in #31 — staff enter the catalog, D-21).

## Environment notes for a new session
- Outbound network is proxied/allow-listed.
- Local PostgreSQL 16 for migration checks: `pg_ctlcluster 16 main start` (DB `migdb`, user/password `mig`).
- Headless Chromium at `/opt/pw-browsers/chromium-*/chrome-linux/chrome` for panel-script smoke tests; no Playwright Python package.
- GitHub through the MCP tools (no `gh`); PR/branch rules in `GIT_WORKFLOW.md`.

## Resume checklist for a new session
(Ready-made prompt: [`NEW_SESSION_PROMPT.md`](NEW_SESSION_PROMPT.md).)
1. Read `AGENTS.md` (+ `CLAUDE.md`), then this file.
2. `git fetch origin`; check `origin/development` vs. your branch; check open PRs and their CI.
3. Ask the owner only for the open items above that still block you.
4. Work in a branch per change; keep `CHANGELOG.md`, `ROADMAP.md`, `MODULE_STATUS.md` and this file current.

## Where things are documented
`AGENTS.md` (rulebook) · `CLAUDE.md` (Claude Code handoff + quirks) · `README.md` (manual: features, config, admin) ·
`CHANGELOG.md` · `ROADMAP.md` · `docs/` — `PROJECT_PRINCIPLES` (requirements register), `DECISIONS`, `GIT_WORKFLOW`, `NAMING_STANDARDS`,
`TESTING`, `SECURITY`, `ENTERPRISE_STANDARDS`, `MODULE_GUIDE`, `MODULE_STATUS`, `run-and-test.pdf` (source `run-and-test.md`,
`python docs/build_pdf.py`) · `.env.example`.
