# Implementation Plan — Databento Pilot + Free Data Tiers (v1.0)

**Authored:** 2026-09-23 · **Status:** PLAN ONLY — nothing installed, purchased, or wired.
**Supersedes:** `docs/databento-integration-plan.md` (2026-08-04) — status reconciliation in §1; its step 3 is already done.
**Companion to:** `JARVIS_MARKET_DATA_TIERS_v2.0.md` (cost comparison), `JARVIS_REBUILD_WORK_BREAKDOWN_v2.0.md` (the full rebuild)

---

## §0. Is this the best path forward? — my honest answer

**Yes — but with one sequencing change, and for a reason I got wrong the first time.**

I originally framed the choice as *data tiers vs. harness rebuild*, and recommended the $0 data tier first. That was
right by accident. The actual reason it is right is sharper:

> **The repo's own 2026-08-04 diagnosis says the binding constraint is `INSUFFICIENT_SAMPLE` — 17–67 OOS trades
> against a 30–100 floor — and that the root cause is data depth (`data_loader.py` hits Polygon's `limit=50000`,
> capping ~2 years of 1h bars). If that diagnosis is correct, no amount of harness work fixes it: the Judge
> cannot certify an edge on 17 OOS trades regardless of how good the infrastructure is.**

That makes the Databento pilot a **one-day, $0 test of the core premise of the entire rebuild**. Either:

- **OOS trade counts jump (predicted 17 → 150+) and verdicts stabilize** → data depth was the constraint, the
  rebuild is justified, and we proceed with confidence; or
- **they don't jump** → the constraint is something else (strategy selectivity, session filters, cost model), and
  we learn that for $0 instead of spending months building a harness for a problem that isn't there.

**What I got wrong:** I wrote a 1,800-line rebuild blueprint before checking whether a 145-line plan with a
falsifiable criterion was already sitting in `docs/`. It was. **You do not need a new plan. You need to run the
one from August 4 that was never executed.**

**What I would change about my own recommendation:** do *not* build the PIT store, verdict store, or HUD first.
Do this pilot first. It is cheap, reversible, and it is the cheapest possible way to find out whether the rebuild
is worth continuing.

**What would change my mind:** if Step 4 (§7) shows the OOS sample does not move, then the constraint is not data
and the priority order changes to strategy/session-selection research — not infrastructure, and not more data.

**One honest caveat about this plan's cost:** the pilot is $0 in *cash* but ~**4–8 hours of your attention** if I
execute the parts that need a browser/account, and ~1 day of agent work. The expensive part is the per-contract
work in Step 5, which is deliberately gated behind Step 4's result.

---

## §1. Status reconciliation — what already exists

| Item | Aug-4 doc assumed | Verified reality (2026-09-23) |
|---|---|---|
| `databento` package installed | step 1, to do | **NOT installed** — `pyarrow`, `zstandard`, `databento`, `pip` all absent from the venv |
| `DATABENTO_API_KEY` | step 1, to do | **NOT set** in `engine/.env` (placeholder exists in `.env.example:104`) |
| `databento_loader.py` | step 3, "write it" | **ALREADY EXISTS** (280 lines) + `data/databento_adapter.py` (192 lines) + **14 tests** |
| Pilot pull MES+MGC 2015→2026 | step 2, to do | **NOT done** |
| Measure OOS sample growth | step 4 | **NOT done** — this is the entire point |
| mbp-1 measured impact | step 5 | **NOT done** |
| Standard subscription price | $179/mo (Aug-4) | **$199/mo** — Databento raised CME Globex pricing 2026-06-22 |
| Doc referenced by the adapter | `docs/decisions/market-data-vendor-roadmap-2026-07-28.md` | **DOES NOT EXIST** (phantom reference in `data/databento_adapter.py:7,104`) |
| Polars/ArcticDB speedup | "not worth it now" | still correct; re-benchmark **after** the pilot (Aug-4 §8) |

**Consequence:** the pilot is **not a build task**. It is: install one package, set one env var, run existing
tested code, and read the result. That is why this plan is short in risk and long in detail.

---

## §2. The one question this plan answers

```
After replacing ~2 years of 1h bars with 16 years of CME history,
do the gate-v2 OOS trade counts for MES (and MGC) rise enough to clear
MIN_OOS_TRADES_TOTAL, and do the verdicts stabilize?
```

Everything in §4–§9 exists to answer that question honestly. If it cannot be answered, the plan has failed
regardless of how much data was downloaded.

---

## §3. Step 0 — Preflight (30 min, do not skip)

| # | Sub-step | Exact action | Expected |
|---|---|---|---|
| 0.1 | Confirm no live-trading surface is touched | `cd engine && grep -n "LIVE_TRADING_ENABLED" .env` | `False` — **if not `False`, STOP and report** |
| 0.2 | Record baseline commit + dirty state | `git -C C:/Users/mattm/ThinkorSwim/jarvis-trader rev-parse HEAD` and `git status --porcelain \| wc -l` | a SHA + a count (baseline for rollback) |
| 0.3 | Disk headroom check | venv python: `shutil.disk_usage('C:/')` | **9.61 GB free** (verified). Installing databento adds ~150 MB — acceptable, but do **not** also start P0-1 archiving concurrently |
| 0.4 | Baseline test run (so a later failure is attributable) | `engine/.venv/Scripts/python.exe -m pytest tests/test_databento_adapter.py tests/test_databento_loader_cache.py -q` | **14 passed** expected (8 adapter + 6 loader-cache) |
| 0.5 | Confirm the loader's dark contract still holds | `engine/.venv/Scripts/python.exe -m backtest.databento_loader` | `API key present: False` / `databento package: False` / `result rows: 0` — **graceful, no traceback** |
| 0.6 | Snapshot the current MES cache truth | `ls -la engine/backtest/cache/MES*.csv` and count rows | this is the "before" number to compare against |
| 0.7 | **Write the baseline into an artifact** | save to `docs/plans/evidence/databento_pilot_baseline_<date>.md` | every later claim diffs against this file |

**Rollback for Step 0:** nothing changed. Delete the artifact if unwanted.

---

## §4. Step 1 — Install and wire Databento ($0, 30 min)

| # | Sub-step | Exact action | Expected | If it fails |
|---|---|---|---|---|
| 1.1 | **Create the Databento account** *(operator)* | sign up at databento.com | `$125` credit visible on the account page | — |
| 1.2 | **Generate an API key** *(operator)* | portal → API keys → create | a key string | **never paste the key into chat** — put it straight into `engine/.env` |
| 1.3 | Install the SDK | `uv pip install --python engine/.venv/Scripts/python.exe databento` | installs **6 packages**: `databento==0.87.0`, `databento-dbn==0.70.0`, `pyarrow==25.0.1`, `zstandard==0.25.0`, `pip==26.2.1`, `pip-system-certs==5.3` | venv has **no pip** (`python -m pip` fails) — that is why `uv pip` is required, not a workaround |
| 1.4 | Add the key to env | append `DATABENTO_API_KEY=<key>` to `engine/.env` | file contains the key; `.env` is gitignored | do **not** put it in `.env.example`, any committed file, or argv |
| 1.5 | Verify the import path | `engine/.venv/Scripts/python.exe -c "import databento, pyarrow, zstandard; print('ok')"` | `ok` | if `ImportError`: re-run 1.3 and check the `--python` path is the venv, not system python |
| 1.6 | Verify the key is *seen* by the loader | `engine/.venv/Scripts/python.exe -m backtest.databento_loader` | `API key present: True`, `databento package: True`, then a fetch attempt for MGC 1h | if `API key present: False` → the loader reads `DATABENTO_API_KEY` via `load_dotenv(engine/.env, override=False)`; an exported shell var wins, a stale one blocks it |
| 1.7 | Re-run the tests (regression) | `python -m pytest tests/test_databento_adapter.py tests/test_databento_loader_cache.py -q` | **14 passed** — unchanged | if a test flips, the install changed behaviour → **stop and report before any paid call** |

**Rollback for Step 1:** `uv pip uninstall --python engine/.venv/Scripts/python.exe databento databento-dbn pyarrow zstandard pip-system-certs` and remove the `.env` line. Zero cost, zero side effects.

---

## §5. Step 2 — Cost-controlled first pull ($0–13, 1–2 h)

**Rule: get the price BEFORE the request, not after.** Databento bills on measured size; a blind multi-year
multi-symbol request is how a "$125 credit" becomes a surprise.

| # | Sub-step | Exact action | Expected |
|---|---|---|---|
| 2.1 | **Run the estimator first** *(operator)* | databento.com/pricing → the estimator widget → dataset `GLBX.MDP3`, schema `ohlcv-1m`, symbols `MES.c.0`, range 2015-01-01 → today | a dollar figure. **Record it in the evidence file.** My arithmetic estimate is $1–2 for this single continuous series; anything wildly higher means the request is wrong |
| 2.2 | Pull the **continuous** series only (cheapest, most informative first) | `python -c "from backtest.databento_loader import fetch_ohlcv; df=fetch_ohlcv('MES','2015-01-01','2026-09-23','1h'); print(len(df), df.index.min(), df.index.max())"` | a row count ~**10× the current cache** (current MES 1h ≈ 12,477 rows; expect ≈120,000+) and a span starting 2015 |
| 2.3 | Confirm the cache was written in the standard naming convention | `ls -la engine/backtest/cache/MES_2015-01-01_2026-09-23_1h.csv` | file exists (`{SYM}_{start}_{end}_{interval}.csv` — same dir + contract as the Polygon caches) |
| 2.4 | Confirm the re-run is a **cache hit, not a re-download** | re-run the 2.2 command and watch for `[DatabentoLoader] Using cached ...` | no second API call → this is the tz-aware `_find_cache` fix working (it silently failed before `b01340b6`) |
| 2.5 | Sanity-check the bars, don't trust the count | check for: monotonic index, no duplicate timestamps, no NaN in OHLC, `volume > 0` fraction, session coverage vs Globex hours | documented in the evidence file |
| 2.6 | Repeat 2.2 for the other four micros | `MNQ`, `MCL`, `MGC`, `M2K` — same pattern | five caches; total usage still estimated **single-digit dollars** |

**Cost checkpoint:** if the estimator says more than **$25**, stop and reconsider scope before pulling. The $125
credit is for the whole research programme, not just the pilot.

**Rollback for Step 2:** delete the new cache CSVs (they are additive; the old caches remain untouched).

---

## §6. Step 3 — Falsify the existing data (1 h)

This step is the most valuable one in the plan and it is free. You now have **two independent sources for the same
symbols** — the existing Polygon/IBKR caches and Databento — which means you can test whether the numbers you have
been making decisions on are *correct*.

| # | Sub-step | Exact action | Expected |
|---|---|---|---|
| 3.1 | Run the built-in cross-check | `python -m data.databento_adapter MES --timeframe 1h --lookback 365 --tolerance 0.1` | a JSON status dict — `compared` with `max_div_pct`, `mean_div_pct`, `over_tolerance_bars` |
| 3.2 | Interpret honestly | `compared` + low divergence → current data is trustworthy. `over_tolerance_bars > 0` → **you have been backtesting on wrong prices**; quantify how wrong | write the numbers down |
| 3.3 | Check the known hazard explicitly | verify no `CL=Colgate` class error: confirm `CL` maps to `CL.c.0` and not an equity ticker (the `data-source-audit-2026-04-16.md` incident) | mapping is in `data/databento_adapter.py:45-51` — assert it |
| 3.4 | Repeat for MGC/MNQ/M2K | same command per symbol | per-symbol divergence table |
| 3.5 | Reconcile the phantom doc reference | `data/databento_adapter.py` cites `docs/decisions/market-data-vendor-roadmap-2026-07-28.md`, which **does not exist** | either create it (pointing at this plan) or fix the two references — a 5-minute cleanup that removes a misleading pointer |

**Rollback for Step 3:** none needed (read-only).

---

## §7. Step 4 — THE MEASUREMENT (the decision point) (2–4 h)

This is the step the entire plan exists for. Everything before it is plumbing; everything after it is conditional.

| # | Sub-step | Exact action | Expected |
|---|---|---|---|
| 4.1 | Identify the runner + verdict to re-run | the MES family with a fresh verdict artifact (`engine/data/gate_v2_verdicts/MES_trend_rank11.json`) and the MGC rank4 runner | one symbol, one family — do **not** fan out |
| 4.2 | Capture the **"before"** numbers | from the existing verdict artifact: OOS trade count, `pf_ci_lower`, `p_edge`, `mc_95th_dd`, `dsr`, `rolling_wfo`, verdict | the Aug-4 doc says **17 OOS trades** for MES and that `INSUFFICIENT_SAMPLE` blocks promotion |
| 4.3 | Re-run the **same** strategy on the deep cache | same runner, same params, pointed at the new `MES_2015-01-01_2026-09-23_1h.csv` (the loader's `_find_cache` will pick the wider file) | a new verdict artifact |
| 4.4 | **Compare, and write the comparison down** | OOS trades before → after; every gate metric before → after; verdict before → after | this is the answer to §2 |
| 4.5 | Apply the pre-registered success criterion | **success = OOS trades rise above `MIN_OOS_TRADES_TOTAL` AND the verdict is not degraded by the wider sample** | if the wider sample *breaks* a previously-passing edge, that is also a finding — and a more important one |
| 4.6 | Run the trial-ledger discipline | every re-run increments the campaign trial count, which **deflates DSR** | if DSR collapses at true campaign count, the "edge" was a product of trial count, not depth — exactly what happened to MGC in 2026-08 |

**Interpretation table — read this before running:**

| Outcome | Meaning | Next action |
|---|---|---|
| OOS trades 17 → 150+, verdict holds or improves | **Data depth was the binding constraint.** Rebuild is justified | proceed to Step 5 + harness work |
| OOS trades rise but verdict FAILs on the wider sample | The edge was a small-sample artifact | **stop the data spend**; go to strategy research |
| OOS trades barely move | The strategy is intrinsically selective — depth isn't the constraint | **stop**; the constraint is signal frequency, not data |
| Divergence in Step 3 was large | The historical numbers were wrong | re-derive every verdict before trusting any of them |

**Rollback for Step 4:** the new verdict artifact is additive; the old one is untouched. Revert by deleting the new
cache and re-running the old runner against the old cache.

---

## §8. Step 5 — Per-contract curves + Open Interest (ONLY if §7 succeeds) (½–1 day)

**This is new code** — and the honest scoping matters, because it is the one genuinely non-trivial build in this plan.

| # | Sub-step | Detail |
|---|---|---|
| 5.1 | Understand why existing code won't do it | `fetch_ohlcv()` pulls `{ROOT}.c.0` (**continuous lead month only**). Per-contract curves need every delivery month — the thing that makes calendar/roll/relative-value backtests possible at all |
| 5.2 | Avoid the known trap | `stype_in="parent"` returns **every constituent contract *and* calendar spreads** (e.g. `MGCG5-MGCJ5`, which legitimately print negative prices). The existing loader's docstring documents this — filter spreads out, do not blindly ingest |
| 5.3 | Write `fetch_contract_curves(symbol, start, end)` | new function in `backtest/databento_loader.py`: pull `definition` + `ohlcv-1m` with `stype_in="parent"`, then filter to outright futures by `instrument_class`/`raw_symbol` |
| 5.4 | Pull Open Interest + settlement | schema `statistics` (settlement, volume, **open interest**) per contract — this is what Norgate charges $270/yr for, available on the same credit |
| 5.5 | Store PIT-correct | every row carries `ingest_ts`, `vintage_ts`, `source='databento'`, `source_hash`, `quality` (blueprint L1 rules) |
| 5.6 | Test it | new tests mirroring `tests/test_databento_loader_cache.py` (cache hit without network, spread exclusion, tz handling) |
| 5.7 | Cost check | re-run the estimator for the per-contract pull; my arithmetic estimate is **~$7** for 6 active months × 10 products × 16y. If it exceeds ~$40, cut the window to 10 years |

**Rollback for Step 5:** new module + new caches; delete both. No existing behaviour changes.

---

## §9. Step 6 — Close the options verdict gap for $0 (parallel track, 2–3 h)

Independent of the futures pilot — this is the other blocking gap (QQQ/AAPL/TSLA trade with **no verdict on file**;
SPY trades on a **REJECTED** one).

| # | Sub-step | Exact action | Expected |
|---|---|---|---|
| 6.1 | ThetaData free account *(operator)* | sign up | **1 year of EOD stocks + options**, 20 req/min |
| 6.2 | Massive/Polygon Options Basic free *(operator)* | sign up | **2 years, daily** — ⚠️ **withholds SPX/DJI/RUT/VIX** (paid tier needed) |
| 6.3 | Enable IBKR delayed data *(operator)* | Account Management → Market Data → enable delayed | clears error **10168** immediately; ends the "0 live option rows" state |
| 6.4 | Write the smallest possible adapter | EOD chain → existing bar-quality gate → verdict path | do **not** build a surface store yet — that is Step-5-conditional work |
| 6.5 | Produce **one** honest options verdict | pick SPY (the one with a stale REJECTED verdict) and re-derive it on real chain data | a verdict you can defend, or an honest FAIL |
| 6.6 | Make the gap visible either way | surface "no verdict on file" for QQQ/AAPL/TSLA on `/evidence` | the plan's own §T5 requirement — visibility first, routing change only with your explicit call |

**Cost:** $0. **Rollback:** delete the adapter; nothing else changes.

---

## §10. Explicitly deferred (do NOT do these yet)

| Deferred | Why now is wrong |
|---|---|
| PIT store / Postgres+Timescale migration | Justified only after §7 says the data is worth storing |
| Verdict store (DB + artifact) replacing the 23 JSON files | Real, but orthogonal to the §2 question |
| HUD rebuild (58 → 14 surfaces) | The UI can't be honest until the verdict path is; also the biggest work item |
| `mbp-1` measured impact (Aug-4 step 5) | Depends on §7 succeeding, and it's the expensive GB |
| Databento Standard $199/mo | Buys **live**, which a paper-only system with a working IBKR leg does not need |
| Polars/ArcticDB activation | Aug-4 §8 proved it is **2× slower** at current sizes; re-benchmark *after* the pilot |
| Per-contract curves (Step 5) | Deliberately gated behind §7's result |
| Any harness work in `JARVIS_REBUILD_WORK_BREAKDOWN_v2.0.md` | Same gate |

---

## §11. Time and cost ledger

| Step | Cash | Agent time | Your time | Gate to proceed |
|---|---:|---|---:|---|
| 0 — Preflight | $0 | 30 min | — | baseline artifact written |
| 1 — Install + wire | $0 | 30 min | ~10 min (account + key) | 14 tests still pass |
| 2 — First pull | **$0–13** | 1–2 h | ~10 min (run the estimator) | estimator ≤ $25 |
| 3 — Cross-check | $0 | 1 h | — | divergence quantified |
| **4 — THE MEASUREMENT** | $0 | 2–4 h | — | **answers §2** |
| 5 — Per-contract | **$0–40** | ½–1 day | — | **only if §7 succeeds** |
| 6 — Free options tiers | $0 | 2–3 h | ~20 min (3 signups) | independent |
| **Total** | **$0–53** | **~2–3 days** | **~40 min** | |

Compare: the rebuild blueprint's full P0–P8 is months. **This plan is two to three days and it tells you whether
the months are worth spending.**

---

## §12. Consolidated rollback

| Step | Undo |
|---|---|
| 1 | `uv pip uninstall ... databento databento-dbn pyarrow zstandard pip-system-certs`; remove the `.env` line |
| 2 | delete `engine/backtest/cache/{SYM}_2015-*_*.csv` |
| 3 | nothing (read-only) |
| 4 | delete the new verdict artifact; re-run the old runner against the old cache |
| 5 | delete the new function + module additions + per-contract caches |
| 6 | delete the options adapter; leave IBKR delayed-data enabled (it is free and strictly better) |

**Nothing in this plan touches** `LIVE_TRADING_ENABLED`, `DO_NOT_TRADE_SYMBOLS`, risk parameters, kill-switch state,
broker routing, or the MES forward-evidence ledger.

---

## §13. Failure modes → what they actually mean

| Symptom | Real meaning | Action |
|---|---|---|
| `databento package not installed` after 1.3 | `uv pip` targeted the wrong interpreter | re-check `--python engine/.venv/Scripts/python.exe` |
| `DATABENTO_API_KEY not set` after 1.4 | an exported shell var is overriding `load_dotenv(override=False)` | check `env \| grep DATABENTO` |
| Estimator far above my arithmetic | wrong schema/symbol/range in the request | fix the request; **do not** submit |
| Fetch returns 0 rows | symbol/stype mismatch (e.g. `MES.c.0` vs `MES.FUT`) | the loader already uses `.c.0` + `stype_in="continuous"`; verify against the portal's symbology |
| Cache never hits, re-downloads each time | the tz-aware compare regressed | `tests/test_databento_loader_cache.py::test_deep_tz_aware_cache_hits` should catch it |
| OOS count rises but DSR collapses | the edge was trial-count-driven, not depth-driven | this is the **correct** answer and a valuable one — see MGC 2026-08 |
| Bars look clean but verdict is worse | wider sample includes regimes the strategy never saw | regime-slice the result before concluding anything |

---

## §14. Kill criteria — when to stop this plan

Stop and re-plan if **any** of these is true:

1. Step 4 shows OOS trade counts do not move meaningfully → the constraint is not data.
2. Step 3 shows large divergence and the existing caches were wrong → re-derive all verdicts before any further
   research (the numbers you have are not trustworthy).
3. Estimator costs exceed $25 before Step 2 / $40 before Step 5 → scope down the window.
4. Two consecutive steps fail their expected output → stop, write the failure into the evidence file, and re-plan
   rather than retrying blindly.
5. **Time-box:** if Steps 0–4 are not complete within **3 working days**, stop and reassess — that is the same
   failure mode that left the Aug-4 plan unexecuted.

---

## §15. Definition of done

- [ ] Baseline artifact written (`docs/plans/evidence/databento_pilot_baseline_<date>.md`)
- [ ] `databento` installed in `engine/.venv`; 14 existing tests still pass
- [ ] `DATABENTO_API_KEY` in `engine/.env` only (never committed, never in argv)
- [ ] Five micro caches pulled 2015→2026 with the standard naming convention; re-run is a cache hit
- [ ] Divergence vs the existing caches quantified per symbol
- [ ] **One** before/after verdict comparison written down with every gate metric
- [ ] A go/no-go decision recorded against §7's interpretation table
- [ ] Phantom doc reference (`docs/decisions/market-data-vendor-roadmap-2026-07-28.md`) resolved
- [ ] Zero change to any safety surface; no live-trading, risk, kill-switch, routing, or symbol-gate edit

---

*Nothing was installed, purchased, or provisioned in the writing of this plan. No credentials were read or written.
No live trading, risk, kill-switch, broker-routing, or symbol-gate change was made or proposed for immediate execution.*
