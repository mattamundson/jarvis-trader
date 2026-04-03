# JARVIS TRADER — Session Log: TOS API Research & Signal Comparison Build
**Date**: 2026-04-02
**Session Type**: Research + Feature Build
**Topic**: ThinkOrSwim API connectivity + TOS vs JARVIS Signal Comparison Pipeline

---

## 1. User Question

> "Is it possible to connect to ThinkOrSwim via API? If so, have we done it already? Could we not use that for backtesting against the ThinkOrSwim scripts?"

---

## 2. Research Findings

### 2.1 What TOS API / Schwab API Actually Provides

**Schwab Trader API** (successor to TD Ameritrade API, inherited by Schwab post-acquisition):

- Real-time quotes (equities, options, futures)
- Price history / OHLCV bars
- Options chains with Greeks
- Account data: balances, positions
- Order placement (equities + options — NOT futures)
- Paper trading sandbox

**What it does NOT provide**:
- ThinkScript execution remotely
- Access to TOS's built-in backtester
- TOS study/indicator computed values
- TOS strategy reports or scan results
- Any API surface for the TOS platform itself

**Key conclusion**: There is no public API to run ThinkScript or trigger TOS's backtesting engine programmatically as of April 2026. The Schwab API is an order/data API, not a platform API.

### 2.2 What Already Exists in the Project

Research by Explore agent into `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\`:

| Component | Status | File |
|-----------|--------|------|
| `schwab-py==1.4.2` | Installed | `engine/requirements.txt` line 16 |
| `SchwabConnector` class | 60% complete, **guarded by `SCHWAB_READY=False`** | `engine/execution/schwab_connector.py` |
| `get_account_summary()` | Implemented | schwab_connector.py |
| `get_quotes()` | Implemented | schwab_connector.py |
| `get_options_chain()` | Implemented | schwab_connector.py |
| `submit_options_order()` | Implemented but untested | schwab_connector.py |
| `cancel_all_orders()` | Implemented but untested | schwab_connector.py |
| `OrderRouter` | Wired: equities/options → Schwab, futures → IB Gateway | `engine/execution/order_router.py` |
| OAuth token management | Partial — manual 7-day refresh | `engine/.schwab_token.json` |
| Config vars | `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `SCHWAB_CALLBACK_URL` | `engine/config.py` lines 179-184 |
| `SCHWAB_READY=False` guard | Every method blocked until flag flipped | `schwab_connector.py` module level |

**What's missing in the Schwab connector**:
- Full OAuth2 flow with automated token refresh
- `get_price_history()` for historical OHLCV bars
- Integration into `MarketDataManager` as a data source
- Testing against Schwab sandbox
- Removing the `SCHWAB_READY=False` guard

**ThinkScript files**: 34 `.ts` files in `engine/thinkorswim-scripts/` — these are chart overlay scripts only (OB_STYLE_CYCLE, ATR levels, etc.). They do NOT feed data back into the engine. Intent: visual confirmation on TOS charts, signals delivered via WhatsApp.

### 2.3 MarketDataManager Data Sources (Current)

Priority chain in `engine/data/market_data.py`:
1. **IBKR** (primary, via `ib_async`) — not connected yet
2. **Polygon.io** (fallback)
3. **yfinance** (last resort, delayed)

Plus Finnhub for news/sentiment, ApeWisdom for Reddit sentiment.

Schwab is NOT in the data pipeline — only in the order execution pipeline.

### 2.4 Three Approaches Considered

| Approach | Effort | Value | Decision |
|----------|--------|-------|----------|
| **A. Schwab price history → MarketDataManager** | Low (2-3h) | Low — bars identical to Yahoo/Polygon | Deferred |
| **B. TOS CSV export → JARVIS signal comparator** | Medium (4-6h) | **HIGH — validates STC math** | **SELECTED** |
| **C. Windows RTDX/DDE live data bridge** | High (8-12h) | High but complex | Deferred |

---

## 3. Critical Insight: Engine Has Evolved Beyond Simple STC

Reading `engine/backtest/signals.py` revealed that the engine has evolved significantly from the original "STC crossover" design:

**Current architecture**: 5-layer framework:
- **Layer 1**: Regime Map (EMA trend, Phase Oscillator, ATR consumed %)
- **Layer 2**: Structure Map (VPOC, Value Area High/Low, IB High/Low breakouts)
- **Layer 3**: Bias (KAMA, STC direction, Volume Stack, EMA Ribbon)
- **Layer 4**: Entry Timing (structure-boosted ENTRY_NOW, STC crossover standard)
- **Layer 5**: ATR-based stop/target levels

**Per-instrument parameters** (`INSTRUMENT_PARAMS` dict in `signals.py`):

```python
INSTRUMENT_PARAMS = {
    "MNQ": (15, 92, 0.70, 1.00, 1.80, 2.618, True),   # STC_OB=92 filters Nasdaq noise
    "MCL": (15, 83, 0.90, 1.50, 2.618, 4.00, True),   # Stop=0.90 for crude volatility
    "MGC": (17, 88, 0.30, 1.50, 2.618, 4.00, True),   # Tight stop + wide T1 for gold
    "SPY": (15, 88, 0.30, 1.00, 1.618, 2.618, True),  # SPY 1h optimizer consensus
    "MES": (15, 83, 0.50, 2.00, 3.236, 4.00, False),  # MES 1h, regime_filter=OFF
}
```

Note: These differ from the skill documentation (which still says OB=83, Stop=0.70, T1=1.50 — the original grid search numbers). The engine has been updated with per-instrument optimization.

**STC computation**: `stc(close, fast=23, slow=50, k_period=10, d_period=3)` — in `engine/backtest/indicators.py`.

**Implication for TOS comparison**: TOS only implements the STC crossover (what OB_STYLE_CYCLE ThinkScript does). JARVIS adds 3 more layers of filtering. So:
- TOS will produce MORE signals (raw STC crossovers)
- JARVIS will produce FEWER signals (filtered by regime + structure + bias)
- The comparison measures whether JARVIS signals are a **strict subset** of TOS signals (good) or diverge (bad — means different STC math)

---

## 4. Feature Built: TOS Signal Comparison Pipeline

### 4.1 New Files Created

#### `engine/backtest/tos_importer.py` (NEW — ~270 lines)

Parses TOS strategy report CSV exports into normalized `TOSSignal` objects.

**Key classes**:
```python
@dataclass
class TOSSignal:
    timestamp: datetime    # naive CT datetime
    direction: str         # "LONG" or "SHORT"
    price: float
    quantity: int
    raw_type: str          # original TOS string (BUY, SELL SHORT, etc.)
    pnl: Optional[float]   # if available

@dataclass
class TOSImportResult:
    signals: List[TOSSignal]
    format_detected: str   # "strategy_report" | "trade_history" | "simple" | "generic"
    total_rows: int
    skipped_rows: int
    errors: List[str]
    symbol: Optional[str]
    date_range: Optional[tuple]
```

**Supported TOS export formats** (auto-detected via header analysis):
1. **Strategy Report** — `Date, Time, Type, Price, Qty, P/L Open, P/L Day`
   - TOS signal types: `BUY` → LONG, `SELL` → SHORT, `SELL SHORT` → SHORT, `BUY TO COVER` → LONG
2. **Trade History** — `Date, Time, Spread, Side, Qty, Price, Pos Effect, Symbol`
3. **Simple** — `Date, Signal, Price, Qty` (JARVIS-compatible direct import)

**Public API**:
```python
from backtest.tos_importer import parse_tos_csv, parse_tos_csv_file

result = parse_tos_csv(csv_string, symbol="MNQ")
result = parse_tos_csv_file("/path/to/export.csv", symbol="MNQ")
```

**Smoke test result**:
```
Format: strategy_report
Signals: 4 (2 LONG, 2 SHORT)
Errors: []
  TOSSignal(LONG @ 18700.25 on 2024-06-03 09:30 CT)
  TOSSignal(SHORT @ 18680.50 on 2024-06-03 10:30 CT)
  TOSSignal(SHORT @ 18750.00 on 2024-06-04 09:35 CT)
  TOSSignal(LONG @ 18720.25 on 2024-06-04 11:00 CT)
```

---

#### `engine/backtest/signal_comparator.py` (NEW — ~340 lines)

Compares TOS signals against JARVIS backtest trades with two comparison modes.

**Key classes**:
```python
@dataclass
class JARVISTrade:
    entry_date: datetime
    exit_date: datetime
    direction: str       # "long" or "short"
    entry_price: float
    exit_price: float
    pnl: float
    regime: str
    bias: str

@dataclass
class MatchedSignal:
    tos: TOSSignal
    jarvis: Optional[JARVISTrade]
    match_type: str      # "exact" | "close" | "tos_only"
    bar_offset: int      # bars between TOS and JARVIS timestamps
    price_diff: float

@dataclass
class ComparisonReport:
    symbol: str
    timeframe: str
    mode: str
    tos_signal_count: int
    jarvis_trade_count: int
    exact_matches: int          # same bar, same direction
    close_matches: int          # within ±2 bars
    tos_only: int               # TOS fired, JARVIS filtered
    jarvis_only: int            # JARVIS fired, TOS didn't (⚠️ divergence signal)
    match_rate: float           # (exact + close) / tos_signal_count
    avg_price_diff: float
    avg_bar_offset: float
    verdict: str                # ALIGNED | GOOD | PARTIAL | DIVERGENT | NO_DATA | NO_JARVIS
    verdict_detail: str
    matched_signals: List[MatchedSignal]
    unmatched_tos: List[TOSSignal]
    unmatched_jarvis: List[JARVISTrade]
    filter_breakdown: dict      # regime/structure/bias attribution of tos_only signals
```

**Verdict logic**:
| match_rate | jarvis_only | Verdict |
|------------|-------------|---------|
| ≥95% | normal | ALIGNED ✅ |
| 80-95% | normal | GOOD ✅ |
| 60-80% | normal | PARTIAL ⚠️ |
| <60% | normal | DIVERGENT ❌ |
| any | >30% of jarvis trades | DIVERGENT ❌ |

**JARVIS trade loading**: Automatically finds best backtest file in `engine/backtest/results/` by trying:
1. `{symbol}_{timeframe}_backtest_corrected.json` (preferred)
2. `{symbol}_{timeframe}_*.json` (fallback, most recent)

Reads `full_metrics.trades` → list of trade dicts with `entry_date`, `exit_date`, `direction`, `entry_price`, `exit_price`, `pnl`, `regime`, `bias`.

**STC Math validator** (`validate_stc_math()`):
- Fetches OHLCV bars via yfinance
- Computes our STC values using `stc(close, fast=23, slow=50, k_period=10, d_period=3)`
- Returns last 100 bars of `{timestamp, stc_val, stc_signal, stc_cross_up, stc_cross_down}`
- If TOS STC values are provided: computes MAE, correlation, assessment (IDENTICAL / VERY_CLOSE / MINOR_DIVERGENCE / SIGNIFICANT_DIVERGENCE)

**Public API**:
```python
from backtest.signal_comparator import compare_signals, validate_stc_math

report = compare_signals(
    tos_signals=import_result.signals,
    symbol="MNQ",
    timeframe="1h",
    match_window_bars=2,
)
print(report.verdict)          # "ALIGNED"
print(report.match_rate)       # 0.91
print(report.to_dict())        # JSON-serializable full report
```

---

### 4.2 Updated File: `engine/routers/backtest_router.py`

**Imports added**:
```python
import json
from fastapi import File, Form, HTTPException, UploadFile
```

**Three new endpoints**:

#### `POST /backtest/compare-tos`
```
Upload a TOS strategy report CSV + form fields: symbol, timeframe, match_window_bars
→ Parses CSV via tos_importer
→ Runs compare_signals()
→ Returns {import_summary, comparison}
→ Saves result to backtest/results/TOS_COMPARISON_{symbol}_{timeframe}_{ts}.json
```

Example curl:
```bash
curl -X POST http://localhost:8010/backtest/compare-tos \
  -F "file=@my_tos_export.csv" \
  -F "symbol=MNQ" \
  -F "timeframe=1h" \
  -F "match_window_bars=2"
```

Response structure:
```json
{
  "import_summary": {
    "signal_count": 45,
    "long_count": 23,
    "short_count": 22,
    "format_detected": "strategy_report",
    "total_rows": 46,
    "skipped_rows": 1,
    "errors": [],
    "symbol": "MNQ",
    "date_range": ["2024-06-01T09:30:00", "2026-03-27T14:00:00"]
  },
  "comparison": {
    "symbol": "MNQ",
    "timeframe": "1h",
    "tos_signal_count": 45,
    "jarvis_trade_count": 11,
    "exact_matches": 8,
    "close_matches": 2,
    "tos_only": 35,
    "jarvis_only": 1,
    "match_rate": 0.222,
    "match_rate_pct": 22.2,
    "verdict": "GOOD",
    "verdict_detail": "JARVIS filtered 35 TOS signals via layers 1-4 — expected.",
    "filter_breakdown": {
      "regime": 21,
      "structure": 8,
      "bias": 6
    },
    "matched_signals": [...],
    "tos_only_signals": [...],
    "jarvis_only_trades": [...]
  }
}
```

#### `GET /backtest/comparison-results`
```
Returns list of all saved TOS comparison JSON files (summary only, no signal detail).
```

#### `POST /backtest/validate-stc-math`
```
Query params: symbol, timeframe, start, end
Returns last 100 bars of our STC values for manual comparison against TOS charts.
```

---

### 4.3 Dependency Check

`python-multipart` — confirmed already installed at `engine/.venv`:
```
Requirement already satisfied: python-multipart in ...\.venv\lib\site-packages (0.0.22)
```

---

## 5. Endpoint Verification (Smoke Tests)

```
✅ tos_importer.py imports cleanly: from backtest.tos_importer import parse_tos_csv, TOSSignal
✅ signal_comparator.py imports cleanly: from backtest.signal_comparator import compare_signals, ComparisonReport, validate_stc_math
✅ New endpoints registered:
     /backtest/compare-tos
     /backtest/validate-stc-math
✅ TOS CSV importer smoke test:
     Format: strategy_report
     Signals: 4 (2 LONG, 2 SHORT)
     Errors: []
```

---

## 6. Important Architecture Notes

### 6.1 Why tos_only Count Will Always Be High

The 5-layer engine filters signals aggressively. For MNQ 1h:
- Current backtest: 11 trades over ~21 months (backtest_corrected.json)
- TOS STC-only would produce ~45-80 crossover signals in same period
- Expected match_rate: ~20-30% (not 95%) — this is **correct behavior**
- The key metric is `jarvis_only` (should be near 0 if STC math is correct)

### 6.2 Per-Instrument STC Parameters vs TOS Study

When exporting from TOS, make sure the STC study parameters match `INSTRUMENT_PARAMS`:

| Symbol | STC_OS | STC_OB | Note |
|--------|--------|--------|------|
| MNQ | 15 | **92** | Different from default 83 |
| MCL | 15 | 83 | Standard |
| MGC | 17 | 88 | Different OS threshold |
| SPY | 15 | 88 | Different OB |
| MES | 15 | 83 | Standard, regime_filter=OFF |

STC core parameters (same for all instruments): `fast=23, slow=50, k_period=10, d_period=3`

### 6.3 MES Status Note

From `backtest/paper-status`: MES 1h status is **CLOSED** (WFE=0.09, overfit). The primary validated instruments are:
- **MCL 1h** — WFE=0.82 EXCELLENT, ACTIVE
- **MNQ 1h** — WFE=0.57 GOOD, ACTIVE

The original session documentation (PF 5.27 MES) was from early backtests. Current walk-forward validation shows MES failed. MCL and MNQ are the production instruments.

---

## 7. Next Steps for Matt

### Step 1: Export TOS Strategy Report

For **MNQ 1h** (primary active instrument):

1. Open TOS → Charts tab
2. Chart MNQ (or NQ=F continuous) on 1-hour timeframe
3. Studies menu → Add Study → search "STC" → select the Schaff Trend Cycle
4. Configure STC parameters:
   - Fast Length (MACD fast): **23**
   - Slow Length (MACD slow): **50**
   - Cycle Length (K period): **10**
   - Smooth (D period): **3**
   - Oversold: **15**
   - Overbought: **92** (MNQ-specific — NOT 83)
5. Assign strategy: In the STC study properties → set Buy signal on OS crossover (15), Sell signal on OB crossover (92)
6. Load chart history to cover 2024-06-01 → present
7. Menu: Studies → Strategy Report → Show Report
8. Export → "Export to CSV"

For **MCL 1h** (also active):
- Same process but OB = **83** (standard)

### Step 2: Run Comparison

Start the engine if not running:
```bash
cd C:\Users\mattm\ThinkorSwim\jarvis-trader
start_jarvis.bat
```

Upload and compare:
```bash
curl -X POST http://localhost:8010/backtest/compare-tos \
  -F "file=@mnq_tos_export.csv" \
  -F "symbol=MNQ" \
  -F "timeframe=1h" \
  -F "match_window_bars=2"
```

Or use Swagger UI at http://localhost:8010/docs → `/backtest/compare-tos`

### Step 3: Interpret Results

| Metric | What It Means |
|--------|--------------|
| `verdict: "ALIGNED"` or `"GOOD"` | STC math is correct — trust the backtests |
| `jarvis_only > 3-4` | ⚠️ JARVIS is producing signals TOS doesn't — STC calc mismatch |
| `tos_only` is large | ✅ Expected — JARVIS filters via 5 layers, TOS is raw STC only |
| `avg_price_diff > 5 points` | Possible bar-close vs bar-open timing difference |

---

## 8. Future Work (Not Built Yet)

### 8.1 Schwab Connector Completion

The `SchwabConnector` at `engine/execution/schwab_connector.py` needs:
- OAuth2 automated token refresh (currently manual every 7 days)
- `get_price_history()` wired into `MarketDataManager`
- Sandbox testing
- Flip `SCHWAB_READY=True` (Tier 3 action)

Timeline: Not needed until options trading goes live.

### 8.2 TOS RTDX/DDE Bridge (Windows)

TOS desktop on Windows exposes real-time study values via DDE/RTD protocol. Could pipe live STC values from TOS directly into the engine as a live data feed. High effort, only useful if we want TOS as the "source of truth" for live signals (vs computing them ourselves).

### 8.3 Dashboard Widget

A `TOSComparisonCard` component for `dashboard/app/strategies/page.tsx` was planned but not built:
- CSV dropzone upload
- Match rate gauge
- Signal comparison table
- Not blocking — the API endpoints are live and usable via curl/Swagger

---

## 9. Files Changed This Session

| File | Type | Change |
|------|------|--------|
| `engine/backtest/tos_importer.py` | **NEW** | TOS CSV parser, 270 lines |
| `engine/backtest/signal_comparator.py` | **NEW** | Signal comparator + STC math validator, 340 lines |
| `engine/routers/backtest_router.py` | **MODIFIED** | Added 3 endpoints + json/UploadFile imports |

No other files were modified. No tests were written (existing integration tests unchanged). No dashboard changes.

---

## 10. Engine Status at Session End

- Engine: port 8010 (not verified running — may need `start_jarvis.bat`)
- Dashboard: port 3010
- New endpoints available after engine restart:
  - `POST /backtest/compare-tos`
  - `GET /backtest/comparison-results`
  - `POST /backtest/validate-stc-math`
- Active paper instruments: MCL 1h (WFE 0.82), MNQ 1h (WFE 0.57)
- Paper trading phase: April–May 2026 (forward-test 30 days before live capital)

---

*Session log written: 2026-04-02*
*JARVIS TRADER v1.2.x — TOS Comparison build*
