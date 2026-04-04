# JARVIS TRADER — Implementation Roadmap
**Version**: 1.0 | **Date**: 2026-04-03 | **Author**: Claude (Cowork Session)

> The north star: three validated instruments — MCL, MNQ, and MES — trading autonomously in paper mode,
> generating 30+ days of clean performance data that passes every gate, before a single live dollar moves.
> MES is not optional. It is the primary re-validation target of Phase 2.

---

## The MES Situation — Read This First

MES currently has WFE=0.09 ("DO NOT TRADE"). This number is not a punishment — it is a signal.
Walk-Forward Efficiency measures how well in-sample performance (PF 5.3 / Sharpe 4.2) translates
to out-of-sample windows. WFE=0.09 means ~91% of that performance is curve-fitting artifact.

**Trading MES at WFE=0.09 with live capital would likely produce losses, not the backtest returns.**

The roadmap below treats MES as a primary workstream — not sidelined, not ignored, but aggressively
attacked with the n-autoresearch experiment loop, RL training, and systematic parameter search until
it earns a WFE ≥ 0.40. That is the only honest path to MES in the portfolio.

**MES Target Gate for paper activation:**
- WFE ≥ 0.40 (minimum viable generalization)
- PF ≥ 2.0 out-of-sample
- Sharpe ≥ 1.5 out-of-sample
- WR ≥ 55%, Trades ≥ 60, Days ≥ 30
- DD ≤ 15% in worst walk-forward window

---

## Phase 0 — Unblock the System (Days 1–3)

**Goal**: Nothing works right now. Fix that before writing a single line of strategy code.

### 0.1 Top Up Anthropic Credits — P0 BLOCKER
Without credits, the 5-stage LLM pipeline returns 400 errors on every call. The entire intelligence
layer of JARVIS is dead.

**Action**: Go to console.anthropic.com → Billing → Add credits.
**Minimum**: $50 to sustain 30 days of paper trading + development (estimate 1,000–2,000 API calls/day).
**Plugin assist**: None. This is a human action.

### 0.2 Commit the ConsecutiveLossTracker P0 Fix
`engine/main.py` (+8 lines) and `engine/risk/safety_layer.py` (+12 lines, loss scaling tiers) are
sitting uncommitted. These are critical safety features.

**Commit order:**
```bash
cd C:\Users\mattm\ThinkorSwim\jarvis-trader
git add engine/main.py engine/risk/safety_layer.py
git commit -m "fix: ConsecutiveLossTracker wiring + loss scaling tiers (3→0.5x, 5→0.25x, 7→halt)"
```

**Plugin assist**: `/code-review` on safety_layer.py changes before committing. Run the safety-reviewer
subagent (`.claude/agents/safety-reviewer`) as required by project rules for any PR touching risk code.

### 0.3 Restart Claude Code
All newly installed plugins (feature-dev, code-review, security-guidance, codex-peer-review, ralph-loop)
are registered in settings.json but won't activate until Claude Code restarts. Do this after step 0.2.

### 0.4 Verify System Health
```bash
curl http://localhost:8010/health
curl http://localhost:8010/safety/status
# Confirm IB Gateway paper (4002) is connected
```

**Expected state at Phase 0 completion:**
- Pipeline responds to POST /pipeline/run with LLM output (not 400 errors)
- ConsecutiveLossTracker committed and tests passing
- All 8 plugins active in Claude Code

---

## Phase 1 — Foundation Hardening (Week 1)

**Goal**: Get the codebase into a clean, committable, tested state. Eliminate the 12 modified files
sitting in limbo. Install the intelligence tools (MCPs, context7).

### 1.1 Commit Triage — 12 Modified Files

These changes exist and need homes. Group by risk:

**Tier 1 — Safe to commit immediately:**
```
.claude/skills/jarvis-trader/SKILL.md       # skill updates
.claude/skills/jarvis-trader/playbooks/     # add-feature.md, debug.md
engine/scanner/signal_scanner.py            # +14 lines, signal scanning
engine/routers/paper_validation_router.py   # +6 lines
engine/agents/bull_researcher.py            # 1-line fix
```

**Tier 2 — Commit with /code-review first:**
```
CLAUDE.md                                   # major rewrite (-153 net)
engine/main.py                              # ConsecutiveLossTracker (Part of 0.2)
engine/risk/safety_layer.py                 # loss scaling tiers (Part of 0.2)
```

**Tier 3 — Commit after verification:**
```
data/paper_trades.json                      # +362 lines new paper trade data (CRLF warning)
engine/learning/data/session_memory.json    # RL Run 10 state
tradingview-mcp                             # submodule — investigate first
```

**Tier 4 — Stage new files:**
```
.claude/agents/                             # 4 subagent definitions
.claude/imports/                            # 4 import files
.claude/rules/backtest-signals.md           # new rules
.claude/rules/dashboard-typescript.md
.claude/rules/engine-python.md
CLAUDE.local.md
engine/notifications/openclaw_notifier.py
scripts/session-context.py
```

**Plugin assist**: `/code-review` on Tier 2 files. `bash scripts/hooks/check-secrets.sh` before push.

### 1.2 Install Intelligence Tools

**Install today (manual sparse-clone method — CLI blocked in nested sessions):**
```
context7         # Live FastAPI, ib_async, pandas-ta docs in context
pyright-lsp      # Python type checking — catch type errors before runtime
SQLite MCP       # Direct DB queries from Claude: uvx mcp-server-sqlite
                 # --db-path C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/data/jarvis_trader.db
```

**SQLite MCP config** (add to `~/.claude/mcp.json`):
```json
{
  "mcpServers": {
    "sqlite": {
      "command": "uvx",
      "args": ["mcp-server-sqlite", "--db-path",
               "C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/data/jarvis_trader.db"]
    }
  }
}
```

**Why SQLite MCP matters**: Query your paper trade history, signal stats, and RL experiment results
directly from Claude without writing Python scripts.

### 1.3 Unify Paper State (Disk JSON vs SQLite)

Two sources of truth for paper trades currently exist:
- `data/paper_trades.json` — the disk file (362 lines of trades)
- `engine/data/jarvis_trader.db` — the SQLite DB

These diverge. The migration script exists (`feat: US-1703`). Run it, verify, and disable the dual-write.

**Plugin assist**: `/codex-peer-review "Should we keep the disk JSON as a backup after SQLite
unification, or remove it? What are the failure mode implications?"`

### 1.4 IB Gateway E2E Paper Verification

The IB Gateway connection was established 2026-04-02 but a full order flow test is pending.

**Test sequence:**
1. `GET /broker/status` — confirm connection
2. `GET /broker/positions` — confirm empty/correct positions
3. Submit one paper MNQ order via `POST /broker/order` (1 contract, immediate cancel)
4. Confirm order appears in IB paper account, cancel confirms
5. Verify P&L tracking picks it up

**Safety check**: Port 4001 is permanently blocked. Paper port 4002 only.

---

## Phase 2 — MES Re-Validation Campaign (Weeks 2–4)

**Goal**: Get MES from WFE=0.09 to WFE≥0.40 through systematic parameter search, RL training,
and walk-forward testing. This is the critical path to a three-instrument portfolio.

### 2.1 Diagnose Why MES Overfits

Before throwing parameters at it, understand the failure mode.

**Hypothesis A — Timeframe mismatch**: MES 1h may have insufficient signal-to-noise. The STC
oscillator (OS=15, OB=83) may be tuned for instruments with higher ATR relative to tick size.

**Hypothesis B — Overfitted regime filter**: The 5-layer regime filter may have been optimized
against MES historical periods that won't repeat.

**Hypothesis C — Sample size**: MES 1h produces fewer qualifying setups than MCL, making the
backtest sensitive to a small number of winning trades.

**Diagnostic actions:**
```bash
# Run walk-forward analysis across multiple MES timeframes
cd engine && .venv/Scripts/python -m backtest.run_backtest --symbol MES --interval 1h --wfe-only
cd engine && .venv/Scripts/python -m backtest.run_backtest --symbol MES --interval 4h --wfe-only
cd engine && .venv/Scripts/python -m backtest.run_backtest --symbol MES --interval 1d --wfe-only
```

**Plugin assist**: `/codex-peer-review "MES 1h WFE=0.09. Run 10 experiments tried [list]. What
parameter axes haven't been explored? Suggest the most orthogonal search directions."`

### 2.2 n-autoresearch MES Experiment Loop

The experiment loop (`feat/experiment-loop` branch) is already built. Re-purpose it for MES
parameter search. This is the engine that got RL Run 10 off the ground.

**Target search space for MES:**

```python
MES_SEARCH_SPACE = {
    # STC parameters
    "stc_os": [10, 12, 15, 18, 20],          # Oversold threshold
    "stc_ob": [80, 83, 85, 88],              # Overbought threshold
    "stc_cycle_length": [10, 12, 15, 23],    # Cycle length

    # ATR stop multipliers (tighter for MES — smaller ATR)
    "atr_stop": [0.50, 0.60, 0.70, 0.85],
    "atr_target": [1.20, 1.50, 1.75, 2.00],

    # Regime filter sensitivity
    "vix_regime_lookback": [10, 20, 30],
    "regime_filter_mode": ["strict", "moderate", "relaxed"],

    # Timeframe
    "interval": ["1h", "4h"],
}
```

**Experiment runner command:**
```bash
cd engine && .venv/Scripts/python -m backtest.run_experiment \
  --symbol MES \
  --search-space engine/backtest/mes_search_space.json \
  --iterations 50 \
  --wfe-threshold 0.40 \
  --output engine/data/mes_experiment_log.json
```

**Plugin assist for overnight runs:**
```
/ralph-loop "Run MES parameter search. Use the n-autoresearch experiment loop at
engine/backtest/run_experiment.py. Search 50 parameter combinations from mes_search_space.json.
For each: compute WFE, PF, Sharpe, WR. When complete:
- engine/data/mes_experiment_log.json has 50 entries
- Top 5 parameter sets sorted by WFE are in mes_top_results.json
- At least one set achieves WFE ≥ 0.40 (if exists)
- No test regressions" --max-iterations 30
```

### 2.3 RL Agent for MES (Experimental)

RL Run 10 is trained on MES (the RL environment is MES-only, per the CLAUDE.md). The RL agent is
a separate, experimental approach that doesn't use the STC strategy — it learns patterns directly
from price action.

**Run WFE validation on RL Run 10:**
```bash
cd engine && .venv/Scripts/python -m strategies.rl_trainer --validate-wfe \
  --model-path engine/data/rl_models/run_10 \
  --symbol MES --interval 1h
```

**If RL Run 10 WFE ≥ 0.40**: The RL agent is a valid path to MES paper trading even if the STC
strategy doesn't pass. Consider running RL and STC in parallel for MES, comparing signals.

**If RL Run 10 WFE < 0.20**: Launch Run 11 with adjusted reward shaping.
```
/codex-peer-review "RL Run 10 reward: entry_cost=-0.01, hold_cost=-0.010, t1_bonus=0.50,
MAX_BARS_IN_TRADE=50. WFE came in at [X]. What reward signal changes would best address
premature exits and reduce overfitting to the training window? Suggest Run 11 config."
```

### 2.4 MES Paper Trading Gate

MES enters paper trading the moment ANY validated configuration passes the gate:

| Metric | Gate | Method |
|--------|------|--------|
| WFE | ≥ 0.40 | Walk-forward over ≥ 6 windows |
| PF | ≥ 2.0 | Out-of-sample windows only |
| Sharpe | ≥ 1.5 | Annualized |
| WR | ≥ 55% | Out-of-sample |
| Trades | ≥ 60 | Total across all windows |
| Max DD | ≤ 15% | Worst walk-forward window |

**Config promotion:** When a parameter set passes, update `engine/config.py` MES section and
set `MES_STATUS = "APPROVED"` with the winning parameters. Requires Tier 3 confirmation.

---

## Phase 3 — Three-Instrument Paper Validation (Weeks 4–8)

**Goal**: All three instruments live in paper mode simultaneously. 30 trading days. Clean metrics.
The system running without human babysitting.

### 3.1 Portfolio Configuration (Target State)

```python
ACTIVE_INSTRUMENTS = {
    "MCL": {"status": "APPROVED", "wfe": 0.82, "timeframe": "1h", "max_contracts": 2},
    "MNQ": {"status": "APPROVED", "wfe": 0.57, "timeframe": "1h", "max_contracts": 2},
    "MES": {"status": "APPROVED", "wfe": ">0.40", "timeframe": "TBD", "max_contracts": 2},
}

# Portfolio-level risk (three instruments)
MAX_TOTAL_MARGIN_UTILIZATION = 0.40   # $4,000 of $10,000 max in margin
MAX_CORRELATED_EXPOSURE = 0.30        # MNQ + MES are both equity-correlated
KILL_SWITCH_DAILY_LOSS = -0.02        # -$200/day — non-negotiable
```

**Correlation note**: MNQ and MES are both equity index futures. Running both simultaneously
creates correlated exposure. The multi-market orchestrator must account for this:

```
/feature-dev "Add position correlation monitoring to multi-market orchestrator.
MNQ and MES are correlated (r ≈ 0.95). When both have open positions, reduce max size
of each to 1 contract (from 2). MCL is uncorrelated — no change. Add correlation matrix
to GET /portfolio/risk endpoint."
```

### 3.2 Validation Dashboard

The 30-day paper validation needs a live scorecard. The validation page exists
(`app/validation/page.tsx` — 1,603 lines). Extend it for three instruments:

```
/feature-dev "Extend validation/page.tsx to show three-instrument scorecard.
Add MES row once status=APPROVED. Show WFE, PF, Sharpe, WR per instrument with
color-coded status (green ≥ gate, yellow close, red failing). Add portfolio-level
P&L chart combining all three."
```

**Plugin assist**: `frontend-design` auto-activates when editing TSX files. Will suggest
layout improvements for the three-instrument view.

### 3.3 Learning System Closure

The learning loop is built but disconnected (per previous session analysis). Connect it:

```
/feature-dev "Wire the learning system to the trading pipeline. Currently:
- learning/events.py records trade events (working)
- learning/feedback.py generates lessons (built but disconnected)
- learning/patterns.py identifies patterns (built but disconnected)
- learning/recommendations.py feeds back to pipeline (disconnected)
Step 4 is missing: recommendations must be injected into Stage 1 (TechnicalAnalyst context)
before each analysis call. Implement the injection point."
```

### 3.4 Nightly Monitoring

Set up automated monitoring so the system can run overnight without manual checks:

```bash
# Engine health check every 15 minutes
# Kill switch status every 5 minutes
# Alert if daily P&L approaches -1.5% (pre-halt warning)
```

**Plugin assist**: `/schedule "Check engine health at http://localhost:8010/health every 15 minutes.
If response is not 200 or safety/status shows kill_switch_active=true, log to
data/system_alerts.json with timestamp."` — Use the schedule skill to set this up.

---

## Phase 4 — Live Trading Readiness (Month 3+)

**Prerequisites — ALL must be true before Phase 4 begins:**

- [ ] 30 trading days paper completed on MCL + MNQ
- [ ] 30 trading days paper completed on MES (after WFE gate passed)
- [ ] All three instruments: PF ≥ 2.0, Sharpe ≥ 1.5, WR ≥ 55%
- [ ] Zero kill switch events in final 10 trading days
- [ ] `/code-review` run on engine/risk/safety_layer.py + engine/execution/ib_gateway.py
- [ ] `trailofbits/skills` security audit completed on safety_layer + middleware
- [ ] Dashboard fully functional (build passes, all 16/16 routes)
- [ ] Dashboard tests exist (Playwright E2E coverage)
- [ ] Schwab connector verified (separate from IB Gateway)

### 4.1 Capital Allocation (Live)

Starting with paper capital discipline: $10,000 paper → $10,000 live.

```
MCL:  2 contracts max, ~$500/contract margin  = $1,000 max exposure
MNQ:  2 contracts max, ~$1,700/contract margin = $3,400 max exposure
MES:  2 contracts max, ~$1,500/contract margin = $3,000 max exposure
Reserve: ~$2,600 buffer
Total margin utilization: ≈ 74% ceiling (within 40% rule per instrument but watch total)
```

Adjust MES/MNQ sizing — one each when both have positions (correlated exposure rule).

### 4.2 Live Activation Sequence (Tier 3 Actions)

Every step below requires explicit confirmation:

1. `engine/config.py` — set `LIVE_TRADING_ENABLED = True` (Tier 3)
2. `engine/config.py` — set `SCHWAB_READY = True` OR confirm IB Gateway live port 4001 (Tier 3)
3. Remove port 4001 block in code — requires safety-reviewer subagent sign-off
4. First live trade: MCL only, 1 contract, with human watching

---

## Plugin Utilization Map

Every phase has a plugin strategy:

| Phase | Plugin | Use |
|-------|--------|-----|
| 0 | `/code-review` | Review safety_layer.py before committing P0 fix |
| 1 | `security-guidance` | Auto-fires on every file edit during commit triage |
| 1 | `/codex-peer-review` | SQLite unification decision |
| 2 | `/ralph-loop` | Overnight MES parameter search (50 iterations) |
| 2 | `/codex-peer-review` | RL reward shaping for Run 11 |
| 2 | `/feature-dev` | Correlation monitoring feature in orchestrator |
| 3 | `/feature-dev` | Three-instrument validation dashboard |
| 3 | `/batch` | Type annotation sweep, docstring coverage |
| 3 | `/ralph-loop` | Decompose engine/main.py (4,269 → <500 lines) |
| 4 | `/code-review` | Pre-live safety audit |
| All | `frontend-design` | Every TSX edit — auto-activates |
| All | `security-guidance` | Every file edit — auto-activates |

---

## Weekly Cadence

```
Monday    — /batch: one codebase-wide improvement (types, docs, tests)
Tuesday   — /code-review: engine/risk/ + engine/execution/ review
Wednesday — MES experiment results review; /ralph-loop new overnight task
Thursday  — Review ralph-loop output + /simplify cleanup
Friday    — /codex-peer-review: architectural decision for next week
```

---

## Critical Path to MES in the Portfolio

The single most important sequence:

```
1. Top up Anthropic credits           (Day 1)
2. Commit P0 fix                      (Day 1)
3. Run MES diagnostic backtests       (Day 2)
4. Launch n-autoresearch experiment   (Day 3)
5. /ralph-loop overnight search x3    (Days 3-6)
6. Validate RL Run 10 WFE             (Day 4)
7. Promote passing config to config.py (When gate clears)
8. MES paper trading starts           (Week 2-4, depends on WFE)
9. 30-day MES paper validation        (Weeks 4-8)
10. MES live with MCL + MNQ           (Month 3+)
```

MES is not excluded from this roadmap. It is the primary research target of Phase 2.
The gate exists to protect your $10,000. Pass the gate and MES is in.

---

## Success Metrics

| Milestone | Target | Measurement |
|-----------|--------|-------------|
| P0 unblocked | Pipeline responds in < 30s | `POST /pipeline/run` latency |
| MES WFE ≥ 0.40 | Before Week 4 | `run_backtest --wfe-only` |
| Three instruments live | Week 4-8 | All three in `ACTIVE_INSTRUMENTS` |
| 30-day paper complete | Month 2 | Validation gate metrics |
| Zero kill switches | Final 10 days | `GET /safety/events` |
| Live trading authorized | Month 3 | Tier 3 confirmation + all gates |
