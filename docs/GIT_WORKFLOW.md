# Git workflow

Applies to every contributor, human or AI. Short version: **branch → PR into `development` → CI green → squash-merge.
`main` is never touched.**

## 1. Branches

| Branch | Purpose | Who writes to it |
|---|---|---|
| `main` | Stable. Still holds the original upstream code. Promoted from `development` **manually by the owner**. | Nobody else |
| `development` | Integration branch; the "branch of record". Always deployable, CI green. | Only via squash-merged PRs |
| `claude/<topic>` | One change = one branch cut from `origin/development` | The author of the change |

- Topic names: lowercase, hyphen-separated, describing the change (`claude/web-i18n`, `claude/client-profiles`, `claude/shipping`,
  `claude/fix-start-keyboard`). Hotfixes: `claude/fix-<what>`. Docs: `claude/docs-<what>`.
- Start every change from a fresh `development`:
  ```bash
  git fetch origin
  git checkout -B claude/<topic> origin/development
  ```
- If the owner has already merged your branch's PR, **do not reuse the branch**: `git checkout -B claude/<topic> origin/development`
  and re-apply what is missing (cherry-pick), then open a new PR.

## 2. Commits

- One logical change per commit; the PR is squashed anyway, so clarity matters more than count.
- Subject: imperative, sentence case, no trailing period, ≤ ~100 chars, says *what the user gets* ("Shipping methods: price,
  free-from threshold, checkout choice, fee on the order"). Body (optional) explains why and lists notable details.
- Trailers (appended by the agent harness for AI-authored commits): `Co-Authored-By: …` and `Claude-Session: …`. Keep them.
- Never commit: `.env`, secrets, `data/`, logs, `__pycache__`, scratch scripts, customer personal data (e.g. `klaud_clients.csv`).

## 3. Before you push

1. Tests: `export TOKEN=1:x OWNER_ID=1 POSTGRES_DB=x POSTGRES_USER=x POSTGRES_PASSWORD=x && python -m pytest -q -p no:cacheprovider`
   — the **whole suite** must pass (≈100 s).
2. A migration? Verify on PostgreSQL 16: `alembic upgrade head` → `alembic downgrade -1` → `alembic upgrade head`; exactly one head
   (`alembic heads`). Back-fills must be tested on real rows.
3. Translations: new strings exist in en + ru + ro (parity tests pass).
4. Docs: `CHANGELOG.md` entry (Unreleased), README for user-visible changes, `docs/MODULE_STATUS.md` / `docs/PROJECT_STATE.md` /
   `ROADMAP.md` if the state changed, `.env.example` for config.
5. Re-read your own diff adversarially (what would make CI or the owner reject this?).

## 4. Pull request

- Base: **`development`**. Title: the change in one line (no "WIP"). Body (use the repo's PR template if one exists):
  - **Summary** — user-visible behaviour, bullets.
  - **Dependencies** — "Depends on #NN" when a migration/code chain requires another PR first.
  - **Test plan** — checked boxes for what *was* run (full suite with the pass count, migration up/down/up, headless browser…) and
    an explicit unchecked box for what was **not** (live Telegram).
  - Footer lines required by the harness (attribution + session link).
- Don't open a PR unless asked/expected; the standing practice in this project is one PR per change.
- Subscribe to the PR's activity (when the tooling allows) and handle CI failures, conflicts and review comments to green.

## 5. CI

`.github/workflows/tests.yml` runs **once per change**: on the `pull_request` event for PR branches (a branch without a PR is not tested), and on `push` only for `development` and `main`. Two jobs run in parallel:
- **Unit tests** — `pytest` with coverage on Python 3.11.
- **Migrations on PostgreSQL** — PostgreSQL 16 service: `alembic upgrade head` → `downgrade -1` → `upgrade head`.
A newer push to the same PR cancels the older run (a "cancelled" run on an old commit is normal; look at the **latest** head SHA).

## 6. Merging

- Method: **squash** (one PR = one commit on `development` = one revert).
- Merge only when both checks are green on the **current head SHA**, there is no conflict, and review comments are resolved.
- Merge call needs `expectedHeadSha` = the **full 40-char SHA** (`git rev-parse HEAD`). A short hash fails with
  `409 Head branch was modified`.
- The owner may merge PRs themselves, sometimes before CI finishes. After any merge: `git fetch origin`, check what is on
  `development`, and re-apply anything that missed the merge on a fresh branch. The first PR after such a merge gives the first
  full CI run of that state — check it.

## 7. Dependent PRs and conflicts

- Prefer independent PRs. When PR B needs PR A (e.g. migration chain, shared model): say so in B's body, merge A first, then merge
  `development` into B (`git merge origin/development`) — **merge commits, never rebase or force-push** a branch someone else may
  have checked out.
- A squash-merged PR leaves its commits unmerged in a dependent branch; the merge usually conflicts only in files both sides
  edited at the same anchor (`bot/i18n/strings_web.py`, `strings_ro_web.py`, README/CLAUDE docs). Resolve by **keeping both sides**,
  then remove exact duplicate keys (a duplicate key in a dict literal silently keeps the last), then run the i18n tests and the suite.
- Never resolve a conflict by dropping the other side's behaviour without understanding it.

## 8. Hotfixes

Same flow, smaller: branch `claude/fix-<what>` from `development`, regression test first (fails before, passes after), PR, merge when
green, tell the owner what to redeploy (`git pull && docker compose up -d --build`, `/start`). Record it in `CHANGELOG.md` under **Fixed**.
Example: #14 (the `/start` crash).

## 9. Rollback

`git revert <squash sha>` on a branch cut from `development` → PR → merge. If the reverted PR added a migration, run
`alembic downgrade -1` on the affected database **before** deploying the revert (the migration's `downgrade` must work — that is why it is
verified up → down → up).

## 10. Promotion to `main` (owner only)

When the owner is satisfied: turn the `Unreleased` block of `CHANGELOG.md` into a dated release, merge `development` → `main`
(owner's action), tag if a release process exists (ROADMAP 6.7). Nobody else pushes to `main`.
