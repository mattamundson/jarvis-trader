# Verdict Lifecycle

> Source of truth for how gate v2 verdicts are created, refreshed, and retired.
> Companion documents: `GATE_V2_FRAMEWORK.md` (criteria math), `CACHE_FILENAME_CONTRACT.md` (data inputs).

---

## Lifecycle Sequence

```
Archive previous verdict
        │
        ▼
Run WFO (walk-forward optimization)
        │
        ▼
Compare new verdict vs archived
        │
   ┌────┴─────────────────────────────┐
   │ No significant drift             │ Significant softening or new FAIL
   ▼                                  ▼
Commit new verdict              Commit + add watch flag (or escalate to NO_TRADE)
```

### Step 1 — Archive Previous

Before any refresh, copy the current verdict file to the archive directory:

```
engine/data/gate_v2_verdicts/<SYMBOL>_<family>_rank<N>_pre-refresh-<YYYY-MM-DD>.json
```

Example:
```
engine/data/gate_v2_verdicts/MES_trend_rank11_pre-refresh-2026-05-07.json
engine/data/gate_v2_verdicts/MGC_trend_rank4_pre-refresh-2026-05-07.json
```

The archive file preserves the state at the moment the refresh was triggered. If the new verdict turns out to be a false regression, the archived file is the rollback target.

**Never delete archive files** — they are the audit trail for performance drift tracking.

### Step 2 — Run WFO

Walk-forward optimization re-evaluates the strategy using the most recent IBKR cache data. Runner invocation pattern (example for MES trend rank11):

```powershell
cd C:\Users\mattm\ThinkorSwim\jarvis-trader
.\engine\.venv\Scripts\python.exe -m engine.backtest.run_mes_trend_rank11
```

The runner:
1. Loads the latest cache via `_find_latest_cache(symbol, interval)` (see `CACHE_FILENAME_CONTRACT.md`)
2. Applies gate v2 checks (see `GATE_V2_FRAMEWORK.md`)
3. Writes a new verdict JSON to `engine/data/gate_v2_verdicts/<SYMBOL>_<family>_rank<N>.json`

WFO window config (typical values; check the specific runner for overrides):

| Parameter | Value |
|---|---|
| IS window | 6 months |
| OOS window | 1 month |
| Step size | 1 month |
| Total windows | ~18 for a 2-year dataset |

### Step 3 — Compare Verdicts

Read the new verdict JSON and the archived pre-refresh JSON side-by-side. Key metrics to compare:

| Metric | Stable (no action) | Minor drift (commit + note) | Significant (commit + watch or escalate) |
|---|---|---|---|
| `pf_ci_lower` | ≤ 5% change | 5-15% drop | > 15% drop OR falls below 1.10 |
| `p_edge` | ≤ 0.05 drop | 0.05-0.15 drop | > 0.15 drop OR falls below 0.95 |
| `mc_95th_dd` | ≤ 1% increase | 1-2% increase | > 2% increase OR exceeds 5% threshold |
| `dsr` | ≤ 0.05 drop | 0.05-0.15 drop | > 0.15 drop OR falls below 0.10 |
| `wfo_verdict` | Same tier | One tier down (e.g., STRONG→MODERATE) | Two tiers down or FAIL |
| `oos_trade_count` | ≤ 10% drop | 10-25% drop | > 25% drop OR drops to 0 |

WFO verdict tiers (strongest to weakest): `STRONG` > `MODERATE` > `WEAK` > `FAIL`.

### Step 4 — Commit Decision

| Verdict delta | Action |
|---|---|
| No significant drift | Commit new verdict JSON; update refresh_date field |
| Minor drift (one metric softening, within thresholds) | Commit new verdict JSON; add `"watch_flag": true` to JSON |
| Significant drift (any metric crosses threshold) | Commit + watch flag; add comment to strategy's runner noting the softening |
| Any PASS → FAIL transition | `DO_NOT_TRADE_SYMBOLS.add(<symbol>)` in the runner; commit; notify Amo |
| Any PASS → NO_TRADE (missing data / bad WFO) | Do NOT commit a corrupted verdict; investigate cache freshness first |

---

## Verdict File Format

Location: `engine/data/gate_v2_verdicts/<SYMBOL>_<family>_rank<N>.json`

```json
{
  "symbol": "MES",
  "family": "trend",
  "rank": 11,
  "verdict": "PASS",
  "routing": "ALT",
  "pf_ci_lower": 2.50,
  "p_edge": 0.98,
  "mc_95th_dd": 0.81,
  "dsr": 1.0,
  "fixed_params_min_pf": 1.351,
  "wfo_verdict": "STRONG",
  "oos_trade_count": 47,
  "refresh_date": "2026-05-07",
  "expires": "2026-06-06",
  "watch_flag": false,
  "params": {
    "fast_period": 60,
    "slow_period": 200,
    "atr_multiplier": 2.0
  }
}
```

Fields:
- `verdict`: `PASS` | `PASS-alt` | `FAIL` | `NO_TRADE`
- `routing`: `CORE` (mc_dd ≤ 5%) | `ALT` (mc_dd ≤ 7%, $50K+ accounts only)
- `expires`: `refresh_date + 30 days` — stale after this date → `NO_TRADE` fail-safe
- `watch_flag`: set to `true` when minor drift detected; triggers heightened monitoring

---

## Refresh Cadence

| Strategy | Last refresh | Next refresh due |
|---|---|---|
| MES trend rank11 | 2026-05-07 | ~2026-06-06 |
| MGC trend rank4 | 2026-05-07 | ~2026-06-07 |

**Trigger for early refresh** (before 30-day cadence):
- New IBKR cache data covering a regime change (e.g., major VIX spike, macro event)
- Engine reports `NO_TRADE` on a symbol with a previous PASS verdict
- `pnl_snapshots` data shows systematic deviation from backtest expectation (> 2 standard deviations over 10 trades)

---

## Failure Modes

| Mode | Symptom | Response |
|---|---|---|
| Stale verdict (> 30 days) | `expires` field in the past | Engine returns `NO_TRADE`; run refresh immediately |
| Missing verdict file | No JSON at expected path | Engine returns `NO_TRADE`; run WFO to create |
| Corrupted verdict (NaN in metrics) | `pf_ci_lower` is `null` or `NaN` | Do NOT commit; investigate inf-cap in `_gate_v2_helpers.py` (inf capped at 5.0 to prevent NaN in bootstrap CI) |
| WFO produces 0 OOS trades | `oos_trade_count: 0` | Family-level signal failure; park the strategy (see MCL family 2026-05-05 as reference) |
| Cache is stale | `_find_latest_cache()` returns `None` | Refresh IBKR cache via `export_ibkr_history.py`; do NOT run WFO on stale data |

---

## DO_NOT_TRADE_SYMBOLS Integration

The `DO_NOT_TRADE_SYMBOLS` frozenset in the engine is the **trading-layer enforcement** of verdict lifecycle decisions. Whenever a strategy transitions to FAIL or its verdict expires:

1. Add the symbol+family key to `DO_NOT_TRADE_SYMBOLS` in the relevant runner's config
2. Commit the change with the verdict JSON in the same commit
3. The engine will skip signal generation for that symbol automatically

Current `DO_NOT_TRADE_SYMBOLS` contents (as of 2026-05-07):
- `MCL` — gate v2 FAIL across all 5 hypotheses (A-E exhausted)
- `MNQ` — gate v2 FAIL (trend family 0 OOS trades; ORB family no edge)

---

## Reference Sessions

| Session | What was validated | Outcome |
|---|---|---|
| 2026-05-07 verdict-refresh | MES trend rank11 | pf_ci_lower 1.35→2.50; STRONG; committed |
| 2026-05-07 verdict-refresh | MGC trend rank4 | 19/19 OOS windows, 65 trades; STRONG; committed |
| 2026-05-06 | MGC rollover fix | _resolve_front_month expiry filter; MGCJ6 expired 2026-04-28 no longer returned |
| 2026-05-05 | MES ORB rank1 | FAIL (p_edge=0.18); ORB family parked |
| 2026-05-05 | MCL Hyp-E | 0 OOS trades on 1d bars; MCL definitively parked |

---

## Cross-references

- Gate v2 criteria and math → `docs/strategy/GATE_V2_FRAMEWORK.md`
- Cache filename contract → `docs/strategy/CACHE_FILENAME_CONTRACT.md`
- Strategy scoreboard → `engine/data/SCOREBOARD.md` (auto-generated)
- `_find_latest_cache` helper → `engine/backtest/_gate_v2_helpers.py`
- Refresh runner pattern → `engine/backtest/run_mes_trend_rank11.py` (reference implementation)
