---
name: backtest-report
description: Generate consistently-formatted human-readable backtest summaries from jarvis-trader `/backtest/*` endpoint responses. Use when the user says "summarize the backtest", "format this backtest", "backtest report", "show me the results", "write up this run", "compare these backtests", or after invoking `/backtest/run`, `/backtest/walk-forward`, or `/wfe/optimize-bayesian` and needing a readable summary. Produces a standard six-section report: Headline, Metrics, Regime Performance, Trade Stats, Risk Flags, Next Actions.
---

# When to use

Activate after any backtest API call where the user needs a human digest rather than raw JSON. Also use when comparing 2+ backtest runs side-by-side, or when preparing a session-log entry that references a backtest.

The goal: the same inputs always produce the same report shape. No creative reformatting — consistency lets Matt skim across runs.

# How to use

## Inputs needed

Either (a) JSON response body from `/backtest/*`, or (b) a call path: instrument, timeframe, date range, strategy variant. If (b), invoke the engine:

```bash
curl -s -H "X-API-Key: $API_KEY" \
  "http://localhost:8010/backtest/run?instrument=MCL&timeframe=1h&start=2025-01-01&end=2025-06-01"
```

## Report template (use exactly this structure)

```
# Backtest — <instrument> <timeframe> <start>..<end>

## Headline
<one sentence: PF, Sharpe, WFE, return pct, verdict (PASS/FAIL/OVERFIT)>

## Metrics
- Profit factor: <value>
- Sharpe ratio: <value>
- Sortino ratio: <value>
- Max drawdown: <value>
- Return: <pct> over <n> days
- Walk-forward efficiency (WFE): <value>  <-- flag OVERFIT if < 0.3
- Composite score: <value>  <-- via validation_metrics.composite_score if available

## Regime Performance
| Regime | Trades | PF | Win% | Avg R |
| ------ | ------ | -- | ---- | ----- |
| Trending-up   | ... |
| Trending-down | ... |
| Chop          | ... |
| Volatile      | ... |

## Trade Stats
- Total trades: <n>
- Win rate: <pct>
- Avg winner: <$>
- Avg loser: <$>
- Largest winner / loser: <$> / <$>
- Longest win streak / loss streak: <n> / <n>

## Risk Flags
<bulleted — only list if present>
- WFE < 0.3 (OVERFIT)
- Max DD > 25% of starting capital
- < 30 trades (insufficient sample)
- Single regime > 80% of total PnL (fragile)
- Sharpe > 5.0 AND WFE < 0.5 (suspiciously good in-sample)

## Next Actions
<1-3 specific next steps — e.g. "re-run with 2024 OOS window", "tighten ATR stop 1.5x -> 1.2x and retest", "check regime-debate config since chop regime lost $X">
```

## Verdict rules (apply mechanically)

- `PASS` if WFE >= 0.5 AND PF >= 1.5 AND max DD pct < 25% AND trades >= 30
- `OVERFIT` if WFE < 0.3 regardless of other metrics (never call this PASS)
- `FAIL` otherwise
- `MARGINAL` if WFE 0.3..0.5 — call it out; do not auto-PASS

## Comparing two runs

Use a second table under Headline:

```
| Metric | Run A | Run B | Delta |
| ------ | ----- | ----- | ----- |
| PF     | 1.8   | 2.1   | +0.3  |
```

# Example

Input: `/backtest/run?instrument=MCL&timeframe=1h&start=2025-01-01&end=2025-06-01` returns `{"pf": 2.3, "sharpe": 1.8, "wfe": 0.82, ...}`

Output headline: `MCL 1h PF 2.3 / Sharpe 1.8 / WFE 0.82 / +14.2% over 151 days — PASS (paper-approved threshold)`

# Hard rules

- Do NOT include metrics that were not in the response — say "not returned" rather than inventing.
- Always flag OVERFIT if WFE < 0.3 even if PF/Sharpe look great (per MEMORY.md MES lesson: PF 5.27 + Sharpe 4.16 was overfit at WFE 0.09).
- Always include a "Risk Flags" section header even when empty — write "None" if clean. Missing section = missing check.
- Never recommend live trading based on a single backtest — minimum recommendation is "run walk-forward" or "run OOS window".
