# JARVIS Rebuild — Data, Compute & Infrastructure Procurement (v2.0)

**Authored:** 2026-09-23 · **Status:** PLANNING ONLY — nothing purchased, provisioned, or subscribed.
**Companion to:** `JARVIS_REBUILD_BLUEPRINT_v2.0.md`, `JARVIS_REBUILD_WORK_BREAKDOWN_v2.0.md`

> **Every cost below is a planning estimate (`[ASSUMPTION]`)** and requires a vendor quote. Data pricing is
> negotiated, usage-tiered, and differs by an order of magnitude between *internal use* and
> *redistribution*. Treat these as budget bands for a decision, not as offers.

**Procurement law:** nothing is bought until the thing that will *measure* it exists. In this system that
means the trial ledger and the Judge (P4) come before any data purchase, because unlogged trials make
deflation a lie and data without a harness is expensive noise.

---

## 0. What JARVIS actually trades (so procurement stays honest)

**Scope fence:** JARVIS is **futures + options + equities**. Commodities (ag/energy curves, WASDE vintages,
weather ensembles, satellite imagery) are **`amo-arbitrage`'s mandate, not JARVIS's** — do not buy them here.

| Class | Instruments | Current state |
|---|---|---|
| Index/rates futures (micro) | MES (active paper), MNQ / MCL / MGC / M2K (blocked) | MES 1h SMA-trend only |
| Equity-index options | SPY, QQQ (watchlist), SPX / VIX (research) | **No verdicts on file for QQQ/AAPL/TSLA; SPY REJECTED but trading** |
| Equities | AAPL, TSLA (optionable watchlist names) + whatever an equities sleeve validates | Trading in paper with **no verdict on file** |
| Crypto | BTC/ETH (research, isolated) | Explicitly non-core |
| Prediction markets | Polymarket (research, isolated) | Explicitly non-core |

Procurement follows *this* list. Buying ag/energy curves, weather ensembles, or satellite imagery for a
system that trades MES, SPY options and AAPL/TSLA is how budgets die — and those purchases belong to
amo-arbitrage's own shopping list.

---

## 1. Priority order (by ROI, not glamour)

| # | Buy | Why it is first | Unblocks |
|---|---|---|---|
| 1 | **Deep continuous futures history** (MES/MNQ/MCL/MGC/M2K, 1m→1d, 10+ years) | Everything in the Judge depends on it; current caches are hand-built and per-symbol | P2, P4 — honest CPCV/PBO for the futures sleeve |
| 2 | **Per-contract-month curves** (settlement, volume, OI per delivery) | Structurally impossible today because only `{SYM}_CONT_ADJ` exists | Roll yield, calendar spreads, honest execution modelling (P2-5, P7-4) |
| 3 | **Options surface history** (SPY/QQQ/SPX/VIX: IV, greeks, OI by strike) | The options sleeve currently trades **without verdicts** — this is the gap | P7-3: real options verdicts instead of an accepted blind spot |
| 4 | **Point-in-time macro/event data** (CPI, payrolls, FOMC, vintages) | Cheap, and retroactively protects every event study | Macro/event sleeve, market brief honesty |
| 5 | **Intraday microstructure** (volume profile, depth where affordable) | Needed for the intraday auction sleeve | P7-2 |
| 6 | **Positioning/flow** (CFTC, ETF flows) | Free-to-cheap, high signal-to-noise for regime | Regime conditioning |
| 7 | **News/sentiment** | Already partly present (Finnhub/Reddit/Discord) | `/intel`, evidence chips |
| 8 | **Compute & observability** | Only after the above; compute is not the constraint | P1, P8 |

---

## 2. Market data

### 2.1 Futures — deep history + per-contract

| Vendor | Content | Notes | Est. annual `[ASSUMPTION]` |
|---|---|---|---|
| **Databento** | CME Globex historical + live, MBO/MBP/trades/bars, per-contract | Best API ergonomics; pay-per-use; the pragmatic first purchase | usage-based, **$2k–$30k** |
| **CME DataMine (direct)** | Settlement, volume, OI per contract month, full history | Canonical source; redistribution licence is separate and expensive | **$15k–$60k** internal |
| **Barchart / ICE / Refinitiv / Bloomberg** | Broad curves + depth | Overkill for 5 micros; justified only if breadth expands | **$25k–$150k+** |
| **IBKR (current)** | Real-time front-month-ish, via local Gateway | Free with account; **cannot** supply historical per-contract OI | **$0** |
| **Existing local caches** | What the repo already built | Keep as a cross-check, never as the primary | $0 |

**Minimum viable purchase:** per-contract settlement + volume + OI for MES/MNQ/MCL/MGC/M2K, plus 1-minute
continuous history 10+ years, delivered as immutable raw files. That single purchase converts the futures
research plane from "hand-built caches per symbol" to a real lakehouse.

### 2.2 Equities / index (options underlyings and the equities sleeve)

| Vendor | Content | Est. annual `[ASSUMPTION]` |
|---|---|---|
| **Polygon.io** | Equities + options aggregates, already a dependency (`polygon-api-client`) | **$200–$3k** (tier-dependent) |
| **Alpaca** | Paper data + paper execution (already a dependency) | **$0** |
| **IEX / Nasdaq Basic** | Alternative equity feeds | **$1k–$12k** |
| **Sharadar / Norgate** | Point-in-time equity fundamentals + survivorship-bias-free history | **$500–$5k** |
| **EDGAR (edgartools)** | Filings — already flagged as an optional dep | free |

### 2.3 Options surface (the gap that matters most)

| Vendor | Content | Notes | Est. annual `[ASSUMPTION]` |
|---|---|---|---|
| **ORATS** | EOD + intraday IV, greeks, skew, term structure, backtests | Best fit for a systematic vol sleeve | **$5k–$50k** |
| **CBOE DataShop** | Index/equity options history, VIX family | Authoritative for SPX/VIX | usage-based |
| **OptionMetrics IvyDB** | Institutional standard, deep history | Priciest; academic-grade | **$30k–$100k+** |
| **CME FOP settles + OI** | Futures options by strike | Bundled with DataMine licensing | licence-dependent |
| **IBKR live chain** | Current path | **Entitlement-blocked** (errors 354 / 10168 / 10197) — account action, see §7 | small subscription |

**Recommendation:** enable IBKR **delayed** data now (free, clears 10168 immediately), buy **CBOE DataShop
or ORATS** for history when the vol sleeve is funded, and treat live options execution data as a
*separate* entitlement decision.

### 2.4 Macro, fundamentals, positioning

| Source | Content | Cost |
|---|---|---|
| **FRED** | Rates, macro series (already a dependency) | free |
| **BLS / BEA / Census** | CPI, payrolls, GDP | free |
| **CME FedWatch / FOMC calendar** | Rate expectations, event dates | free |
| **CFTC** (disaggregated + TFF) | Managed money, producer/merchant positioning | free |
| **Nasdaq Data Link / Quandl** | Convenience wrappers | $0–$5k |
| **Vintage/revision vendor** | "As originally published" macro history | **$10k–$50k** |

**Action with no cost:** start snapshotting every macro release *as published* today, with `vintage_ts`.
You cannot buy this back retroactively if you never captured it.

### 2.5 News, sentiment, alternative

| Source | Content | Cost |
|---|---|---|
| **Finnhub** | News + sentiment (already a dependency) | free tier |
| **Reddit (praw)** | WSB/retail sentiment (already a dependency) | free |
| **Discord (own channels)** | Corey commentary, alerts (already ingested) | free |
| **TradingView CDP** | Chart/level context (already integrated) | free with account |
| **X/Twitter** | Bookmarks pipeline (already built) | free/paid tier |
| **Gdelt / NewsAPI / Benzinga** | Broader news coverage | $0–$10k |

---

## 3. Compute & infrastructure

| Need | Option | Est. cost `[ASSUMPTION]` |
|---|---|---|
| **Trading plane host** (dedicated Linux, UPS, wired) | Mini-PC (e.g. 8-core/32 GB) purchased once, or small cloud VM | **$700–$2k one-off** / **$20–$120/mo** |
| **Research plane burst** | Spot CPU instances + optional GPU for ML | **$50–$400/mo** |
| **Object storage (immutable RAW)** | Cloudflare R2 / S3 | **$10–$200/mo** |
| **Postgres + TimescaleDB** | Self-hosted on the trading host; managed later | **$0** / **$200–$2k/mo** managed |
| **Redis** | Self-hosted (already present) | $0 |
| **Observability** | Grafana Cloud free tier → paid; or self-hosted | **$0–$1.5k/mo** |
| **CI** | GitHub Actions (currently blocked by billing) | **$0–$100/mo** |
| **Backup** | Off-box object storage + PITR | **$10–$100/mo** |
| **Network ingress** | Tailscale (already used) + DNS | **$0–$50/mo** |

**Note on the current machine:** 14 cores / 33.8 GB / **9.6 GB free disk** with every plane colocated. The
trading-plane host purchase is the single highest-value infrastructure dollar in this document, because it
converts a contention-prone shared box into an isolated, supervised, restart-safe unit.

---

## 4. Software (mostly free; the cost is integration)

| Need | Choice | Cost |
|---|---|---|
| Backtest engine | **NautilusTrader** (already partially present) + **vectorbt** for sweeps | free (engineering cost) |
| Research compute | Polars + DuckDB + Parquet | free |
| Orchestration | Prefect / Dagster (self-hosted) or APScheduler hardened | free / $500–$3k/mo managed |
| Experiment tracking | MLflow or a registry table in Postgres | free |
| Feature store | Feast or a PIT table contract | free (engineering) |
| LLM providers | Anthropic / OpenAI / Gemini / local (already multi-provider) | **$3k–$30k/yr** |
| Embeddings/RAG | Voyage (already used) + Chroma (already used) | $0–$5k |

---

## 5. Cost model (year 1, indicative)

| Aspect | Band `[ASSUMPTION]` | Share |
|---|---|---|
| Market data (futures deep + curves + options surface) | $25k–$150k | ~55–75% |
| Reference/alt data (macro vintages, positioning, news) | $5k–$60k | ~10–25% |
| Infrastructure (host, burst, storage, observability, CI) | $6k–$40k | ~10–20% |
| LLM inference | $3k–$30k | ~5–15% |
| **Labor** | **$0** | **No labor line.** JARVIS is a single-operator personal system: build and upkeep are agent loops, and Amo's hours are the calendar constraint, not a cost |
| **Total year 1 (cash)** | **~$40k–$280k** | 100% external services |

**Correction on the record — two superseded passes, disclosed.** The first pass priced "people" at
**$250k–$600k (2 FTE)**; the second "corrected" it to **$25k–$195k of contracted build labor**. Both were
wrong for the same reason: **they priced labor at all.** This is a personal, single-operator system — there
is nobody to hire and no salary line. The 78-task count legitimately measures **required attention**
(73 `[AUTO]` tasks + 11 operator gates), and attention is expressed in hours, not dollars.

**The honest reading:** money buys exactly one thing here — **resolution** (data). It does not buy conviction,
and it does not buy the build. The binding constraint remains credible, cost-surviving, forward-confirmed
edge, which is gated by the Judge, not by a subscription.

---

## 6. What NOT to buy yet (and why)

| Tempting | Verdict | Reason |
|---|---|---|
| Satellite imagery / weather ensembles | **No** | No agricultural exposure in the traded universe |
| Level-2 depth for every instrument | **No** | Only the intraday sleeve needs it, and only after that sleeve is funded |
| Tick data at full retention | **No** | Store bounded windows; ticks are a cost sink without a microstructure thesis |
| GPU cluster | **No** | The ML in this system is tabular/light; burst spot is enough |
| A second broker integration | **Not yet** | One working, reconciled broker beats three half-integrated ones |
| Managed everything (K8s, service mesh) | **No** | One host, three containers, systemd. Complexity is a risk multiplier on a safety-adjacent system |
| Public-facing data product | **Not yet** | Redistribution licensing is a six-figure conversation and **productization is not a goal** — it would be a separate project |
| Anything assuming multiple users | **No** | No SSO, no RBAC tooling, no multi-tenant infra, no per-seat pricing. One operator, one auth boundary |
| Compliance/audit tooling | **No** | Nothing here is regulated activity; the audit trail exists to keep the *system* honest, not to satisfy a regulator |

---

## 7. Owner actions (only Amo can do these)

| # | Action | Why | Blocks |
|---|---|---|---|
| A-1 | **IBKR market-data entitlements** — review Account Management → Market Data Subscriptions; enable **delayed** data (free, clears error 10168); clear competing sessions (10197); confirm the paper account ID is correct | Options pipeline currently reports entitlement errors and writes 0 live option rows; the page must not imply live options data | P7-3 |
| A-2 | **GitHub billing/spend** — restore Actions so CI can start | Every PR is currently unverifiable; hosted runs fail before steps execute | P0-8, all merges |
| A-3 | **Trunk ratification** — decide which branch is master of truth and protect it | 38 open PRs, 14 worktrees, no answerable "what is deployed" | P0-6, P0-7 |
| A-4 | **Trading-plane host** — approve and purchase the dedicated Linux box (or VM) | The plane split is the highest-value infra change | P1 |
| A-5 | **Data budget approval** — approve the futures-deep + per-contract purchase first | Unblocks the Judge's real workload | P2, P4 |
| A-6 | **Options gap decision** — halt SPY/QQQ/AAPL/TSLA paper routing until verdicts exist, or accept in writing | Current state is accepted-but-invisible; the rebuild makes it visible either way | P7-3 |
| A-7 | **`[safety-review]` sign-offs** — risk, execution, config, kill-switch, symbol-gate PRs | Nothing safety-adjacent merges without Amo | P3, P5 |
| A-8 | **Live-trading graduation** — never autonomous, never implied | `LIVE_TRADING_ENABLED` stays `False` through all phases | P8-8 |

---

## 8. Vendor evaluation checklist (apply to every purchase)

```
[ ] Delivers point-in-time correctness (vintage or as-of semantics documented)
[ ] Historical depth sufficient for CPCV windows (≥10 years for futures)
[ ] Per-contract granularity where the strategy needs term structure
[ ] API allows full-history backfill without rate-limit games
[ ] Raw payloads storable immutably (we keep our own archive)
[ ] Licensing: internal use OK; redistribution terms stated in writing
[ ] Cost scales with usage, not with seats (single-operator use, one account)
[ ] Contract has an exit (no multi-year lock without a break clause)
[ ] A named measurement in this blueprint is unblocked by it — otherwise: don't buy
```

---

## 9. Decision gates before spending

| Gate | Must be true |
|---|---|
| G1 | The trial ledger + Judge are wired (P4) — otherwise the data cannot be interpreted |
| G2 | The RAW/immutable layer exists (P2-2) — otherwise history is lost again |
| G3 | A named measurement is unblocked by the purchase |
| G4 | A written quote exists (no purchase from a price list) |
| G5 | Amo approves the budget line |
| G6 | A rollback/exit path exists (cancel, downgrade, or migrate) |

---

*Nothing in this document was purchased, provisioned, or subscribed. No credentials were read. No live
trading, risk, kill-switch, broker-routing, or symbol-gate change was made or proposed for immediate
execution.*
