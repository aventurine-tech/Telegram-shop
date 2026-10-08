# Engineering standards

The quality bar for this project. These apply to every PR; reviewers (the owner or an agent) use them as the checklist.
Complements `AGENTS.md` (rules), `GIT_WORKFLOW.md`, `TESTING.md`, `SECURITY.md`, `NAMING_STANDARDS.md`.

## 1. Definition of Done
- [ ] Behaviour implemented and matches the owner's wording/screenshots (R-xx in `PROJECT_PRINCIPLES.md`).
- [ ] Tests added/updated; **full suite green locally**; CI green on the head SHA.
- [ ] en + ru + ro strings, professionally worded; parity tests pass.
- [ ] Migration (if any): additive, reversible, verified up → down → up on PostgreSQL 16, single head, back-fill tested.
- [ ] Docs updated: `CHANGELOG.md`, README (user-visible), `docs/MODULE_STATUS.md`, `docs/PROJECT_STATE.md`, `ROADMAP.md`, `.env.example`.
- [ ] Security checklist (`SECURITY.md` §4) passed; no secrets/personal data committed.
- [ ] PR text states honestly what was and was not verified.

## 2. Code quality
- Readable first: names that say what/why, short functions, early returns, no dead code, no commented-out code.
- Match the surrounding style (formatting, naming, comment density); comments explain *why*, not *what*.
- Single responsibility per module; business rules live in `bot/database/methods/` (testable without Telegram), handlers/views stay thin.
- No duplicated rules: totals, stock, status transitions exist once (`orders.py`); presentation helpers are shared (`order_view.py`).
- Errors: validate at the boundary, raise/return explicit codes, show the user a translated message; log unexpected exceptions with context.
- Async hygiene: no blocking calls in handlers; long loops yield (batch + `await asyncio.sleep`); every background task is cancel-safe.
- Dependencies: pinned exactly, minimal, justified.

## 3. Database standards
- Constraints belong in the database (`NOT NULL`, `CHECK`, FKs with explicit `ondelete`, unique keys) as well as in code.
- Money `Numeric(12, 2)`; timestamps timezone-aware UTC; integer stock; indexes for every filter/sort used on a list page.
- Migrations: one revision per PR, guarded with `inspect`, data back-fills in SQL that works on PostgreSQL *and* is harmless on empty tables;
  `downgrade` removes exactly what `upgrade` added.
- Transactions: row-lock what you mutate (`with_for_update`), lock in a deterministic order, keep them short, no network I/O inside.

## 4. UX standards (customer and staff)
- One screen per chat (clean chat), the welcome line above the persistent menu; never leave dead buttons (a stale button gets an answer).
- Every flow has a way back; every error says what to do next, in the user's language.
- Staff screens show only actions valid for the current state; destructive actions ask for confirmation.
- Web panel: localized end to end (including chrome and validation), consistent labels (`web.col.*`), mobile-width usable, no horizontal page scroll.

## 5. Performance & reliability
- Lists paginate (`lazy_paginator`, SQLAdmin paging); heads-only product queries; avoid N+1 (`selectinload`/joined queries); cache read-mostly
  data with explicit invalidation (`cache_utils`).
- Telegram limits are budgets: ≤ ~30 msg/s overall (mailings: 25 per second batch), captions 1024, messages 4096, callback data 64 bytes.
- Background work is restart-safe (idempotent, resumed from a log — mailings — or explicitly "interrupted, not resumed").
- Fail soft for customers (a profile refresh error never blocks a purchase), fail loud for staff (logged with context).

## 6. Observability
Logs via `bot/logger_mesh.py` (stdout and/or file, audit file separate); `/health`, `/metrics` (JSON) and `/metrics/prometheus` exist;
audit log for admin mutations. Roadmap 6.3: structured logs + alerts.

## 7. Review checklist (what the reviewer looks for)
1. Does it do what the owner asked, in all three languages?
2. Could it oversell, double-charge, double-send, or leak data? (money/stock/messages/PII)
3. Are permissions and error paths tested?
4. Is the migration safe on a database with real rows?
5. Does it keep the persistent menu/clean-chat behaviour intact?
6. Docs/changelog/roadmap updated? Honest test plan?

## 8. Release & operations
- `development` is always deployable; `main` is promoted by the owner. Deploy: `git pull && docker compose up -d --build`, then `/start` (migrations run on start).
- After deploy: open the panel, check **Marketing → Mailings** test message, place a test order, confirm the order card shows delivery lines.
- Backups before risky migrations; know the rollback path (`GIT_WORKFLOW.md` §9).
- Versioning: none yet; dated releases in `CHANGELOG.md` when `development` is promoted (roadmap 6.7).

## 9. Working with the owner
Short, plain reports: what changed, what was verified, what was not, what you need next. Screenshots are bug reports. Ask only
blocking, owner-level questions, with options and a recommendation. Keep the open-items list current.
