# Prompt for starting a new chat session

Paste the block below as the **first message** of a new session. It tells the assistant what to read, which rules apply, where the
project stands and what is waiting on the owner. Keep it current: when the open items or the project state change, update the
"Where we stopped" part (and `docs/PROJECT_STATE.md`) in the same PR.

_Last updated: 2026-10-07 — everything through PR #31 is merged into `development`._

```
You are continuing work on the Telegram shop bot in the repository aventurine-tech/Telegram-shop (working dir /home/user/Telegram-shop). I am the owner (radug@aventurine.tech). I write in English/Russian and send screenshots of the live bot and web panel — treat them as bug reports.

START HERE, before doing anything:
1. Read AGENTS.md (the canonical rulebook), then CLAUDE.md, then docs/PROJECT_STATE.md.
2. Skim, as needed: docs/PROJECT_PRINCIPLES.md (my requirements register R-01…), docs/DECISIONS.md, docs/GIT_WORKFLOW.md, docs/TESTING.md, docs/MODULE_GUIDE.md, docs/MODULE_STATUS.md, CHANGELOG.md, ROADMAP.md.
3. Run `git fetch origin` and check `origin/development` and the open PRs. The last state I know: everything through PR #31 is merged into `development` (latest: #28 favorites, #29 profile details, #30 command menu, #31 UMBRA importer removed). `main` is untouched.

Standing rules (details in AGENTS.md):
- One branch `claude/<topic>` cut from `origin/development` + one PR into `development` per change; squash-merge when CI is green, with the FULL head SHA as expectedHeadSha. Never touch `main`.
- Never touch my `.env` (edit `.env.example`, tell me what to add by hand). No secrets or customer data in git.
- Every user-facing string in EN + RU + RO (bot and web), professional wording, Romanian ș/ț with comma.
- Tests for every change; run the whole suite locally before pushing:
  export TOKEN=1:x OWNER_ID=1 POSTGRES_DB=x POSTGRES_USER=x POSTGRES_PASSWORD=x; python -m pytest -q -p no:cacheprovider   (~100 s, 2055 passed / 6 skipped at last full count; re-count and update the docs)
- Migrations: additive, reversible, verified up→down→up on local PostgreSQL 16 (pg_ctlcluster 16 main start); alembic head is f2b8d0e6a3c9.
- Every PR also updates CHANGELOG.md, ROADMAP/MODULE_STATUS/PROJECT_STATE when the state changes, and README/.env.example when relevant.
- Report honestly what was and was not verified (nothing has been checked by you in live Telegram — only tests, local PostgreSQL, headless Chromium).
- I may merge PRs myself before CI finishes: re-check origin/development after any merge and re-apply anything that missed it on a fresh branch.
- GitHub goes through the mcp__github__* tools (no gh CLI); load them with ToolSearch if they are missing.

What exists (all merged): physical-goods shop, MIA + cash on delivery, subcategories, weight options, clean chat + welcome line above the persistent menu, EN/RU/RO bot and fully translated web panel, grouped sidebar (Orders, Clients, Payments, Catalog incl. Shipping, Marketing incl. Mailings, Settings), Mailings with rich editor/segments/schedule/test, client profiles with order history (no import by design), shipping methods with price/free-from, light/dark panel theme, ⭐ Favorites, Profile → My details with checkout "use saved", ☰ command menu. The catalog is entered by staff (no crawler/importer).

Open items waiting on me (ask me again only if still blocking):
1. Whether the requirements register (docs/PROJECT_PRINCIPLES.md §4) and ROADMAP.md are correct — I have not reviewed them yet.
2. I will deploy the latest code and test live; I will report problems with screenshots.

First task in this session: give me a 5-line status (what is on development, open PRs, CI state, what is blocked on me), then wait for my instructions. Candidate next work from ROADMAP.md (do NOT start without my choice): print order, customer groups + unsubscribe, orders list with localized statuses/filters, import page in the web panel (only if I ask).
```
