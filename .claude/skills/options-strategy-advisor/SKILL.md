---
name: options-strategy-advisor
description: Explain and analyze options strategies (covered calls, spreads, straddles, iron condors, earnings plays) for jarvis-trader's equities options book. Use when the user asks "what's a covered call", "analyze this iron condor", "should I trade a straddle before earnings", "what are my Greeks", or wants a strategy comparison. `OPTIONS_WATCHLIST` is SPY/QQQ only as of 2026-08-17 (AAPL/TSLA were removed after failing certification) — use the working `/options-signals/*` delayed-chain analytics for those two; for AAPL/TSLA or any other ticker, fall back to theoretical/HV-based analysis and say so. The `/options/*` router (`engine/routers/options_router.py`) is a disabled/stub module — its chain, Greeks, positions, and analyst endpoints do not return real data; do not use them (see "Why the `/options/*` router is off-limits" below). Never places or recommends placing a live order — output is analysis only.
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

## The live options watchlist is SPY/QQQ only — AAPL/TSLA were removed

`engine/config.py`'s `OPTIONS_WATCHLIST` default is `["SPY", "QQQ"]` as of 2026-08-17 — AAPL and TSLA were explicitly removed after failing daily-SMA-trend gate-v2 WFO certification (AAPL: sample-starvation, 1-3 OOS trades; TSLA: p_edge 0.50-0.56). `engine/CLAUDE.md`'s "Equities" table describing four live names (SPY/QQQ/AAPL/TSLA) is stale against current code — don't cite it as current state. Conveniently, this means the two names still on the watchlist are exactly the two with working analytics (`/options-signals/*` above); there is no live chain/Greeks/IV source for AAPL, TSLA, or any other ticker — pull current price from `GET /prices/snapshot?symbols=<TICKER>` if useful, and otherwise treat them like the theoretical/educational path below, saying explicitly that no live options analytics back the numbers.

Also: a watchlist symbol's paper fills are not automatically options trades — the scanner routes an options spread only when `trade_dec.is_spread` is set; otherwise it's an underlying-equity trade. Don't assume every SPY/QQQ paper fill in `/brokers/positions` is an option position — check what it actually is before describing it as one. In fact `/brokers/positions`' own `_normalise_paper_position()` doesn't carry option-specific fields at all (no strikes, expiry, or contract type — just symbol/direction/quantity/entry_price/entry_time), so it cannot answer "what does jarvis's options book actually look like" on its own; treat any options-specific detail from it as unavailable rather than inferring it.

## This skill never executes

**The real order path** (verified against source, not `engine/options/strategy_executor.py` — that module only builds `OptionsOrder` dataclasses and is never called by anything that submits an order): `main.py` sees `trade_dec.is_spread`, calls `execution/oms_v2.py:execute_options_spread()`, which calls `execution/order_router.py:OrderRouter.route_order()` — the actual IBKR/Schwab dispatch point, gated by the hardcoded `risk/safety_layer.py`. Note `REQUIRE_HUMAN_APPROVAL = False` is the standing config (`.claude/rules/safety.md`), so `approval/service.py` is not currently a mandatory per-trade gate on this path — don't cite it as one.

This skill's job stops at analysis and education — say what a trade would look like, never place it, and never suggest bypassing the safety layer. This holds even when calling `/options/strategy/recommend`, whose response is a literal order object: report its fields as illustrative, never as a ticket to submit.

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
# Use the project's configured interpreter, not bare `python`:
# engine/.venv/bin/python (Linux/cloud sessions) or engine/.venv/Scripts/python (Windows).
API_KEY=$(engine/.venv/bin/python - <<'PY'
from pathlib import Path
for line in Path('engine/.env').read_text(encoding='utf-8', errors='ignore').splitlines():
    if line.startswith('API_KEY='):
        print(line.split('=', 1)[1].strip().strip('"\''))
        break
PY
)

# Delayed-chain snapshot: expected move, probability ladder, VIX/VIX3M term structure, per-horizon atm_iv
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/options-signals/latest"

# Ranked, defined-risk opportunity candidates from that same chain (SPY/QQQ)
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/options-signals/opportunity-board"

# Current price for a SPECIFIC symbol — the default (no ?symbols=) is SPY,QQQ,MES,MNQ,MCL and will NOT include AAPL/TSLA/etc.
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/prices/snapshot?symbols=AAPL"

# Broker-backed position view (IBKR + Schwab + paper tracker) — NOT /options/positions
curl -s -H "X-API-Key: $API_KEY" "http://localhost:8010/brokers/positions"
```

Before treating `/options-signals/latest` as current: check the top-level `generated_at`/`data_quality` (only ever "ok" or "partial" — a fetch either worked or didn't, this does NOT mean the quote is fresh), AND the specific horizon's own `quality`/`notes` (each horizon is independently marked `"degraded"` with a note when its `quote_ts` is >60 min old — a market holiday or feed outage can leave the top-level fields looking fine while the horizon you're using is stale). Don't stop at the top-level fields. Also treat a **null `quote_ts`** on a horizon as unusable — `parse_chain()` can return `quote_ts=None` when CBOE's timestamp field is missing/unparseable, and the staleness check only degrades a horizon when `quote_ts is not None`, so a chain with no timestamp at all stays `quality="ok"` by omission, not because it's actually fresh.

Also check the **VIX/VIX3M regime block separately** — its own caching (in the snapshot generator) reuses the last successful fetch indefinitely on a refresh failure, annotating `regime.source` with "refresh failed" but not touching `regime.as_of_date` or the top-level `data_quality`. A weeks-old regime can silently sit behind an "ok" snapshot. Check `regime.source` for a "refresh failed" marker and `regime.as_of_date` against today before citing the term-structure classification as current.

Before treating `/prices/snapshot` output as a current price: check that symbol's `is_live` field, not just `as_of` — `as_of` is stamped at **fetch time** for every source, including `csv_cache`, so a prior-day close can carry a timestamp that looks fresh (confirmed by `engine/tests/test_actionable.py:test_board_cached_source_withheld_even_with_fresh_timestamp`, which exists specifically to catch this trap). When `is_live` is `false` (or `source` is `"unavailable"`), treat the price as unknown/stale regardless of how recent `as_of` looks — say "last available price via `<source>`, live status unconfirmed" rather than implying it's a current observation.

Before treating `/brokers/positions` as the current book: check `ibkr.connected`, `ibkr.positions_stale`, `schwab.connected`, and `reconciliation.health`. When both brokers are unreachable, `reconciliation.health` reports `"blind"` and the position arrays come back empty — that is "we don't know," not "flat." Never treat a blind or stale response as confirmation there's no existing exposure before suggesting adding risk.

Workflow for a SPY/QQQ question ("analyze my SPY iron condor", "what's SPY's expected move"):
1. Pull `/options-signals/latest` for the real expected move / probability ladder / per-horizon `atm_iv` — never invent a stock price or IV, and never substitute the VIX/VIX3M term-structure numbers for a symbol's own `atm_iv` when pricing QQQ legs (VIX is an SPX-derived index; using it as QQQ's volatility input mis-prices the legs). VIX/VIX3M term structure is a separate regime signal, not a pricing input.
2. If the user wants a recommendation rather than an analysis of a specific trade they named, pull `/options-signals/opportunity-board` and check the returned board's own `status`, `candidate_count`, and each candidate's `reject_reasons` before presenting anything: when all candidates fail quality filters, `status` is `"degraded"`, `candidate_count` is `0`, but the `candidates` array still contains the rejected structures (the code falls back to showing rejects rather than an empty list). Only present a candidate with `status == "ok"` and empty `reject_reasons`; otherwise say the board found nothing that passed its own filters. It's explicitly labeled "not a trade signal," so frame any accepted candidate as a ranked payoff shape worth reviewing, not a recommendation to act on. Two more limits on the board itself: (a) it always projects the symbol's **nearest** horizon — if the user asked for a specific DTE or "end of week," check the candidate's actual `expiry` and say the requested horizon isn't what's shown rather than silently substituting nearest-expiry; (b) its ranking `ev` is computed as a **binary payoff approximation** (`pop * max_gain - (1-pop) * max_loss`), which doesn't capture the continuous P/L between strikes on a vertical spread — don't cite `ev`/`ev_to_max_loss` as a precise expected value, just as the board's own (rough) ranking heuristic.
3. If they gave you specific legs, you can only sanity-check strikes/premium that actually appear in a returned board candidate (its own generated verticals) or the ATM straddle in `/options-signals/latest` — the snapshot has no arbitrary-strike chain lookup. For a leg the response doesn't cover (e.g. a wing of a 4-leg iron condor, or a strike far from ATM), say plainly that no matching quote is available rather than inventing one, then walk Steps 5-9 with whatever real numbers you do have.
4. For incremental-risk questions ("should I add another iron condor"), check `/brokers/positions` for the actual current book (with the connected/stale/health checks above) — not `/options/positions`, which reads an unpopulated store. If any position came from Schwab, treat its option-specific fields as unreliable: `brokers_router._normalise_schwab_position()` looks for a nested `instrument` object and camelCase `averagePrice`/`marketValue` keys, but `SchwabConnector.get_positions()` actually returns flat, snake_case fields — so every Schwab row silently defaults to `sec_type="EQUITY"` with `avg_price`/`market_price` as `None`, even for real option positions. Say Schwab option detail is unavailable rather than trusting `sec_type` from this endpoint.

## AAPL, TSLA, and any other ticker (theoretical / educational path)

Treat AAPL, TSLA, and anything else outside SPY/QQQ identically: no working chain/IV/Greeks source exists for them. Pull current price from `/prices/snapshot?symbols=<TICKER>` if useful (checking its provenance fields per above); the theoretical Black-Scholes walkthrough below is fine for everything else, with user-supplied or Historical-Volatility-estimated inputs. Say explicitly that no live options analytics back the numbers ("theoretical, HV-based" or "using the price/IV you gave me").

**Black-Scholes recap (education only — do not add this as new engine code):**

```
d1 = [ln(S/K) + (r + sigma^2/2) * T] / (sigma * sqrt(T))
d2 = d1 - sigma * sqrt(T)
Call = S*N(d1) - K*e^(-rT)*N(d2)
Put  = K*e^(-rT)*N(-d2) - S*N(-d1)
```

This is the zero-dividend European formula. SPY, QQQ, and AAPL all pay dividends — the formula as written overvalues calls and undervalues puts, and misses early-assignment risk around ex-dividend dates on American-style equity/ETF options entirely. Say so explicitly whenever dividends are relevant (longer-dated contracts, a trade spanning an ex-div date, or covered-call/protective-put analysis on a dividend payer) rather than presenting the zero-dividend number as exact — `engine/options/premium_calculator.py`'s `black_scholes_price()` doesn't take a dividend yield either, so label the output "zero-dividend approximation" in that case rather than implying it accounts for it.

If you need to actually run these numbers rather than just quote them (e.g. to sanity-check a user-supplied example), reuse `engine/options/premium_calculator.py` functions in a throwaway Python `-c` snippet rather than writing a new pricer.

## Supported strategies (for explanation and P/L walkthroughs)

The engine actually has **two different, inconsistent VIX-regime-to-strategy mappings** in its code: `engine/options/strategy_executor.py` (EXTREME→protective put, HIGH→bull put spread, NORMAL→covered call, LOW→iron condor — but never called by anything that submits an order) and `engine/markets/options/strategy_pipeline.py`'s `OptionsStrategyPipeline` (low→iron condor, normal→credit spread, high→skip — wired into `OptionsMarketModule`, which does appear to be a live scanning module). Don't cite either one as "the" engine default when comparing a strategy to jarvis's behavior; this skill's own recommendations come from `/options-signals/opportunity-board` (above), not from replicating either mapping.

### Income
1. **Covered Call** — own stock, sell call (income, caps upside).
2. **Cash-Secured Put** — sell put with cash backing.
3. **Poor Man's Covered Call** — LEAPS call + short near-term call.

### Protection
4. **Protective Put** — own stock, buy put (insurance).
5. **Collar** — own stock, sell call + buy put.

### Directional
6. **Bull Call Spread** / 7. **Bull Put Spread** / 8. **Bear Call Spread** / 9. **Bear Put Spread**

### Volatility
10. **Long Straddle** / 11. **Long Strangle** / 12. **Short Straddle** / 13. **Short Strangle**

### Range-bound
14. **Iron Condor** / 15. **Iron Butterfly**

### Advanced
16. **Calendar Spread** / 17. **Diagonal Spread** / 18. **Ratio Spread**

## Analysis workflow

### Step 1 — Gather inputs
Required: ticker, strategy, strikes, expiration(s), contract count. Optional: IV (else HV, or for SPY/QQQ the matching horizon's `atm_iv` from `/options-signals/latest`), risk-free rate (default ~3-month T-bill). **Stock-backed strategies** (covered call, protective put, collar) additionally need the underlying **share quantity and cost basis** — contract count alone doesn't establish that a short call is actually covered, and correct net delta, max profit, and breakeven all depend on the stock leg. Ask for it rather than assuming 100 shares/contract at an unstated basis.

### Step 2 — Volatility
SPY/QQQ: use the matching symbol/horizon's own `atm_iv` from `/options-signals/latest` as the pricing input — this is real option-derived IV, unlike `/options/iv-rank` (an HV proxy, do not use). Treat the snapshot's VIX/VIX3M term-structure classification (contango/backwardation/flat) as a separate regime signal for framing the trade, never as the volatility input for a specific symbol's Black-Scholes price (VIX is SPX-derived and will misprice QQQ). AAPL/TSLA/other tickers: estimate HV from historical closes if the user hasn't supplied IV, and say so.

### Step 3 — Price the legs
SPY/QQQ: sanity-check against the delayed-chain-derived numbers actually present in `/options-signals/latest` (the ATM straddle) or a `/options-signals/opportunity-board` candidate — see the leg-coverage limit in Step 3 of the live-data workflow above. AAPL/TSLA/other tickers: quote the Black-Scholes formula inline (see above), don't hand-roll a new script for it.

### Step 4 — Greeks
There is no working live Greeks source for any symbol (`/options/greeks` always reports zero — see above). For a hypothetical trade, compute per-leg Greeks by hand using the standard formulas (delta, gamma, theta, vega, rho), then scale each leg to dollar exposure as `per_share_greek × (+1 long / −1 short) × contract_quantity × 100` before summing across legs — equity options are 100-share contracts, so a raw per-share Greek understates exposure 100x if reported directly (e.g. one long call with delta 0.50 is ~$50 of underlying-equivalent exposure per $1 move, not $0.50). **0DTE legs** (a horizon expiring today, `dte_calendar == 0`) divide by zero in the standard Black-Scholes formulas if `T` is computed as calendar-days/365 — the engine's own `calculate_greeks()` raises on `T <= 0` for the same reason. Use the actual fraction of a year remaining until the contract's settlement cutoff (not whole calendar days), or say the calculation is unavailable once that cutoff has passed.

| Greek | Meaning (per share — multiply by 100 × contracts × long/short sign for $ exposure) |
|-------|---------|
| Delta | Change in option price per $1 move in underlying |
| Gamma | Delta's rate of change per $1 move |
| Theta | Daily time decay |
| Vega | Change in option price per 1-point IV change |
| Rho | Change in option price per 1% rate change |

### Step 5 — Simulate P/L
Max profit, max loss, breakeven(s), rough probability-of-profit band. An ASCII P/L diagram is a nice-to-have, not required — don't over-produce it for a quick question. **Exception — Calendar and Diagonal spreads**: their legs expire on different dates, so there is no single terminal intrinsic-value payoff to compute — the remaining long leg's value at the short leg's expiry depends on then-current spot and IV, not just intrinsic value. Don't state a fixed max profit or breakeven for these two; instead walk 2-3 spot/IV scenarios at the near-leg expiry and label them as scenario-dependent estimates, not exact figures.

### Step 6 — Strategy-specific walkthrough
Cover setup, max profit/loss, breakeven, Greeks, assignment risk, when to use / avoid, exit plan. Keep it to the strategy actually asked about — don't dump all 18 unless the user wants a comparison table.

### Step 7 — Earnings strategies
Fetch the earnings date if the engine/watchlist tooling has it available (check for an earnings-calendar source in `engine/` before assuming there is none). Flag IV-crush risk explicitly for any pre-earnings long-premium strategy (straddle/strangle), and IV-crush *benefit* for short-premium strategies (iron condor) — this is the single most common mistake retail options traders make and the original skill's IV-crush framing is worth keeping verbatim in spirit.

### Step 8 — Risk sizing
Position size against the user's stated risk tolerance (max loss × contracts <= risk budget), same logic as the original skill. This is advisory sizing for the user's own broker account discussion, not jarvis's own capital allocation — jarvis's own `$5K/instrument` cap and kill-switch live in `engine/config.py` / `.claude/rules/safety.md` and are not yours to recompute or override here. **Undefined-risk strategies** (naked short straddle/strangle, a net-short-call uncovered ratio spread — anything without a bought wing capping upside loss) have genuinely unbounded max loss, so `max loss × contracts <= budget` has no solution: don't substitute broker margin requirement or a stress-test number for max loss and quietly produce a contract count. Say plainly that no finite size satisfies a fixed dollar risk budget there, and that sizing is a margin/risk-tolerance question instead. **Exception**: an uncovered *put* ratio spread is not unbounded — the underlying can't go below zero, so its max loss is large but finite (compute it at the zero-price floor) and normal max-loss-based sizing still applies. Only net-short-call ratios and naked calls/straddles/strangles are truly unbounded.

### Step 9 — Output
A short markdown report: setup, P/L summary, Greeks, risk assessment, entry/exit/stop guidance, when-to-use vs avoid, and (if useful) an alternatives comparison table. Match the depth to the question — a one-line "what's a collar" question doesn't need Step 9's whole template; a "should I put this trade on" question does.

## Never

- Never call an external pricing API (FMP or otherwise) for SPY/QQQ — `/options-signals/*` is the source of truth for those two.
- Never use `/options/chain`, `/options/greeks`, `/options/iv-rank`, `/options/positions`, or `/options/analyst` as if they returned real data — verified non-functional/misleading (see "Why the `/options/*` router is off-limits" above). Use `/options-signals/*`, `/brokers/positions`, and hand-computed Greeks instead.
- Never present AAPL/TSLA numbers as live-data-backed — there is no working chain/IV/Greeks source for them; theoretical/HV-based only, and say so.
- Never reimplement Black-Scholes/Greeks as new engine code — `engine/options/premium_calculator.py` and `engine/options/greeks_monitor.py` already have correct math; extend those files if a real gap is found, don't fork the logic into a skill script.
- Never place, submit, or draft an order, and never present `/options/strategy/recommend`'s returned `OptionsOrder` as a ticket to submit — real order placement goes through `execution/oms_v2.py` → `execution/order_router.py` (gated by `risk/safety_layer.py`), all out of scope for this skill.
- Never present an `/options-signals/opportunity-board` candidate the board itself rejected (check `status`/`candidate_count`/`reject_reasons` — see Step 2 of the live-data workflow above) as a legitimate recommendation.
- Never invoke a broker action, or treat a `blind`/disconnected `/brokers/positions` response as confirmation of a flat book (see the workflow note above) — say the position state is unknown instead.
