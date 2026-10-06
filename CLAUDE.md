# CLAUDE.md — start here in a new Claude Code session

**Read [`AGENTS.md`](AGENTS.md) first** — it is the full, canonical rulebook (owner's rules, workflow, architecture rules,
definition of done). This file only adds what is specific to Claude Code and keeps the quick reference you need most.

Then read [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md) (what exists / open items / risks) and, as needed:
[`docs/PROJECT_PRINCIPLES.md`](docs/PROJECT_PRINCIPLES.md) (requirements register) · [`docs/MODULE_GUIDE.md`](docs/MODULE_GUIDE.md) (code map) ·
[`docs/GIT_WORKFLOW.md`](docs/GIT_WORKFLOW.md) · [`docs/TESTING.md`](docs/TESTING.md) · [`docs/NAMING_STANDARDS.md`](docs/NAMING_STANDARDS.md) ·
[`docs/SECURITY.md`](docs/SECURITY.md) · [`docs/ENTERPRISE_STANDARDS.md`](docs/ENTERPRISE_STANDARDS.md) · [`docs/DECISIONS.md`](docs/DECISIONS.md) ·
[`docs/MODULE_STATUS.md`](docs/MODULE_STATUS.md) · [`CHANGELOG.md`](CHANGELOG.md) · [`ROADMAP.md`](ROADMAP.md) ·
[`README.md`](README.md) (user manual) · [`docs/run-and-test.pdf`](docs/run-and-test.pdf) (step-by-step test guide).

## The rules you must not forget (summary of AGENTS.md §1)

- Branch `claude/<topic>` from `origin/development` → PR **into `development`** → squash-merge when CI is green
  (`expectedHeadSha` = the **full** SHA from `git rev-parse HEAD`; a short hash makes the merge fail with 409).
  **`main` is never touched.**
- **Never touch the owner's `.env`** (edit `.env.example`, tell the owner what to add).
- **Honest reporting**: nothing has been verified in live Telegram by Claude — only tests, local PostgreSQL, headless Chromium.
- **en + ru + ro** for every user-facing string, bot and web; professional wording; Romanian ș/ț with comma.
- The owner may merge PRs early: re-fetch `origin/development` after each merge and re-apply anything that missed it on a
  fresh branch. When a squash-merged PR's branch is still under a dependent PR, merge `development` into the dependent
  branch (translation files then conflict at the same anchor: keep both sides, drop exact duplicate keys).
- Update `CHANGELOG.md` (+ docs) in every PR. Record any new owner rule in AGENTS.md / PROJECT_PRINCIPLES / DECISIONS the same day.

## Claude Code specifics

- **No `gh` CLI.** GitHub goes through the `mcp__github__*` tools (create/merge PR, read checks, comments). They can
  disconnect: reload with `ToolSearch` → `select:mcp__github__create_pull_request,…`. Attribute commits with the trailers the
  harness gives (`Co-Authored-By`, `Claude-Session`) — see `docs/GIT_WORKFLOW.md`.
- After opening a PR you may be subscribed to its events (`subscribe_pr_activity`): act on CI failures/conflicts, ignore
  echoes of your own comments. For "merge when CI finishes", use `send_later` as a one-shot check-in instead of polling or `sleep`.
- Long suites: `python -m pytest …` takes ~100 s; if it times out in the foreground it continues in the background —
  read its output file instead of re-running.
- Temporary files go to the session scratchpad, never into the repo. Don't commit `__pycache__`, `data/`, logs, scratch scripts.
- Screenshots from the owner arrive as images: read them, identify the exact screen/string, fix, and say what changed.

## Commands

```bash
export TOKEN=1:x OWNER_ID=1 POSTGRES_DB=x POSTGRES_USER=x POSTGRES_PASSWORD=x
python -m pytest -q -p no:cacheprovider            # ~100 s, 2055 passed / 6 skipped at last count
```

Migration check (PostgreSQL 16 in the container): `pg_ctlcluster 16 main start`; then with
`POSTGRES_HOST=localhost POSTGRES_DB=migdb POSTGRES_USER=mig POSTGRES_PASSWORD=mig`: `alembic upgrade head` →
`alembic downgrade -1` → `alembic upgrade head`. **Alembic head: `f2b8d0e6a3c9`** (profile details) ← `e1a7c9d5f2b8` (favorites) ← `d1f6b8c4e5a7` (shipping) ← `c9e5a7b3d4f6` (client profiles)
← `b8d4f6a2c3e5` (mailings) ← `a7c3e5f1b2d4` (product options) ← …; files in `migrations/versions/`.
CI: `.github/workflows/tests.yml` — "Unit tests" + "Migrations on PostgreSQL".

Deploy (owner): `git pull && docker compose up -d --build`, then `/start` once in the bot (migrations run on start).

## Quick code map (full version: `docs/MODULE_GUIDE.md`)

| Area | Where |
|---|---|
| Entry, middleware order | `bot/main.py` — CleanChat (outermost) → analytics → auth → language → profile → security; rate limit separately |
| Models | `bot/database/models/main.py` |
| DB methods | `bot/database/methods/` — `orders.py` (all stock/money transactions), `shipping.py`, `mailings.py`, `profiles.py`, `item_options.py`, `translations.py`, `product_images.py`, `web_users.py`, `lazy_queries.py` |
| Customer bot | `bot/handlers/user/` — `main.py` (/start, welcome line, profile), `bottom_nav.py`, `shop_and_goods.py`, `cart.py`, `checkout.py`, `language.py` |
| Admin bot | `bot/handlers/admin/` |
| Web panel | `bot/web/admin.py` (ModelViews, app factory), `mailings.py`, `accounts.py`, `export.py`, `templates/` (own copies of SQLAdmin list/create/edit/details/modals, `layout.html`, `_macros.html`, `order_details.html`, `client_details.html`, `mailing_details.html`) |
| Background services | `bot/misc/services/` — `recovery.py` (MIA expiry, health, **mailing scheduler**), `mailing_sender.py`, `cleanup.py`, `order_view.py`, `restock_notifier.py` |
| i18n | `bot/i18n/` — `strings*.py` (en/ru) and `strings_ro_*.py`; `localize()` uses a per-update ContextVar language |
| Localized names | `bot/misc/localized.py` — `pick`, `derive_canonical`, `clean_name`, `LANGS` |
| Clean chat / profile | `bot/middleware/clean_chat.py`, `bot/middleware/profile.py` |
| UMBRA import | `scripts/crawl_umbramd.py`, `scripts/import_catalog.py`, `scripts/umbramd/` |

## Quirks learned the hard way

**SQLAdmin 0.16.1** — action names are normalised (`confirm_payment` → `confirm-payment`); a class defining a method twice
keeps the last; relationship select labels are `str(obj)`; field order = WTForms creation counters (`_own_language_first`);
stock templates don't print field `description` (hints double as placeholders); `ValueError` in `on_model_change` → 400 with
the message; list rows link to `/admin/<class identity>/details/<id>` (the object's own class); an upload field on the form
needs a placeholder attribute on the model (`Goods.picture = None`, `Mailings.picture = None`); `after_model_change` must not
touch server-refreshed columns (lazy load → `MissingGreenlet`) — `MailingAdmin` logs from `data` instead; nullable boolean
columns render as a True/False select (we translate them in `LocalizedModelView.scaffold_form`); SQLAdmin's built-in
templates are English-only — we ship **our own copies** (`list/create/edit/details`, `modals/`) using `web.sa.*` keys, and the
save buttons keep SQLAdmin's English *values* (`Save`, `Save and continue editing`…) because the backend compares them.
**WTForms** — messages follow the panel language through `LocalizedForm.Meta.get_translations` (needs the `ru`/`ro` catalogues
shipped with WTForms 3.1.2).

**Telegram** — the persistent keyboard rides on a message (the **welcome line**); Telegram rejects whitespace / zero-width /
Braille-blank text ("text must be non-empty") and **drops the keyboard if that message is deleted**; keep it above the menu
(send it first, then the screen); the bot can delete messages only within 48 h; `/start` sweeps the 100 ids before it.

**Clean chat** (`CLEAN_CHAT=1`) — one screen per private chat; `outside_screen()` excludes messages that must stay; sends to
other chats / background sends are untouched.

**Mailings** — never resumed after a restart (marked *Interrupted*), batches of 25 + 1 s, placeholders resolved per
recipient through `bot.get_chat`, picture uploaded once then reused by `file_id`, text sanitised to Telegram's tag set.

**Environment** — outbound traffic goes through a proxy with an allow-list; Chromium for panel-script smoke tests is under
`/opt/pw-browsers`; there is no Playwright Python package.
