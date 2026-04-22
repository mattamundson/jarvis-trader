# Scheduler and watchlist scan

## What runs

- **APScheduler** job `watchlist_scan` (`engine/main.py` lifespan): weekdays **9:00–15:00 Chicago**, minutes **0 and 30**.
- **Symbols**: first **two** `FUTURES_WATCHLIST` entries as futures, first **three** `OPTIONS_WATCHLIST` as non-futures.
- **Behavior**: calls `TradingPipeline.analyze_and_decide` per symbol, logs decisions via `_log_decision`, sends WhatsApp when action ≠ `hold` (subject to cooldown), and **does not** open paper trades or call IB automatically.

## Manual trigger

- `POST /scheduler/scan-now` — same loop as the job; returns per-symbol results JSON. Also writes `pipeline_runs` rows with `source=manual_scan`.

## Persistence

- Each successful (or failed) scheduler iteration inserts a row into **`pipeline_runs`** via `insert_pipeline_run` with `source=scheduler` (see `approval/pipeline_history.py`). Use this for audit and dashboard history without treating scans as executions.

## Related

- `POST /pipeline/run` — on-demand single-symbol run; may create **pending trade approvals** when `requires_human` is true, and may open paper trades when allowed.
- `GET /watchlist/scan` — **MTF STC** summary only (not the full LLM pipeline).
