# Parallel Paper Testing Runbook

## What it is

Multi-account paper testing runs the same engine, the same signals, and the same
data feed against TWO paper accounts simultaneously:

| Account | Config | Purpose |
|---------|--------|---------|
| A | Production `engine/.env` | Control — current live-paper config |
| B | `engine/config-challenger.yaml` overrides | Challenger — hypothesis under test |

Both accounts receive identical trade signals.  The only difference is the
risk parameters (position size, max contracts, loss halts).  After 90+ days the
tearsheet diff reveals whether the challenger's tighter or looser risk envelope
produces better risk-adjusted returns, or whether the difference is noise.

## Why this exists

Config optimisation is a survivorship-bias trap.  Backtesting a risk parameter
produces an in-sample optimum; forward-testing the same config on live paper
data against a control account reveals whether the parameter actually matters.

## Default: OFF

`ENABLE_PARALLEL_PAPER=0` in `engine/.env.example`.  Account B rows are never
written unless you explicitly enable the flag.  All existing functionality is
unchanged.

## Activation

1. **Create the challenger config:**
   ```
   copy engine\config-challenger.yaml.example engine\config-challenger.yaml
   ```
   Edit `engine/config-challenger.yaml` — set only the parameters you want
   to test.  Allowed keys and valid ranges are enforced at startup:

   | Key | Type | Range |
   |-----|------|-------|
   | `MAX_POSITION_SIZE_PCT` | float | 0.01 – 0.10 |
   | `MAX_CONTRACTS_PER_INSTRUMENT` | int | 1 – 5 |
   | `MAX_DAILY_LOSS_PCT` | float | 0.01 – 0.05 |
   | `MAX_DRAWDOWN_PCT` | float | 0.05 – 0.20 |
   | `CONSECUTIVE_LOSS_HALT` | int | 3 – 10 |

2. **Enable the flag:**
   In `engine/.env`:
   ```
   ENABLE_PARALLEL_PAPER=1
   ```

3. **Apply the schema migration:**
   The next engine restart automatically runs migration 027 which adds
   `account_id` columns to `paper_trades` and `pnl_snapshots`.  No manual
   SQL needed.

4. **Restart the engine:**
   ```powershell
   .\restart_engine.ps1
   ```
   Startup log should include:
   ```
   Challenger config loaded from engine/config-challenger.yaml: ['MAX_POSITION_SIZE_PCT', ...]
   Migration 027 applied — account_id columns added to paper_trades and pnl_snapshots.
   ```

## Validation

After activation, verify dual-emit is working:

```powershell
Invoke-RestMethod http://127.0.0.1:8010/portfolio/paper/account/A/stats?days=7 -Headers @{'X-API-Key'='<API_KEY>'}
Invoke-RestMethod http://127.0.0.1:8010/portfolio/paper/account/B/stats?days=7 -Headers @{'X-API-Key'='<API_KEY>'}
```

Account B `n_trades` should increment alongside Account A after the first
signal fires.

## Dashboard

Navigate to `/parallel-paper` in the dashboard.  Two-column layout shows:
- Equity curves (inline SVG sparklines)
- Sortino, Sharpe, Calmar, Max DD, Win rate
- Side-by-side tearsheet diff with delta column

Window selector: 30d / 90d / 180d.

## Statistical guidance — when to trust the result

| Window | Status | Notes |
|--------|--------|-------|
| < 30 days | Noise | P&L differences are not meaningful |
| 30 days | Marginal | Enough to detect catastrophic divergence only |
| 90 days | Recommended minimum | Covers multiple market regimes |
| 180 days | Confident | Statistically distinguishable with ~100+ trades per config |

**30 days is barely above the noise floor.**  Do not conclude one config is
better than the other based on a single month of paper trading.  Momentum
regimes, choppy regimes, and event-driven days all need representation.

The correct decision rule is:

1. Wait 90 days minimum.
2. Account B Sortino > Account A Sortino (or whichever metric you care about).
3. The difference exceeds 0.20 Sortino units (practical significance, not just
   statistical).
4. Promote the challenger: copy its overrides into `engine/.env` and retire
   `config-challenger.yaml`.

## Disabling parallel testing

```
# engine/.env
ENABLE_PARALLEL_PAPER=0
```

Restart the engine.  Account A trades continue as normal.  Account B rows
remain in the DB for post-hoc analysis but no new B rows are written.

## Safety invariants

- Only paper accounts.  `LIVE_TRADING_ENABLED=False` is not overridable by
  the challenger config — it is hard-blocked in `config_challenger.py`.
- `IBKR_PORT` cannot be overridden — both accounts share the same paper
  broker connection.
- Kill switch (`-2% daily / -10% drawdown`) remains at production thresholds
  for the engine-level safety layer.  Account B's `MAX_DAILY_LOSS_PCT` is a
  per-account risk parameter, not a kill-switch override.
- [RISK] If both accounts hit the daily loss halt simultaneously, the safety
  layer's `kill_switch_active` fires on Account A (production) thresholds and
  halts ALL order emission — including Account B.  Account B's tighter halt
  threshold is advisory only (enforced in analytics, not in the safety layer).
  The recovery flow resets the engine-level state; Account B resumes alongside
  Account A.  Future work: per-account kill switch state in `system_state` table.

## Cross-references

- [[QUANTSTATS_TEARSHEET_RUNBOOK]] — full QuantStats metrics reference
- [[STARK_MODE_OPERATING_PHILOSOPHY]] — when to promote a challenger to production
- `engine/config_challenger.py` — whitelist enforcement source
- `engine/parallel_paper.py` — dual-emit logic
- `engine/database/migrations.py` migration 027 — schema changes
