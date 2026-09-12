> [!CAUTION]
> **Legacy evidence only.** These criteria may describe historical paper
> diagnostics but cannot authorize live trading or satisfy JARVIS-MIP-1.0
> M10/M11. The legacy CLI is retired and always exits nonzero.

# Phase 3 Readiness Criteria — Detail

**Status**: Authoritative (supersedes the vibes-based checklist)
**Last Updated**: 2026-05-20
**Owner**: Matt (Trader)

This document defines the 10 programmatic Phase 3 criteria, explains the formula
and rationale for each threshold, and distinguishes what is checked
programmatically from what still requires human judgment.

---

## Running the Check

```bash
# HTTP endpoint (engine must be running on 8010):
curl -H "X-API-Key: <key>" http://127.0.0.1:8010/readiness/phase3
curl -H "X-API-Key: <key>" "http://127.0.0.1:8010/readiness/phase3?format=markdown"

# Standalone CLI:
engine/.venv/Scripts/python scripts/phase3_readiness_report.py
engine/.venv/Scripts/python scripts/phase3_readiness_report.py --db engine/data/jarvis_trader.db --json

# Exit codes: 0=GO, 1=WAIT, 2=NO-GO (usable in CI)
```

---

## How to Interpret GO / WAIT / NO-GO

| Verdict | Meaning |
|---------|---------|
| **GO** | All BLOCKER criteria pass AND at most 1 WARNING fails |
| **WAIT** | All BLOCKER criteria pass but more than 1 WARNING fails |
| **NO-GO** | Any BLOCKER criterion fails |

Even a **GO** verdict does not authorise live trading. Matt must also complete
the human-review checklist at the bottom of this document.

---

## The 10 Criteria

### C1 — `paper_trading_window` (BLOCKER)

**Formula:** `age_days(MIN(paper_trades.exit_time WHERE status='closed')) >= 60`

**Threshold:** 60 calendar days.

**Rationale:** Futures strategies that look good in the first month frequently
degrade in month 2 due to regime changes (FOMC cycles, seasonal patterns,
roll-cost dynamics). 60 days captures two distinct 30-day windows and spans
at least one full options expiration cycle. The 30-day threshold in the old
PHASE3_READINESS.md was insufficient — it excluded early-month vs end-month
liquidity divergence.

**Data source:** `paper_trades.exit_time` (SQLite).

---

### C2 — `paper_trades_count` (BLOCKER)

**Formula:** `COUNT(*) WHERE status='closed' >= 100`

**Threshold:** 100 completed trades.

**Rationale:** Standard quantitative finance requirement for minimum sample
size. Fewer than 100 trades cannot reliably distinguish a 55% edge from a
50% edge at 95% confidence. At 2-3 trades/day, 100 trades requires 33-50
trading days, which naturally enforces C1 as well.

**Data source:** `paper_trades` table (SQLite).

---

### C3 — `win_rate` (BLOCKER)

**Formula:** `wins / total WHERE exit_time >= NOW()-60d >= 0.55`

**Threshold:** 55% over the last 60 calendar days.

**Rationale:** 55% is the minimum directional edge required for the strategy
to produce a profit factor > 1.0 after a realistic 1:1 risk/reward ratio. At
MES 1-tick stops, the effective R:R is closer to 1:1.5, meaning 55% becomes
the floor for break-even live performance after slippage. This matches the
threshold in the old PHASE3_READINESS.md.

**Data source:** `paper_trades.pnl, exit_time` (SQLite).

---

### C4 — `profit_factor` (BLOCKER)

**Formula:** `SUM(pnl WHERE pnl>0) / SUM(ABS(pnl) WHERE pnl<0) >= 1.5`

**Threshold:** 1.5 over the last 60 calendar days.

**Rationale:** PF 1.5 is the industry-standard minimum for a strategy worth
trading live. PF 2.0 (old runbook threshold) was set for backtest performance;
live performance degrades by 20-40% due to slippage, partial fills, and
data-feed latency. A PF of 1.5 in paper provides headroom for that degradation
while still remaining positive-expectancy. Gate v2 uses PF 1.5 via `pf_ci_lower`.

**Data source:** `paper_trades.pnl, exit_time` (SQLite).

---

### C5 — `max_drawdown` (BLOCKER)

**Formula:** `MAX((realized_peak_equity - portfolio_equity) / realized_peak_equity) <= 0.08`

**Threshold:** 8% from realized equity peak, over the last 60 days.

**Rationale:** The hardcoded kill switch fires at 10% drawdown. The 8%
readiness threshold provides a 20% safety buffer — if paper trading is
approaching the kill-switch level, the engine is not ready for live capital.
The 15% threshold in the old PHASE3_READINESS.md was higher than the
kill-switch itself, which was logically inconsistent (you could be "ready"
while already past your own stop-out point).

**Phantom drawdown fix (2026-05-21, migration_029):**
The original formula used `peak_equity`, which includes unrealized MTM
from open positions. On 2026-05-11, an open short that was deeply in-profit
set `peak_equity = 24_617`; when the market recovered intraday the equity
"dropped" 40.2% on paper while every closed trade was profitable (+$60,617
realized). C5 reported NO-GO due to this phantom drawdown.

Fix: added `realized_peak_equity` column to `pnl_snapshots` (migration_029).
C5 now uses `realized_peak_equity` (running max of closed-trade-only equity).
This column is NOT the same as `peak_equity`.

**Kill switch vs C5 — intentional difference:**
- **Kill switch** (`safety_layer.py`) uses `peak_equity` (MTM).  This is correct:
  an open position with a large unrealized gain that then reverses IS a real
  intraday exposure risk.  If the engine gets caught long at the high and the
  market crashes, the MTM drawdown matters before trades can be closed.  The
  kill switch must act on MTM equity.
- **C5 readiness** uses `realized_peak_equity` (closed trades only).  This
  measures strategy quality over 60 calendar days; intraday MTM fluctuations
  that fully reverse before close are noise for strategy evaluation.
- The two peaks are independent.  If Matt manually clears the kill switch,
  only `peak_equity` gets reset; `realized_peak_equity` is monotonically
  non-decreasing and does NOT reset.

**Data source:** `pnl_snapshots.portfolio_equity, realized_peak_equity, date` (SQLite).

Fallback: if `realized_peak_equity` is NULL for all rows (pre-migration_029
database), C5 falls back to MTM `peak_equity` and logs a warning in the
evidence string.  Run `engine/.venv/Scripts/python -c "from database.migrations
import run_migrations; import sqlite3; run_migrations(sqlite3.connect('data/jarvis_trader.db'))"` to apply migration_029 and eliminate the fallback.

---

### C6 — `sortino_ratio` (BLOCKER)

**Formula:** `(mean_daily_return / downside_std) * sqrt(252) >= 1.0`

where `downside_std` = `sqrt(mean(returns^2) FOR returns < 0)` (population
denominator, not just negative days, per standard Sortino definition).

**Threshold:** 1.0 annualised.

**Rationale:** Sortino penalises only downside volatility, making it more
appropriate than Sharpe for futures strategies that are explicitly trying to
cut losses short while letting winners run. Sortino 1.0 annualised is
approximately equivalent to Sharpe 0.7-0.8 for typical futures return
distributions. The old runbook cited Sharpe 1.5 as a target — that threshold
is reasonable for backtests but not achievable in 60 days of paper data with
typical noise levels.

**Data source:** `pnl_snapshots.daily_pnl, portfolio_equity` (SQLite).
Requires >= 10 rows; fewer rows return FAIL.

---

### C7 — `consecutive_loss_streak` (WARNING)

**Formula:** `MAX(consecutive_losing_trades WHERE exit_time >= NOW()-60d) <= 5`

**Threshold:** <= 5 in the last 60 days.

**Severity:** WARNING (not BLOCKER) — a streak of 6 is serious but not
necessarily fatal if it occurred during a known regime anomaly. Matt reviews.

**Rationale:** The existing `loss_tracker` module halts at N consecutive losses
(configurable, currently 3). A pre-flight readiness check at 5 catches patterns
that the in-session tracker might miss (e.g., spread across trading days with
the tracker resetting). Five is one more than the standard "tilt threshold" of 4
recognised in behavioral trading research.

**Data source:** `paper_trades.pnl, exit_time` (SQLite).

---

### C8 — `kill_switch_invocations` (BLOCKER)

**Formula:** `COUNT(kill_switch_activations WHERE timestamp >= NOW()-60d) <= 2`

**Threshold:** At most 2 activations in the last 60 days.

**Rationale:** Each kill switch activation represents a hard-limit breach
(-2% daily or -10% drawdown). Zero activations is ideal. One activation with
a documented post-mortem is acceptable. Two activations suggests a systemic
issue that must be investigated before live capital. Three or more is a
disqualifying red flag.

**Data source:** Engine logs (`KILL SWITCH ACTIVATED` lines) with timestamp
parsing, falling back to `system_state` table (current state only).

---

### C9 — `engine_uptime_stability` (WARNING)

**Formula:** `restarts_in_last_30d / 30 < 1.0`

**Threshold:** Average less than 1 restart per day over the last 30 days.

**Severity:** WARNING (not BLOCKER) — restarts are sometimes planned
(e.g., after a code update). Matt reviews the reason.

**Rationale:** A crashing engine is more dangerous in live mode than in paper
mode because live orders may be partially filled when the engine restarts.
At most 1 restart/day average is equivalent to roughly weekly planned restarts
with no unplanned crashes.

**Data source:** `engine/data/pm2_restart_history.json`, falling back to
`engine/data/pm2_restart_count_72h.json` (extrapolated), then benefit-of-doubt
pass if no file exists.

---

### C10 — `safety_layer_test_coverage` (BLOCKER)

**Formula:** `line_coverage(tests/test_safety_layer.py vs risk/safety_layer.py) >= 95%`

**Threshold:** 95% line coverage measured via `pytest --cov=risk.safety_layer`.

**Rationale:** The safety layer is the only hard-line defense against runaway
orders. Every branch that is untested is a potential live-trading exploit.
95% is achievable with current test count (existing suite passes at ~94%);
the delta is ~30 lines that need explicit branch coverage. 100% would be ideal
but creates fragility against internal refactors.

**Data source:** `coverage.py` output, parsed from pytest-cov report.

---

## What Is NOT in the Programmatic Check

The following items still require human judgment and cannot be automated:

- **Hardware kill switch wired:** Physical emergency stop that cuts IB Gateway
  connection independent of the engine process. Required before any live session.

- **Account-level OCO orders configured:** Protective orders at the broker level
  (not just engine-level) ensure protection if the engine process dies mid-trade.

- **Live IB Gateway port (4001) unblocked:** Currently permanently blocked at
  the network level (`LIVE_TRADING_ENABLED = False` and port 4001 firewalled).
  The network-level block must be manually lifted, which requires physical access
  to the router/firewall configuration. This is a deliberate out-of-band control.

- **Phase 3 PR with `[safety-review]` tag approved:** Any commit that sets
  `LIVE_TRADING_ENABLED = True` must have a `[safety-review]` tag and must be
  reviewed and approved before merge. The programmatic check cannot substitute
  for code review.

- **Capital commitment confirmed and documented:** The exact dollar amount, the
  account to trade from, and the per-instrument allocation must be documented in
  the session log before the live flip. This is a business decision, not a
  technical one.

---

## Cross-References

- `docs/runbooks/PHASE3_READINESS.md` — original manual checklist (updated)
- `docs/runbooks/PHASE3_LIVE_TRANSITION.md` — transition runbook (updated)
- `engine/readiness/phase3_criteria.py` — programmatic criterion implementations
- `engine/routers/readiness_router.py` — HTTP endpoint
- `scripts/phase3_readiness_report.py` — CLI tool
- `engine/tests/test_phase3_readiness.py` — test suite
- `docs/STARK_MODE_OPERATING_PHILOSOPHY.md` — broader risk philosophy
- `engine/risk/safety_layer.py` — the safety layer these criteria protect
