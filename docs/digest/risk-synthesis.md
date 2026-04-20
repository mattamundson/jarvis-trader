# Risk Module — Research Digest Synthesis

**Date**: 2026-04-16
**Source bucket**: `C:\Users\mattm\discord-export\digest-raw\by-module\risk.json`
**Items classified**: 3 (all X.com posts, 0 GitHub repos)
**Counts**: Novel = 0 | Noise = 3 | Dedup = 0 | GitHub READMEs read = 0

---

## TL;DR

The classifier tagged 3 X posts as "risk," but **none contain an actual risk management technique, formula, sizing rule, stop-loss method, or drawdown metric**. All three are misrouted noise. Two are off-topic entirely (OpenClaw tooling, SMB acquisition life-hack). The third (`baynkr`) is a snarky meta-comment that *mentions* Sharpe ratios and curve-fitting as cautionary framing, but proposes no method.

**No recommendations. No code changes. Existing risk stack is unchanged.**

---

## Existing Risk Stack (reference, unchanged)

- `engine/risk/safety_layer.py` — `SafetyLayer` guards `submit_paper_order`, gated by `LIVE_TRADING_ENABLED`
- `engine/agents/trader.py:290-293` — PositionSizer: **0.5x–1.5x integer-clamped to max_contracts=2** (confirmed 2026-04-10 audit)
- `engine/agents/trader.py:367-398` — VIX-based position sizing
- `engine/risk/pnl_monitor.py` — kill switch + daily PnL monitor (persists across restarts)
- `engine/backtest/monte_carlo.py` — 18 simulation types (risk-of-ruin, GARCH VaR/CVaR, Kelly, Levy jump, crisis stress)
- Capital envelope: $10K total, $5K per instrument (MCL + MNQ)

---

## Novel Techniques Ranked

**None.** Zero of 3 items cleared the bar ("README contains an actual technique, not just 'we support risk management'"). No GitHub repos in this bucket, so no READMEs to read.

---

## Noise (3/3 items — all rejected)

### 1. `benjaminbadejo` (2026-04-13) — OpenClaw plugin recommendation
> "I highly recommend turning on both QMD and the new 'Active-Memory' plugin in OpenClaw..."

**Verdict**: NOT risk-related. Misrouted — belongs in agent-tooling bucket if anywhere. No sizing rule, no stop method, no drawdown metric. OpenClaw is already deeply integrated (see MEMORY.md: 23 ready skills, WhatsApp approvals, cron suite). Classifier false-positive, likely triggered on the word "memory" or "plugin" collocating with past risk content.

**Receipt**: `risk.json` item 1, status_id `2043076618093003122`

### 2. `benkellyone` (2026-04-14) — SMB acquisition advice
> "If I wanted to quit my job & replace my salary in 2026... Go to SMBmarket and filter for businesses making $10k+/month in cash flow."

**Verdict**: Entirely off-topic. Small-business acquisition life-hack. Zero relevance to futures/options position sizing, stops, drawdown, or portfolio risk. Classifier false-positive — probably matched on "cash flow" + dollar amounts.

**Receipt**: `risk.json` item 2, status_id `2043678410308763850`

### 3. `baynkr` (2026-04-16) — Agent-harness skepticism
> "People want to believe in the agent harness fantasy... the whole thing runs itself and of naturally posts a 2.5+ Sharpe. Rest assured this is always curve fit noise."

**Verdict**: Closest to on-topic (mentions Sharpe, curve-fit) but **proposes no technique**. It is a cautionary take on multi-agent trading stacks — directly applicable as a warning against over-trusting the SDK pipeline's backtest metrics (e.g., MES PF=5.27 / Sharpe=4.16 / WFE=0.09 which MEMORY.md already flags as `OVERFIT`). Reinforces existing discipline rather than introducing new method.

**Actionable takeaway (not novel)**: The MES WFE=0.09 bypass is exactly the curve-fit trap `baynkr` warns about. Existing paper-approved list (MCL WFE=0.82, MNQ WFE=0.57) already reflects this discipline. No change needed; the sentiment is already encoded in the WFE gate.

**Receipt**: `risk.json` item 3, status_id `2044826817412956172`

---

## Receipts

- **Source JSON**: `C:\Users\mattm\discord-export\digest-raw\by-module\risk.json` (3 items, all `kind: "x"`, 0 `readme_path` fields)
- **Cross-referenced**: `engine/risk/safety_layer.py`, `engine/agents/trader.py:290-293` (sizer bounds), `engine/agents/trader.py:367-398` (VIX sizing) — all unchanged
- **Prior audit confirming existing stack**: MEMORY.md 2026-04-10 "Sprint Gap Closure" section, manifest correction #1 (the 0.5x–1.5x sizer bounds)
- **Classifier error rate in this bucket**: 3/3 = 100% noise. Recommend tightening the risk-module classifier prompt to require at least one of: `{position sizing, stop loss, drawdown, Sharpe, Sortino, Kelly, VaR, CVaR, risk parity, volatility targeting, kill switch, circuit breaker, max loss, trailing stop}` in the source text, not just topic-adjacent keywords.

---

## Final Answer

**Counts**: 3 items in, 0 novel techniques out, 3/3 noise.
**Output path**: `C:\Users\mattm\ThinkorSwim\jarvis-trader\docs\digest\risk-synthesis.md`
**Code changes**: None (as constrained).
