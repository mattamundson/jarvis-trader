# `MES_trend_rank11` re-run on the repaired ruler (2026-09-18, round 3 T4)

## Why

`MES_trend_rank11_deep-2026-08-17-refresh` was the store's strongest historical claim — a **CORE**
PASS with `p_edge` 0.9968, the only verdict that qualified on the core path rather than the ALT path.
The trust register (PR #888) filed it as `no-provenance` + `pass-at-risk`: not shown false, not shown
true, unsupportable by its own artifact. One run converts that into a measurement.

## Ref under test (read back, not assumed)

| | |
|---|---|
| worktree HEAD | `9691707679a1aac9233f8d072f9156c59bf98cc6` |
| `origin/master` | `9691707679a1aac9233f8d072f9156c59bf98cc6` (equal) |
| `engine/backtest/backtester.py` blob | `660311c30515e18d4c3fae80ae941b71baaa761b` (the post-ledger-fix blob) |
| cache selected | `MES_2019-05-05_2026-08-26_1h.csv` — 43,010 bars, 2019-05-05 → 2026-08-26 |
| command | `env -u PYTHONPATH .venv/Scripts/python.exe backtest/run_mes_trend_rank11.py` |

Ref equality and the blob hash were printed by the run script itself. This is deliberate: an earlier
round-3 task asserted a checkout that had silently failed, so every measurement now carries the ref it
actually ran on.

## Result: the CORE PASS reproduces

| metric | archived 2026-08-17 refresh¹ | re-run 2026-09-18 | CORE floor | |
|---|---|---|---|---|
| verdict | PASS | **PASS** | — | reproduced |
| via | core | **core** | — | reproduced |
| `p_edge` | 0.9968 | **0.9959** | ≥ 0.95 | PASS |
| `pf_ci_lower` | 1.2714 | **1.229** | ≥ 1.10 | PASS |
| `mc_95th_dd` | — | **4.507 %** | ≤ 5 % | PASS |
| `dsr` (grid) | 0.9861 | **0.9818** | ≥ 0.10 | PASS |
| `wfo_consistency` | MODERATE | **MODERATE** | — | reproduced |
| grid trials | 3 | **3** | — | — |
| `cache_provenance` | **absent** | **present** | — | **fixed** |
| `deflation` block | absent | absent | — | still missing |

¹ as recorded by the verdict-store audit (PR #867) and the trust register (PR #888). The pre-run
verdict was not present at `data/gate_v2_verdicts/MES_trend_rank11.json`, so those are the audit's
recorded values rather than a byte-comparison against a snapshot.

**Conclusion 1 — the PASS is stable, not an instrument artifact.** Its 2026-08-17 CORE PASS and its
later `INSUFFICIENT_SAMPLE` arc are separated by data/period, not by the ledger defect: re-run on the
repaired ruler over the full 7.3-year span, it passes core again, with metrics moved only slightly by
the corrected cost charges (`p_edge` −0.0009, `dsr` −0.0043, `pf_ci_lower` −0.0424).

**Conclusion 2 — it is now verifiable.** Unlike all 75 other artifacts, this verdict records the cache
it ran on: `MES_2019-05-05_2026-08-26_1h.csv`, 43,010 rows, hash `e26631c0…`. It is the first
*historical* PASS to become content-addressed. Provenance recording (PRs #868/#869) works.

## Why the runner printed two FAILs under a PASS verdict

The run printed `FAIL fixed_params_min_pf: 0.8945 (need >= 1.2)` and `FAIL mc_95th_dd_pct: 4.5070
(need <= 4.0)` while declaring `PASS via core`. This is **not** a verdict inconsistency — verified in
code (`run_mes_trend_rank11.py` lines 463-475 against `_gate_v2_helpers.py`):

    CORE = pf_ci_lower >= 1.10  AND  p_edge >= 0.95  AND  mc_95th_dd <= 0.05
    ALT  = CORE + dsr >= 0.30 + fixed_params_min_pf >= 1.20 + mc_95th_dd <= 0.04 + ...

The printed thresholds (1.20, 4.0) are **ALT-path** floors. The CORE path does not require them, so a
CORE PASS with `fixed_params_min_pf` 0.8945 and `mc_95th_dd` 4.507 % is correct. The output is
nevertheless misleading: it presents ALT thresholds as the gate without saying so. **Clarity defect,
not a gate defect** — recorded here rather than silently accepted.

## The deflation blind spot persists, and it is the decision-relevant part

`dsr` here is deflated against **3 grid combos**. The campaign count for MES is **214** (PR #872,
deduped from distinct artifacts), and the measured cliff on a comparable candidate is
`0.97 @4 → 0.21 @200` (PR #886). `dsr` 0.9818 at 214 trials would be far below even the CORE floor of
0.10.

The rank11 runner records **no `deflation` block** (`"deflation" in metrics` → `False`); only the
vix_pctile runner was wired for that in PR #873. So this PASS cannot currently state its campaign
number — it is `pass-at-risk` by measurement, not merely by flag.

This is significant for the T2 decision: the "nine unevaluable PASSes" now has a *second* candidate
demonstrating the same shape as the live verdict — a PASS whose significance is carried by a
single-digit trial count. Two of two examined PASSes are in that class.

## Follow-up (bounded, not done here)

Wire `deflation_report()` into this runner as was done at `run_mes_trend_vix_pctile_rank1.py`
lines 384-444 — additive and report-only. Deliberately **not** done in this task: a code change to a
runner under time pressure is how the earlier batch-provenance edit broke 39 files, and the finding
above does not depend on it. Tracked as round-3 T6 (family-wide deflation reporting).

## Reproduce

    cd engine
    env -u PYTHONPATH .venv/Scripts/python.exe backtest/run_mes_trend_rank11.py

Expect `PASS-CORE`, `p_edge` ≈ 0.9959, and a `cache_provenance` block naming the 43,010-row deep cache.
