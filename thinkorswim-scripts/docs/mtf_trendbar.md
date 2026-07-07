# MTF Trend Bar — ThinkScript Study

**File**: `shared_mtftrendbarSTUDY.ts`  
**Author**: Unknown (legacy shared file)  
**JARVIS Layer**: 1 (Regime Map)  
**Status**: Ported  
**Python counterpart**: `engine/backtest/indicators.py::cci()`  
**Panel**: Upper

---

## Purpose

Multi-timeframe CCI-based trend confirmation. Provides supplementary regime signal via **Commodity Channel Index** zero-cross detection. Trails behind price at current bar (drawn as `s` plot) and shows directional flip arrows (up/down) when CCI crosses zero. Defaults to 5-minute aggregation but fully configurable.

---

## JARVIS Mapping

| JARVIS Signal | TOS Visual |
|---|---|
| Supplementary regime confirmation (Layer 1) | CCI trend change triggers up/down arrows on chart |
| `cciTrendNow >= 0` = long bias | Green trail line (`s`, `s1` plots) |
| `cciTrendNow < 0` = short bias | Red trail line (`s`, `s1` plots) |
| CCI zero-cross up | Green UP arrow appears |
| CCI zero-cross down | Red DOWN arrow appears |

**Note**: This study is **not a primary entry signal**. It is used to **confirm regime shifts** detected by other Layer 1 signals (EMA Ribbon, Phase Oscillator). When CCI arrows align with STC crossovers or IB breakouts, confidence increases.

---

## TOS Inputs (Configurable)

| Input | Default | Type | Description |
|---|---|---|---|
| `length` | 50 | Integer | CCI lookback period (typical range 20–100) |
| `timeframe` | AggregationPeriod.FIVE_MIN | Agg Period | Multi-timeframe mode (5m default; set to HOUR, DAILY, etc. for confirmation on different TF) |
| `atr_period` | 5 | Integer | ATR period for trail calculation (affects trail tightness) |

**Hardcoded values**:
- `state` (default = `init`) — Internal trend state machine (init → long → short → long ...)
- `st` (zero threshold) — CCI zero line; all comparisons are `>= 0` or `< 0`

---

## Visual Elements

1. **Trail Lines** (`s` plot, `s1` plot)
   - **Green** when CCI >= 0 (long regime)
   - **Red** when CCI < 0 (short regime)
   - Line weight: 2 pixels
   - Plotted on upper (price) panel
   - Represents ATR-based dynamic support/resistance during trend

2. **Arrows**
   - **Green UP arrow** (`uparrow`) — CCI just crossed above zero (bar N-1 was < 0, bar N is >= 0)
   - **Red DOWN arrow** (`dnarrow`) — CCI just crossed below zero (bar N-1 was >= 0, bar N is < 0)
   - Default color: green for up, red for down
   - No painting strategy override — standard arrow appearance

3. **CCI Calculation**
   - Typical price = (close + low + high) / 3
   - CCI = (typical_price - SMA(typical_price, length)) / (linear_deviation * 0.015)
   - Zero-cross = trend direction flip

---

## Install (ThinkorSwim Steps)

1. **Open ThinkorSwim** desktop application
2. Go to **Charts** tab
3. Click **Studies** (beaker icon) in upper right of chart
4. Click **Edit Studies**
5. In the Studies window, click the code bracket icon (`</>`) — **thinkScript Editor**
6. Click **Open** (folder icon)
7. Navigate to `thinkorswim-scripts/` directory
8. Select **`shared_mtftrendbarSTUDY.ts`**
9. Click **Save As** — name it `"MTF Trend Bar"` (or leave as auto-generated)
10. Close the editor
11. In **Edit Studies** window, find `"MTF Trend Bar"` in the list
12. Double-click to add to chart
13. Configure **Inputs** (optional):
    - `timeframe` — change from 5-min to HOUR or DAILY for confirmation on different aggregation
    - `length` — adjust CCI period (50 is standard, try 30–80 for noise reduction)
    - `atr_period` — tighten/loosen trail (5 is default)
14. Click **Apply**, then **OK**
15. **Verify**: Green and red trail lines appear on chart; arrows fire on CCI zero-cross bars

---

## Alerts (Creating TOS Alerts)

| Signal | Alert Condition | Sound | Use Case |
|---|---|---|---|
| **CCI Cross Up** | `uparrow` plot is not NaN (UP arrow fires) | Ding | Supplementary long entry confirmation |
| **CCI Cross Down** | `dnarrow` plot is not NaN (DOWN arrow fires) | Ding | Supplementary short entry confirmation |
| **Trail turns green** | `s` color changes to green (CCI >= 0) | (No alert) | Visual confirmation only — monitor manually |
| **Trail turns red** | `s` color changes to red (CCI < 0) | (No alert) | Visual confirmation only — monitor manually |

**Setup**: Right-click chart → **Add Alert for Study Plot** → Select `uparrow` or `dnarrow` → Choose sound.

---

## Known Limits / Gotchas

1. **State machine complexity**: The script uses a 3-state switch (init → long → short) with nested conditionals. Line 35 checks `cciTrendNow <= st`, which should be `cciTrendNow < st` (off-by-one). This may cause one-bar delays in state transitions on zero-cross. **Verify on historical bars** that arrows fire on the correct bar.

2. **Multi-timeframe lag**: When `timeframe` is set to HOUR or DAILY, the CCI is calculated from aggregated bars. On a 5-minute chart with HOUR aggregation, the hourly bar updates only once per hour, so arrows may fire in a burst on the hour boundary. Use intraday charts (5m, 15m) for real-time confirmation.

3. **Trail plot redundancy**: Both `s` and `s1` plots draw the same data with slight logic differences. `s1` recalculates trail on every bar; `s` uses state machine. Prefer `s` for primary signal; `s1` is backup.

4. **CCI period sensitivity**: Default period=50 is a long lookback. Noisy markets may cause false zero-crosses. Grid search in INTEGRATION_GUIDE suggests CCI(50) is optimal for MES 1h; adjust if used on SPY/QQQ.

5. **No volume weighting**: CCI uses only price, not volume. Cannot detect order-flow reversals. Combine with Volume Stack or TPO Score for full context.

6. **Arrows only on zero-cross**: Arrows fire only when CCI crosses the zero line. Mid-range CCI movements (e.g., 15 → 35) do not trigger arrows. Use the color change of the trail line as the primary signal.

---

## Python Counterpart Validation

From `engine/backtest/indicators.py::cci()` (lines 226–236):

```python
def cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 50) -> pd.Series:
    """
    Commodity Channel Index (CCI).
    Used by shared_mtftrendbar script with period=50.
    Zero-cross = trend direction change.
    """
    typical = (high + low + close) / 3
    ma = typical.rolling(period).mean()
    mean_dev = typical.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    result = (typical - ma) / (0.015 * mean_dev.replace(0, np.nan))
    return result.fillna(0)
```

**Match**: TOS script (line 12) and Python both use:
- `(price - Average(price, length)) / linDev / 0.015`
- `price = (c + l + h) / 3`
- `linDev` = linear deviation (mean absolute deviation)
- Constant divisor = 0.015

Calculation is **exact match**. Backtest results using `cci()` in Python will align with TOS visual arrows.
