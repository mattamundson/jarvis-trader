# Data Budget Allocation at $100–200/mo (v1.0)

**Authored:** 2026-09-23 · **Status:** ANALYSIS ONLY — nothing purchased or wired.
**Supersedes the "spend as little as possible" framing** in `JARVIS_MARKET_DATA_TIERS_v2.0.md`.
**Correction acknowledged:** I optimized for minimum spend because that was the original brief. Given a
$100–200/mo ceiling, the optimum changes — and this document recomputes it.

---

## §1. The finding that changes the answer

**Databento publishes OPRA (US equity options) historical data at `$0.04/GB` — 12.5× cheaper per GB than CME
futures (`$0.50/GB`), against the same `$125` signup credit.**

Arithmetic for the full JARVIS options watchlist, 13 years (2013→2026), daily option-chain bars:

| Underlying | Distinct contracts (est.) | Rows | GB @ 40 B | Cost @ $0.04/GB |
|---|---:|---:|---:|---:|
| SPY | 150,000 | 9,000,000 | 0.36 | $0.01 |
| QQQ | 120,000 | 7,200,000 | 0.29 | $0.01 |
| AAPL | 120,000 | 7,200,000 | 0.29 | $0.01 |
| TSLA | 90,000 | 5,400,000 | 0.22 | $0.01 |
| SPX | 40,000 | 2,400,000 | 0.10 | $0.00 |
| VIX | 25,000 | 1,500,000 | 0.06 | $0.00 |
| **Total** | | **32,700,000** | **1.31** | **$0.05** |

**Sensitivity — how wrong can this be before it matters:**

| Error multiple | Size | Cost | vs ThetaData Value ($480/yr) |
|---|---:|---:|---|
| 1× (estimate) | 1.3 GB | $0.05 | 9,600× cheaper |
| 10× | 13.1 GB | $0.52 | 920× cheaper |
| 100× (absurdly pessimistic) | 130.8 GB | $5.23 | 92× cheaper |

**Conclusion:** for *historical* options research, the subscription providers are not competitive on price.
What they actually sell is **intraday granularity, real-time access, and ongoing freshness** — not history.

---

## §2. What money buys here, and what it doesn't

| Money **can** buy | Money **cannot** buy |
|---|---|
| Options history across multiple vol regimes | The campaign trial ledger (code, must exist) |
| Per-contract futures curves + open interest | Honest OOS accounting |
| Intraday granularity instead of daily | PIT discipline in the store |
| Real-time L1 and a second live feed | A single verdict authority |
| Pre-computed surfaces and greeks (ORATS) | **A reason to believe** — that's what the pilot measures |

The binding constraint remains **whether the Judge can certify an edge**. So the allocation principle is:
**spend on the two things money genuinely buys (cross-regime options depth, per-contract futures structure);
refuse to spend on anything that does not move the Judge.**

---

## §3. Recommended allocation inside $100–200/mo

### Phase 1 — Steady state: **$74/mo**

| Line | $/mo | What it actually buys | Why it's worth it |
|---|---:|---|---|
| IBKR US Snapshot + Futures Value Bundle | $10.00 | Real-time futures L1 | Cheapest real-time futures in existence; **waived at $30/mo commissions** |
| IBKR OPRA Top-of-Book L1 | $1.50 | Real-time options L1 | Waived at $20–25 commissions; also clears the 10168 delayed-data error |
| ThetaData Options Value | $40.00 | 4y of **1-minute** option snapshots, real-time, **incl. SPX & VIX** | The non-substitutable piece: intraday option path-dependence (stops, rolls) cannot be modelled on daily bars |
| Norgate Futures Package | $22.50 | ~100 futures markets, individual contracts + back-adjusted continuous, **daily open interest**, ~1980→, local, no rate limits | Removes per-pull costs and rate limits from the research loop; OI in a convenient local form |
| **Total** | **$74.00** | | **$888/yr** — well inside the ceiling |

### Phase 2 — Conditional one-time purchases (buy only when the sleeve is real)

| Line | Cost | What it buys | When to buy |
|---|---:|---|---|
| **ORATS near-EOD backfill 2007→present** | **$599 one-time** | Options history **through the GFC**, with smoothed-market-value greeks, IVs, and 100+ proprietary indicators (~500 GB) | When a vol sleeve is funded and needs pre-2007-inclusive regime coverage. **Roughly 5 months of the $99/mo recurring alternative** |
| ORATS near-EOD recurring | $99/mo | Continuing daily updates | Only if forward tests need daily freshness — otherwise refresh from Databento OPRA in batches |
| FirstRate per-symbol futures one-time | ~$29–200 each | Alternative to Norgate if you prefer one-time over subscription | Only if you'd rather not subscribe |
| **Databento Standard** | **$199/mo** | Live + 16y L0 + 1y L1 + 1mo L2/L3, and the gateway to unlimited historical pulls | **Last thing you buy.** It buys redundancy and throughput, not measurement |

### The whole budget, deployed

```
Always:            Databento (usage, ~$10-30 one-time from the $125 credit)   -> futures + options history
Steady state:      $74/mo   IBKR 11.50 + ThetaData 40 + Norgate 22.50
Reserve:           $100/mo  untouched — enough to add Databento Standard or ORATS recurring
                   on a month's notice, or to buy ORATS backfill ($599) in a single month
```

Total committed cash in year 1: **~$888 + ~$30 one-time = ~$918**, with ~$300–$1,000 of optional capacity
deliberately unspent until a measurement justifies it.

---

## §4. Revised tier table (superseding the "spend minimum" version)

| Config | $/mo | What it adds over the previous | Verdict |
|---|---:|---|---|
| **A. $0** | $0 | Databento credit → deep per-contract futures history **and** 13y options chains; free tiers; IBKR delayed | The **pilot** configuration. Run this first — it answers whether certification is even possible |
| **B. $11.50** | $11.50 | Real-time futures + options L1 | The minimum viable *operating* configuration |
| **C. $74** | $74.00 | + intraday options (ThetaData) + local per-contract/OI/40y (Norgate) | **Recommended steady state** |
| **D. $173** | $173.00 | + ORATS recurring daily options EOD with SMV greeks | Justified once the vol sleeve runs daily forward tests |
| **E. $261–$372** | $261+ | + Databento Standard live (or ORATS backfill amortized) | Only for live redundancy or heavy research throughput |

**Recommended: A → B → C**, with D and E held in reserve.

---

## §5. What I would *not* buy even with the budget

| Rejected | Why |
|---|---|
| ORATS 1-minute intraday (**$199/mo + $1–2k S3 storage/transfer**) | The S3 footnote turns a $199/mo plan into a multi-thousand-dollar exercise; ThetaData at $40/mo covers the same need |
| Databento Plus ($1,750) / Unlimited ($4,500) | Prices venue-scale volume JARVIS will never consume |
| Market-by-order (L3) | Hundreds of GB for a microstructure thesis that doesn't exist |
| CME DataMine + redistribution licence | Licensing is for a product; productization is not the goal |
| Polars/ArcticDB activation | Already benchmarked at **2× slower** at current sizes (2026-08-04). Re-test after the data grows 10× |
| Anything commodity | `amo-arbitrage`'s mandate |

---

## §6. Does this make the *sequencing* different? Partly.

The pilot still goes first, for a sharper reason than before:

- It is now **even cheaper** than I said — the $125 credit covers futures *and* options, so Phase A is
  essentially free.
- It still answers the only question that matters: **can the Judge certify anything?**
- But with a real budget, there is now a legitimate case for **running Phase B/C in parallel** rather than
  serially, because sequential waiting has a cost the earlier analysis ignored: **calendar time**.

**Revised sequencing:** run the pilot (Phase A) and wire the $11.50 IBKR lines immediately — the IBKR lines are
trivial, ongoing, and useful regardless of the pilot's outcome. Hold the $40 + $22.50 subscriptions until the
pilot reports (they buy *intraday* and *convenience*, not answers). Hold ORATS and Databento Standard until a
sleeve exists that fails without them.

**The one thing the budget genuinely improves:** it removes the "can we afford this?" question from every
research decision, which lets the pilot's outcome drive the next move instead of price.

---

*Nothing purchased or provisioned. The $0.04/GB OPRA figure and $599/$99/$199 ORATS figures were read from
vendor pages in September 2026 and must be confirmed at the estimator/checkout before any purchase. No
credentials read or written; no safety surface touched.*
