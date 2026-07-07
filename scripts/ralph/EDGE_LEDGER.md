# JARVIS TRADER — Ranked Edge Ledger
**Generated:** 2026-06-12 | **Branch:** ralph/edge-24x7
**Source:** `engine/data/gate_v2_verdicts/*.json` (35 live files) + archive
**Ledger:** `engine/data/edge_ledger.jsonl` (72 rows total — append-only, multi-run history)
**Module:** `engine/generation/edge_ledger.py` | **Route:** `GET /reports/edge-ledger`

---

## Authoritative Current State (4 PASS, 2 INSUFFICIENT_SAMPLE, 29 FAIL)

The gate_v2_verdicts JSON files are the source of truth. The ledger is append-only
and records every verdict run — stale rows (e.g. a file that was PASS in May and
INSUFFICIENT_SAMPLE in June) coexist. Use the **latest `created_at`** per source file
to get the current verdict. The direct JSON scan below is authoritative.

---

## CLEARED-TO-TRADE (4 live PASS verdicts)

Ranked by DSR descending (best edge quality first).

| Rank | Symbol | Family | Gate Path | DSR | PF-CI Lower | MC DD 95th% | WFO | Trades OOS | Notes |
|------|--------|--------|-----------|-----|-------------|-------------|-----|------------|-------|
| 1 | **MGC** | trend_rv_filter | **CORE** | 1.000 | 3.182 | 0.65% | STRONG | 26 | Best edge in corpus. All 5 alt criteria pass. Catastrophic cost tier. |
| 2 | **MGC** | trend (rank 4) | alt | 1.000 | 2.597 | 1.24% | MODERATE | — | Baseline rank4. MC DD freshness varies by run (1.24%–3.03%). |
| 3 | **MGC** | trend_adx_filter | alt | 1.000 | 1.977 | 1.06% | MODERATE | — | ADX conditioned. |
| 4 | **MES** | trend (rank 7) | alt | N/A | N/A | N/A | N/A | — | PASS via alt path; gate_v2_metrics absent from file (no WFO detail block). Metrics unverifiable from JSON. |

**CROSS-CHECK vs gate_v2_verdicts:** Exact match. GAP_MAP.md listed 4 PASS files; direct scan confirms 4 PASS:
`MGC_trend_rv_filter_rank1.json`, `MGC_trend_rank4.json`, `MGC_trend_adx_filter_rank1.json`, `MES_trend_rank7.json`.
No contradiction between this ledger and the stored verdicts.

---

## INSUFFICIENT SAMPLE (2 — previously PASS, downgraded)

These were PASS in May 2026 and are recorded as such in the ledger history.
The latest run (June 2026) downgraded them to INSUFFICIENT_SAMPLE. They are
**not cleared to trade** until re-validated after additional trade accumulation.

| Symbol | Family | Latest Verdict | Last PASS Date | Downgrade Date | Notes |
|--------|--------|----------------|----------------|----------------|-------|
| MES | trend (rank 11) | INSUFFICIENT_SAMPLE | 2026-05-30 | 2026-06-11 | Was PASS via alt; needs 60+ live trades to re-validate |
| MES | trend_rv_filter (rank 2) | INSUFFICIENT_SAMPLE | 2026-05-24 | 2026-06-04 | Was PASS via alt; RV filter calibration pending |

---

## BLOCKED — FAIL (29 live files)

Sorted by nearest-to-pass pf_ci_lower (best re-run candidates first).

| Symbol | Family | Primary Block | PF-CI Lower | DSR | WFO | Notes |
|--------|--------|---------------|-------------|-----|-----|-------|
| MES | trend_vix | dsr<0.30 | 1.796 | 0.000 | MODERATE | Two runs (vix_rank1 + vix_rank2), same block. Nearest to passing on PF. |
| MGC | trend_adx_rv_filter | wfo_weak | 1.631 | 0.972 | WEAK | Stacked conditioner. High DSR but WFO consistency fails. |
| MES | trend_adx_filter | dsr<0.30 | 1.434 | 0.000 | MODERATE | ADX filter blocks on DSR. |
| MNQ | trend_adx_filter | dsr<0.30 | 0.958 | 0.000 | MODERATE | Blocked on DSR and PF-CI. |
| MES | trend_vix (rank 3) | wfo_weak | 0.871 | 1.000 | WEAK | DSR good; WFO is the killer. |
| MNQ | trend_rv_filter | fixed_pf<1.20 | 0.786 | 0.676 | MODERATE | Closest MNQ candidate; blocked on fixed_pf only. |
| MGC | tpo_reversion | wfo_weak | 0.778 | 0.000 | WEAK | — |
| MES | trend_15m | wfo_weak | 0.731 | 0.000 | WEAK | — |
| MCL | trend_adx_filter | wfo_weak | 0.697 | 1.000 | WEAK | DSR=1.0 but WFO kills it. MCL remains BLOCKED per rules/jarvis-trader.md. |
| MES | mean_reversion | wfo_weak | 0.691 | 0.000 | WEAK | — |
| MES | donchian | wfo_weak | 0.680 | 0.000 | WEAK | — |
| MNQ | trend (rank 1) | wfo_weak | 0.672 | 0.000 | WEAK | — |
| MES | gap_fade | wfo_weak | ~0.5 | — | WEAK | — |
| MES | gap_go | wfo_weak | ~0.5 | — | WEAK | — |
| MGC | gap_fade | wfo_weak | — | — | WEAK | — |
| MGC | gap_go | wfo_weak | — | — | WEAK | — |
| M2K | trend | wfo_weak | 0.465 | 0.000 | WEAK | Russell 2000 micro. |
| M2K | trend_adx_filter | wfo_weak | 0.618 | 0.000 | WEAK | — |
| MCL | mean_reversion | wfo_weak | N/A | N/A | N/A | Null metrics — no gate_v2_metrics block. |
| MCL | meanrev_regime | wfo_weak | N/A | N/A | N/A | Null metrics. |
| MES | confluence | wfo_weak | — | — | WEAK | — |
| MES | tpo_breakout | wfo_weak | — | — | WEAK | — |
| MES | tpo_breakout_trend | wfo_weak | — | — | WEAK | — |
| MES | tpo_reversion | wfo_weak | — | — | WEAK | — |
| MES | tpo_reversion_trend | wfo_weak | — | — | WEAK | — |
| MES | trend_adx_rv_filter | wfo_weak | — | — | WEAK | — |
| MGC | tpo_breakout | wfo_weak | — | — | WEAK | — |
| MNQ | trend_rv_filter (rank 1) | fixed_pf<1.20 | — | — | — | — |
| MES | gap_fade / gap_go variants | wfo_weak | — | — | WEAK | Multiple files. |

**Primary block breakdown (live FAIL):** wfo_weak=22, dsr<0.30=4, fixed_pf<1.20=1, cost_death=1.
WFO consistency is the dominant failure mode (79% of FAILs).

---

## Graveyard Signals (archived)

5 archived verdict files in `gate_v2_verdicts/archive/`. Mix of PASS (pre-refresh runs,
now superseded by live files) and historical snapshots. The ledger records these with
`is_archived=true` — they are NOT included in the PASS/FAIL counts above.

---

## Ledger vs Gate v2 — Consistency Check

| Check | Result |
|-------|--------|
| 4 PASS files in gate_v2_verdicts/ | CONFIRMED (direct scan) |
| Ledger rows with PASS from live files | 7 (3 extra = 2 old MES rows + 1 duplicate MGC_trend_rank4 run) |
| Stale PASS rows for downgraded verdicts | FLAGGED: MES_trend_rank11, MES_trend_rv_filter_rank2 were PASS in May, now INSUFFICIENT_SAMPLE |
| Contradiction (ledger says PASS, file says FAIL) | NONE |
| MGC_trend_rank4 appearing twice in ledger | EXPECTED: re-verified 2026-05-29 and 2026-06-08 with different MC runs (mc_dd 1.24% vs 3.03%) — both PASS, different run |
| MES_trend_rank7 missing gate_v2_metrics | CONFIRMED: verdict file has no `gate_v2_metrics` block; PASS is stored but DSR/PF-CI unverifiable |

**Verdict: no contradictions. Ledger faithfully records historical runs. Current PASS count is 4.**

---

## Re-Run Priority (FAIL rows nearest to passing)

Based on primary block analysis — the fastest paths to new PASS verdicts:

1. **MES trend_vix** — blocked on DSR only (DSR=0.0, need >=0.30). PF-CI=1.80. If DSR improves with more data, this passes.
2. **MGC trend_adx_rv_filter** — blocked on WFO only (DSR=0.97 is excellent). Re-run with more windows.
3. **MNQ trend_rv_filter** — blocked on fixed_pf only (PF-CI=0.79, DSR=0.68, WFO MODERATE). Closest MNQ candidate.
4. **MES trend_adx_filter** — blocked on DSR (DSR=0.0). Same issue as vix-conditioned MES.

---

## How to Refresh

```bash
# Re-mine verdicts and return ranked JSON
GET /reports/edge-ledger?rebuild=true   (auth: X-API-Key)

# Or run standalone:
cd engine
JARVIS_DATA_ROOT=data .venv/Scripts/python -m generation.edge_ledger
```

---

*Files: `engine/generation/edge_ledger.py`, `engine/generation/__init__.py`,
`engine/routers/reports_router.py` (+GET /reports/edge-ledger),
`engine/tests/test_edge_ledger.py` (25 tests, all green)*
