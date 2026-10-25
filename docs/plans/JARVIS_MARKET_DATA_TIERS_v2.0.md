# JARVIS Market Data — Tiered Comparative Analysis (v1.0)

**Authored:** 2026-09-23 · **Status:** ANALYSIS ONLY — nothing purchased, subscribed, or wired.
**Question answered:** *"Spend as little as possible on market data with the most upside — what are the tiers,
what do we get, what does each cost?"*
**Companion to:** `JARVIS_REBUILD_DATA_INFRA_PROCUREMENT_v2.0.md` (this is the costed, decision-ready version of it)

> **Pricing caveat, stated up front.** Every price below was read from the vendor's own page in **September 2026**
> unless marked otherwise. Prices marked `[ASSUMPTION]` are my estimates **with the method shown** — not quotes.
> Verify before purchase: vendor pricing is usage-tiered, negotiated, and has moved several times in 2026
> (Databento raised plan prices in June 2026; Cboe changed quote-size semantics in June 2026).

---

## 0. Bottom line

> **PARTIALLY SUPERSEDED (2026-09-23):** this document was written to a *"spend as little as possible"* brief.
> Given a **$100–200/mo** ceiling the optimum changes — see `JARVIS_DATA_BUDGET_ALLOCATION_100-200_v1.0.md`.
> The key revision: **Databento prices OPRA (equity options) historical data at $0.04/GB** (12.5× cheaper than
> CME futures), so 13 years of option chains for the whole watchlist costs cents — meaning the subscription
> options vendors are not price-competitive for *history*. They sell intraday + real-time + freshness.
> The tier logic below still holds; the **options-history** recommendation is now "buy it from Databento."

**The two gaps that actually block the rebuild are closable for $0.**

| Gap | Current state | Cheapest real fix | Cost |
|---|---|---|---|
| **Per-contract curves + Open Interest** (calendar, roll, relative-value backtests are structurally impossible today) | Only `{SYM}_CONT_ADJ` continuous series exist | Databento historical pay-as-you-go using the **$125 signup credit** | **$0** (est. usage ~$7–13) |
| **Options surface** (QQQ/AAPL/TSLA trade with **no verdict on file**; SPY trades on a REJECTED one) | No options history at all; IBKR entitlement-blocked | ThetaData **FREE** tier (1y EOD) + Massive/Polygon **Options Basic FREE** (2y daily) | **$0** |

Then, and only then, **$11.50–34/mo** buys real-time + a comfortable local history library. Everything above
~$100/mo is deferrable until a sleeve exists that can consume it.

**Recommended path: T0 → verify → T1 (optional Norgate) → T2 only when the vol sleeve is funded.**

---

## 1. What you already own (marginal cost $0)

| Asset | State | Evidence |
|---|---|---|
| IBKR account (paper) | Live, port 4002, `ib_async` installed | `engine/.env` has `IBKR_*`; engine connects |
| Wired vendor keys | **None** for market data — no Polygon, Databento, Alpaca, Finnhub, FRED, Schwab | verified key-by-key in `engine/.env` |
| LLM keys | Anthropic, OpenAI, Google, Moonshot, Vertex | present |
| Local history | **140 MB** of per-symbol CSVs in `engine/backtest/cache` (ES/NQ/M2K/CL/GC/DIA/IWM/GLD + more), 7.3 GB `engine/data` | directory listing |
| Free ingest paths already in code | `finnhub`, `praw` (Reddit), `fredapi`, `yfinance`, TradingView CDP, Discord | installed + imported |
| Adapters already written | `polygon` client, `alpaca`, `databento_adapter.py`, `databento_loader.py`, `export_ibkr_history.py` | installed / in repo |

**Implication:** wiring a new vendor is an **env key + an adapter run**, not a new subsystem. The `databento`
client library is the one missing piece (`databento` package not installed; adapter code exists).

---

## 2. The tier table

| Tier | $/mo | $/yr | What you get | What it unlocks | Verdict |
|---|---:|---:|---|---|---|
| **T0 — Truth floor** | **$0** | **$0** | Databento $125 signup credit (historical), ThetaData FREE (1y EOD options+stocks), Massive Options Basic FREE (2y daily), Alpaca FREE (IEX real-time), IBKR delayed toggle, FRED/CFTC/Cboe public/yfinance | **Per-contract minute bars + OI for all 5 micros, 2010→present**; daily options chains for the watchlist; equities daily — i.e. *both blocking gaps closed* | **DO THIS FIRST** |
| **T1 — Trader floor** | $34.00 | $408 | IBKR US Snapshot + Futures Value Bundle $10; IBKR OPRA Top-of-Book L1 $1.50 (both commission-waivable); Norgate Futures $270/yr (=$22.50/mo) | Real-time futures L1 + options L1; **~100 futures markets with individual contracts + back-adjusted continuous + Open Interest, back to ~1980**, stored locally, no rate limits | **DO THIS** (Norgate optional but the best $22.50 in the list) |
| **T2 — Research grade** | $106.33 | $1,276 | T1 + ThetaData Options Value $40 (4y, 1-min snapshots, **incl. SPX & VIX**) + Massive Options Starter $29 (all contract history) + Databento top-up usage | **Intraday options surface** → real options verdicts instead of the current accepted blind spot; intraday vol/term-structure/skew research | **When the vol sleeve is funded** |
| **T3 — Production-adjacent** | $290.50 | $3,486 | Databento Standard $199 (live + 16y L0, 1y L1) + IBKR bundle $11.50 + ThetaData Standard $80 (8y, tick, NBBO) | Live feed **independent of IBKR** (removes a single point of failure); NBBO for honest fill/slippage modelling | **Defer** — paper-only system with a working IBKR leg does not need a second live feed |
| **T4 — Institutional** | ~$5,899 | ~$70,788 | ORATS All-In $899 + Cboe DataShop/OptionMetrics (~$500, `[ASSUMPTION]`) + Databento Unlimited CME $4,500 | Smoothed IV surfaces, full OPRA tick archive, exchange-direct per-contract OI, redistribution rights | **Not justified now** — the Judge cannot consume it yet |

---

## 3. The arithmetic that changes the answer

Databento bills historical data **pay-as-you-go at a published floor of $0.50/GB**, needs **no subscription**, and
gives **$125 in free credits on signup**. So the relevant question is: how many GB is JARVIS's futures research set?

Method (shown so you can check it): 23-hour Globex session × 60 min × 252 sessions = **347,760 bars/symbol-year**.

| Dataset | Size estimate | Cost at $0.50/GB | Inside $125 credit? |
|---|---:|---:|---|
| Continuous minute bars, 5 micros + 5 full-size, 16y | **2.2–3.3 GB** | **$1.11–1.67** | ✅ easily |
| **Per-contract minute bars** (~6 active delivery months × 10 products × 16y) | **13.4 GB** | **$6.68** | ✅ easily |
| CME statistics (settlement, volume, **open interest**) | ~1 GB | ~$0.50 | ✅ |
| BBO / mbp-1, 10 symbols × 5y (wide uncertainty) | 25–150 GB | $12.50–75.00 | ✅ still inside |
| Market-by-order (L3) — the expensive one | hundreds of GB | $100s+ | ❌ skip |

**Conclusion:** the *entire* futures research dataset JARVIS needs — per-contract minute bars, open interest,
and even BBO for a few years — lands **inside the $125 signup credit**. The first meaningful decision on
market data spend can legitimately be **"spend nothing."**

**Caveats (do not skip):**
1. Databento bills on **their** measured compressed size, and may apply minimum per-request charges. My figures
   are arithmetic estimates, **not a quote**. Run their in-page price estimator before requesting.
2. BBO volume varies enormously by product (0.5–3 GB/symbol-year is a wide band) — that is the real uncertainty.
3. The $199 Standard subscription buys **live** data, not history. History does not require it.

---

## 4. Cheapest path to each specific unlock

| Unlock | Cheapest source | $/mo | Notes |
|---|---|---:|---|
| Daily-bar futures verdicts (MES/MNQ/MCL/MGC/M2K) | Databento $125 credit (or a Norgate free trial) | **$0** | Enough to run CPCV/DSR/PBO honestly |
| **Per-contract curves + Open Interest** | **Norgate Futures $270/yr** | **$22.50** | Individual contracts + back-adjusted continuous, OI daily, ~1980→, local files, no rate limits |
| Minute-bar per-contract history 2010→2026 | Databento credit | **$0** | ~$7–13 est. usage |
| Real-time futures L1 | IBKR futures bundle | **$10** | Waived at $30/mo commissions |
| EOD options chains 1–2y (closes the QQQ/AAPL/TSLA verdict gap at daily resolution) | ThetaData FREE + Massive Options Basic FREE | **$0** | Note: Massive Basic **withholds SPX/DJI/RUT/VIX** |
| **13 years of option chains (2013→)** for the whole watchlist | **Databento OPRA** (usage) | **~$0.05–5 one-time** | $0.04/GB floor — 32.7M rows ≈ 1.3 GB. Supersedes the subscription options below for *history* |
| **Intraday options surface incl. SPX & VIX** | ThetaData Options Value | **$40** | 4y, 1-min snapshots, real-time — the non-substitutable piece (daily bars can't model intraday stops/rolls) |
| Options history through the GFC, with SMV greeks + 100+ indicators | ORATS near-EOD backfill | **$599 one-time** | 2007→, ~500 GB; ≈5 months of the $99/mo recurring alternative |
| Options tick/NBBO for honest fill modelling | ThetaData Options Standard | **$80** | 8y, full NBBO quotes |
| Live feed independent of IBKR | Databento Standard | **$199** | Only worth it if IBKR reliability is the binding problem |
| Longer futures history for regime studies (~1980→) | Norgate | included in T1 | Full-size contracts available; micros since Jun 2019 |

---

## 5. Vendor detail (verified 2026-09 unless noted)

### Futures
| Vendor | What it is | Price | Covers the micros? |
|---|---|---|---|
| **IBKR** | Broker feed, real-time L1 | US Snapshot + Futures Value Bundle **$10/mo** (waived at $30 commissions) | Yes (MES/MNQ/MCL/MGC/M2K) |
| **Norgate Futures** | Local history library, individual contracts + continuous (unadj + back-adj), OHLCV + **OI**, settlement prices | **$270/yr** ($148.50/6mo) | **Yes — MES, MNQ, M2K, MYM since Jun 2019**, plus ES/NQ/RTY/CL/GC and ~100 markets |
| **Databento** | API + flat files, CME/CBOT/NYMEX/COMEX futures **and options on futures**, 650k+ symbols, 16y+ | Usage-based **from $0.50/GB**, no subscription; **$125 free credit**; Standard **$199/mo** (live) | Yes (all CME micros) |
| **FirstRate Data** | One-time purchase, 122 futures tickers, 1m/5m/30m/1h + daily, individual contracts + 3 continuous variants | one-time per dataset or "Most Active Futures Bundle"; updates ~**$60–100/mo** after 1 free month; exact prices JS-rendered (**not verified**; ES reported ~$200 one-time, unconfirmed) | MES/MNQ/M2K sold individually; **MGC/MCL only in the bundle** |
| **CME direct (non-pro)** | Exchange list price, for reference | Top-of-Book **$1.55/mo** per exchange, all-exchange bundle **$4.65**; Depth **$12.10**/exchange, **$36.50** bundle | n/a (venue price) |

### Options
| Vendor | What it is | Price | Index options (SPX/VIX)? |
|---|---|---|---|
| **ThetaData** | Per-contract greeks/IV, tick + NBBO; also indices and rates (SOFR/Treasuries 30y) | **FREE** (1y EOD stocks+options, 20 req/min) · Value **$40/mo** (4y, 1-min snapshots) · Standard **$80/mo** (8y, tick, full NBBO) · Pro **$160/mo** (12y, full stream) | **Yes — docs explicitly include SPX and VIX** (NDX needs Pro) |
| **Polygon / Massive** | Options chains + ticks | Basic **FREE** (2y, daily) · Starter **$29/mo** (all contract history, daily) · Developer **$79/mo** (second aggregates) · Advanced **$199/mo** (tick, real-time greeks/IV) | Yes, **but Basic withholds SPX/DJI/RUT/VIX** — needs a paid tier |
| **ORATS** | Smoothed IV surfaces, 100+ indicators, near-EOD since 2007, 1-min intraday since Aug 2020 | Delayed **$199/mo** (20k req) · Live **$299/mo** · Live Intraday **$599/mo** · All-In **$899/mo**. ⚠️ a second source lists $99/$199/$399 — **verify directly** | Yes |
| **Cboe DataShop** | Exchange-direct historical: Option EOD Summary, Option Quotes, Option Trades, CFE Futures Trades | Per-dataset/per-query e-commerce; secondary source says institutional sets "from ~$500/mo" `[ASSUMPTION]` | Yes (it *is* the SPX/VIX venue) |
| **Alpaca** | Broker feed incl. OPRA options | Free (IEX real-time, 15-min delayed SIP, 200 rpm) · Algo Trader Plus **$99/mo** (SIP real-time + OPRA + 10k rpm) | n/a |

### Equities
| Source | Price | Note |
|---|---|---|
| Alpaca free | $0 | IEX real-time; 15-min delayed SIP |
| Polygon/Massive stocks Basic | $0 | 5 req/min |
| yfinance | $0 | already installed; fine for daily/15m research |
| Sharadar / Norgate stocks | $50–100/mo `[ASSUMPTION]` | point-in-time fundamentals + delisted history — **only worth it for a real equities sleeve** |

---

## 6. Recommended sequence (spend nothing until each step is verified)

1. **Wire Databento with the $125 credit.** `pip install databento`, add `DATABENTO_API_KEY` to `engine/.env`,
   run the existing `databento_adapter.py` against the micro complex. **Run their estimator first**; pull
   `ohlcv-1m` + `statistics` (settlement/volume/**open interest**) for MES/MNQ/MCL/MGC/M2K **per contract** plus
   continuous, 2010→present. Expected usage: **$7–13**. → *per-contract curves + deep history, $0.*
2. **Enable the free tiers** — IBKR delayed toggle (clears error 10168), ThetaData free (1y EOD options),
   Massive Options Basic free (2y daily), Alpaca free. → *daily options chains for the watchlist, $0.*
3. **Run the Judge on what you now have.** Per-contract relative-value and daily-bar futures verdicts become
   possible for the first time. If the Judge produces something worth sizing, continue; if not, **stop spending.**
4. **Then T1 ($11.50/mo, + $22.50/mo optional):** IBKR futures bundle + OPRA L1 for real-time; Norgate if you
   want a local, rate-limit-free library with back-adjusted continuous series and 40 years of history.
5. **T2 only when the vol sleeve is funded** ($40 ThetaData Value, +$29 Massive Starter). Intraday surface is
   the prerequisite for a real options verdict, and nothing above T2 is justified before that.
6. **Never** buy T3/T4 until a sleeve exists that fails *because* the data is insufficient — and you can name
   the specific measurement that fails.

---

## 7. What not to buy

| Don't buy | Why |
|---|---|
| Databento Unlimited ($4,500/mo) / Plus ($1,750/mo) | Prices the wrong thing — JARVIS needs *coverage*, not venue-scale volume |
| Market-by-order (L3) | Hundreds of GB; no microstructure thesis in the plan |
| ORATS All-In ($899/mo) before the vol sleeve exists | Smoothed surfaces are a *refinement* of raw chains you don't have yet |
| CME DataMine + redistribution licence | Licensing is for a product; **productization is not a goal** (single-operator mandate) |
| A second live feed (Databento Standard $199) while IBKR works | Solves a reliability problem you can solve for $10/mo with the IBKR bundle |
| Per-seat or multi-user plans | One operator, one account |
| Anything commodity-related | That is **amo-arbitrage's** mandate, not JARVIS's |

---

## 8. Pre-purchase verification checklist

```
[ ] Run the vendor's own price estimator for the exact symbol/schema/date range (Databento's is on their pricing page)
[ ] Confirm the vendor covers the exact symbols: MES, MNQ, MCL, MGC, M2K (micros), SPY/QQQ/AAPL/TSLA + SPX/VIX (options)
[ ] Confirm historical depth >= the CPCV window you need (10y realistic; 16y available at Databento)
[ ] Confirm Open Interest is included if per-contract curves are the goal
[ ] Confirm internal-use-only licensing is sufficient (no redistribution needed)
[ ] Confirm cancel-anytime / no lock-in
[ ] Confirm the adapter exists or is <= 1 day of work (databento adapter exists; others may not)
[ ] Name the measurement this purchase unblocks — if you cannot name it, do not buy
```

---

## 9. Open uncertainties (be honest about what I could not verify)

1. **Databento's billed size** for JARVIS's exact pull — estimator required; my $7–13 is arithmetic, not a quote.
2. **FirstRate Data's current prices** — JS-rendered, not in the HTML; the ~$200 ES figure is a Reddit report.
3. **ORATS pricing** — two sources disagree ($99/$199/$399 vs $199/$299/$599/$899); rechecked-date source says the
   latter. Verify before deciding.
4. **Norgate intraday availability for the micros** — the package documents **daily** OHLCV + OI; intraday
   minute bars for micros are **not confirmed** (FirstRate and Databento are the intraday paths).
5. **Cboe DataShop** is per-dataset and quote-based; treat the ~$500/mo figure as `[ASSUMPTION]`.
6. **Databento options-on-futures** (for a future futures-options sleeve) is *available* on the same platform —
   not costed here because JARVIS's options mandate is equity-index options.

---

*Nothing was purchased, subscribed, or provisioned. No credentials were read or written. No live trading, risk,
kill-switch, broker-routing, or symbol-gate change was made or proposed for immediate execution.*
