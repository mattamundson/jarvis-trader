---
name: agent-debate-explain
description: Narrate what a jarvis-trader 5-stage pipeline run actually did — stage-by-stage, with the debate scores, advisor calls, and final trader verdict explained in plain English. Use when the user says "why did the pipeline say buy", "explain this signal", "walk me through the debate", "what happened on that trade", "narrate the pipeline", or after a `/pipeline/run` or `/pipeline/run/sdk` call produces a result that needs interpretation. Produces a stage-1-through-stage-5 summary with confidence, tie-break notes, and advisor/IC ensemble influence.
---

# When to use

Activate when the user needs to understand an existing pipeline result — not to run a new one. Source data is the pipeline response JSON or the trade log for a specific trade_id.

Specifically useful for:

- Post-mortems on trades that lost
- Explaining why a confluence trade got a bigger size
- Auditing whether the advisor was called and what it said
- Debugging "debate score = 0.000" incidents (fixed 2026-04-15 but worth sanity-checking)

# How to use

## Inputs

One of:
- Full `/pipeline/run` JSON response
- `trade_id` -> fetch via `GET /trades/<id>` and `GET /debates/<trade_id>`
- Session log excerpt mentioning a pipeline decision

## Narrative template (follow stage order, always all 5)

```
# Pipeline Narration — <instrument> <timestamp>

## Stage 1 — Market Analyst
Input bar: <OHLCV, regime classification>
Indicators fired: <STC OS/OB, ATR, hidden pivots, VIX band>
Regime: <5-layer classification result>
Time-of-day filter: <passed / blocked because ...>

## Stage 2 — Debate (Bull vs Bear)
Bull researcher score: <value> — key evidence: <top 2-3 items>
Bear researcher score: <value> — key evidence: <top 2-3 items>
Net score: <bull - bear> vs threshold <value>
Tie-break applied: <yes/no — if yes, which rule from debate.py:454-482>
IC-weighted ensemble adjustment: <delta, reasoning>

## Stage 3 — Advisor (Claude Opus, if invoked)
Was called: <yes/no — triggered by |score-threshold| <= 0.05 OR confidence < 0.5>
Verdict: <AdvisorVerdict result>
Refinement: <any parameter changes suggested>
Cost impact: <token counts if available>

## Stage 4 — Social / Sentiment
ApeWisdom signal: <value>
News sentiment: <value>
Weight in final decision: <percent>

## Stage 5 — Trader (Execution)
Confluence multiplier: <value>
VIX-based sizing: <value>
Final position size: <contracts> (bounds 0.5x..1.5x, integer-clamped to max_contracts=2)
Stop loss: <price, ATR multiple used>
Take profit: <price, ATR multiple used>
Decision: <BUY / SELL / HOLD>
Confidence: <value>

## Plain-English summary
<2-3 sentences: what the pipeline saw, why it went this direction, what the primary driver was>

## Red flags (if any)
- Debate score near threshold (< 0.05 margin)
- Advisor disagreed with debate direction
- Regime classification low-confidence
- Social weight dominant (> 40%) with thin sentiment data
```

## Sizing math disclosure

Per MEMORY.md (2026-04-10 sprint audit): position sizing is **0.5x..1.5x, integer-clamped to max_contracts=2** — NOT the commonly-cited 0.25x..1.0x. State the bounds correctly; reference `engine/agents/trader.py:290-293` if the user wants proof.

## Advisor trigger rules

Per `debate.py:509-582` and `trader.py:524-590`:
- Inconclusive debate: `|bull_score - bear_score - threshold| <= 0.05`
- Low-confidence trade: confidence < 0.5

If neither triggered, state "Advisor not invoked (debate decisive at |delta|=<value>, confidence=<value>)".

# Example

User: "Why did the pipeline buy MCL at 84.20?"

Output walks through: Stage 1 regime = trending-up, STC crossed out of OS at 15.2 / Stage 2 bull 0.62 vs bear 0.31, delta 0.31 well above threshold 0.15, no tie-break needed, IC ensemble muted bear slightly / Stage 3 advisor NOT invoked (decisive) / Stage 4 ApeWisdom neutral, news mildly bullish / Stage 5 confluence mult 1.2x, VIX 14 -> 1.0x, final 1 contract, stop 83.40 (1.5x ATR), tp 85.80 (3.0x ATR), confidence 0.71. Plain English: trending regime + STC reversal + bull evidence margin produced a 1-contract long with tight stop.

# Hard rules

- Always report all 5 stages even when a stage was bypassed — say "bypassed: <reason>" rather than skipping.
- If debate score is literally 0.000, flag it — that was a known bug class (fixed 2026-04-15, but worth confirming on any new occurrence).
- Do not editorialize about whether the trade was "good" — this skill narrates, it does not grade. Use `backtest-report` for PnL evaluation.
- If the advisor was invoked, always report the cost/token delta — token efficiency matters.
