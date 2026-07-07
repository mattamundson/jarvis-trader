# Gate v2 — Strategy Promotion Framework

**Status:** ACTIVE (`GATE_V2_ENFORCE_ROUTING=1` in `engine/.env` since 2026-04-21)
**Activation decision:** `docs/decisions/gate_v2_phase3_full.md`

---

## Overview

Gate v2 is the statistical validation system that decides whether a strategy is allowed to route signals to the paper-trading approval queue. A strategy must hold a valid (non-stale) PASS verdict in `engine/data/gate_v2_verdicts/` for any of its signal outputs to leave `NO_TRADE`.

**Default-deny:** a missing or stale verdict → all signals rewritten to `NO_TRADE`. The gate never fails open.

---

## Architecture — Module Map

| Module | Path | Role |
|--------|------|------|
| Runner scripts | `engine/backtest/run_<sym>_<family>_rank<n>.py` | Compute metrics, produce verdict JSON |
| Shared helpers | `engine/backtest/_gate_v2_helpers.py` | `_find_latest_cache()`, CI bootstrap, DSR, MC |
| Verdict lifecycle | `engine/backtest/verdict_lifecycle.py` | archive → write → diff → journal (one call: `commit_verdict()`) |
| Compare verdicts | `engine/backtest/compare_verdicts.py` | Drift detection between old and new verdict; `ThresholdConfig` YAML |
| Policy / routing gate | `engine/backtest/gate_v2_policy.py` | `is_strategy_authorized()`, `is_ungate_eligible()`, `VerdictSnapshot` |
| Journal | `engine/backtest/track_verdict_journal.py` | Append-only `_journal.csv` in the verdicts dir |
| Paper config | `engine/backtest/paper_config.py` | `PAPER_CONFIGS` dict: per-symbol `enabled` flag |
| Threshold config | `engine/data/compare_verdicts_config.yaml` | Per-symbol drift thresholds for the compare step |

---

## Dual-Pathway Verdict System

Each verdict is scored on two independent pathways. The overall verdict is PASS if **either** passes.

### Core Pathway (4 criteria, all must pass)

| Metric | Key | Threshold | Meaning |
|--------|-----|-----------|---------|
| MBB profit-factor lower bound | `pf_ci_lower` | ≥ 1.10 | CI lower bound on PF across MBB bootstrap iterations |
| Positive-edge probability | `p_edge` | ≥ 0.95 | Fraction of MBB bootstrap runs with PF > 1 |
| Max 95th-percentile MC drawdown | `mc_95th_dd_pct` | ≤ 5% | Worst-case equity drawdown across 500 Monte Carlo runs |
| Deflated Sharpe Ratio | `dsr` | ≥ 0.10 | Sharpe after correction for multiple-testing selection bias |

### Alt Pathway (5 criteria, all must pass)

The alt pathway allows promotion when one or two core criteria are borderline, as long as the strategy demonstrates cross-validation robustness.

| Metric | Key | Threshold | Meaning |
|--------|-----|-----------|---------|
| DSR (alt floor) | `dsr` | ≥ 0.30 | Tighter DSR floor on the alt path |
| Rolling WFO consistency | `rolling_wfo` | MODERATE or STRONG | Stability of OOS performance across rolling windows |
| Fixed-param min PF | `fixed_params_min_pf` | ≥ 1.20 | Minimum PF across a fixed parameter grid (not just champion) |
| Cost survivability | `cost_survives_through` | ≥ "realistic" | Strategy remains profitable under realistic to catastrophic cost scenarios |
| MC drawdown (alt ceiling) | `mc_95th_dd_pct` | ≤ 4.0% | Tighter drawdown ceiling on the alt path |

### `passed_via` field

| Value | Meaning |
|-------|---------|
| `"core"` | All 4 core criteria passed |
| `"alt"` | Core failed ≥1 criterion; all 5 alt criteria passed |
| `null` | FAIL (both pathways failed) |

---

## Verdict File Format

Files live at `engine/data/gate_v2_verdicts/{SYMBOL}_{family}_rank{n}.json`.

```json
{
  "symbol": "MES",
  "family": "trend",
  "rank": 11,
  "verdict": "PASS",
  "passed_via": "alt",
  "core_verdict": "FAIL",
  "alt_verdict": "PASS",
  "n_core_passed": 3,
  "n_alt_passed": 5,
  "created_at": "2026-05-22T09:01:22.925323+00:00",
  "aux_freshness": {
    "rolling_wfo": "2026-05-22T09:01:22.925323+00:00",
    "fixed_params": "2026-05-22T09:01:22.925323+00:00",
    "cost_sweep": "2026-05-22T09:01:22.925323+00:00"
  },
  "gate_v2": {
    "verdict": "PASS",
    "passed_via": "alt",
    "core_reasons": ["...", "..."],
    "alt_reasons": ["...", "..."],
    ...
  },
  "champion_params": { "fast": 50, "slow": 200, "atr_trail_mult": 2.0 },
  "gate_v2_metrics": {
    "pf_ci_lower": 2.50,
    "p_edge": 0.75,
    "dsr": 1.0,
    "mc_95th_dd_pct": 0.81,
    "fixed_params_min_pf": 1.52,
    "wfo_consistency": "STRONG",
    "cost_survives_through": "catastrophic"
  },
  "wfo_config": { "total_oos_trades": 61 },
  "lineage": { ... },
  "wfo_windows": [ ... ]
}
```

**Staleness:** any verdict with `created_at` older than 14 days is treated as missing by `gate_v2_policy`. The 14-day window tolerates one missed weekly Saturday cron before signals halt.

---

## Verdict Lifecycle (`verdict_lifecycle.py`)

Runners call one function instead of managing each step manually:

```python
from backtest.verdict_lifecycle import commit_verdict

summary = commit_verdict(
    verdict_doc=gate_output,   # dict from the runner
    symbol="MES",
    family="trend",
    rank=11,
    verdicts_dir=engine_root / "data" / "gate_v2_verdicts",
)
if summary["needs_review"]:
    print("[WARN] Drift detected — review before deploying to paper trading")
```

Internally `commit_verdict()` performs four steps atomically:

1. **Archive** — moves the existing JSON to `archive/` with an ISO-8601 timestamp suffix
2. **Write** — serialises the new verdict as pretty-printed JSON (sanitises `inf` → `null`)
3. **Compare** — diffs old vs. new via `compare_verdicts.compare()` using per-symbol YAML thresholds
4. **Journal** — appends or replaces the row in `_journal.csv`

Return keys: `archived_path`, `verdict_path`, `diff`, `needs_review`, `journal_rows`.

---

## Drift Detection (`compare_verdicts.py`)

`compare_verdicts.compare(old, new, cfg)` produces a diff dict flagging:

- **verdict_transition** — e.g. `"PASS -> FAIL"` or `"PASS-alt -> PASS-core"`
- **champion_drift** — per-param `{old, new, pct_change, exceeds_threshold}` entries
- **metric_deltas** — numeric or string changes to each gate metric
- **oos_delta** — change in total OOS trade count
- **warnings** — symbol/family mismatch alerts
- **needs_review** — bool; True if any transition, threshold breach, or mismatch

### Threshold Config

`engine/data/compare_verdicts_config.yaml` controls drift sensitivity:

```yaml
default:
  param_drift_threshold: 0.10   # 10% parameter change triggers review
  rating_drop_pf_ci: 0.15
  rating_drop_dsr: 0.20
  rating_drop_mc_dd: 0.50

# Per-symbol overrides
MES:
  param_drift_threshold: 0.10
# MGC:
#   param_drift_threshold: 0.15
```

`verdict_lifecycle.compare_verdicts()` loads this config automatically — no manual config plumbing needed in runners.

---

## Routing Gate (`gate_v2_policy.py`)

### `is_strategy_authorized(symbol) -> tuple[bool, str]`

Single source of truth for paper-order authorization. Three sequential checks:

1. **Not in `VALIDATION_ONLY_INSTRUMENTS`** — pipeline-level phase/WFE block
2. **`paper_config.enabled=True`** — records that gate v2 approval was granted
3. **Non-stale gate v2 PASS verdict on disk** — `is_ungate_eligible()` returns True

```python
authorized, reason = is_strategy_authorized("MES")
# True, "authorized"
# OR
# False, "MES has no valid non-stale gate v2 PASS verdict (verdicts expire after 14 days)"
```

### Other public API

| Function | Returns | Use |
|----------|---------|-----|
| `get_last_verdict(symbol)` | `VerdictSnapshot \| None` | Newest non-stale verdict for a symbol |
| `is_ungate_eligible(symbol)` | `bool` | True iff any family has a fresh PASS |
| `list_verdicts()` | `list[VerdictSnapshot]` | All non-stale snapshots, newest first |

### `VerdictSnapshot` schema validation

`VerdictSnapshot.from_dict(doc)` raises `ValueError` (naming the offending field) on any invalid enum value or missing required key. `_iter_verdict_files()` catches and logs these — corrupt files are silently skipped rather than producing wrong routing decisions.

---

## Halt Level Integration (`safety_layer.py`)

Gate v2 verdict state flows into the tiered halt model:

| HaltLevel | Condition |
|-----------|-----------|
| `NORMAL` | No halts active |
| `SOFT_HALT` | Loss tracker multiplier < 1.0 (position size reduced) |
| `HARD_HALT` | Kill switch active — all new orders rejected |
| `EMERGENCY_FLATTEN` | Hard halt + `emergency_flatten_and_halt()` called — positions being liquidated |

`SafetyLayer.current_halt_level` synthesises these into one tier. `emergency_flatten_and_halt()` atomically activates the kill switch and liquidates all open positions.

---

## Running a Verdict Refresh

### Single runner (e.g. MES trend rank 11)

```bash
cd engine
.venv/Scripts/python backtest/run_mes_trend_rank11.py
```

The runner:
1. Loads the latest cache CSV from `data/`
2. Runs rolling WFO, fixed-params grid, cost sweep, Monte Carlo
3. Calls `commit_verdict()` — archives old, writes new, diffs, updates journal
4. Prints `[lifecycle] MES_trend_rank11.json -> written (archived: ...) | diff=OK | journal+1`

### Weekly cron (Saturday 01:00 CT)

Installed via APScheduler in the engine. Runs all active runners in sequence.

To trigger manually:
```bash
curl -X POST http://127.0.0.1:8010/gate-v2/refresh-all \
  -H "X-API-Key: <key>"
```

### Checking verdict freshness

```bash
curl http://127.0.0.1:8010/gate-v2/status
# Returns per-symbol verdict age, pass/fail, champion params
```

Or via Python:
```python
from backtest.gate_v2_policy import list_verdicts
for v in list_verdicts():
    print(f"{v.symbol} {v.family} rank{v.rank}: {v.verdict} via {v.passed_via} (age {v.age_days():.1f}d)")
```

---

## Adding a New Symbol to Gate v2

1. **Create a runner** — copy the closest existing runner, update symbol/params/cache path
2. **Add to `PAPER_CONFIGS`** in `engine/backtest/paper_config.py` with `enabled=False` initially
3. **Run the runner** — produces a verdict JSON in `data/gate_v2_verdicts/`
4. **If PASS:** flip `enabled=True` in `PAPER_CONFIGS`, remove from `VALIDATION_ONLY_INSTRUMENTS`
5. **Add a per-symbol threshold override** in `data/compare_verdicts_config.yaml` if needed
6. **Tag all commits** `[safety-review]` per `rules/commits.md` (changes touch `engine/backtest/`)

---

## Interpreting Verdicts

| Verdict | `passed_via` | Meaning | Action |
|---------|-------------|---------|--------|
| PASS | core | All 4 core criteria met — strong unconditional edge | Route normally |
| PASS | alt | Core failed one criterion; 5 alt criteria all met — edge with caveats | Route; note which core criterion failed |
| FAIL | null | Both pathways failed | Block routing; do not promote |
| (missing) | — | No verdict file, or verdict > 14 days old | Block routing (fail-safe default-deny) |

A `PASS-alt` result where the failing core criterion is `p_edge < 0.95` is the most common pattern — it means the bootstrap says edge probability is below 95% but the rolling WFO and fixed-param grid both confirm robustness across parameter space.

---

## Key Constants (do not modify without `[safety-review]` commit)

| Constant | Value | Location |
|----------|-------|----------|
| `MAX_VERDICT_AGE_DAYS` | 14 | `gate_v2_policy.py:36` |
| `GATE_V2_ENFORCE_ROUTING` | 1 (env var) | `engine/.env` |
| Core PF CI lower threshold | 1.10 | runner scripts |
| Core p_edge threshold | 0.95 | runner scripts |
| Core MC 95th DD threshold | 5.0% | runner scripts |
| Core DSR threshold | 0.10 | runner scripts |
| Alt DSR floor | 0.30 | runner scripts |
| Alt fixed-params min PF | 1.20 | runner scripts |
| Alt MC DD ceiling | 4.0% | runner scripts |

---

## Cross-References

- `docs/decisions/gate_v2_phase3_full.md` — activation decision memo (2026-04-21)
- `engine/backtest/gate_v2_policy.py` — policy implementation
- `engine/backtest/verdict_lifecycle.py` — lifecycle pipeline
- `engine/backtest/compare_verdicts.py` — drift detection + YAML config
- `engine/data/compare_verdicts_config.yaml` — per-symbol thresholds
- `engine/data/gate_v2_verdicts/` — live verdict files
- `engine/data/gate_v2_verdicts/_journal.csv` — append-only history
- `.claude/rules/safety.md` — safety invariants (gate thresholds listed)
- `ml-pitfalls-defense.md` — statistical context (DSR, permutation tests)
