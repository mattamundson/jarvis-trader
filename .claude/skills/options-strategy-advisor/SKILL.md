---
name: options-strategy-advisor
description: Explain and analyze options strategies (covered calls, spreads, straddles, iron condors, earnings plays) for jarvis-trader's equities options book. Use when the user asks "what's a covered call", "analyze this iron condor", "should I trade a straddle before earnings", "what are my Greeks", or wants a strategy comparison. For SPY/QQQ use the working `/options-signals/*` delayed-chain analytics; for AAPL/TSLA (traded per `OPTIONS_WATCHLIST` but with no working options analytics behind them) and any other ticker, fall back to theoretical/HV-based analysis and say so. The `/options/*` router (`engine/routers/options_router.py`) is a disabled/stub module — its chain, Greeks, positions, and analyst endpoints do not return real data; do not use them (see "Why the `/options/*` router is off-limits" below). Never places or recommends placing a live order — output is analysis only.
---

# Options Strategy Advisor

_Adapted from [tradermonty/claude-trading-skills](https://github.com/tradermonty/claude-trading-skills) `options-strategy-advisor` skill (MIT). The original is a standalone Black-Scholes + FMP-API tool for generic retail stock options education. jarvis-trader has two separate options subsystems: a disabled/stub `engine/options/` + `/options/*` router (do not use — see below), and a working, actually-running delayed-chain analytics pipeline (`engine/analysis/options_implied.py`, `engine/analysis/options_opportunity_board.py`, served at `/options-signals/*`) for SPY/QQQ only. This version routes through the working pipeline instead of reimplementing Black-Scholes, and is explicit about the gap for AAPL/TSLA and any other ticker._

## Why the `/options/*` router is off-limits

A Codex review of this skill (PR #815) verified, against the actual code, that every `/options/*` endpoint this skill originally pointed to is non-functional or misleading. Confirmed by reading the source directly:

- **`GET /options/chain/{symbol}` always 404s.** `engine/options/chain_fetcher.py:fetch_chain()` builds an `OptionsChain` with `calls: list = []` and `puts: list = []` that are never populated, and `options_router.py` raises 404 whenever both lists are empty — which is always.
- **`GET /options/iv-rank/{symbol}` is not option IV rank.** `chain_fetcher.get_iv_rank()` computes a rank from 21-day close-to-close *historical* volatility, not option-implied volatility, and silently returns `50.0` (presented as "neutral") whenever data is missing.
- **`GET /options/greeks` always returns all-zero Greeks.** `options_router.py` instantiates a fresh `OptionsPositionManager()` per request, whose `GreeksMonitor` starts empty and is never rehydrated from the persisted position store.
- **`GET /options/positions` reads a store nothing populates.** `OptionsPositionManager.add_position()` has zero production callers (`grep -rn "add_position(" engine/` outside tests and the class itself returns nothing) — real option fills route through `OrderRouter`/Schwab and never reach this SQLite table, so it can read empty while real positions exist.
- **`GET /options/analyst/{symbol}` never returns a real verdict.** `agents/options_analyst.py:OptionsAnalyst._skew_signal/_term_signal/_gamma_signal` are hardcoded to always abstain (`return (0.0, False)`) and `_get_iv_rank()` always returns `None` — it's either "disabled" or `no_iv_data`, never a signal.
- **`POST /options/strategy/recommend` returns a fully-specified order, not a classification.** `OptionsOrder` is documented in `strategy_executor.py` as "a complete options order ready for review or execution" with concrete strikes/premium/max-risk. Calling it is fine for illustrating what the engine's own VIX-regime logic would build, but never present its output as anything other than an illustrative structure, and never feed it into an execution call.

None of this is a reason to reimplement Black-Scholes or Greeks in this skill (`engine/options/premium_calculator.py` and `greeks_monitor.py` still have correct math, they're just not wired to real data) — it's a reason to use the pipeline that actually works instead.

## What actually works: `/options-signals/*`

`engine/scripts/options_signals_snapshot.py` runs every 30 minutes on weekday RTH, fetches free CBOE delayed chains plus VIX/VIX3M daily CSVs, and writes `engine/data/options_signals/latest.json`. `engine/routers/options_signals_router.py` serves it read-only:

- `GET /options-signals/latest` — the raw snapshot: ATM-straddle expected move (abs and %), delta-implied probability ladder, VIX/VIX3M term-structure regime, per symbol/horizon (`engine/analysis/options_implied.py`).
- `GET /options-signals/opportunity-board` — ranked, defined-risk bounded-strategy candidates computed from that same chain (`engine/analysis/options_opportunity_board.py`), explicitly self-labeled `"not a trade signal"` and analysis-only (no broker, no order routing).

**Coverage is SPY/QQQ only** (per the module's own docstrings) — this does not extend to AAPL/TSLA.

## Only four equities are live in paper — but only two have working analytics

SPY, QQQ, AAPL, TSLA (`engine/config.py` `OPTIONS_WATCHLIST`) all submit live paper option orders (`engine/CLAUDE.md` "Equities" table has their gate-v2/WFE status — SPY is REJECTED and trading anyway per Amo's 2026-08-03 decision, QQQ/AAPL/TSLA have no gate-v2 verdict on file at all). Of those four, only **SPY and QQQ** have a working live-data source (`/options-signals/*` above). For **AAPL and TSLA**, there is currently no working chain, Greeks, or IV source in the engine — pull current price from `GET /prices/snapshot` if you need it, and otherwise treat AAPL/TSLA exactly like the theoretical/educational path below, saying explicitly that no live options analytics back the numbers.

## This skill never executes

Order placement lives in `engine/options/strategy_executor.py` + `approval/service.py` + the hardcoded `risk/safety_layer.py`. This skill's job stops at analysis and education — say what a trade would look like, never place it, and never suggest bypassing the approval/safety layer. This holds even when calling `/options/strategy/recommend`, whose response is a literal order object: report its fields as illustrative, never as a ticket to submit.

## When to use

- Educational questions: "What's a covered call?", "How does an iron condor work?"
- Strategy simulation / comparison: "What's my max profit on a bull call spread?", "Covered call vs protective put?"
- Greeks explanation: "What's my delta exposure?", "What are my portfolio Greeks?"
- Earnings-related options questions: "Should I trade a straddle before NVDA earnings?"
- Position sizing guidance for an options trade the user is considering

## Live data path (SPY, QQQ only)

Call the engine directly — port 8010, `X-API-Key` header (current value in `engine/.env`, rotates — read at use time, never hardcode).

```bash
# Read API_KEY at use time from engine/.env; never paste or commit the value.
API_KEY=$(python - <<'PY'
from pathlib import Path
for line in Path('engine/.env').read_text(encoding='utf-8', errors='ignore').splitlines():
    if line.startswith('API_KEY='):
        print(line.split('=', 1)[1].strip().strip('"\''))
        break
PY
)

# Delayed-chain snapshot: expected move, probability ladder, VIX/VIX3M term structure
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/options-signals/latest"

# Ranked, defined-risk opportunity candidates from that same chain (SPY/QQQ)
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/options-signals/opportunity-board"

# Current price (works for any symbol, including AAPL/TSLA)
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/prices/snapshot"

# Broker-backed position view (IBKR + Schwab + paper tracker) — NOT /options/positions
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/brokers/positions"
```

Check `generated_at` / `data_delayed_minutes` / `data_quality` in the `/options-signals/latest` response before treating it as current — this is a 30-minute-cadence delayed CBOE feed, not real-time, and self-reports staleness rather than being computed fresh per request.

Workflow for a SPY/QQQ question ("analyze my SPY iron condor", "what's SPY's expected move"):
1. Pull `/options-signals/latest` for the real expected move / probability ladder / term-structure regime — never invent a stock price or IV.
2. If the user wants a recommendation rather than an analysis of a specific trade they named, pull `/options-signals/opportunity-board` and present its ranked candidates — remember it's explicitly labeled "not a trade signal," so frame it as ranked payoff shapes worth reviewing, not a recommendation to act on.
3. If they gave you specific legs, sanity-check strikes/premium against the snapshot's chain-derived numbers, then walk Steps 5-9 below using the real numbers.
4. For incremental-risk questions ("should I add another iron condor"), check `/brokers/positions` for the actual current book — not `/options/positions`, which reads an unpopulated store.

## AAPL, TSLA, and any other ticker (theoretical / educational path)

AAPL and TSLA trade live in jarvis's paper book (`OPTIONS_WATCHLIST`) but have no working chain/IV/Greeks source — treat them the same as any ticker outside SPY/QQQ. Pull current price from `/prices/snapshot` if useful; the theoretical Black-Scholes walkthrough below is fine for everything else, with user-supplied or Historical-Volatility-estimated inputs. Say explicitly that no live options analytics back the numbers ("theoretical, HV-based" or "using the price/IV you gave me") — this is the honest default for AAPL/TSLA questions, not just a fallback for unrelated tickers.

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
Required: ticker, strategy, strikes, expiration(s), contract count. Optional: IV (else HV, or for SPY/QQQ the `/options-signals/latest` snapshot's own VIX/VIX3M and expected-move data), risk-free rate (default ~3-month T-bill).

### Step 2 — Volatility
SPY/QQQ: use the VIX/VIX3M term-structure regime and expected-move data from `/options-signals/latest`, not a manual HV calc — this is real option-derived data (ATM-straddle pricing), unlike `/options/iv-rank` (see above, an HV proxy, do not use). AAPL/TSLA/other tickers: estimate HV from historical closes if the user hasn't supplied IV, and say so.

### Step 3 — Price the legs
SPY/QQQ: sanity-check against the delayed-chain-derived numbers in `/options-signals/latest` and `/options-signals/opportunity-board`. AAPL/TSLA/other tickers: quote the Black-Scholes formula inline (see above), don't hand-roll a new script for it.

### Step 4 — Greeks
There is no working live Greeks source for any symbol (`/options/greeks` always reports zero — see above). For a hypothetical trade, compute per-leg Greeks by hand using the standard formulas (delta, gamma, theta, vega, rho) and sum across legs — same math `engine/options/greeks_monitor.py` implements correctly, just not wired to real positions, so walk it by hand instead of citing the endpoint.

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

- Never call an external pricing API (FMP or otherwise) for SPY/QQQ — `/options-signals/*` is the source of truth for those two.
- Never use `/options/chain`, `/options/greeks`, `/options/iv-rank`, `/options/positions`, or `/options/analyst` as if they returned real data — verified non-functional/misleading (see "Why the `/options/*` router is off-limits" above). Use `/options-signals/*`, `/brokers/positions`, and hand-computed Greeks instead.
- Never present AAPL/TSLA numbers as live-data-backed — there is no working chain/IV/Greeks source for them; theoretical/HV-based only, and say so.
- Never reimplement Black-Scholes/Greeks as new engine code — `engine/options/premium_calculator.py` and `engine/options/greeks_monitor.py` already have correct math; extend those files if a real gap is found, don't fork the logic into a skill script.
- Never place, submit, or draft an order, and never present `/options/strategy/recommend`'s returned `OptionsOrder` as a ticket to submit — order placement requires `engine/options/strategy_executor.py` + the approval/safety layer, both out of scope for this skill.
- Never contradict the engine's own VIX-regime strategy selection (`strategy_executor.classify_vix_regime`) with an ad hoc alternative unless the user explicitly asks "what would you do differently."
