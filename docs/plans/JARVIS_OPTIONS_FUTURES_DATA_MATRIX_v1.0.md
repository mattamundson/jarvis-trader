# Options vs Futures Data — Per-Domain Matrix (v1.0)

**Authored:** 2026-09-23 · **Status:** ANALYSIS ONLY — nothing purchased or wired.
**Answers:** *"What about options and futures data?"*
**Supersedes:** the two-domain framing in `JARVIS_MARKET_DATA_TIERS_v2.0.md` and
`JARVIS_DATA_BUDGET_ALLOCATION_100-200_v1.0.md` — there are **four** data domains, not two, and the options one
has a problem neither document surfaced.

---

## §1. The finding that reframes the priority order

`backtest/run_spy_qqq_options_vertical.py` states its own pricing, verbatim:

```
* Pricing: Black-Scholes synthetic chain. IV proxy = max(20d realized vol,
  VIX/100 for SPY, 1.10*VIX/100 for QQQ) — NO historical IV surface exists
  in the repo, so this is the documented point-in-time proxy
```

**Every options conclusion in the repo rests on a Black-Scholes chain with IV proxied from realized vol / VIX —
not on real quoted option prices.** That is honest, documented engineering, and it is exactly the gap that a
~$0.05–5 purchase closes.

**Why this matters financially, not just philosophically:** the variance risk premium means **implied vol is
systematically *higher* than realized vol**. A proxy built from `max(20d realized vol, VIX/100)` therefore tends
to **underprice long-premium structures** — so the SPY and QQQ debit-vertical results are likely **optimistic**.
Buying real chains does not just improve the evidence; it is a direct test of whether those results survive.

**Consequence: 13 years of real option chains becomes the #1 data priority in the entire plan** — ahead of
per-contract futures curves, ahead of everything except the futures pilot itself.

---

## §2. Four data domains

| # | Domain | Instruments | Current state | Real cost |
|---|---|---|---|---|
| **1** | **Futures** | MES, MNQ, MCL, MGC, M2K | Continuous caches; per-contract + OI absent | ~$7–13 one-time + $10/mo |
| **2** | **Equity / index options** | SPY, QQQ, AAPL, TSLA, SPX, VIX | **Priced by synthetic proxy; no real chain history** | **~$0.05–5 one-time** + $1.50–$40/mo |
| **3** | **Options ON futures (FOP)** | MES/ES, MNQ/NQ, CL, GC options | **Completely absent from the engine** | $0.50/GB (same dataset) — gate is entitlement + scope |
| **4** | **Equities (underlying)** | AAPL, TSLA, index proxies | Works via free tiers | $0 |

---

## §3. Domain 1 — Futures (MES/MNQ/MCL/MGC/M2K)

| Need | Source | Cost | Status |
|---|---|---|---|
| Deep continuous history (16y, 1m→1d) | **Databento** CME `GLBX.MDP3` | ~$1–2 from the $125 credit | loader **already built** (280 lines + tests) |
| **Per-contract curves + open interest** | Databento (`definition` + `statistics`) | ~$7 est. | needs a new `fetch_contract_curves()` — continuous-only today |
| Local library, per-contract + back-adjusted, OI, ~1980→, no rate limits | **Norgate Futures** | $270/yr ($22.50/mo) | covers MES/MNQ/M2K/MYM since Jun 2019 |
| Real-time L1 | **IBKR** US Snapshot + Futures Value Bundle | $10/mo (waived at $30 commissions) | already have the account |
| Independent live feed | Databento Standard | $199/mo | **defer** |
| One-time alternative | FirstRate (ES ~$29/symbol) | one-time | fallback if you'd rather not subscribe |

**Verdict: domain is solved and cheap.** The only real build is per-contract curves (§6).

---

## §4. Domain 2 — Equity / index options (the actual gap)

| Need | Source | Cost | Note |
|---|---|---|---|
| **13 years of real option chains (2013→)** for the whole watchlist | **Databento OPRA** | **~$0.05–5 one-time** ($0.04/GB floor; 32.7M rows ≈ 1.3 GB) | **Priority #1** — replaces the synthetic proxy |
| Intraday option snapshots (4y, 1-min, incl. **SPX & VIX**) | ThetaData Options Value | $40/mo | daily bars can't model intraday stops/rolls |
| Real-time options L1 | IBKR OPRA Top-of-Book | $1.50/mo (waived at $20–25 commissions) | also clears the 10168 delayed-data error |
| Real-time chains via API | Polygon/Massive — `options/chain_fetcher.py` already calls it | Free Basic / $29 Starter | **`POLYGON_API_KEY` is NOT set** — the real-chain path is dark |
| Pre-computed IV surfaces, SMV greeks, 100+ indicators, **2007→** | ORATS near-EOD backfill | **$599 one-time** | the only route to pre-2013 (the GFC) |
| Options EOD freshness going forward | ORATS $99/mo or Massive Starter $29/mo | monthly | optional |

**Existing code that is ready but dark:** `options/chain_fetcher.py` (`fetch_chain`, `filter_by_delta`,
`find_strike_by_delta`, `get_iv_rank`, `fetch_nearest_expiries`) + `options/_polygon_skew.py` (skew, term
structure, spot) + `data/options_signals/chain_snapshots/`. All require `POLYGON_API_KEY` → currently unset.

**Verdict: the highest-leverage purchase in the plan.** $0.05–5 converts every options result from
proxy-priced to market-priced.

---

## §5. Domain 3 — Options ON futures (absent entirely)

| Fact | Verified |
|---|---|
| JARVIS code handling FOP (futures options) | **NONE** — the only `FuturesOption`/`FOP` matches in the repo are inside the vendored `ib_async` library |
| What exists | `options/chain_fetcher.py` handles equity-style chains only; the watchlist is SPY/QQQ/AAPL/TSLA |
| Data availability | Databento CME Globex includes **"all futures and options on futures"** — 650,000+ symbols, 16y, same **$0.50/GB** |
| What gates it | (a) **IBKR FOP market-data entitlement** — the 354/10168/10197 error class observed on the options path; (b) a scope decision, since no strategy needs it today |

**Why it's worth naming anyway:** a futures system with defined-risk futures-options structures is the natural
risk-managed extension of MES/MNQ trend trading, and the data is already on a dataset you're buying. The
decision is **not** a purchase — it's "do we want this capability," which needs an IBKR entitlement check first.

**Verdict: do not buy data for it. Do check the IBKR entitlement** — the answer is free and it determines
whether the option exists at all.

---

## §6. Domain 4 — Equities (underlying)

| Need | Source | Cost |
|---|---|---|
| Daily/15m bars for AAPL/TSLA/SPY/QQQ | Alpaca free (IEX real-time), Polygon Basic free, yfinance | $0 |
| Intraday bars, point-in-time fundamentals, delisted history | Sharadar / Norgate stocks | $50–100/mo `[ASSUMPTION]` |

**Verdict: free tiers are sufficient until a real equities sleeve exists.**

---

## §7. Revised purchase order

| Priority | Purchase | Cost | Why in this position |
|---|---|---:|---|
| **1** | Databento futures deep pull (continuous) | ~$0 from credit | answers the `INSUFFICIENT_SAMPLE` question (the pilot) |
| **2** | **Databento OPRA — 13y option chains** | **~$0.05–5** | replaces a synthetic proxy with real market prices across all six underlyings |
| **3** | IBKR futures bundle + OPRA L1 | $11.50/mo | real-time L1; mostly commission-waivable |
| **4** | Databento per-contract curves + OI | ~$7 + new code | unlocks calendar/roll/relative-value backtests |
| **5** | Norgate Futures | $22.50/mo | local per-contract library, OI, ~1980→, no rate limits |
| **6** | ThetaData Value | $40/mo | intraday option granularity (path-dependent structures) |
| **7** | ORATS near-EOD 2007 backfill | $599 one-time | only route to pre-2013 options history |
| **8** | Databento Standard | $199/mo | live redundancy — last |

**Total to close every substantive gap through priority 5: ~$34/mo + ~$12 one-time.**
Full steady state including 6: **$74/mo.**

---

## §8. What this changes about the pilot

The pilot in `JARVIS_DATABENTO_PILOT_IMPLEMENTATION_PLAN_v1.0.md` should be widened by one step, at essentially
zero cost:

- **Step 2b (new): pull OPRA daily chains for SPY/QQQ/AAPL/TSLA/SPX/VIX, 2013→present.**
  Expected cost ~$0.05 (up to ~$5 if I'm 100× wrong). Confirm at the estimator first.
- **Step 4b (new): re-run the SPY and QQQ vertical runners on *real* chains** instead of the Black-Scholes
  proxy, and compare verdicts.

**Pre-registered prediction to test:** because implied vol usually exceeds realized vol, real chains should show
the debit verticals buying at richer premiums than the proxy assumed → **results should get worse**. If SPY's
already-REJECTED verdict and QQQ's PASS both survive real chains, that is real evidence. If QQQ's PASS collapses,
the pilot has paid for itself before a single subscription.

---

## §9. Bottom line

- **Futures data:** solved and cheap. ~$7–13 one-time + $10/mo.
- **Equity/index options data:** **the real gap** — the system's options evidence is proxy-priced, and real
  chains cost about as close to nothing as a data purchase can get (~$0.05–5 for 13 years).
- **Options on futures:** absent from the engine, available on a dataset you're already buying, gated by an IBKR
  entitlement you should check for free.
- **Equities:** free tiers are enough.
- **The whole four-domain picture fits in $34–74/mo** plus ~$12–$612 of optional one-time purchases.

---

*Nothing purchased or provisioned. All prices read from vendor pages in September 2026 and must be confirmed at
the estimator/checkout. No credentials read or written; no live-trading, risk, kill-switch, broker-routing, or
symbol-gate change was made or proposed.*
