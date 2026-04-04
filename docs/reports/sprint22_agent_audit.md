# Sprint 22 Agent Data Feed Audit

**Date**: 2026-04-04
**Purpose**: Confirm real data flows to each Stage 1 pipeline agent
**Files modified**: `engine/agents/technical_analyst.py`, `engine/agents/news_analyst.py`, `engine/agents/social_analyst.py`, `engine/agents/fundamental_analyst.py`

---

## Summary

| Agent | Data Source | Status | Fix Applied |
|-------|-------------|--------|-------------|
| TechnicalAnalystAgent | IB Gateway → Polygon → CSV cache via `data_manager.get_bars()` | PASS | `[AGENT_INPUT]` logging added at entry + after bars fetch |
| NewsAnalystAgent | Finnhub company-news API (7-day lookback) + optional `data_manager.get_news()` | NEEDS_REVIEW | `[AGENT_INPUT]` logging + explicit warning when 0 headlines |
| SocialAnalystAgent | ApeWisdom Reddit trending API (no auth) + optional StockTwits | NEEDS_REVIEW | `[AGENT_INPUT]` logging + warning when no social data |
| FundamentalistAgent | FRED CSV (Fed Funds Rate, 10Y Yield, VIX) + Finnhub equity metrics | PASS | `[AGENT_INPUT]` logging + futures-specific prompt note |

---

## TechnicalAnalystAgent

**File**: `engine/agents/technical_analyst.py`

**What it receives**:
- `symbol` (str), `timeframe` (str, default "15m"), `is_futures` (bool)
- OHLCV DataFrame from `data_manager.get_bars(symbol, lookback_days=30, timeframe=timeframe)`
- Requires `_MIN_INTRADAY_BARS = 50` bars minimum; falls back to daily (`lookback_days=365, timeframe="1d"`)
- Optionally enriches with composite signal metadata (STC+ORB+VWAP) for MES instruments

**Source**: `data_manager.get_bars()` — waterfall: IB Gateway → Polygon → CSV cache → None

**Status**: PASS — core technical pipeline is solid. Daily fallback is properly implemented. `_compute_indicators()` is deterministic Python (no LLM involved). Current price is fetched independently via `data_manager.get_current_price()` if not in bar data.

**Known risk**: If `data_manager.get_bars()` returns an empty DataFrame AND daily fallback also fails, an empty report with signal=0.0/confidence=0.0 is returned. This is correct behavior.

**Fix applied**:
```python
logger.info(
    "[AGENT_INPUT] TechnicalAnalyst received: symbol=%s timeframe=%s is_futures=%s",
    symbol, timeframe, is_futures,
)
# ... after bars fetch:
logger.info(
    "[AGENT_INPUT] TechnicalAnalyst bars fetched: symbol=%s bars=%d timeframe=%s",
    symbol, len(df) if not df.empty else 0, timeframe,
)
```

---

## NewsAnalystAgent

**File**: `engine/agents/news_analyst.py`

**What it receives**:
- `symbol` (str)
- Headlines from Finnhub `/company-news` endpoint (7-day window, up to 20 items)
- Optional supplemental headlines from `data_manager.get_news()` if the data manager exposes that method
- Deduplicated by headline text[:80], newest first

**Source**: Finnhub News API — requires `FINNHUB_API_KEY` environment variable OR `llm_client.finnhub_key` attribute

**Status**: NEEDS_REVIEW

**Likely issue**: Finnhub free tier does NOT include the company news endpoint. If `FINNHUB_API_KEY` is not set, the Finnhub block is entirely skipped. If the key is set but on a free plan, HTTP 403 is returned (logged as a warning). Result: 0 headlines → `_neutral_report()` is returned (signal=0.0, confidence=0.1).

**Futures symbols (MCL, MNQ)**: Finnhub company news is designed for equity tickers. Futures symbols like `MCL` or `MNQ` will return 0 headlines. This is expected behavior — the neutral fallback is correct.

**Fix applied**:
```python
logger.info(
    "[AGENT_INPUT] NewsAnalyst received: %d headlines for %s, source=%s",
    len(headlines) if headlines else 0, symbol,
    "finnhub/data_manager" if headlines else "none",
)
if not headlines:
    logger.warning(
        "[AGENT_INPUT] NewsAnalyst: 0 headlines from source for %s — using neutral fallback",
        symbol,
    )
```

The existing `_neutral_report()` already returns an honest neutral signal. No fake data is ever injected.

---

## SocialAnalystAgent

**File**: `engine/agents/social_analyst.py`

**What it receives**:
- `symbol` (str)
- ApeWisdom trending data: a list of `{ticker, mentions, upvotes, rank, mentions_24h_ago}` dicts — public API, no auth required
- Optional StockTwits data: `{bullish_count, bearish_count, total_messages, watchlist_count}` — requires `STOCKTWITS_TOKEN`

**Source**:
- ApeWisdom: `https://apewisdom.io/api/v1.0/filter/all-stocks` — no key required, ~100ms
- StockTwits: `https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json` — requires token

**Status**: NEEDS_REVIEW

**Key issue**: ApeWisdom tracks Reddit equity tickers. Futures symbols (MCL, MNQ, MES) will NOT appear in the trending list. Both `symbol_data` and `stocktwits_data` will be None for futures. The existing `_neutral_report()` path handles this correctly — `{symbol} not found in social trending data` with confidence=0.2.

**ApeWisdom availability**: Public API with no auth. Likely rate-limited or occasionally unavailable. `_fetch_apewisdom()` has a try/except returning `[]` on failure — the agent gracefully returns neutral.

**Fix applied**:
```python
logger.info(
    "[AGENT_INPUT] SocialAnalyst received: sentiment=%s for %s, source=%s",
    str(symbol_data)[:80] if symbol_data else "None", symbol,
    "apewisdom+stocktwits" if symbol_data and stocktwits_data else (
        "apewisdom" if symbol_data else ("stocktwits" if stocktwits_data else "none")
    ),
)
if symbol_data is None and stocktwits_data is None:
    logger.warning(
        "[AGENT_INPUT] SocialAnalyst: no social data for %s — using neutral fallback",
        symbol,
    )
```

---

## FundamentalistAgent

**File**: `engine/agents/fundamental_analyst.py`

**What it receives**:
- `symbol` (str), `is_futures` (bool, default True)
- FRED macro data: `fed_funds_rate` (FEDFUNDS series), `us_10y_yield` (DGS10), `vix` (VIXCLS) — fetched via CSV endpoint, no API key
- Hardcoded fallback defaults if FRED is unavailable: `fed_funds_rate=4.33`, `us_10y_yield=4.30`, `vix=20.0`
- For equities only (is_futures=False): Finnhub company profile + basic financials (P/E, P/B, beta, etc.)

**Source**: FRED CSV (`https://fred.stlouisfed.org/graph/fredgraph.csv`) — no auth required

**Status**: PASS

**Notes**:
- FRED fetch has proper per-series fallback to hardcoded defaults — analysis is never blocked
- For futures (MCL, MNQ), `is_futures=True` — equity fundamentals are skipped intentionally
- The LLM now receives an explicit note: "No traditional P/E, P/B, or company fundamentals are applicable. Use macro regime only." — removes ambiguity
- FRED CSV is updated daily (not intraday) — this is correct for macro regime assessment

**Fix applied**:
```python
logger.info(
    "[AGENT_INPUT] FundamentalistAgent received: symbol=%s is_futures=%s "
    "vix=%.2f yield_10y=%s fundamentals_count=%d",
    symbol, is_futures, key_metrics.get("vix", 0.0),
    key_metrics.get("us_10y_yield", "N/A"), len(equity_metrics),
)
if is_futures and not equity_metrics:
    logger.info(
        "[AGENT_INPUT] FundamentalistAgent: futures instrument %s — macro-only analysis "
        "(no P/E or company fundamentals available for futures contracts)", symbol,
    )
```

LLM prompt now includes:
```python
futures_note = (
    f"\nNOTE: {symbol} is a futures instrument. No traditional P/E, P/B, or company "
    f"fundamentals are applicable. Use macro regime only.\n"
    if is_futures else ""
)
```

---

## [AGENT_INPUT] Logging Added

All 4 agents now log `[AGENT_INPUT]` at INFO level at the start of `analyze()`.

After triggering `POST /scanner/trigger`, look for these patterns in engine logs:

```
INFO agents.technical_analyst   [AGENT_INPUT] TechnicalAnalyst received: symbol=MCL timeframe=1h is_futures=True
INFO agents.technical_analyst   [AGENT_INPUT] TechnicalAnalyst bars fetched: symbol=MCL bars=720 timeframe=1h
INFO agents.news_analyst        [AGENT_INPUT] NewsAnalyst received: 0 headlines for MCL, source=none
WARNING agents.news_analyst     [AGENT_INPUT] NewsAnalyst: 0 headlines from source for MCL — using neutral fallback
INFO agents.social_analyst      [AGENT_INPUT] SocialAnalyst received: sentiment=None for MCL, source=none
WARNING agents.social_analyst   [AGENT_INPUT] SocialAnalyst: no social data for MCL — using neutral fallback
INFO agents.fundamental_analyst [AGENT_INPUT] FundamentalistAgent received: symbol=MCL is_futures=True vix=18.50 yield_10y=4.3 fundamentals_count=0
INFO agents.fundamental_analyst [AGENT_INPUT] FundamentalistAgent: futures instrument MCL — macro-only analysis
```

---

## Diagnosis: Expected Behavior for Futures (MCL, MNQ)

| Agent | Expected for MCL/MNQ | Honest? |
|-------|----------------------|---------|
| TechnicalAnalyst | 50–720 bars of OHLCV → full indicator set → LLM synthesis | YES |
| NewsAnalyst | 0 headlines → neutral signal (0.0, confidence=0.1) | YES — futures not covered by Finnhub news |
| SocialAnalyst | Not in ApeWisdom → neutral signal (0.0, confidence=0.2) | YES — futures not retail-mentioned on Reddit |
| FundamentalistAgent | FRED macro only (VIX, 10Y, Fed Funds) → macro regime signal | YES — PASS |

The pipeline operates honestly: TechnicalAnalyst and FundamentalistAgent provide real signal; NewsAnalyst and SocialAnalyst return explicit low-confidence neutrals for futures instruments.

---

## Recommendations

1. **Monitor [AGENT_INPUT] logs after first live pipeline run** — grep for `[AGENT_INPUT]` to confirm all 4 fire
2. **NewsAnalyst consistently returns 0**: Verify Polygon/Finnhub plan includes News API. If Finnhub free tier, either upgrade or accept neutral is correct behavior for futures
3. **SocialAnalyst neutral is correct behavior** for futures — do not attempt to inject fake Reddit sentiment
4. **FundamentalistAgent FRED fallback values** in `FRED_DEFAULTS` should be reviewed quarterly — currently set to Q1 2026 levels
5. **TechnicalAnalyst is the highest-signal agent for futures** — ensure `data_manager.get_bars()` is returning live IB Gateway data (not cached/stale)
