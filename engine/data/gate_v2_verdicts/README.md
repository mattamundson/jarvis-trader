# gate_v2_verdicts — Deep-Data Standard & Verdict Inventory

Verdict files for gate v2 strategy certification. Each `*.json` is one gate-v2
run: verdict (PASS/FAIL), `passed_via` (core/alt), `gate_v2_metrics`
(pf_ci_lower, p_edge, mc_95th_dd, dsr, wfo_consistency, fixed_params_min_pf),
WFO config, and reasons.

## Deep-data standard (established 2026-08-17)

**Only the deep cache certifies edge.** Shallow (~2.3y) caches do NOT certify —
every verdict used for promotion/demotion decisions must be produced on the
deep cache:

- Deep cache: `backtest/cache/MES_2015-01-01_2026-08-16_1h.csv` — 42,826 bars,
  actual span **2019-05-05 → 2026-08-14 (7.27y)** (filenames can lie — the
  `MES_2015-01-01_*` name starts at 2019-05-05; verify from data, not filename).
- VIX: `backtest/cache/VIX_1990-01-02_2026-08-17_1d.csv` — 9,224 daily bars
  (fetched 2026-08-17). Prior to this NO VIX file existed and every VIX gate
  silently no-op'd, making all "VIX-adjusted" results vacuous.
- Shallow caches are **quarantined, not certified**: during the 2026-08-17 deep
  revalidation they were moved out of the certification path to
  `wt-deep-reval-20260817/engine/backtest/cache/_shallow_isolated/` (that
  worktree has since been removed by peer cleanup — the policy stands: never
  certify on shallow data; the deep cache is the only validation standard).

## Deep verdicts (2026-08-17) — 1 PASS, 7 FAIL

| File | Verdict | Notes |
|------|---------|-------|
| `MES_trend_rank11.json` | ✅ **PASS (core)** | p_edge 0.9924, pf_ci 1.1402, DSR 0.9704, WFO MODERATE, 69 OOS trades, 82 windows. Sole deep PASS. |
| `MES_trend_rv_filter_rank1.json` | ❌ FAIL | RV≥9% filter degrades edge on deep data (0.992→0.551). RV filter REMOVED from live config via PR #707. |
| `MES_donchian_rank1.json` | ❌ FAIL | |
| `MES_meanrev_rank1.json` | ❌ FAIL | |
| `MES_orb_rank1.json` | ❌ FAIL | |
| `MES_pre_fomc.json` | ⚠️ INSUFFICIENT_SAMPLE | |
| `MES_turn_of_month.json` | ❌ FAIL | |
| `MGC_trend_rank4.json` | ❌ FAIL | MGC's last nominal ALT-path champion collapsed under deep data. |

## 2026-08-18 — Equity options deep validation (E7-FOLLOWUP) — 0 PASS, 2 FAIL

Debit bull-call verticals on the CERTIFIED SPY/QQQ SMA-trend signals (same ENTRY_NOW events the
shares strategy trades), gate-v2 ALT battery, deep 1d caches. Data verified FIRST with
`backtest.cache_completeness.inspect_cache_file` (both `trustworthy=True`, 0 suspicious gaps;
`US_MARKET_HOLIDAYS` extended back to 2015 — independent NYSE cross-check, zero genuine holes;
evidence script `engine/e7f_verify_caches.py`). Seeded/deterministic — re-runs reproduce
bit-identical metrics. RESEARCH-ONLY: no paper/live routing.

| File | Verdict | Notes |
|------|---------|-------|
| `SPY_options_vertical_sma_10_40_2.0.json` | ❌ FAIL | 36 tr / 26 OOS (<30), pf_ci_lower 1.0604 (<1.2), p_edge 0.8972, DSR 0.884 (inflated by tiny PnL variance), WR 38.9%, total PnL $7.73/11.6y, WFO WEAK. 30-delta/5-wide/30-DTE debit vertical does not rescue the shares edge. |
| `QQQ_options_vertical_sma_8_40_2.5.json` | ❌ FAIL | 36 tr / 27 OOS (<30), pf_ci_lower 0.5554 (<1.2), p_edge 0.724, DSR 0.724, WR 38.9%, total PnL $8.05/11.6y, WFO WEAK, non-stationary. |

Runner: `engine/backtest/run_spy_qqq_options_vertical.py`; trades CSVs under
`engine/data/options_backtests/`; journal row in `docs/BACKTEST_JOURNAL.md` (2026-08-18
E7-FOLLOWUP entry). Candidate 2 (VRP harvest) NOT run — gated on candidate 1 PASS; candidate 3
(dealer gamma) data-gated on GEX feed.

## Metric defects — do NOT quote raw engine numbers

1. **Sharpe inflated** (`backtest/metrics.py:31`): 252 annualization applied to
   per-trade returns. Correct: `honest_sharpe = engine_sharpe *
   sqrt(actual_trades_per_year / 252)`. No MES config has ever had true Sharpe > 1.
2. **DSR under-deflates**: `n_trials` = runner's own grid count (rank11 → 3), not
   campaign count (hundreds). DSR is a cliff — PASS at 3 collapses by 9 trials.
   Re-deflate before trusting any PASS.
3. **Always compute CAGR** — the certified live champion 50/200/2.0 is **−0.26%
   CAGR** over 7.27y at fixed params.
4. **Backtester silently drops entries with R:R < 1.2** (`backtester.py:1018`) —
   0 trades with no error usually means this, not a signal bug.

## Archive policy

Stale, pre-deep, or shallow-contaminated verdicts are archived to
`archive/` (e.g. `MES_trend_rank11_pre-deep-2026-08-17.json`,
`MES_trend_rank11_shallow-contaminated-2026-08-17.json`) — never deleted.
The `_journal.csv` at this level is the append-only run log; a summary of the
deep revalidation wave is in `docs/BACKTEST_JOURNAL.md` (2026-08-16/17 entries).

See `engine/backtest/_gate_v2_helpers.py` for canonical threshold constants and
`backtest/test_gate_v2_policy.py` to verify no accidental threshold drift.

## 2026-08-18 — unreadable-verdict repair (kanban B2)

**Question asked: "GATE_V2_ENFORCE_ROUTING=1 is set and many verdict files are
unreadable (missing `rank`) — is MES paper trading actually blocked?"**

**Answer: NO — MES is NOT blocked.** Verified three ways:

1. `gate_v2_policy.is_ungate_eligible("MES", family_prefixes={"trend"})` returns
   `True` — MES has two fresh trend-family PASS verdicts:
   - `MES_trend_rank11.json` (PASS core, 2026-08-16, DSR 0.9704, pf_ci 1.1402)
   - `MES_trend_rank11_honest_dsr.json` (PASS core, 2026-08-18, DSR 0.8781,
     pf_ci 1.2714 — honest n_trials re-deflation per the metric-defect note above)
2. Runtime path `backtest.signals.generate_instrument_signals(..., "MES")` with
   `GATE_V2_ENFORCE_ROUTING=1` emits `ENTRY_NOW` (not forced NO_TRADE).
3. MES is not in `DO_NOT_TRADE_SYMBOLS` and `paper_config` has it enabled=True.
   (MGC is the fully blocked one: DO_NOT_TRADE + `is_ungate_eligible` False.)

**Repaired verdict files** — 6 files failed the `VerdictSnapshot.from_dict`
schema (missing `rank`, one also missing `family`). None were MES files, but all
now parse so the policy module stops logging "unreadable verdict file" warnings:

| File | Verdict | Fix applied |
|------|---------|-------------|
| `MGC_trend_baseline.json` | PASS (stale) | `rank: 0` (baseline variant, not a rank grid) |
| `MGC_trend_mtf.json` | INSUFFICIENT_SAMPLE | `rank: 0` (mtf variant) |
| `MNQ_orb_rank1.json` | FAIL | `rank: 1` (filename declares rank1) |
| `QQQ_sma_cert_10_40_2.0.json` | FAIL | `rank: 0`, `family: "trend"` (cert runner schema) |
| `ZB_trend_diversifier.json` | INSUFFICIENT_SAMPLE | `rank: 0` (diversifier) |
| `ZN_trend_diversifier.json` | INSUFFICIENT_SAMPLE | `rank: 0` (diversifier) |

All 99 verdict JSONs now pass schema validation; `tests/test_gate_v2_policy.py`
(40) + `tests/test_gate_v2_routing_enforcement.py` (25) = 65 passed.

**Decision: keep `GATE_V2_ENFORCE_ROUTING=1`.** The enforcement is working as
designed — it fails open (missing/stale/FAIL → NO_TRADE) and MES clears it via
fresh PASS verdicts. No config change needed. The unreadable files were a data
hygiene issue (producers writing non-rank-grid variants without the required
`rank` key), now repaired in place. Verdict files remain gitignored runtime
state per the 2026-06-06 stale-verdict incident; this repair is on-disk only.
