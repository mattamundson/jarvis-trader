# JARVIS TRADER — Weekly Commander's Brief
**Week of:** 2026-04-20 → 2026-04-26 (Sunday review)
**Generated:** 2026-04-26 (automated Sunday review task)
**Source:** EOD reports Apr 20–24, premarket briefs, scan files, handoffs, engine logs
**Note:** Engine unreachable from review sandbox (paper mode, Windows host). All data sourced from log files and EOD reports. API data not available for live pull.

---

## WEEK IN REVIEW (Apr 20–26)

**Net P&L for the week:** $0.00 realized (no profitable trades closed this week)
- 4 trades were closed Thursday Apr 23 (trades #138–141), all at entry price = $0.00 P&L each
- This is a confirmed **exit price recording bug** — EOD closer is booking exits at entry price, not market price
- Cumulative realized P&L since inception: $150–$180 (discrepancy between analytics endpoints — see SYSTEM HEALTH)

**Win rate (week):** 0% (0/4 trades — all zero P&L)
**Profit Factor (week):** Not calculable (denominator = 0)
**Sharpe (week):** 0.00
**Total signals generated (week):** ~30 pipeline runs (all HOLD)
**Trades taken:** 4 (all zero P&L)
**Trades skipped (HOLD):** ~30 signals, all forced to HOLD — split between ATR unavailability and Anthropic API failure
**Best trade:** None — all $0
**Worst trade:** None — all $0

**Week narrative in plain terms:**

Monday and Tuesday ran cleanly on the infrastructure side but generated zero real trades — MCL's ATR data was unavailable, preventing stop/target calculation and forcing HOLD even when the debate said BEAR_WINS. The big positive this week was the Tier A statistical hardening: bootstrap CI, Deflated Sharpe Ratio, and canonical contract specs all shipped with 50+ tests. Gate v2 dual-pathway evaluator was completed and is now a Tier 3 decision document.

Wednesday surfaced three hard blockers to live deployment via the `deployment-verification-agent` — none were on the radar before: (1) no broker-side STP orders anywhere in the codebase, (2) position-size gate rejects a 1-contract MES order due to notional vs initial capital misconfiguration, (3) scanner has been disabled since April 10. Also caught 558 pm2 restarts (crash loop, not yet root-caused).

Thursday was a full pipeline blackout: Anthropic API returned 401 Unauthorized, Ollama fallback was also down, IBKR disconnected, and Polygon unavailable simultaneously. The system operated on stale data and generated zero actionable signals. The EOD position closer ran and booked 4 trades at $0 — confirming the exit price bug is structural, not intermittent.

Friday's pipeline ran on the same broken state (API still 401, market data still zero). The MCL rounded base pattern at $95.30 (trigger $97.74) and MNQ at ADX=53 very strong trend are technically compelling setups being completely missed. Gate v2 is now enforcing NO_TRADE routing on both instruments (MCL meanrev fails CI threshold, MNQ fails both strategy families).

---

## PAPER VALIDATION SCORECARD

**Validation window:** 2026-04-02 → 2026-05-02 (30 days)
**Days elapsed:** ~24 calendar days / 6 active trading days counted

| Gate | Required | Current | Status | Notes |
|---|---|---|---|---|
| Days Active | ≥ 30 | 6 of 24 elapsed | 🔴 FAILING | Only 6 days with trade activity |
| Total Trades | ≥ 60 | 24 | 🔴 FAILING — 36 short | Need 36 more in 6 remaining days |
| Win Rate | ≥ 55% | 8.33% (2/24) | 🔴 FAILING | Far below gate |
| Profit Factor | ≥ 2.0 | 9999 (artifact) | 🟡 UNRELIABLE | 1 real winner; denominator=0 |
| Sharpe Ratio | ≥ 1.5 | 10.39 (artifact) | 🟡 UNRELIABLE | Same — statistically meaningless |
| Max Drawdown | ≤ 15% | 0.00% (per EOD) | 🟢 PASSING | But drawdown reporting inconsistency flagged |

**Estimated gate pass date:** Not achievable by May 2 at current pace.
- To hit 60 trades in 6 remaining calendar days: need 6 trades/day. Current average: ~1.5/day.
- Win rate is structurally broken while API is down — zero real decisions being made.
- The 30-day clock expires May 2. A reset/extension of the paper window is likely necessary.

**Phase 3 Readiness:** ❌ NOT READY — multiple structural blockers, not just statistical ones.

---

## INSTRUMENT BREAKDOWN

### MCL (Micro WTI Crude Oil) — Paper Active, WFE 0.82

| Metric | Value |
|---|---|
| Trades (all-time paper) | 16 |
| Wins | 1 (6.25% win rate) |
| Net P&L | $100.00 |
| Avg winner | $100.00 |
| Avg loser | $0.00 (exit price bug) |
| Best trade | +$100 (2026-04-03, MCL LONG 33s hold) |
| Gate v2 status | FAIL — meanrev rank 1 `mbb_pf_ci_lower=0.9983` (below 1.10) |

**This week's MCL activity:** 0 trades executed. Rounded base pattern forming at $95.30, neckline trigger $97.74. ATR was unavailable Mon–Tue forcing HOLDs; API failure Thu–Fri preventing any analysis. MCL spiked +3.6% Friday on Strait of Hormuz/Iran news to ~$92.88 — a significant move entirely missed.

**Regime context:** MCL has been in TRENDING regime (ADX 35–53 range). When ATR returns, breakout/momentum is the priority strategy family — but gate v2 is currently blocking MCL mean-reversion, and there's no trend family registered for MCL in the gate.

### MNQ (Micro Nasdaq-100) — Paper Active, WFE 0.57

| Metric | Value |
|---|---|
| Trades (paper validation DB) | 0 registered |
| Wins | 0 |
| Net P&L | $0.00 |
| Gate v2 status | FAIL — breakout `mbb_pf_ci_lower=1.0696` (below 1.10); trend alt path UNSCORED |

**This week's MNQ activity:** 0 trades. Pipeline ran but all HOLD (API failure). ADX=53 very strong trend regime at $27,243 — extended bullish. Intel earnings beat drove +19% surge in underlying this week. MNQ validation shows 0 trades despite instrument being active — MNQ trade writes to validation DB need verification.

**Note:** MNQ trend family's alternate gate path is UNSCORED because `fixed_params` and `cost_sweep` inputs are missing. Fresh gate run needed before this family can qualify via alt path.

### MES — DO NOT TRADE (WFE 0.09, paper-authorized only)

Not in active pipeline per rules. Scanner disabled since April 10. 7 paper trades logged historically, all $0 P&L. Deployment blockers confirmed by verification agent.

---

## SYSTEM HEALTH

### Errors from engine_error.log (this week)

**🔴 P0 — Anthropic API 401 Unauthorized (Thursday Apr 23 onward)**
The Trader LLM and all dependent agents (debate scoring, IC synthesis, social synthesis, news analysis) are returning 401 Unauthorized from `api.anthropic.com`. Every pipeline cycle since Thursday has defaulted to HOLD.
- Affected: all pipeline stages that call LLM
- Impact: zero real trading decisions since approximately Apr 23 14:00 UTC
- Fix: update `ANTHROPIC_API_KEY` in `engine/.env`, restart with `.\restart_engine.ps1`

**🔴 P0 — Market Data Blackout (Thursday–Friday)**
IBKR disconnected + Polygon unavailable simultaneously. All symbols showing `current_price=0.0`. CSV cache stale by 23+ days.
- Likely cause: IBKR Gateway connection drop, possibly related to crash loop
- Fix: reconnect IB Gateway (paper port 4002), verify Polygon API key quota

**🔴 P0 — Exit Price Recording Bug**
Trades #138–141 (Apr 23) all closed at entry price. EOD position closer is not marking to market before close. `PortfolioTracker.get_trades_by_date()` method is also missing (causes `EOD_SUMMARY` task to 500).
- Impact: all performance metrics are artifacts; real P&L cannot be assessed
- Fix: fix exit price logic in EOD closer; implement `get_trades_by_date` method

**🟡 P1 — Health Endpoint TypeError (recurring all week)**
`engine/main.py:582`: `bool(getattr(data_manager.ibkr, "is_connected", False))` — `is_connected` is already a bool literal, not callable.
- Non-blocking for trading but breaks monitoring automation
- Fix: `getattr(data_manager.ibkr, 'is_connected', False)` directly (remove `bool()` call)

**🟡 P1 — pm2 Restart Loop (Wednesday Apr 22)**
Engine showed 558 total restarts on April 22, increasing by 61 during a 2-hour monitoring window. Not yet root-caused.
- Risk: mid-trade restart with no broker-side STP = naked position (paper phase only risk, but must be fixed before live)
- Fix: `pm2 logs jarvis-engine --lines 2000 --nostream | grep -Ei "(error|disconnect|kill|traceback)"` — check for crash pattern

**🟡 P1 — Drawdown Reporting Inconsistency (three different values)**
Three separate reporting surfaces give three different drawdown numbers:
- `config.py`: MAX_DRAWDOWN_PCT = 0.10 (authoritative: -10%)
- `/safety/circuit-breakers` API: `drawdown_limit_pct = -0.20` (-20%)
- Scan report Apr 24: "Drawdown from Peak: 12.46%" vs EOD Apr 24: "Drawdown: 0.00%"
- This requires `[safety-review]` tagged audit to reconcile. If real drawdown is 12.46% and hard limit is -10%, system is already past the kill switch boundary.

**🟡 P1 — Scanner Disabled Since Apr 10**
`WATCHLIST_SCAN_ENABLED=false` in `engine/.env`. Root-cause fixes for the contamination incident confirmed committed (`be6927d` + `94c4793`, 42 regression tests green). Re-enable is waiting on explicit operator authorization.
- Impact: trade count accumulation is near-zero without the scanner

**LLM costs (week):** Not available (engine offline for review). Estimated minimal — API failed Wednesday night, so LLM was consumed only Monday/Tuesday/Wednesday morning.

**Kill switch events:** None triggered. System nominal on that front.

---

## STRATEGY ALIGNMENT

**Signal parameters vs. backtest:** Cannot assess meaningfully — ATR unavailability Mon–Tue and API failure Thu–Fri means no real pipeline signals were generated this week. Gate v2 is now overriding routing for both instruments.

**Gate v2 status:**
- MCL: FAIL (meanrev rank 1, mbb_pf_ci_lower=0.9983 < 1.10, DSR=0.0)
- MNQ: FAIL both families (breakout mbb_pf_ci_lower=1.0696 < 1.10; trend alt path unscored)
- Both instruments forced to NO_TRADE by router when `GATE_V2_ENFORCE_ROUTING=1`

**Regimes this week:**
- MCL: TRENDING (ADX 35–53) — breakout/momentum strategies preferred
- MNQ: TRENDING (ADX 53) — very strong trend; breakout setup active
- Neither instrument had a validated strategy to deploy in this regime

**MES conditional failure (confirmed this week):** 43% of live MES signals in strong-ADX regime lose money. Validates the WFE=0.09 suspension.

**Walk-forward concerns:** Gate v2 is currently the most relevant fitness test. Both instruments failing gate v2 is the primary strategic signal — not a calibration problem but a sample-size and validation-methodology problem. The Tier A bootstrap analysis shows the failures are likely sample-size artifacts (n=24–36 trades → wide CI), not actual edge absence. The gate v2 dual-pathway evaluator is the right framework to resolve this, but it requires a Tier 3 decision to adopt revised thresholds.

**Three live deployment blockers discovered (deployment-verification-agent, Apr 22):**
1. **No broker-side STP orders** — "trailing stop" in `trend_signals.py` is static and never reaches IBKR. Naked position if engine restarts.
2. **Position-size gate rejects 1 MES** — INITIAL_CAPITAL=10000 makes 1 MES (~$35K notional) a 356% position → safety reject. Config needs recalibration for micro contracts.
3. **Scanner disabled 12+ days** — MCL/MNQ have only 3 paper trades since Apr 10, none meaningful.

---

## MACRO CONTEXT FOR NEXT WEEK (Apr 28 – May 2)

**Note:** Federal Reserve calendar page was unreachable for live verification. Events below sourced from premarket brief Apr 24 + general knowledge. Treat FOMC dates as [Unverified].

**Key events:**
- **Apr 29 (Tue):** Consumer Confidence (Conference Board)
- **Apr 30 (Wed):** [Unverified] FOMC Meeting — Day 1. Q1 GDP Advance (first estimate for Q1 2026)
- **May 1 (Thu):** [Unverified] FOMC Rate Decision + Powell press conference. ADP Employment. PCE Deflator (Fed's preferred inflation gauge)
- **May 2 (Fri):** Nonfarm Payrolls (April). ISM Manufacturing PMI

**FOMC context:** No rate cut is expected at this meeting (Fed Funds currently 4.33%). Any dovish language shift would be MCL bearish (stronger USD) and MNQ/equity bullish. Hawkish surprise = commodity spike + equity sell.

**MCL contract calendar:** Currently trading June 2026 contract (CLM26). May contract (CLK26) rolled approximately Apr 21–22. Next roll date for June contract is approximately May 20–21. No contract roll risk during the upcoming week.

**Geopolitical risk:** Iran/Strait of Hormuz situation remains unresolved as of Apr 24. MCL at $92.88–$95.30 reflects a supply-risk premium. If diplomatic progress surfaces, expect a sharp MCL reversal ($5–$10 down). If escalation: MCL could spike toward $100. This is a tail-risk environment for crude — position sizing should reflect that when scanner is re-enabled.

**Elevated risk periods next week:**
- Wed Apr 30: GDP + FOMC Day 1 — expect elevated VIX into decision
- Thu May 1: FOMC decision + press conference (12:30–2:00 PM ET window) — HALT trading during this window
- Fri May 2: NFP 8:30 AM ET — standard macro event caution

---

## ACTION ITEMS FOR NEXT WEEK

**[P1] Fix Anthropic API key (Monday morning, before any other work)**
Every pipeline run is returning HOLD due to 401. The system is completely blind. Rotate the key at `console.anthropic.com`, update `engine/.env`, restart with `.\restart_engine.ps1`. Verify with `/llm/stats` endpoint returning healthy status. This is the gating item — nothing else matters until the LLM is back.

**[P1] Reconcile drawdown reporting and confirm kill switch threshold**
Three surfaces reporting three different drawdown values. The scan showing 12.46% vs EOD showing 0.00% is a critical discrepancy. If the real drawdown is 12.46% and the enforced limit is -10%, the kill switch boundary has already been crossed. Requires `[safety-review]` tagged PR: audit `safety_layer.py` to confirm which drawdown value is authoritative and correct the API response to match `config.py` (-10%).

**[P1] Re-enable scanner with explicit authorization**
All root-cause fixes for the April 10 contamination are committed and tested. The scanner has been off for 16 days. Without it, the 60-trade validation gate cannot be reached. If Matt is comfortable with the fix verification, the authorization is a single sentence: "Flip WATCHLIST_SCAN_ENABLED to true and restart the engine." This unblocks trade accumulation.

**[P2] Fix EOD closer exit price bug**
Trades are being closed at entry price instead of market price. This makes win rate, P&L, and all downstream metrics meaningless. Implement `get_trades_by_date()` on `PortfolioTracker` and fix the mark-to-market logic in the EOD position closer.

**[P2] Root-cause pm2 restart loop (558 restarts)**
Before any live trading consideration, the crash loop must be understood. Run: `pm2 logs jarvis-engine --lines 2000 --nostream | grep -Ei "(error|disconnect|kill|traceback)" | tail -50`. If restarts are from TV-CDP iteration (parallel session commits), confirm they're resolved. If they're from a different source, fix before re-enabling scanner.

---

## PHASE 3 READINESS

**Assessment:** On-track is the wrong frame — the paper validation window expires May 2 and the statistical gates cannot be met in 6 remaining days. The real question is whether to formally extend the paper window and what the recalibrated gate criteria should be.

**Biggest risk to the timeline:** The Anthropic API failure has silenced the pipeline for 3+ days. Even if the key is rotated Monday, the 60-trade gate requires ~6 trades/day for the remaining window — a pace the system has never achieved. The paper window almost certainly needs an extension, framed as an honest acknowledgment that the validation period was impacted by infrastructure outages beyond strategy performance.

**What's actually progressing:** The statistical rigor of the validation framework (Tier A bootstrap/DSR) is materially better than it was two weeks ago. Gate v2 dual-pathway is a principled improvement over the original point-estimate gate. The underlying strategy math (MCL WFE 0.82, MNQ WFE 0.57) hasn't degraded — the validation pipeline just hasn't had enough clean trade data to evaluate it fairly.

**Single biggest risk to the live trading timeline:** The absence of broker-side STP orders (Blocker 1 from deployment-verification-agent). Even if all statistical gates pass, you cannot go live with a strategy that has no broker-side stop. Engine restart = naked position. This is a real engineering task, not a config toggle, and it hasn't been scoped yet.

---

*Generated by JARVIS automated weekly review task | 2026-04-26 | Paper mode — no real capital at risk*
*Engine not reachable for live API pull — all data sourced from EOD reports, scan files, and handoffs*
*Next weekly review: 2026-05-03*
