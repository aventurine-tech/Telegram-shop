# Security

Describes what is implemented (so you know what to rely on), the rules every change must follow, and what the operator must do.
Report suspected vulnerabilities privately to the owner — not in public issues or PR comments.

## 1. Threat model (what we defend against)
Anonymous internet users hitting the web panel/webhook; malicious or curious customers; a compromised/over-privileged staff
account; concurrent requests racing on stock/money; leaked secrets; abusive input (HTML/markup, CSV formula injection, huge
files); accidental mass-mailing; personal-data exposure (customers' names, usernames, phones, addresses).
Out of scope: a compromised host or database, Telegram itself.

## 2. Implemented controls
| Area | Control |
|---|---|
| **Money & stock** | Reservation/release and balance moves run in one DB transaction under row locks, goods locked in id order (no deadlocks); order status transition table; the **total is recomputed server-side** and compared to what the customer confirmed (`expected_total`, includes the delivery fee); MIA payments require human verification; referral commission paid exactly once on *completed*; DB `CHECK` constraints (non-negative amounts, no self-referral, `balance_used ≤ total`). |
| **Access control** | Telegram-ID authentication; 11-bit permission bitmask with subset validation (cannot create/assign a role exceeding your own); role cache cleared on every change; blocked users rejected before handlers. |
| **Web panel auth** | Accounts in the DB with hashed passwords (`bot/web/passwords.py`), Admin and Staff levels re-checked against the DB on **every request** (disabling/demoting is immediate); login limiter (5 attempts/15 min per IP); 30-min sessions, `SameSite=strict`, `Secure` cookie when HTTPS; constant-time comparisons; proxy-aware client IP (trusts `X-Forwarded-For` only from loopback). |
| **Startup guard** | The process **refuses to start** with the default `SECRET_KEY` or `ADMIN_PASSWORD='admin'` when the panel is reachable (`ADMIN_HOST` not loopback, or webhook on). |
| **Web authorization per view** | Admin-only: *Web accounts*, *Mailings* (+ the mailing image route); Staff get the rest according to role; every view is covered by `authenticate`; custom routes (`/export/*`, `/mailing-image/*`) check `current_web_user`. |
| **Audit** | Every create/edit/delete in the panel and sensitive bot actions are written to the audit log (retention `AUDIT_RETENTION_DAYS`, default 90). Mailing cancel/duplicate/create are audited without dumping row contents. |
| **Input handling** | ORM-parameterised queries only; customer text length-limited and HTML-escaped for staff; **mailing HTML sanitised** to Telegram's tag set (links limited to `http(s)://`, `tg://`, `mailto:`), placeholders escaped; search `LIKE` wildcards escaped; CSV export neutralises formula injection; item names control-character filtered; uploaded pictures verified as real JPEG/PNG/WEBP, size/pixel-limited (decompression-bomb guard). |
| **Rate limiting** | Global and per-action limits with temporary bans (Redis atomic script, per-process fallback); admins bypass windows but not bans. |
| **Replay/stale guard** | Taps on transactional messages older than 1 h are rejected; webhook secret token compared in constant time. |
| **Secrets** | Only via environment (`.env`, never committed); `/health` does not leak internals to anonymous callers. |
| **Messaging safety** | Mailings are Admin-only, scheduled/cancellable, never auto-resumed (no duplicate sends), batch-throttled, test-to-self first; blocked and opted-out users skipped; every message has an unsubscribe button; a per-recipient log (ids and outcomes only) is kept. |

## 3. Personal data
Stored about customers: Telegram id, first/last name, @username, language, phone, delivery address, order history, staff notes.
- Collected from Telegram and from what the customer typed at checkout; not imported from other systems (D-14).
- Visible only to authenticated panel users/staff with the relevant permission; exported only via authenticated CSV.
- **Never commit** exports (`klaud_clients.csv`), logs or database dumps; never paste customer data into issues/PRs/chats.
- On request, an Admin account erases a client's personal data from the client's page (**Erase personal data**, see `docs/BACKUP_AND_RESTORE.md`); old backups still hold it until they expire. Automatic retention is on the roadmap (6.4).

## 4. Rules for every change
1. New handler/view/route → enforce authentication **and** the right permission/role; add a test for the denied case.
2. Never build SQL from strings; never interpolate user text into HTML/JS without escaping (use `escape`/`Markup` deliberately).
3. Don't log secrets, tokens, full phone numbers or addresses; keep audit details short and structured.
4. Anything that sends messages to many people needs a cancel path, a throttle and a test with a fake bot.
5. Migrations must not relax constraints; new money columns are `Numeric(12, 2)` with a non-negative `CHECK`.
6. Third-party input (uploads, Telegram profile fields) is untrusted: validate, limit, escape.
7. Dependencies are pinned exactly; add one only with a reason, check its licence and maintenance.
8. Never edit the owner's `.env`; never commit real credentials, IBANs or phone numbers (use placeholders in `.env.example`).

## 5. Operator checklist (production)
- [ ] `SECRET_KEY` = long random value (`python -c "import secrets; print(secrets.token_hex(32))"`), `ADMIN_PASSWORD` strong, change the bootstrap admin password after first login.
- [ ] Panel behind HTTPS (reverse proxy); `ADMIN_COOKIE_SECURE=auto/1`; restrict `ADMIN_HOST` if not public; set `WEBHOOK_SECRET` if using webhooks.
- [ ] Redis enabled with a password if you run more than one worker; database not exposed to the internet.
- [ ] Regular PostgreSQL backups (`scripts/backup_db.sh` + cron, copied off the machine, restore practised — `docs/BACKUP_AND_RESTORE.md`); log rotation; disk alerts.
- [ ] Staff accounts: Staff level unless Admin is needed; remove accounts of people who left.
- [ ] Set real `MIA_*` details only on the server `.env`; verify transfers manually before confirming.

## 6. Known gaps / roadmap
Per-process web login limiter (not shared across workers); two-step sign-in for panel accounts is optional per person (never forced; D-23); no automated personal-data retention (erasure is manual);
no browser-level tests of the panel. Tracked in `ROADMAP.md` (Phase 6). CI runs `scripts/scan_secrets.py` on every PR (bot tokens, private keys, passwords in URLs);
log and error text goes to the owner as a short alert without tracebacks (`ERROR_ALERTS`).
