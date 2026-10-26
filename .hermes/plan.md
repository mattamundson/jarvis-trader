# Open-Hour Bar Refresh Implementation Plan

> **For Hermes:** Execute this plan with strict RED-GREEN-REFACTOR discipline and independent review.

**Goal:** Correct later snapshots of a still-forming OHLCV bar in `market_data_bars` while making finalized historical rows immutable.

**Architecture:** Keep `save_bars()` as the single write choke point. Replace unconditional duplicate suppression only for supported intervals with an atomic SQLite upsert that refreshes a conflicting row when the persisted snapshot was captured before the bar closed and the incoming snapshot is newer. Once a persisted snapshot's `fetched_at` is at or after its scheduled bar end, future conflicts remain no-ops.

**Tech stack:** Python 3.12, pandas, SQLite, pytest, Ruff.

---

## Safety boundary

- Work only in `fix/open-hour-bar-upsert-20261025`, based on current `origin/master`.
- Read-only market-data persistence only; do not change execution routing, accounts, risk, symbol gates, kill switch, orders, or `.env`.
- Preserve `127.0.0.1:4001` as the sole operational Gateway endpoint.
- Do not operationally probe MCL or MNQ. MGC remains `DO_NOT_TRADE`.
- Produce a focused PR; do not deploy or merge this new behavior without a separate explicit `[safety-review]` authorization.

## Task 1 — Lock the MGC open-hour regression with a failing test

**Files:**
- Modify: `engine/tests/test_bars_repository.py`

1. Add a deterministic test that writes an MGC `1h` snapshot fetched before bar end, then a newer snapshot at the same timestamp.
2. Assert one stored row remains and its close/volume/source/fetched timestamp match the newer snapshot.
3. Run only that test with the canonical project interpreter and confirm it fails because `INSERT OR IGNORE` retains the first snapshot.

## Task 2 — Implement the minimal atomic refresh

**Files:**
- Modify: `engine/data/bars_repository.py`

1. Add a fixed supported-interval-to-minutes mapping.
2. Build the conflict SQL only from that trusted mapping; unknown intervals retain insert-ignore behavior.
3. On primary-key conflict, update OHLCV/source/fetched_at only when:
   - the stored snapshot was fetched before the scheduled bar end;
   - the incoming snapshot was fetched later than the stored snapshot; and
   - OHLCV differs, or the newer snapshot was fetched at/after bar end and therefore finalizes the row.
4. Preserve a known volume when the newer snapshot has null volume.
5. Update return-value/log wording from “new rows” to “inserted or refreshed rows.”
6. Run the focused regression and confirm GREEN.

## Task 3 — Prove finalized history cannot mutate

**Files:**
- Modify: `engine/tests/test_bars_repository.py`

Add and run focused tests for:
- a row first fetched at/after bar end remains immutable;
- an older out-of-order snapshot cannot replace a newer provisional snapshot;
- an identical repeat remains a no-op;
- a mixed batch updates only provisional rows;
- null incoming volume preserves a previously known volume;
- unsupported intervals retain insert-ignore semantics.

## Task 4 — Reconcile documentation and callers

**Files:**
- Modify: `engine/data/bars_repository.py`
- Modify only if needed: `engine/database/migrations.py`
- Modify: `engine/scripts/backfill_market_data_bars.py`

1. Remove stale claims that every conflict is ignored.
2. Confirm historical backfills are immutable because their existing rows were fetched after bar end.
3. Confirm callers tolerate the count meaning inserts plus legitimate provisional refreshes.

## Task 5 — Verify and publish the focused PR

1. Run `tests/test_bars_repository.py` with the canonical interpreter and no CLI `-m` override.
2. Run affected architecture/write-path tests with `-k`, never `-m`.
3. Run changed-file Ruff, `py_compile`, and `git diff --check`.
4. Verify the diff against `origin/master` contains only the plan, repository implementation, tests, migration documentation, and directly affected backfill wording.
5. Obtain independent spec and code-quality review; resolve every blocking finding.
6. Commit, push, and open a `[safety-review]` PR documenting rollback and the execution/risk non-impact boundary.
7. Do not merge or deploy this new behavior without a new explicit human `[safety-review]` authorization.

## Finish line

- The original MGC reproduction is RED before implementation and GREEN afterward.
- Finalized rows and historical backfills are proven immutable.
- The focused test module and write-path guards pass.
- Static checks pass.
- PR exact head and file scope are verified.
- The currently deployed engine remains unchanged and execution remains fail-closed.
