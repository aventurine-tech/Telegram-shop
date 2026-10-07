# AGENTS.md — rules for every AI agent and developer working on this repository

This is the **canonical, tool-agnostic rulebook**. `CLAUDE.md` adds only what is specific to Claude Code. If anything
here conflicts with your own habits, this file wins; if it conflicts with a direct instruction from the owner, the owner
wins and this file should then be updated (see §10).

**Project:** a Telegram shop bot for **physical goods** (aiogram 3 · async SQLAlchemy 2 + PostgreSQL · optional Redis ·
SQLAdmin/Starlette web panel). Exactly **two payments**: **MIA** (manual instant transfer, verified by staff) and **cash on
delivery / pickup**. **English, Russian and Romanian everywhere** (bot *and* web). Currency **MDL**. Integer stock.
First real catalog: **UMBRA hookah tobacco**. Catalog entered by staff. Repo: `aventurine-tech/Telegram-shop`.

## 0. Read first (in this order)

1. This file.
2. [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md) — what exists right now, open items, known risks.
3. [`docs/PROJECT_PRINCIPLES.md`](docs/PROJECT_PRINCIPLES.md) — product + engineering principles and the **owner's requirements register**.
4. [`docs/MODULE_GUIDE.md`](docs/MODULE_GUIDE.md) — where the code lives and how the parts fit.
5. For the task at hand: [`docs/GIT_WORKFLOW.md`](docs/GIT_WORKFLOW.md), [`docs/TESTING.md`](docs/TESTING.md),
   [`docs/NAMING_STANDARDS.md`](docs/NAMING_STANDARDS.md), [`docs/SECURITY.md`](docs/SECURITY.md),
   [`docs/ENTERPRISE_STANDARDS.md`](docs/ENTERPRISE_STANDARDS.md).
6. History and plans: [`CHANGELOG.md`](CHANGELOG.md), [`ROADMAP.md`](ROADMAP.md), [`docs/DECISIONS.md`](docs/DECISIONS.md),
   [`docs/MODULE_STATUS.md`](docs/MODULE_STATUS.md).

## 1. Non-negotiable rules (from the owner)

1. **One branch + one PR per change.** Branch `claude/<topic>` cut from `origin/development`; PR **into `development`**;
   squash-merge when CI is green. **Never push to, merge into, or otherwise touch `main`** — promoting `development` →
   `main` is the owner's manual decision.
2. **Never edit, overwrite or print the owner's `.env`.** Change `.env.example` only and tell the owner, in words, what
   to add by hand. Never commit secrets, tokens, real IBAN/phone numbers, or customer personal data (the Botobot client
   export `klaud_clients.csv`, `data/`, logs).
3. **Report honestly.** Say exactly what was verified and how (unit tests, local PostgreSQL, headless browser) and what was
   **not** (nothing has been verified by us in a live Telegram chat). Never claim "works on the device" without having
   seen it. If a test fails, say so with the output; if a step was skipped, say that.
4. **Full suite green locally before every push**; CI ("Unit tests" + "Migrations on PostgreSQL") green before merging.
5. **Everything user-facing is translated** into **en + ru + ro**, in the bot *and* the web panel, professionally
   (no machine-literal calques; Romanian with comma-below **ș/ț**). A feature is not done until all three languages exist.
6. **Do not break the persistent menu.** The bottom keyboard (Catalog · Cart · Profile) rides on the localized welcome
   line, which must always sit *above* the menu. See `docs/DECISIONS.md` D-07 before touching `/start`, language change or
   clean-chat code.
7. **Owner decides scope.** When a choice is genuinely the owner's (new feature scope, naming that is visible to
   customers, anything touching money/stock rules), ask once with concrete options and a recommendation; otherwise pick
   the conventional default, say so, and proceed.
8. **Don't import or ask to import personal data.** Client profiles fill themselves from Telegram and orders; there is
   deliberately no client-import tool (D-14).

## 2. Workflow in short (details: `docs/GIT_WORKFLOW.md`)

```
git fetch origin
git checkout -B claude/<topic> origin/development
… change + tests + docs + CHANGELOG entry …
export TOKEN=1:x OWNER_ID=1 POSTGRES_DB=x POSTGRES_USER=x POSTGRES_PASSWORD=x
python -m pytest -q -p no:cacheprovider        # whole suite, ~100 s, must pass
git commit  (message + trailers, see GIT_WORKFLOW)  →  git push -u origin claude/<topic>
open PR into development  →  wait for CI  →  squash-merge with expectedHeadSha = full `git rev-parse HEAD`
```

- The owner sometimes merges PRs themselves (even before CI ends). After any merge, **re-fetch `origin/development`**; a
  commit that missed the merge goes onto a **fresh branch** from `development` — never stack on a merged PR.
- A PR that depends on an unmerged PR (e.g. a migration chain) says so in its body; merge the dependency first, then
  merge `development` into the dependent branch (merge commits, **never rebase/force-push** shared branches).
- Every PR updates: tests, `CHANGELOG.md` (Unreleased), README if user-visible, `docs/MODULE_STATUS.md` /
  `docs/PROJECT_STATE.md` when a module's state or the open items change, `.env.example` when config changes.

## 3. Architecture rules that are easy to break

- **The database is the source of truth for money and stock.** Reservation/release, balance moves and order status
  transitions run in one transaction under row locks (`bot/database/methods/orders.py`); the web panel's order actions call
  the same functions. Never reimplement stock or total logic in a handler or view.
- **Totals are recomputed server-side** and compared with what the customer confirmed (`expected_total`); the delivery
  fee is part of `orders.total` (and kept separately in `delivery_fee`).
- **Canonical vs translated names.** `name`/`description` (main language = `BOT_LOCALE`) are the unique lookup keys;
  `name_en/ru/ro` are display-only; read with `pick(row, field, lang)`. Anything accepting a name resolves it in any
  language, case-folded **in Python** (SQLite `lower()` is ASCII-only).
- **Catalog shape.** Two category levels max; a category holds subcategories *or* products. A product's weight options
  are separate `Goods` rows (`variant_of`, name `"<head> · <label>"`); lists/search show heads only.
- **Migrations are additive and reversible** (`upgrade` + `downgrade`, idempotent guards with `inspect`), one revision per
  PR, verified up → down → up on PostgreSQL 16 locally before pushing. Single alembic head at all times.
- **Web panel** = SQLAdmin 0.16.1 on top of Starlette. Our template overrides live in `bot/web/templates/`; all panel text
  goes through `localize()` (`web.*` keys). SQLAdmin quirks are listed in `CLAUDE.md` and `docs/MODULE_GUIDE.md`.
- **Telegram limits are real**: caption 1024, message 4096, no blank messages, bot can delete messages only within 48 h,
  reply keyboards need a message to live on, ~30 messages/second. Respect them in code *and* in tests.
- **No secrets in code or logs.** Customer text is length-limited and HTML-escaped when shown to staff; mailing HTML is
  sanitised to Telegram's tag set.

## 4. Tests (details: `docs/TESTING.md`)

- A change without a test is unfinished. New behaviour → new test; a bug → a regression test that fails before the fix.
- The suite uses in-memory SQLite shared across tests (never assume an empty table), `FakeCache`, and a **key-echo
  `localize` mock** for handler modules (new localizing handler modules must be added to `_LOCALIZING_MODULES` in
  `tests/conftest.py`; web code uses the real `localize`).
- Web tests drive the real app with `httpx.ASGITransport`; JS in the panel is smoke-tested with headless Chromium
  (`--dump-dom`).
- i18n parity (en/ru/ro keys and `{placeholders}`) is enforced by `tests/test_i18n.py` and `tests/test_web_i18n.py`.

## 5. Code style

- Match the surrounding code: naming, comment density, idiom. Comments only for the non-obvious "why".
- Naming rules: `docs/NAMING_STANDARDS.md`. Small focused modules; no dead code; no speculative abstractions.
- Don't add dependencies without need; pins in `requirements.txt` are exact.
- Prefer editing existing files; new files only when a module genuinely has a new responsibility.

## 6. Security checklist for any change (details: `docs/SECURITY.md`)

Auth/permissions checked on every new handler/view · parameterised queries only · user text escaped · rate limits intact ·
no new unauthenticated routes (image routes check the web session) · audit log entry for admin mutations · no secrets in
logs · migrations don't loosen constraints.

## 7. Definition of done

Code + tests + translations (en/ru/ro) + docs/CHANGELOG + migration verified (if any) + full suite green + PR with an
honest test plan + CI green. Then merge (squash) — or leave to the owner if they asked to merge themselves.

## 8. Communication

- The owner writes in English/Russian and sends **screenshots of the live bot and panel** — treat them as bug reports and
  fix what they show; explain in plain language, briefly, what changed and what remains.
- Keep the owner's open questions visible (see `docs/PROJECT_STATE.md` → *Open items*) and re-ask only when still blocking.
- Don't narrate every step; report outcomes, risks and the next decision needed.

## 9. Environment notes

- Needs `TOKEN, OWNER_ID, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD` in the environment to import settings.
- Local PostgreSQL 16 for migration checks: `pg_ctlcluster 16 main start` (DB `migdb`, user/password `mig`, `POSTGRES_HOST=localhost`).
- Headless Chromium for panel scripts: `/opt/pw-browsers/chromium-*/chrome-linux/chrome --headless --no-sandbox --dump-dom file://…`.
- Outbound network may be proxied/allow-listed.

## 10. Keeping these rules alive

When the owner states a new rule, preference or decision, **record it the same day**: the rule here (§1/§3) or in
`docs/PROJECT_PRINCIPLES.md` (requirements register), the reasoning in `docs/DECISIONS.md`, and mirror anything
Claude-specific in `CLAUDE.md`. Documentation that disagrees with the code is a bug — fix it in the same PR.
