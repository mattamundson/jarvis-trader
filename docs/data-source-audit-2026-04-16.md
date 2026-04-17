# Data Source Incident — 2026-04-16

> **Status**: Defensive fix shipped 2026-04-16. Backtest contamination audit complete 2026-04-16 (T1.5 closed).

## T1.5 Audit result (2026-04-16, 23:40 CT)

All 78 CSV files in `engine/backtest/cache/` scanned via
`engine/scripts/audit_polygon_contamination.py`. Every file's min/max
close prices fall inside the plausible band for the futures instrument
named in the filename. **No contaminated files detected**.

Concretely — for each symbol, the cached price range matched the
futures range with no overlap into the equity range:

| Symbol | Cached range | Futures band | Equity price (for reference) |
|---|---|---|---|
| MCL / CL | 55-124 | 25-150 | Colgate-Palmolive ~$85 (overlaps — volatility check also passed) |
| MES / ES / ES_F | 3589-7036 | 3000-8500 | ESSA Pharma ~$1-$15 |
| MNQ / NQ_F | 10728-26371 | 8000-32000 | Nasdaq Inc. ~$50-$75 |
| MGC / GC | 1623-5591 | 1400-6500 | GC equity ~$60-$80 |
| M2K / RTY | 1645-2746 | 1000-3500 | — |
| SPY | 496-695 | 250-800 | (is an equity ETF; correctly sourced) |

**Implication**: prior backtest validation numbers
(MCL: WFE 0.82 / Sharpe 4.16 / PF 5.27, etc.) are **not contaminated by
the Polygon equity-ticker bug**. They may still be affected by other
issues (regime shift, overfit, etc. — see rolling WFE monitoring), but
not by stock-price-as-futures-price corruption.

**Regression protection**: `engine/tests/test_cache_contamination_audit.py`
re-runs the audit on every test invocation. A contaminated file cannot
silently sneak back in (e.g. if Polygon is partially re-enabled later).

## What happened

While diagnosing apparent Polygon.io rate-limiting (T1.1 in roadmap-2026-04-15.md), a test query revealed:

```bash
$ curl "https://api.polygon.io/v3/reference/tickers?ticker=CL&apiKey=..."
{"results":[{"ticker":"CL","name":"Colgate-Palmolive Company",
             "market":"stocks","type":"CS",...}]}
```

`CL` on Polygon's free plan is **Colgate-Palmolive Company** common stock, traded on NYSE — **not crude oil futures**. The `engine/data/market_data.py:36,51` symbol map was routing `MCL → CL` for futures price requests, meaning any time the engine fell back from IBKR to Polygon for a crude oil futures price, it would receive Colgate-Palmolive's stock price instead.

Same trap for the other standard-futures tickers (`NQ`, `ES`, `GC`) — each is an unrelated equity on Polygon's stock-only free plan.

## How long has this been wrong

The 2026-04-05 audit comment in `market_data.py:32` claims `CL = $85.41 ✅ (crude oil — proxy for MCL)`. That $85.41 was Colgate-Palmolive's stock price, not crude oil's. The correctness check was based on "the number is plausible for crude" — but $85 happens to be plausible for a major consumer-goods stock too. So the bug has existed since at least 2026-04-05, possibly longer.

## Blast radius

**Runtime** (`engine/data/market_data.py`):
- `get_historical_bars()` — Polygon was Tier 2 fallback for the technical analyst's bar series
- `get_current_price()` — Polygon was Tier 3 fallback for snapshot prices

**Backtest** (`engine/backtest/data_loader.py`):
- `BacktestDataLoader.load()` — Polygon was the primary historical data source via `_fetch_via_polygon()`. **This is the contaminating path for any cached CSV that was generated from a Polygon fetch instead of from IBKR.**

**Why this didn't catch fire sooner**: IBKR was usually connected and serving live prices, so the Polygon fallback rarely fired in production. When IBKR was offline (yesterday's logs show this), the engine fell through to CSV cache rather than Polygon — but only because the CSV cache was populated correctly. If the CSV cache had been generated *via Polygon* (i.e. via the backtest data loader path), the cache itself would contain Colgate-Palmolive prices labeled as MCL.

## Fix (shipped 2026-04-16)

`engine/data/market_data.py`:
- `POLYGON_FUTURES_MAP` is now empty — `dict[str, str] = {}`.
- New `POLYGON_FUTURES_BLOCKLIST: frozenset` containing every futures symbol the codebase currently uses (`MCL`, `MNQ`, `MES`, `MGC`, `M2K`, `MYM`, `CL`, `NQ`, `ES`, `GC`, `RTY`, `YM`, `SI`, `ZB`, `ZN`).
- Both Polygon call sites (`get_historical_bars`, `get_current_price`) check the blocklist and skip Polygon entirely for futures. Falls through to subsequent tiers (CSV cache for historical, "unavailable" for current price).

`engine/backtest/data_loader.py`:
- `load()` now imports `POLYGON_FUTURES_BLOCKLIST` and short-circuits with `return None` for any blocklisted symbol, before calling `_fetch_via_polygon()`.

`engine/tests/test_polygon_futures_blocklist.py` (new):
- 12 regression tests enforcing: (a) blocklist coverage of all known futures, (b) `POLYGON_FUTURES_MAP` is and stays empty, (c) `BacktestDataLoader.load("MCL", ...)` returns `None`.

## What this fix does NOT do

1. **Does not validate existing CSV cache files.** If any of the cached files in `engine/backtest/cache/` were generated via Polygon instead of IBKR, they contain Colgate-Palmolive prices (or NQ-the-stock, ES-the-stock, GC-the-stock prices) labeled as futures. Audit pending (T1.5).
2. **Does not invalidate prior backtest results.** The MCL `WFE 0.82 / Sharpe 4.16 / PF 5.27` numbers may or may not be valid depending on which data source was used during validation. Re-validation may be required (T1.5).
3. **Does not provide a working real-time futures data source.** With Polygon disabled and IBKR-live unreliable, the system depends on the CSV cache for historical bars and on IBKR snapshots for current prices. If both fail, the engine produces empty technical reports (correct behavior — no signal rather than wrong signal), but produces no signals.

## Re-enabling Polygon for futures (future work)

Requires:
1. Subscription to a Polygon plan that includes futures (`Stocks Advanced` does NOT — needs the dedicated futures product, ~$199/mo at time of writing).
2. Verification of the correct ticker format. Polygon's futures tickers may use `I:CL` (continuous index) or contract-specific like `C:CLF26` (Jan 2026 Crude). Bare `CL` will continue to return Colgate-Palmolive.
3. Per-symbol smoke test (price-range sanity) before adding to `POLYGON_FUTURES_MAP`.
4. Update `POLYGON_FUTURES_BLOCKLIST` to remove the now-supported symbols.
5. Update `test_polygon_futures_blocklist.py::test_polygon_futures_map_is_empty` to allow the new entries.

## References

- Roadmap: `docs/session-logs/roadmap-2026-04-15.md` (T1.1 = origin task, T1.5 = audit follow-up)
- Memory: `C:\Users\mattm\.claude\projects\C--windows-system32\memory\MEMORY.md` § "P0 Actions"
- Code: `engine/data/market_data.py:30-78`, `engine/backtest/data_loader.py:215-231`
- Tests: `engine/tests/test_polygon_futures_blocklist.py`
