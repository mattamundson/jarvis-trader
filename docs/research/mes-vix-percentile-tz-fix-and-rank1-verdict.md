# MES VIX-percentile tier gate — tz-alignment fix and rank1 verdict record

Date: 2026-09-17
Author: unattended strategy-validation loop (`Jarvis-Strategy-Validation-Loop`)
Queue item: `MES_sma_trend_vix_pctile_blockCrisis_v1` (priority 4, `ready_to_backtest`)
Runner: `engine/backtest/run_mes_trend_vix_pctile_rank1.py`
Cache: `MES_2019-05-05_2026-08-26_1h.csv` — 43,010 bars, 2019-05-05 → 2026-08-26 (7.31y),
0 duplicate / 0 NaN timestamps, sha256 `e26631c012b128284e61526dad78e7d39a3c180634dad7398a7dd8cc225f83fe`.
VIX: yfinance `^VIX` daily, 1,855 bars, 2019-05-06 → 2026-09-17.

Scope: research evidence only. No live/paper routing, risk limit, kill-switch, broker,
`.env`, PM2, active-instrument gate, or order behaviour was changed. MES remains
**not approved** (rank11 verdict on file is `INSUFFICIENT_SAMPLE`/FAIL).

## 1. Blocker found: pandas-3 mixed-tz comparison aborted every window

The first execution of the preregistered runner produced **no OOS results and no verdict**:
82/82 windows aborted, 328 identical errors:

```
[WARN] IS error block=none: Cannot compare dtypes datetime64[s] and datetime64[us, UTC]
```

Root cause: `backtest/trend_signals.py` compared a tz-naive daily VIX index
(`datetime64[s]`, from yfinance) against a tz-aware bar index (`datetime64[us, UTC]`,
because `MES_2019-05-05_2026-08-26_1h.csv` stores `+00:00` offsets). pandas ≥ 3.0 raises
`TypeError` on mixed-tz comparisons instead of silently comparing unequal, so
`vix_daily.reindex(bar_dates, method="ffill")` raised inside every window.

Direct causal proof (same cache, pandas 3.0.5):

```
OLD path: vix idx datetime64[s]  vs bar_dates datetime64[us, UTC]
          -> TypeError: Cannot compare dtypes datetime64[s] and datetime64[us, UTC]
NEW path: vix idx datetime64[s]  vs bar_dates datetime64[us]
          -> OK, VIX ffilled onto 43,008 / 43,010 bars (range 11.54 - 82.69)
```

Blast radius: ten modules pass `vix_df` into `generate_sma_trend_signals`
(`iterate.py`, `signals.py`, `composite_strategies.py`, `verify_honest_metrics.py`, and the
`run_mes_trend_vix*` / `run_trend_vix_pctile_gate` runners), so the entire VIX-gated
research family was silently unmeasurable on any tz-aware cache under pandas 3.

### Fix

`backtest/trend_signals.py` — one helper, `_daily_date_index()`, normalizes both sides to a
tz-naive midnight index before any comparison or ffill `reindex`. Tz-aware indexes are
converted to UTC first, so the calendar date stays the UTC date — identical to the previous
behaviour on caches stored without offsets, and no look-ahead is introduced (the daily close
is still only ffilled forward onto later bars).

Regression tests: `engine/tests/test_trend_signals_vix_tz_alignment.py` (9 tests) — the mixed-tz
case, tz-aware/tz-naive parity of the resulting `vix_level` series, point-in-time same-day ffill,
the Crisis block, and a discriminating control proving the tier series is not silently all-NaN.

## 2. Second blocker: runtime config guard on the research path

With the dtype bug fixed, all windows then failed on
`1 validation error for TradingConfig — API_KEY must be explicitly set to a real value`,
because the `Backtester` import chain validates runtime config. Resolved the documented way:
an explicit **non-secret dummy** `API_KEY` in the process environment only. No `.env` file was
read, written, or printed. This runner footprint (research script → runtime config validation)
is a known sandboxing wrinkle, not a config change.

## 3. Verdict produced (deep cache, 82 OOS windows)

| metric | value | floor / note |
|---|---|---|
| verdict | **PASS via alt** | core path FAIL |
| `pf_ci_lower` | 2.2562 | ≥ 1.10 ✓ |
| `p_edge` | **0.5926** | ALT does not gate on p_edge; **< 0.60 documented activation criterion**, and < 0.75 rank11 baseline / lineage target ✗ |
| `mc_95th_dd_pct` | 0.9053 % | ≤ 4.0 (ALT) ✓ |
| `dsr` | 0.9752 | ≥ 0.30 (ALT) ✓ **but deflated for n_combos=4 only — see caveat** |
| `wfo_consistency` | MODERATE | MODERATE/STRONG ✓ |
| `fixed_params_min_pf` | 1.5030 | ≥ 1.20 ✓ |
| `cost_survives_through` | pessimistic | catastrophic tier FAIL (PF 0.1379, 9 trades) |
| OOS windows with trades | 54 / 82 | 63 total OOS trades |
| champion `blocked_tiers` | **`[]` (no gate)** | pre-registered hypothesis was `["Crisis"]` |

Per-combo fixed-params result on the full deep cache — the block made results **worse**:

```
block=[]                    PF=1.6952  trades=122
block=[Crisis]              PF=1.5581  trades=112
block=[Crisis, HighVol]     PF=1.5030  trades=89
block=[HighVol]             PF=1.7095  trades=99
```

## 4. Interpretation — this is not promotion evidence

1. **The pre-registered hypothesis is falsified as an improvement.** Blocking the Crisis tier
   lowers PF (1.6952 → 1.5581) and blocking Crisis+HighVol lowers it further (1.5030). The
   in-sample champion selected on the majority of windows is the *no-gate* baseline, i.e. the
   adaptive percentile gate adds nothing over the plain SMA(60,200) trend on this cache.
2. **The ALT PASS is mechanically correct but weak.** The ALT conjunction is
   `dsr ≥ 0.30 ∧ wfo ∈ {MODERATE,STRONG} ∧ fixed_params_min_pf ≥ 1.20 ∧ cost_passes ∧ mc_95th_dd ≤ 0.04`;
   p_edge is not part of it. The candidate still misses the documented activation criterion
   `p_positive_edge ≥ 0.6` (0.5926) and its own stated target `p_edge ≥ 0.75`.
3. **DSR is not trustworthy as reported.** The runner deflates for its own grid size
   (`n_combos=4`). The true MES-campaign trial count against this deep cache is in the
   hundreds, and DSR is a cliff (a PASS at 3–4 trials collapses by 9). Re-deflate before any
   claim rests on `dsr=0.9752`.
4. **No CAGR was computed.** The runner records PF/DD/Sharpe per window but no equity or PnL,
   so the economic-triviality check (`CAGR` first — the certified live champion 50/200/2.0 is
   −0.26 % CAGR over 7.27y at fixed params) is **outstanding**. Per-window Sharpe values are
   engine-annualized and must not be quoted without the observed trades-per-year correction.

## 5. Decision

- **Not promoted.** `candidate_registry.json` frozen params are left **unchanged**
  (`fast=60, slow=200, atr_trail_mult=2.0, vix_regime_block=["Crisis"], vix_regime_lookback=252`).
- **No new id registered.** The registry's activation protocol says to register a new id when
  the run's champion blocked-tier set differs from `["Crisis"]`. Here the champion is the empty
  set — there is no Crisis-blocked champion to register, and the no-gate baseline is simply the
  already-recorded rank11 trend, so the correct record is a falsification, not a new candidate.
- `MES_sma_trend_vix_pctile_blockCrisis_v1` stays at `status: paused` / `deployed_live: false`.
  Its `lock_in_sample` is intentionally left `PENDING`: populating it from an ALT PASS whose
  champion is the baseline would overclaim.

## 6. Evidence artifacts

Archived to `C:/Users/mattm/master-jarvis/second-brain/reports/strategy-validation-20260917/`
(the verdict JSON is gitignored by `.gitignore:341`, so it is archived outside the repo):

| artifact | archived path | sha256 |
|---|---|---|
| verdict JSON (28,100 bytes) | `.../strategy-validation-20260917/MES_trend_vix_pctile_rank1_verdict_2026-09-17.json` | `90c9bd80590015ddec118ad29e9f59043d5b19aae4075619f77d19039555771a` |
| pre-fix aborted run log (43 KB) | `.../strategy-validation-20260917/mes_vix_pctile_rank1_run_PREFIX_aborted_2026-09-17.log` | `6a2880c4d157eb09ba5da3f2a8292e1e386d667a2bcd7cbe9833feac22cc2d3f` |
| post-fix verdict run log (18 KB) | `.../strategy-validation-20260917/mes_vix_pctile_rank1_run_POSTFIX_verdict_2026-09-17.log` | `3b02942b907227dd4c36f52ff507cab26f721987cdc197209a07bb003bc7f920` |

Live (gitignored) verdict path: `engine/data/gate_v2_verdicts/MES_trend_vix_pctile_rank1.json`,
created_at `2026-09-17T21:47:39Z`.

Reproduction (from `engine/`, deep cache in `backtest/cache/`):

```bash
env -u PYTHONPATH API_KEY='local-research-sandbox-dummy-not-a-credential' \
  .venv/Scripts/python.exe backtest/run_mes_trend_vix_pctile_rank1.py
```

## 7. Next bounded evidence step

`CAGR` + honest (observed-trades-per-year) Sharpe for the champion, and a DSR re-deflation at the
true MES-campaign trial count, before any further claim is made about this family. Neither is
promotion evidence; both are research-only.
