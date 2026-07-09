# RISK-010 — Async/Unbounded Test-Timeout Pattern Scan

**Date:** 2026-07-09
**Scope:** `engine/tests/` (full tree, including nested `test_discord_deep_analyzer/`)
**Trigger:** `docs/strategic/05_RISK_REGISTER.md` RISK-010 ("async test flakiness") is marked
"Open — verify" with no supporting evidence. This scan supplies that evidence after PR #348
(merged 2026-07-09) fixed one confirmed instance in `test_daily_pnl_single_writer.py`
(`ENGINE_ROOT.rglob("*.py")` walked all 24,915 files under `engine/.venv/Lib/site-packages`
with only `tests/` excluded — observed >30s hang on a single `path.read_text()` call under
concurrent test runs / disk contention).

This is an investigation only. No test files were modified.

## Method

1. Grepped `engine/tests/` for `rglob(`, `os.walk(`, `.glob(` (recursive and non-recursive),
   and `scandir(`/`iterdir(` to find directory-walk patterns that could touch large,
   unbounded trees (principally `engine/.venv/`).
2. Grepped for `time.sleep(`, `asyncio.sleep(`, and bare `while` loops to find polling /
   waiting constructs with no time or iteration bound.
3. Checked the global pytest configuration (`engine/pyproject.toml`) for a suite-wide
   timeout backstop, since that changes the severity of any given instance.
4. For every hit, read enough surrounding code to determine whether the construct is
   actually bounded (by a fixed small n, a deadline, a step cap, or a small/known
   directory) or genuinely open-ended.

## Headline finding: one more unfixed instance of the exact PR #348 bug class

**`engine/tests/test_no_direct_bar_writes.py:45`** — `_engine_py_files()`:

```python
EXCLUDE_DIRS = ("tests",)   # line 41 — no .venv/node_modules/.git exclusion

def _engine_py_files():
    for path in ENGINE_ROOT.rglob("*.py"):     # line 45
        rel = path.relative_to(ENGINE_ROOT).as_posix()
        if any(rel == d or rel.startswith(d + "/") for d in EXCLUDE_DIRS):
            continue
        yield path, rel
```

This is byte-for-byte the same shape as `test_daily_pnl_single_writer.py` *before* PR #348:
`ENGINE_ROOT = Path(__file__).resolve().parent.parent` (i.e. `engine/`), walked with
`.rglob("*.py")`, excluding only `"tests"`. `engine/.venv/` (confirmed present at
`C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv`) and `engine/.venv.failed-rebuild-*/`
sit directly under `ENGINE_ROOT` and are **not** excluded, so every run of
`test_save_bars_is_sole_bar_writer` and `test_allowlist_is_current` walks and
`.read_text()`s the entire `.venv` site-packages tree.

**Verified scale (live measurement, main repo checkout, not this worktree — this worktree
has no `.venv` of its own):**

```
cd engine && python -c "... Path('.').rglob('*.py') ..."
total .py files under engine/: 26960   elapsed: 25.9s (no contention)
```

That is the same order of magnitude as the 24,915 files cited in the PR #348 commit message
for the now-fixed `daily_pnl` test — this file has not been given the same fix. Under disk
contention (the exact condition PR #348 documents: "observed: >30s timeout on a single
`path.read_text()` call during concurrent test runs"), this test is exposed to the identical
failure mode: a single slow read pushes the test past pytest's global 30s timeout.

**Risk assessment: HIGH — same bug class as the fixed instance, currently unpatched, runs
in every default `pytest` invocation (no `manual`/`integration` marker).** This is the
clearest, highest-confidence finding of the scan and the one I'd prioritize for a follow-up
one-line fix mirroring PR #348 (`EXCLUDE_DIRS = ("tests", ".venv", "node_modules", ".git")`).

## Other `rglob`/`glob` directory-walk sites — bounded, low risk

| File:line | Pattern | Why it's bounded |
|---|---|---|
| `test_daily_pnl_single_writer.py:58` | `ENGINE_ROOT.rglob("*.py")`, `EXCLUDE_DIRS = ("tests", ".venv", "node_modules", ".git")` | **Fixed in PR #348.** Confirmed via `git log`/`git show bf57346`. Runtime dropped from "~30s+ (timeout)" to 2.93s per the commit message. |
| `test_no_direct_anthropic_posts.py:59` | `(ENGINE_ROOT / d).rglob("*.py")` for `d in ("agents", "discord")` | Scoped to two small subdirectories, not `ENGINE_ROOT` itself. Verified live: `agents/` = 35 `.py` files, `discord/` = 59 `.py` files, neither contains a nested `.venv`. Recursive walk of ~94 files is not a hang risk regardless of exclusion list. |
| All `Path(...).glob("*.ext")` hits (non-recursive, single-level) — `test_analyze_jarvis_log.py:376`, `test_backup_database.py:83/96`, `test_bookmark_vault_renderer.py:276`, `test_cache_contamination_audit.py:39/44`, `test_discord_deep_analyzer/test_gbrain_sink.py:31`, `test_free_daily_export.py:119`, `test_paper_runner_atomic_state.py:25/42`, `test_reconcile_questdb.py:347/393`, `test_trading_journal.py:337`, `test_verdict_schema.py:209` | Non-recursive `.glob()` on `tmp_path`-scoped, cache, vault, or journal directories | Single-level listing (no recursion into subdirectories) against small, test-owned or bounded-size real directories — cannot recurse into `.venv` even if it were a sibling. No hang risk. |
| `test_routes_wired.py:222` | `glob.glob(os.path.join(router_dir, "*_router.py"))` | Non-recursive, scoped to one known router directory. Low risk. |

`os.walk(`, `scandir(`, and unbounded `iterdir()` recursion: **no matches** in `engine/tests/`
(the two `iterdir()` hits found are `not any(dir.iterdir())` emptiness checks on `tmp_path`
fixtures — single-level, bounded, unrelated to this bug class).

## Sleep / polling patterns — mostly bounded, no second hang-class instance found

Grepped all `time.sleep(`/`asyncio.sleep(` calls (61 matches across ~25 files) and all
`while` loops. Global backstop first, since it changes every verdict below:

**`engine/pyproject.toml:54` sets `timeout = 30`** (pytest-timeout, applied to every
collected test by default; `manual`-marked tests are excluded from collection entirely per
`addopts = ["-m", "not manual"]`). This caps the worst case for any single non-`manual` test
to ~30s before pytest-timeout's watchdog fires. Two caveats worth flagging for the follow-up
decision, not fixed by this scan:
- On Windows, pytest-timeout falls back to its **thread-based** timeout method (no
  `SIGALRM`); on fire it dumps stacks and hard-kills the process (`os._exit`), which aborts
  the *entire* pytest run, not just the offending test — so "capped at 30s" still means one
  bad test can zero out an entire CI run's results, not fail gracefully as a single red test.
  This is exactly what the PR #348 root-cause note describes.
  [UNVERIFIED: exact pytest-timeout method selection on this repo's pinned version — inferred
  from pytest-timeout's documented Windows behavior, not independently confirmed by running it.]
- `manual`-marked tests (`test_ibkr_e2e_paper.py`, three tests) are **excluded from the
  timeout net entirely** because they're excluded from default collection — the pyproject.toml
  comment for this addopts line says as much: "'manual' tests need a live IB Gateway and hang
  the asyncio loop (no timeout can interrupt the tick subscription)". This is a documented,
  intentional exception, not a latent bug.

Classified every hit:

**Well-designed timeout/deadline tests (exemplars, not risks):**
- `test_options_backtest_router.py:87-94` (`_wait_for_status` helper) — polls with
  `time.monotonic()` deadline + explicit `AssertionError` on timeout. This is the *correct*
  pattern the other polling code should be compared against.
- `test_llm_call_timeout.py:88-120` — three `asyncio.sleep(30)` calls, all wrapped in
  `client._bounded(...)` with a short (0.2s) timeout under test, and each asserts
  `elapsed < 3.0`. Deliberately simulates a hang to prove the production timeout guard fires;
  low risk because the whole point of the test is that the 30s sleep is never reached. Minor
  edge case: if the production `_bounded()` timeout regresses and stops firing, this test
  would race pytest-timeout's global 30s ceiling instead of failing with a clear assertion —
  acceptable given what the test needs to simulate.
- `test_scanner_pause_responsiveness.py:140-148` — `asyncio.sleep(3600)` inside a real task
  that is explicitly `.cancel()`-ed via `scanner.stop()` within the same test; asserts
  `real_task.cancelled() or real_task.done()`. Low risk — the long sleep is never awaited to
  completion by design.

**Unbounded `while` polling loop — same *shape* as the fixed bug class, lower blast radius:**
- `test_rl_module.py:187` (`test_rl_environment_episode_metrics`) and `:203`
  (`test_rl_environment_full_episode_no_crash`) — `while not done:` with no step cap, relying
  solely on the `TradingEnvironment`'s own `terminated`/`truncated` flags to end the loop.
  Data is synthetic and finite (`n_bars=200`/`150`), so termination is expected in practice,
  but there is **no explicit escape hatch** — contrast with the sibling file
  `test_rl_strategy.py:131-135`, which has the *identical* `while not terminated:` shape but
  guards it: `if steps > 200: pytest.fail(...)`. If a future regression in
  `TradingEnvironment`'s bar-exhaustion logic ever fails to set `terminated`/`truncated`,
  these two tests hang with no diagnostic until the global 30s pytest-timeout kills the whole
  run — same *failure signature* as the rglob bug (silent unbounded wait, no local backstop),
  just gated behind an internal-code-correctness assumption instead of a filesystem-size
  assumption. **Risk: MODERATE** — not filesystem I/O, so it can't degrade under disk
  contention the way the rglob instances can, but it is the one other "no local bound, relies
  on an external invariant" pattern found in the sweep, and the fix is trivial (copy the
  `test_rl_strategy.py` step-cap idiom into both loops).

**Fixed small-duration sleeps — flakiness risk under load, not a hang risk:**
The remaining ~50 `sleep()` calls (`test_price_cache.py`, `test_speculation.py`,
`test_risk_alert_manager.py`, `test_risk_coverage_supplement.py`, `test_task_board.py`,
`test_pipeline_run_human_gate.py`, `test_ib_data_watchdog.py`, `test_ib_reconnect.py`,
`test_pipeline_profiler.py`, `test_scheduler_safety.py`, `test_alert_wiring_smoke.py`,
`test_alert_manager_delivery_logging.py`, `test_predictive_maintenance.py`, `test_scanner.py`,
`test_orchestrator.py`) are all single fixed-duration sleeps (0–1.1s) used to cross a TTL
boundary, let an event loop tick, or wait for a debounce window — every one of them always
returns on its own; none loop indefinitely. `test_speculation.py`'s TTL tests
(`ttl=1` + `time.sleep(1.1)`, three call sites) have the tightest margin (0.1s) and are the
most likely of this group to flake under heavy CPU contention, but flaking (occasional false
red) is a different failure mode from hanging (never completes) and is out of scope for
RISK-010 as scoped ("async test flakiness" in the register's title notwithstanding — the
concrete incident that opened this investigation was a hang, not a flake).

**Gated by markers, excluded from default collection:**
`test_ibkr_e2e_paper.py` (`@pytest.mark.manual`, 3 sites) and `test_ib_paper_e2e.py`
(`@pytest.mark.integration_ib`, 3 sites) contain real IB Gateway sleeps but are excluded from
default `pytest` runs (`-m "not manual"` in addopts; `integration_ib` per pyproject.toml's
marker doc "skips if unavailable"). Not evaluated further — out of scope for the default CI
hang risk this scan is chasing.

## Summary table

| Finding | File:line | Bug class | Risk | Status |
|---|---|---|---|---|
| `.rglob("*.py")` over `ENGINE_ROOT` w/ only `tests` excluded | `test_no_direct_bar_writes.py:45` | Unbounded recursive walk incl. `.venv` (~27k files) | **HIGH** | **Unfixed** |
| Same pattern | `test_daily_pnl_single_writer.py:58` | same | — | Fixed, PR #348 (bf57346) |
| `.rglob("*.py")` scoped to `agents/`+`discord/` | `test_no_direct_anthropic_posts.py:59` | Recursive walk, but small bounded dirs | Low | No action needed |
| Non-recursive `.glob()` on tmp/cache/vault dirs (13 sites) | see table above | Bounded by construction | Low | No action needed |
| `while not done:` w/ no step cap (2 sites) | `test_rl_module.py:187,203` | Unbounded wait on internal invariant, no local backstop | Moderate | Candidate for step-cap fix (pattern exists 2 lines away in sibling file) |
| Fixed-duration sleeps (~50 sites) | multiple | Bounded, some tight margins | Low (flakiness, not hang) | No action needed |
| `manual`/`integration_ib`-gated IB sleeps | `test_ibkr_e2e_paper.py`, `test_ib_paper_e2e.py` | External-service wait | Low (excluded from default runs) | No action needed |

## Recommendation for the follow-up fix decision

1. **Do first, trivial, high-confidence:** apply the identical one-line fix from PR #348 to
   `test_no_direct_bar_writes.py:41` — change `EXCLUDE_DIRS = ("tests",)` to
   `EXCLUDE_DIRS = ("tests", ".venv", "node_modules", ".git")`. Same root cause, same fix
   shape, already precedented and reviewed once.
2. **Optional, low-cost:** add the `test_rl_strategy.py`-style step cap
   (`if steps > N: pytest.fail(...)`) to the two `while not done:` loops in
   `test_rl_module.py`. Not urgent (synthetic/finite data makes non-termination unlikely
   today) but cheap insurance and brings the file in line with its own sibling test's idiom.
3. **No action recommended** for the non-recursive globs, the bounded `agents`/`discord`
   rglob, the deadline-based poll helper, the deliberately-simulated-hang timeout tests, the
   cancelled-long-sleep test, or the marker-gated IB integration tests — all are either
   correctly bounded already or intentionally excluded from default collection.
4. Once (1) is applied, RISK-010 in `docs/strategic/05_RISK_REGISTER.md` can be updated from
   "Open — verify" to reflect: one instance found and fixed pre-scan (PR #348), one sibling
   instance found by this scan and fixed, remainder of the test tree swept clean of the same
   bug class as of 2026-07-09.
