# Phase 3 Live Trading Readiness Checklist

**Status**: Pre-deployment validation framework
**Last Updated**: 2026-05-20
**Owner**: Matt (Trader)

## Programmatic Check (run this first)

The 10 graduation criteria below are now codified as a programmatic GO/WAIT/NO-GO check.
Run it before reviewing the manual checklist:

```bash
# HTTP (requires engine running on port 8010):
curl -H "X-API-Key: <key>" http://127.0.0.1:8010/readiness/phase3

# Markdown report:
curl -H "X-API-Key: <key>" "http://127.0.0.1:8010/readiness/phase3?format=markdown"

# CLI (standalone, no engine required):
engine/.venv/Scripts/python scripts/phase3_readiness_report.py
# Exit 0=GO, 1=WAIT, 2=NO-GO
```

The 10 codified criteria with their thresholds:

| # | Criterion | Severity | Threshold |
|---|-----------|----------|-----------|
| C1 | `paper_trading_window` | BLOCKER | >= 60 calendar days of paper trading |
| C2 | `paper_trades_count` | BLOCKER | >= 100 completed closed trades |
| C3 | `win_rate` | BLOCKER | >= 55% win rate (last 60 days) |
| C4 | `profit_factor` | BLOCKER | >= 1.5 profit factor (last 60 days) |
| C5 | `max_drawdown` | BLOCKER | <= 8% max drawdown from peak (last 60 days) |
| C6 | `sortino_ratio` | BLOCKER | >= 1.0 annualised Sortino (last 60 days) |
| C7 | `consecutive_loss_streak` | WARNING | Max losing streak <= 5 (last 60 days) |
| C8 | `kill_switch_invocations` | BLOCKER | Kill switch triggered <= 2 times (last 60 days) |
| C9 | `engine_uptime_stability` | WARNING | Engine restarts < 1/day avg (last 30 days) |
| C10 | `safety_layer_test_coverage` | BLOCKER | test_safety_layer.py >= 95% line coverage |

**Note:** The programmatic check is necessary-but-not-sufficient. Matt must also
complete the manual checklist below (hardware kill switch, OCO orders, IB port 4001
unblocked, [safety-review] PR approved, capital commitment confirmed).

See `docs/runbooks/PHASE3_READINESS_CRITERIA.md` for full formula and rationale.

---

## Overview

Phase 3 transitions from paper validation to live capital deployment. This checklist ensures all safeguards are in place before enabling `LIVE_TRADING_ENABLED = True`.

**CRITICAL**: Live trading is permanently disabled in code until ALL gates pass.

---

## Graduation Gates

### 1. 30-Day Validation Period (Required)

All validated instruments must meet minimum performance thresholds over a continuous 30-day window:

| Metric | Target | Why |
|--------|--------|-----|
| Profit Factor | >= 2.0 | Win ratio sustainable long-term |
| Sharpe Ratio | >= 1.5 | Risk-adjusted returns acceptable |
| Win Rate | >= 55% | Better than coin flip with edges |
| Trade Count | >= 60 | Sufficient sample size |
| Days Active | >= 30 | Full monthly cycle |
| Max Drawdown | <= 15% | Stay within tolerance |

**Check**: `GET /paper/validation/status` — each instrument must show `is_validated: true`

**Current Status** (as of 2026-05-24 Tier-3 flip):
- MES: APPROVED (active paper; p_edge=0.75, ALT gate v2 PASS)
- MGC: APPROVED (active paper; p_edge=0.6842, ALT gate v2 PASS)
- MCL: HALTED (DO_NOT_TRADE; WFE=0.82, hypotheses A-E exhausted)
- MNQ: HALTED (DO_NOT_TRADE; WFE=0.57, fails gate v2)
- M2K: REJECTED (SMA/ORB/Donchian all FAIL)

---

### 2. Safety Layer Audit

Hardcoded kill switches and limits must be verified operational.

**Tests Required**:
- [ ] Daily P&L halt at -2% triggers correctly
- [ ] Drawdown halt at -10% from peak triggers correctly
- [ ] Kill switch activation/deactivation works (requires human auth)
- [ ] Order rate limiting (10/min) enforced
- [ ] Position size caps enforced (max 2 micro contracts, max 5% capital)

**Check**: `GET /safety/status` returns all circuit breakers green

---

### 3. Interactive Brokers Gateway Configuration

Paper trading validated on port **4002** (paper mode). Live trading (Phase 3+) will move to **4001**.

**Requirements**:
- [ ] Port 4001 permanently blocked in code during Phase 2
- [ ] IB Gateway paper account (4002) passes connectivity test
- [ ] Paper balance >= $10,000 USD
- [ ] All futures symbols (MCL, MNQ) have live market data feed
- [ ] Account approval for micro futures trading

**Check**: `GET /health/full` — IB Gateway subsystem returns healthy status

---

### 4. Schwab Connector Status

Charles Schwab integration is optional for Phase 3 but documented here.

**Status**: `SCHWAB_READY = False` (not activated)

**When deploying to Schwab in future**:
- [ ] OAuth2 credentials provisioned and tested
- [ ] Account approval for micro futures and options trading
- [ ] Backup broker to IB Gateway (failover logic)

---

### 5. Position Sizing Verification

Max position size calculated via ATR-based framework respects hardcoded caps.

**Hardcoded Limits** (non-negotiable):
- Max contracts per instrument: 2 (micro)
- Max overnight position: 1 contract
- Max single order value: $5,000
- Max position size: 5% of portfolio (=$500 on $10k)
- Max margin utilization: 40%

**Check**: `GET /safety/position-size?symbol=MCL&atr=10&account_value=10000`

Returns position recommendation respecting all limits.

---

### 6. Kill Switch Functional Test

Manual kill switch can be activated/deactivated by human operator only.

**Procedure**:
1. Start with `kill_switch_active: false` (GET /safety/status)
2. POST /safety/kill-switch/activate with reason
3. Verify `kill_switch_active: true` appears immediately
4. POST /safety/kill-switch/deactivate with `authorized_by: test`
5. Confirm reset to `false`

**Check**: `GET /safety/status` — `kill_switch_active` field toggles cleanly

---

### 7. Human Approval Workflow

`REQUIRE_HUMAN_APPROVAL = True` enforces manual trading gate at all times.

**Mechanism**:
- Every trade submitted by agents goes to RiskManagerAgent (Stage 4)
- RiskManagerAgent can veto any trade
- FundManagerAgent (Stage 5) provides final approval
- Pipeline does NOT submit to broker without human sign-off

**Check**: Review `engine/agents/pipeline.py` Stage 4 & 5 logic

---

## System Status Endpoint

Query all gates at once:

```bash
curl http://localhost:8010/system/phase3-readiness \
  -H "X-API-Key: your-api-key"
```

**Response**:
```json
{
  "validation_gates_met": true,
  "safety_tests_passing": true,
  "live_trading_disabled": true,
  "kill_switch_functional": true,
  "position_limits_verified": true,
  "ibkr_paper_validated": true,
  "overall_ready": false,
  "gates": {
    "validation_gates": {"passed": true, "details": {...}},
    "safety_tests": {"passed": true, "details": {...}},
    ...
  },
  "notes": "Validation gates OK. LIVE_TRADING_ENABLED still False. Ready when human approves."
}
```

---

## Deployment Process

### Prerequisites
- [ ] All graduation gates pass
- [ ] 30-day validation complete
- [ ] Checklist signed off by Matt
- [ ] Backup communication method tested

### Go-Live (Tier 3 only)

1. **Code Change**: Set `LIVE_TRADING_ENABLED = True` in `engine/config.py`
2. **Restart**: `./restart_engine.ps1`
3. **Verify**: Check `/system/phase3-readiness` returns `overall_ready: true`
4. **Monitor**: Watch dashboard and alert on kill switch

---

## Rollback

If critical failure:
1. Kill switch activates automatically at -2% daily or -10% drawdown
2. Manual fallback: POST /safety/kill-switch/activate
3. Code rollback: Set `LIVE_TRADING_ENABLED = False` and restart

---

## References

- `engine/config.py` — Risk parameters (source of truth)
- `engine/risk/safety_layer.py` — Kill switch & circuit breaker logic
- `engine/agents/pipeline.py` — 5-stage approval workflow
- `docs/runbooks/PAPER_TRADING.md` — Validation gate details
- `.claude/rules/safety.md` — Non-negotiable safety invariants
