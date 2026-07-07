# Verdict Lifecycle — Archive → WFO → Compare → Commit

*Reference doc for the gate v2 verdict refresh workflow.*

---

## Overview

A "verdict" is the output of one WFO runner: a JSON file under `engine/data/gate_v2_verdicts/`
that records whether a strategy's parameter combination cleared gate v2 thresholds and is
authorized for live/paper trading. Verdicts expire after 30 days (`VERDICT_TTL_DAYS = 30` in
`scoreboard.py` and `live_readiness.py`).

The lifecycle has four phases:

```
1. ARCHIVE  — save the current live verdict before re-running
2. WFO      — re-run the runner to generate a fresh verdict
3. COMPARE  — diff old vs new: did the champion hold or regime-shift?
4. COMMIT   — commit the new verdict (or roll forward to next rank)
```

---

## Phase 1: Archive

Before re-running, copy the current verdict into `engine/data/gate_v2_verdicts/archive/`.
This preserves the old file so `compare_verdicts.py` can diff them.

```powershell
# Example: archiving MES rank11 before a refresh
$src = "engine\data\gate_v2_verdicts\MES_trend_rank11.json"
$dst = "engine\data\gate_v2_verdicts\archive\MES_trend_rank11.json"
Copy-Item $src $dst -Force
```

The archive directory is excluded from `scoreboard.py`'s glob (`*.json` at the directory root only).

---

## Phase 2: WFO (Walk-Forward Optimization)

Run the runner for the rank being refreshed. The runner:
1. Pulls bars from the cache (see `engine/data/cache/`).
2. Walks over parameter grid + OOS windows.
3. Calls `_compute_gate_v2()` on the champion parameter set.
4. Writes a new JSON to `engine/data/gate_v2_verdicts/<SYMBOL>_<family>_rank<N>.json`.

```powershell
# From engine/ directory
.venv\Scripts\python backtest\run_mes_trend_rank11.py
```

Active runner scripts:

| Symbol | Family | Rank | Script |
|--------|--------|------|--------|
| MES | trend | 11 | `run_mes_trend_rank11.py` |
| MGC | trend | 4 | `run_mgc_trend_rank4.py` |
| MCL | meanrev | 1 | `run_mcl_meanrev_rank1.py` |
| MNQ | trend | 1 | `run_mnq_trend_rank1.py` |

---

## Phase 3: Compare

Use `compare_verdicts.py` to diff the archived and refreshed verdicts:

```powershell
.venv\Scripts\python -m backtest.compare_verdicts `
    engine\data\gate_v2_verdicts\archive\MES_trend_rank11.json `
    engine\data\gate_v2_verdicts\MES_trend_rank11.json
```

The tool outputs:
- **Verdict transition** — PASS→PASS, PASS→FAIL, FAIL→PASS, core→alt, etc.
- **Champion param drift** — each param's % change vs the `PARAM_DRIFT_THRESHOLD` (default 10%)
- **Metric deltas** — pf_ci_lower, p_edge, dsr, mc_dd%, fixed_min_pf, wfo, cost
- **OOS sample delta** — more trades = more statistical confidence
- **DECISION line** — "NO SIGNIFICANT DRIFT — safe to commit" or "MANUAL REVIEW NEEDED"

Exit codes:
- `0` — no significant drift; safe to commit
- `1` — verdict transition or param drift; manual review
- `2` — file read/parse error

### --alert-on-rating-drop mode (CI use)

```powershell
.venv\Scripts\python -m backtest.compare_verdicts old.json new.json --alert-on-rating-drop
```

Exit 1 only on degradation (PASS→FAIL, core→alt, >15% pf_ci drop, >20% DSR drop, >50% mc_dd rise).
Improvements and neutral drift return exit 0.

### Threshold config

Thresholds can be tuned per-symbol in `engine/data/compare_verdicts_config.yaml`:

```yaml
default:
  param_drift_threshold: 0.10
  rating_drop_pf_ci: 0.15
  rating_drop_dsr: 0.20
  rating_drop_mc_dd: 0.50
# MES:
#   rating_drop_pf_ci: 0.20
```

---

## Phase 4: Commit

### Case A: Champion held (no significant drift)

The `compare_verdicts` DECISION line says "NO SIGNIFICANT DRIFT". Commit the new verdict.

```powershell
git add engine\data\gate_v2_verdicts\MES_trend_rank11.json
git commit -m "chore(verdicts): refresh MES trend rank11 (champion held, N more OOS trades)"
```

### Case B: Verdict improved (FAIL→PASS or PASS-alt→PASS-core)

Champion drifted but in the right direction. Commit and note the shift.

```powershell
git commit -m "chore(verdicts): MES rank11 improved PASS-alt → PASS-core on refresh"
```

### Case C: Verdict degraded (PASS→FAIL) or major param drift

Run the next-rank runner instead of committing the degraded verdict.

```powershell
# Roll forward: run rank12 instead of committing rank11 FAIL
.venv\Scripts\python backtest\run_mes_trend_rank12.py
# If rank12 passes, commit that and update DO_NOT_TRADE logic if needed
```

If the entire family fails (all remaining ranks FAIL), activate the kill switch for that symbol
and investigate regime change before resuming.

---

## Scoreboard

After committing any verdict, regenerate the scoreboard:

```powershell
.venv\Scripts\python backtest\scoreboard.py
```

This refreshes `engine/data/SCOREBOARD.md` with current PASS/FAIL counts and next-expiry dates.

---

## Key files

| File | Purpose |
|------|---------|
| `engine/data/gate_v2_verdicts/*.json` | Live verdicts (consulted by live_readiness.py) |
| `engine/data/gate_v2_verdicts/archive/` | Archived verdicts for diffing |
| `engine/data/SCOREBOARD.md` | Auto-generated portfolio scoreboard |
| `engine/data/compare_verdicts_config.yaml` | Per-symbol threshold overrides |
| `engine/backtest/compare_verdicts.py` | Diff tool |
| `engine/backtest/scoreboard.py` | Scoreboard generator |
| `engine/backtest/_gate_v2_helpers.py` | Gate v2 threshold constants + math |
| `engine/live_readiness.py` | Uses verdicts for go/no-go gate |

---

## Refresh schedule

| Symbol | Verdict expires | Next action |
|--------|----------------|-------------|
| MES rank11 | 2026-06-06 | Re-run `run_mes_trend_rank11.py` before that date |
| MGC rank4 | 2026-06-07 | Re-run `run_mgc_trend_rank4.py` before that date |

Use `python backtest/scoreboard.py --no-write` to see current expiry dates without writing.
