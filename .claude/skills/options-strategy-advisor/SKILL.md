---
name: options-strategy-advisor
description: Explain and analyze options strategies (covered calls, spreads, straddles, iron condors, earnings plays) for jarvis-trader's equities options book. Use when the user asks "what's a covered call", "analyze this iron condor", "should I trade a straddle before earnings", "what are my Greeks", or wants a strategy comparison. For SPY/QQQ/AAPL/TSLA (the four names jarvis actually trades in paper — see engine/CLAUDE.md "Equities" table) always pull live chain/Greeks/IV-rank from the engine's own `/options/*` endpoints rather than recomputing Black-Scholes from scratch — jarvis already has a production pricing engine (`engine/options/`). For any other ticker, theoretical/educational analysis is fine. Never places or recommends placing a live order — output is analysis only.
---

# Options Strategy Advisor

_Adapted from [tradermonty/claude-trading-skills](https://github.com/tradermonty/claude-trading-skills) `options-strategy-advisor` skill (MIT). The original is a standalone Black-Scholes + FMP-API tool for generic retail stock options education. jarvis-trader already ships a live options pricing/Greeks/strategy engine (`engine/options/`, `engine/routers/options_router.py`) trading SPY/QQQ/AAPL/TSLA in paper — this version is a thin advisory layer on top of that engine instead of a second Black-Scholes implementation. Do not reintroduce the FMP dependency or reimplement `black_scholes_price` / Greeks — they already exist in `engine/options/premium_calculator.py` and `engine/options/greeks_monitor.py`._

## Why this isn't a straight import

jarvis-trader is not a generic retail-options sandbox. Before using this skill, know:

- **Engine already computes real Greeks and prices** from live chain data: `engine/options/premium_calculator.py` (Black-Scholes pricing, PoP, EV, spread metrics) and `engine/options/greeks_monitor.py` (Greeks, IV solver, IV rank/percentile, portfolio Greeks). Reimplementing these in a new script is exactly the "re-implements something already shipped" case `.claude/rules/meta-discipline.md` #2 tells you to flag, not do.
- **Engine already auto-selects a strategy by VIX regime** — `engine/options/strategy_executor.py` builds protective puts (VIX EXTREME), bull put spreads (VIX HIGH), covered calls (VIX NORMAL), or iron condors (VIX LOW) via `classify_vix_regime()`. `POST /options/strategy/recommend` exposes this. Don't propose an ad hoc strategy-selection heuristic that contradicts it.
- **Only four equities are actually live in paper**: SPY, QQQ, AAPL, TSLA (`engine/config.py` `OPTIONS_WATCHLIST`; see `engine/CLAUDE.md` "Equities" table for their gate-v2/WFE status — SPY is REJECTED and trading anyway per Amo's 2026-08-03 decision, QQQ/AAPL/TSLA have no gate-v2 verdict on file at all). Anything you say about "the current position" or "current Greeks exposure" for these four must come from the live engine endpoints below, not from a hypothetical example.
- **This skill never executes.** Order placement lives in `engine/options/strategy_executor.py` + `approval/service.py` + the hardcoded `risk/safety_layer.py`. This skill's job stops at analysis and education — say what a trade would look like, never place it, and never suggest bypassing the approval/safety layer.

## When to use

- Educational questions: "What's a covered call?", "How does an iron condor work?"
- Strategy simulation / comparison: "What's my max profit on a bull call spread?", "Covered call vs protective put?"
- Greeks explanation: "What's my delta exposure?", "What are my portfolio Greeks?"
- Earnings-related options questions: "Should I trade a straddle before NVDA earnings?"
- Position sizing guidance for an options trade the user is considering

## Live data path (SPY, QQQ, AAPL, TSLA)

Call the engine directly — port 8010, `X-API-Key` header (current value in `engine/.env`, rotates — read at use time, never hardcode). Do not call FMP or any external pricing API for these four names.

```bash
# Live chain (calls, puts, Greeks, IV rank, underlying price) — nearest expiry
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/options/chain/SPY"

# Aggregated portfolio Greeks across all open options positions
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/options/greeks"

# IV rank for a symbol
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/options/iv-rank/SPY"

# VIX-regime-based strategy recommendation (the engine's own logic, not a new heuristic)
curl -s -H "X-API-Key: $API_KEY" -X POST "http://localhost:8010/options/strategy/recommend" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "SPY", "vix": 18.5, "underlying_price": 560.0, "dte": 30}'

# Open options positions
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/options/positions"

# OptionsAnalyst verdict (stage-6 pipeline signal, LLM-assisted)
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/options/analyst/SPY"
```

Workflow for a live-name question ("analyze my SPY iron condor", "what's AAPL's IV rank"):
1. Pull `/options/chain/{symbol}` and `/options/iv-rank/{symbol}` for real inputs — never invent a stock price or IV.
2. If the user wants a recommendation rather than an analysis of a specific trade they named, call `/options/strategy/recommend` and explain *why* that regime maps to that strategy (see Step 7 below) — don't substitute your own strategy pick.
3. If they gave you specific legs, price/Greeks-check those legs against the chain data, then walk Steps 5-9 below using the real numbers.
4. Always note current open positions (`/options/positions`) if the question is about incremental risk ("should I add another iron condor") — don't analyze in a vacuum.

## Theoretical / educational path (any other ticker)

For tickers outside SPY/QQQ/AAPL/TSLA, jarvis has no live engine, no chain, no position book — this is pure education/comparison and the theoretical Black-Scholes walkthrough below is fine, with user-supplied or Historical-Volatility-estimated inputs. Say explicitly that no live data backs the numbers ("theoretical, HV-based" or "using the price/IV you gave me").

**Black-Scholes recap (education only — do not add this as new engine code):**

```
d1 = [ln(S/K) + (r + sigma^2/2) * T] / (sigma * sqrt(T))
d2 = d1 - sigma * sqrt(T)
Call = S*N(d1) - K*e^(-rT)*N(d2)
Put  = K*e^(-rT)*N(-d2) - S*N(-d1)
```

If you need to actually run these numbers rather than just quote them (e.g. to sanity-check a user-supplied example), reuse `engine/options/premium_calculator.py` functions in a throwaway Python `-c` snippet rather than writing a new pricer.

## Supported strategies (for explanation and P/L walkthroughs)

### Income
1. **Covered Call** — own stock, sell call (income, caps upside). Engine's VIX-NORMAL default.
2. **Cash-Secured Put** — sell put with cash backing.
3. **Poor Man's Covered Call** — LEAPS call + short near-term call.

### Protection
4. **Protective Put** — own stock, buy put (insurance). Engine's VIX-EXTREME default.
5. **Collar** — own stock, sell call + buy put.

### Directional
6. **Bull Call Spread** / 7. **Bull Put Spread** (engine's VIX-HIGH default) / 8. **Bear Call Spread** / 9. **Bear Put Spread**

### Volatility
10. **Long Straddle** / 11. **Long Strangle** / 12. **Short Straddle** / 13. **Short Strangle**

### Range-bound
14. **Iron Condor** (engine's VIX-LOW default) / 15. **Iron Butterfly**

### Advanced
16. **Calendar Spread** / 17. **Diagonal Spread** / 18. **Ratio Spread**

## Analysis workflow

### Step 1 — Gather inputs
Required: ticker, strategy, strikes, expiration(s), contract count. Optional: IV (else HV or, for the live four, the engine's IV-rank endpoint), risk-free rate (default ~3-month T-bill).

### Step 2 — Volatility
Live four: use `/options/iv-rank/{symbol}` and the chain's embedded IV, not a manual HV calc. Other tickers: estimate HV from historical closes if the user hasn't supplied IV, and say so.

### Step 3 — Price the legs
Live four: read theoretical/mid prices straight off the chain response. Other tickers: quote the Black-Scholes formula inline (see above), don't hand-roll a new script for it.

### Step 4 — Greeks
Live four: `/options/greeks` gives portfolio-level aggregation; for a hypothetical single trade not yet in the position book, compute per-leg Greeks by hand using the standard formulas (delta, gamma, theta, vega, rho) and sum across legs — same math the engine uses in `greeks_monitor.py`, just walked by hand for a what-if.

| Greek | Meaning |
|-------|---------|
| Delta | $ change per $1 move in underlying |
| Gamma | Delta's rate of change per $1 move |
| Theta | Daily time decay |
| Vega | $ change per 1-point IV change |
| Rho | $ change per 1% rate change |

### Step 5 — Simulate P/L
Max profit, max loss, breakeven(s), rough probability-of-profit band. An ASCII P/L diagram is a nice-to-have, not required — don't over-produce it for a quick question.

### Step 6 — Strategy-specific walkthrough
Cover setup, max profit/loss, breakeven, Greeks, assignment risk, when to use / avoid, exit plan. Keep it to the strategy actually asked about — don't dump all 18 unless the user wants a comparison table.

### Step 7 — Earnings strategies
Fetch the earnings date if the engine/watchlist tooling has it available (check for an earnings-calendar source in `engine/` before assuming there is none). Flag IV-crush risk explicitly for any pre-earnings long-premium strategy (straddle/strangle), and IV-crush *benefit* for short-premium strategies (iron condor) — this is the single most common mistake retail options traders make and the original skill's IV-crush framing is worth keeping verbatim in spirit.

### Step 8 — Risk sizing
Position size against the user's stated risk tolerance (max loss × contracts <= risk budget), same logic as the original skill. This is advisory sizing for the user's own broker account discussion, not jarvis's own capital allocation — jarvis's own `$5K/instrument` cap and kill-switch live in `engine/config.py` / `.claude/rules/safety.md` and are not yours to recompute or override here.

### Step 9 — Output
A short markdown report: setup, P/L summary, Greeks, risk assessment, entry/exit/stop guidance, when-to-use vs avoid, and (if useful) an alternatives comparison table. Match the depth to the question — a one-line "what's a collar" question doesn't need Step 9's whole template; a "should I put this trade on" question does.

## Never

- Never call an external pricing API (FMP or otherwise) for SPY/QQQ/AAPL/TSLA — the engine's own chain/Greeks endpoints are the source of truth for those four.
- Never reimplement Black-Scholes/Greeks as new engine code — `engine/options/premium_calculator.py` and `engine/options/greeks_monitor.py` already do this; extend those files if a real gap is found, don't fork the logic into a skill script.
- Never place, submit, or draft an order — that requires `engine/options/strategy_executor.py` + the approval/safety layer, both out of scope for this skill.
- Never contradict the engine's own VIX-regime strategy selection (`strategy_executor.classify_vix_regime`) with an ad hoc alternative unless the user explicitly asks "what would you do differently."
