# engine/data/ — Data Store Layout

Auto-managed data directory for JARVIS TRADER. Do not manually edit JSON verdict files.

## Subdirectories

| Directory | Contents | Owner |
|-----------|----------|-------|
| `gate_v2_verdicts/` | Per-strategy gate v2 verdict JSONs | WFO runners (`run_*.py`) |
| `gate_v2_verdicts/archive/` | Pre-refresh verdict snapshots | Verdict refresh workflow |
| `live_readiness_reports/` | Daily live-readiness gate outputs (YYYY-MM-DD.md) | `live_readiness.py` cron |
| `post_trade_reports/` | Daily post-trade PnL summaries | `daily_post_trade_report.py` |

## Key Files

| File | Description |
|------|-------------|
| `SCOREBOARD.md` | Auto-generated strategy portfolio table; run `engine/backtest/scoreboard.py` to refresh |
| `gate_v2_verdicts/MES_trend_rank11.json` | MES SMA(60,200) trend verdict — PASS (alt), active paper trading |
| `gate_v2_verdicts/MGC_trend_rank4.json` | MGC SMA(50,120) trend verdict — PASS (alt), active paper trading |

## Gate v2 Verdict Schema

Each `gate_v2_verdicts/*.json` file follows this shape:

```json
{
  "symbol": "MES",
  "family": "trend",
  "rank": 11,
  "verdict": "PASS",
  "passed_via": "alt",
  "created_at": "<ISO 8601 UTC timestamp>",
  "gate_v2_metrics": {
    "pf_ci_lower": ...,
    "p_edge": ...,
    "mc_95th_dd_pct": ...,
    "dsr": ...,
    "wfo_consistency": "STRONG | MODERATE | WEAK",
    "fixed_params_min_pf": ...,
    "cost_survives_through": "optimistic | realistic | pessimistic | catastrophic"
  }
}
```

See `docs/strategy/GATE_V2_FRAMEWORK.md` for threshold definitions and math.

## Scoreboard Refresh

```powershell
.\engine\.venv\Scripts\python.exe -m engine.backtest.scoreboard
```

Writes `engine/data/SCOREBOARD.md`. Run after any verdict refresh or new strategy run.
