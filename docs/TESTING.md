# Testing

**Rule: a change without a test is unfinished.** New behaviour → new tests; a bug → a regression test that fails before the fix.
State at last count: **2055 passed, 6 skipped** (~100 s).

## 1. Running

```bash
export TOKEN=1:x OWNER_ID=1 POSTGRES_DB=x POSTGRES_USER=x POSTGRES_PASSWORD=x   # settings import needs them
python -m pytest -q -p no:cacheprovider                  # everything
python -m pytest -q -p no:cacheprovider tests/test_shipping.py -x   # one file, stop at first failure
```
`pytest.ini`: `asyncio_mode = auto` (plain `async def test_…`). The foreground tool limit is 120 s; a long run may be moved to
the background — read its output file rather than restarting it.

## 2. How the suite is built (`tests/conftest.py`)

| Piece | Behaviour |
|---|---|
| Database | One in-memory **async SQLite** engine for the session (`setup_test_database`), created from the models. **Shared across tests** — never assume a table is empty; use unique ids/names per test (`UID = 990001`…) and clean what you create. `db_cleanup` (autouse) deletes the rows of the core tables after each test (reviews, carts, promos, orders, goods, categories, users, web users, custom roles…). **Tables it does not know** (`mailings`, `shipping_methods`, …) are *not* reset — a test that writes to them must clean up itself (see the autouse `_clean` fixtures in `tests/test_web_mailings.py` and `tests/test_shipping.py`), or add the table to `db_cleanup`. |
| Cache | `FakeCache` replaces Redis/in-memory caches (`fake_cache`, autouse). |
| Background tasks | `safe_create_task` is patched to schedule the coroutine on the running loop immediately. |
| Env | `patch_env_keys` pins configuration (currency, payment flags…). |
| `localize` | In handler/keyboard modules it is replaced by a **key-echo mock**: `localize("btn.x", a=1)` returns the key (plus kwargs), so tests assert on keys, not wording. Modules listed in `_LOCALIZING_MODULES` are patched — **a new handler/keyboard module that calls `localize` must be added there**. Web code (`bot/web/*`) uses the real `localize` and asserts real text. |
| Factories | `user_factory`, `category_factory`, `item_factory`, `role_factory`, `operation_factory`, `referral_earning_factory`; `tests/factories.py` for helpers. |
| Telegram doubles | `mock_bot`, `make_message(text=…, user_id=…)`, `make_callback_query(data=…, user_id=…)`, `fsm_context` (real in-memory FSM). Assert on `msg.answer.call_args`, `call.message.edit_text.call_args`, callback data of the markup. |

## 3. Patterns

- **Transactions** (`orders.py`, shipping, mailings core): call the DB method, assert returned `(ok, code, data)` and the stored rows.
- **Handlers**: drive the flow step by step with the doubles, then assert the FSM state/data and the final DB state
  (`tests/test_payment_handlers.py`, `tests/test_shipping.py::TestCheckoutFlow`). Patch outward notifications
  (`patch("bot.handlers.user.checkout.notify_new_order", new_callable=AsyncMock)`).
- **Web panel**: build the real app with `create_admin_app()`, log in with `httpx.AsyncClient(transport=httpx.ASGITransport(app=app, …))`
  after `create_web_user(...)`, set the language cookie (`LANG_COOKIE`) and assert on HTML, status codes and the database
  (`tests/test_web_mailings.py`, `tests/test_client_profiles.py`, `tests/test_web_i18n.py`). Forms: `client.post(url, data=…, files=…)`
  — a 302 means saved, 400 means the `ValueError` message from `on_model_change`.
- **Middleware**: call it with a stub handler and `SimpleNamespace` events (`tests/test_client_profiles.py::TestMiddleware`).
- **Background jobs**: use a fake bot (`AsyncMock`), tiny batch sizes and `batch_delay=0` (`tests/test_mailings_core.py`).
- **i18n**: `tests/test_i18n.py` and `tests/test_web_i18n.py` check key parity across en/ru/ro and identical `{placeholders}`. New keys must
  be added to all three or the suite fails.
- **Time**: SQLite returns naive datetimes, PostgreSQL aware ones — normalise before comparing (`_utc()` in `bot/web/mailings.py`).

## 4. Beyond the unit suite

| Check | When | How |
|---|---|---|
| **Migrations on PostgreSQL** | every PR that touches `migrations/` (CI runs it for all PRs) | `pg_ctlcluster 16 main start`; `export POSTGRES_HOST=localhost POSTGRES_DB=migdb POSTGRES_USER=mig POSTGRES_PASSWORD=mig`; `alembic upgrade head`, `alembic downgrade -1`, `alembic upgrade head`; `alembic heads` shows exactly one head. For a back-fill, insert rows at the previous revision first (create the `roles` row before `users`) and inspect the result with `psql`. |
| **Panel JavaScript** (mailing editor, option rows, role tags) | when you change widget scripts | write a small HTML harness that embeds the widget output, run `chrome --headless --no-sandbox --dump-dom file://…` (`/opt/pw-browsers/chromium-*/chrome-linux/chrome`) and read the resulting DOM. |
| **Importer** | catalog changes | `python -m scripts.import_catalog --dry-run …` against a scratch database. |
| **Live acceptance** | before promoting to `main` | step-by-step guide `docs/run-and-test.pdf` (source `run-and-test.md`) on a real bot — **owner-run**; Claude has not done this. |

## 5. What is *not* covered (be honest about it)
Real Telegram behaviour (keyboards, deletions, rate limits, `get_chat` for every user), real MIA transfers, mobile UI of the web panel,
concurrency under production load, Redis-enabled deployments beyond the unit doubles. Say so in PR test plans.

## 6. Writing a good test
Name it as a sentence; one behaviour per test; arrange with factories; assert the **observable result** (DB rows, markup, text), not
internals; add the failing case first for bugs; keep tests independent (shared DB!); don't sleep — patch time or delays; keep new
test files under the naming rules in `NAMING_STANDARDS.md`.
