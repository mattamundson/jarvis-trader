# Canonical API endpoints (no shadowing)

Use this list when wiring dashboards, scripts, or docs. If you add a second route for the same concern, FastAPI may register only the first — treat duplicates as bugs.

## Validation progress

| Canonical | Notes |
|-----------|--------|
| `GET /paper/validation/progress` | **Source of truth** for 30-day paper validation metrics (`paper_validation_router`). |
| `GET /validation/progress` | **Deprecated** — returns `301` to `/paper/validation/progress` ([`validation_router.py`](../../engine/routers/validation_router.py)). |

## RL / strategies

| Canonical | Notes |
|-----------|--------|
| `POST /strategies/rl/train` | Background PPO training ([`strategies_router.py`](../../engine/routers/strategies_router.py)). |
| `POST /strategies/rl/train-walkforward` | Walk-forward training. |

[`strategy_router.py`](../../engine/routers/strategy_router.py) (singular) is **not mounted** in [`main.py`](../../engine/main.py); it is deprecated scaffolding only. All RL HTTP entry points live on `strategies_router`.

## Greeks / options

| Canonical | Notes |
|-----------|--------|
| `engine/options/greeks_monitor.py` | **Real** `GreeksMonitor` and pricing helpers. |

There is **no** `engine/analytics/greeks_monitor.py` in the active tree; options code imports from `options/greeks_monitor` only.
