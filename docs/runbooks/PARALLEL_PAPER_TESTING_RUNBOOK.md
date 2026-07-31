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

## Per-account kill switch

Migration 028 adds a `per_account_kill_state` table that lets Account A and
Account B halt **independently** during parallel paper testing.

### Dual-layer architecture

```
                   ┌────────────────────────────────┐
                   │  GLOBAL kill switch             │
                   │  (system_state table)           │
                   │  Fires on: -6% daily / -20% DD  │
                   │  Halts: ALL order emission      │
                   └────────────────────────────────┘
                            │ defense in depth
                   ┌────────┴──────────┐
            ┌──────┴──────┐    ┌───────┴─────┐
            │  Account A  │    │  Account B  │
            │  per-acct   │    │  per-acct   │
            │  kill state │    │  kill state │
            └─────────────┘    └─────────────┘
           fires on A's own   fires on B's own
           thresholds only    thresholds only
```

The GLOBAL kill switch is **canonical** and unchanged.  Per-account state is
**additive**: either account can be halted independently, but the global switch
always overrides both.

### How it activates

Per-account halt is triggered from the engine's internal risk checks only —
there is no external trigger HTTP route (by design — kill switches must not
be triggerable by external callers).  The engine calls:

```python
safety_layer.trigger_per_account_kill(
    account_id="B",
    metric="max_daily_loss",   # or "max_drawdown" | "consecutive_loss"
    value=-112.50,
    reason="Account B daily realized loss -$112.50 exceeded threshold",
)
```

This sets `active=1` for Account B only.  Account A continues to emit.

### Monitoring

```powershell
# Check Account A kill state
Invoke-RestMethod http://127.0.0.1:8010/safety/account/A/kill-state `
    -Headers @{'X-API-Key'='<API_KEY>'}

# Check Account B kill state
Invoke-RestMethod http://127.0.0.1:8010/safety/account/B/kill-state `
    -Headers @{'X-API-Key'='<API_KEY>'}
```

Response shape:
```json
{
  "account_id": "B",
  "active": true,
  "triggered_at": "2026-05-21T14:22:01",
  "reason": "Account B daily realized loss -$112.50 exceeded threshold",
  "trigger_metric": "max_daily_loss",
  "trigger_value": -112.5,
  "cleared_at": null
}
```

### Recovery procedure

1. **Identify the trigger**: read `trigger_metric` and `trigger_value` from
   the state endpoint to understand why the account halted.
2. **Clear the halt** (human-only):
   ```powershell
   Invoke-RestMethod http://127.0.0.1:8010/safety/account/B/kill-state/clear `
       -Method POST `
       -Headers @{'X-API-Key'='<API_KEY>'} `
       -Body '{}' -ContentType application/json
   ```
3. **Verify**: re-poll the state endpoint — `active` must be `false` and
   `cleared_at` must be populated.
4. **Do NOT restart the engine** to clear a per-account halt — the per-account
   state persists across restarts and the engine will re-read it on startup.

### Guarantee

> The GLOBAL kill switch is canonical.  If the global switch fires, BOTH
> accounts halt regardless of their individual per-account state.  Clearing
> a per-account halt does NOT affect the global kill switch.  To resume trading
> after a global halt, use `POST /safety/kill-switch/deactivate` (separate endpoint).

### Schema (migration_028)

```sql
CREATE TABLE IF NOT EXISTS per_account_kill_state (
    account_id      TEXT    PRIMARY KEY,
    active          INTEGER NOT NULL DEFAULT 0,
    triggered_at    TEXT,
    reason          TEXT,
    trigger_metric  TEXT,    -- "max_daily_loss" | "max_drawdown" | "consecutive_loss"
    trigger_value   REAL,
    cleared_at      TEXT
);
```

Default state: no rows.  A missing row for an account_id is equivalent to
`active=0` (inactive) — the engine treats absence as not halted.

## Safety invariants

- Only paper accounts.  `LIVE_TRADING_ENABLED=False` is not overridable by
  the challenger config — it is hard-blocked in `config_challenger.py`.
- `IBKR_PORT` cannot be overridden — both accounts share the same paper
  broker connection.
- Kill switch (`-6% daily / -20% drawdown`) remains at production thresholds
  for the engine-level safety layer.  Account B's `MAX_DAILY_LOSS_PCT` is a
  per-account risk parameter for the per-account kill check, not a global
  kill-switch override.
- Per-account kill state is default-inactive (migration_028 adds the table;
  rows only appear when an account halts).
- There is no external HTTP route to TRIGGER a per-account halt — only the
  engine's internal risk checks call `trigger_per_account_kill()`.
- Per-account state is only consulted when `ENABLE_PARALLEL_PAPER=1`.  When
  the flag is off, all per-account functions are no-ops.
- [RISK] Positions are per-account in the `paper_trades` table (account_id
  column).  The two accounts share the same paper IB connection but their
  P&L snapshots and kill states are fully independent.  There is no shared
  position state between A and B — each account's trades are separately tagged
  via `account_id` and aggregated independently.

## Cross-references

- [[QUANTSTATS_TEARSHEET_RUNBOOK]] — full QuantStats metrics reference
- [[STARK_MODE_OPERATING_PHILOSOPHY]] — when to promote a challenger to production
- `engine/config_challenger.py` — whitelist enforcement source
- `engine/parallel_paper.py` — dual-emit logic
- `engine/database/migrations.py` migration 027 — schema changes
