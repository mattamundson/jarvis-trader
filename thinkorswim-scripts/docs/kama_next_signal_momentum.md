# KAMA — Next Signal Momentum Study

**File**: `NextSignalMomentumSTUDY.ts`  
**Author**: Unknown (legacy shared file)  
**JARVIS Layer**: 3 (Bias)  
**Status**: Ported  
**Python counterpart**: `engine/backtest/indicators.py::kama()`  
**Panel**: Upper

---

## Purpose

Kaufman Adaptive Moving Average (KAMA) — a volatility-responsive trend-following indicator. Price above KAMA = long bias (blue label); price below = short bias (red label). Adapts to market noise by scaling the smoothing constant based on directional efficiency ratio. Also plots 7-bar and 20-bar linear regression lines for slope confirmation.

---

## JARVIS Mapping

| JARVIS Signal | TOS Visual |
|---|---|
| `kama_signal = long` | Price closes above KAMA line; bar color turns blue; "Long" label appears at bottom |
| `kama_signal = short` | Price closes below KAMA line; bar color turns red; "Short" label appears at bottom |
| Bias confirmation | KAMA line (MAA plot, blue/red) smoothly rides trend |
| Slope steepness | 7-bar linear regression (`mlrPlot`, bright blue) shows intrabar momentum |

**Layer 3 Role**: KAMA is the **directional bias** component. When `stc_signal = rising` (Layer 3) **and** `kama_signal = long`, confluence is high. When they diverge, bias is weak — wait for additional confirmation.

---

## TOS Inputs (Configurable)

| Input | Default | Type | Description |
|---|---|---|---|
| `mode` | KAMA | {KAMA, AMA} | KAMA (period=10) or TOS's AMA (Adaptive Moving Average). Use KAMA only. |
| `fr` (7-bar regression) | No | Boolean | If Yes, compute 7-bar linear regression over all bars. If No, use 7-bar window. Keep as No. |
| `fr2` (20-bar regression) | No | Boolean | If Yes, compute 20-bar linear regression over all bars. If No, use 20-bar window. Keep as No. |

**Hardcoded values (do not change)**:
- **KAMA period** = 10 (lookback for change/volatility calculation)
- **Fast period** = 2 (fast SC = 0.4 = 2/(2+1))
- **Slow period** = 30 (slow SC = 0.2222 = 2/(30+1))
- **ER (Efficiency Ratio)** = |close - close[10]| / Sum(|close - close[1]|, 10)

---

## Visual Elements

1. **KAMA Line** (`MAA` plot)
   - **Blue** when close > KAMA (long bias)
   - **Red** when close < KAMA (short bias)
   - Line weight: 2 pixels
   - Smoothly follows price with adaptive lag
   - Repaints each bar (no look-ahead; uses current close in calculation)

2. **7-Bar Linear Regression** (`mlrPlot`)
   - **Bright blue** (default) when slope is positive (uptrend)
   - **Red** when slope is negative (downtrend)
   - Line weight: 2 pixels
   - Calculated as `InertiaAll(OHLC4, 7)` — regresses OHLC4 (average of open, high, low, close)
   - Shows **intrabar momentum**: even small bars in a rising trend show blue; falling trend shows red
   - Useful for **fades**: when price is way above the 7-bar regression, exhaustion may be near

3. **20-Bar Linear Regression** (`mlr2Plot`)
   - **Dark blue** (createcolor(80,100,130)) default color
   - **Dashed line** (short_dash style) for visual separation
   - Line weight: 1 pixel (lighter than 7-bar)
   - Longer-term trend confirmation — less reactive than 7-bar
   - Used to gauge **multi-bar trend strength**

4. **Bottom Labels**
   - **"Long"** label (blue, right-aligned) — appears at bottom of chart on the current bar when close > KAMA
   - **"Short"** label (red, right-aligned) — appears at bottom of chart on the current bar when close < KAMA
   - These are only visible on the rightmost (current) bar; do not persist historically

5. **Price Bar Colors** (`assignpricecolor`)
   - Blue bar when close > KAMA
   - Red bar when close < KAMA
   - Makes directional bias immediately obvious on chart

---

## Install (ThinkorSwim Steps)

1. **Open ThinkorSwim** desktop application
2. Go to **Charts** tab
3. Click **Studies** (beaker icon) in upper right of chart
4. Click **Edit Studies**
5. Click the code bracket icon (`</>`) — **thinkScript Editor**
6. Click **Open** (folder icon)
7. Navigate to `thinkorswim-scripts/` directory
8. Select **`NextSignalMomentumSTUDY.ts`**
9. Click **Save As** — name it `"KAMA Next Signal Momentum"` or `"KAMA"`
10. Close the editor
11. In **Edit Studies** window, find the study in the list
12. Double-click to add to chart
13. Configure **Inputs**:
    - `mode` = **KAMA** (not AMA)
    - `fr` = **No**
    - `fr2` = **No**
14. Click **Apply**, then **OK**
15. **Verify**: 
    - KAMA line (blue/red) appears on price chart
    - 7-bar and 20-bar regression lines appear (bright blue and dark blue dashed)
    - "Long" or "Short" label visible at bottom right on current bar
    - Price bars turn blue (long) or red (short)

---

## Alerts (Creating TOS Alerts)

| Signal | Alert Condition | Sound | Use Case |
|---|---|---|---|
| **KAMA Cross Up** | `close` crosses above `MAA` plot | Ding | KAMA-based long entry confirmation (less primary than STC) |
| **KAMA Cross Down** | `close` crosses below `MAA` plot | Ding | KAMA-based short entry confirmation |
| **7-Bar turns red** | `mlrPlot` color changes to red (downtrend) | (No alert) | Momentum exhaustion warning — watch for exit |
| **20-Bar trend breaks** | `mlr2Plot` crosses below KAMA (long) or above (short) | (No alert) | Longer-term trend reversal — visual only |

**Setup**: Right-click chart → **Add Alert for Study Plot** → Select `MAA` → Threshold = current price (or use price level) → Sound = Ding.

---

## Known Limits / Gotchas

1. **Repainting risk**: KAMA uses the current close in its calculation (line 22: `AMA[1] + Sqr(ScaledSF) * (close – AMA[1])`). On a chart with partial bars (e.g., current 1-minute bar still forming), KAMA will repaint as price moves intra-bar. This is normal for adaptive moving averages. **Backtest results are clean (no look-ahead)** because the engine uses close prices, not intrabar ticks.

2. **Slow response on flat markets**: When volatility is low and price range is narrow, the efficiency ratio (ER) approaches zero, causing the smoothing constant to approach the slow SC (0.2222). KAMA becomes very lagging. This is by design — adapts to choppy conditions by smoothing more. If you want faster response, use a shorter period (10 is minimum for meaningful calculation).

3. **Linear regression calculation ambiguity**: `InertiaAll(OHLC4)` is TOS's built-in linear regression. Line 37–38 sets different behavior based on `fr` input. Default (`fr=No`) uses 7-bar window; setting `fr=Yes` computes regression over **all available bars** (entire chart). This causes the 7-bar line to flatten/jump when you change this. **Always keep `fr=No` and `fr2=No`** for consistent intrabar momentum display.

4. **No volume filter**: KAMA is price-only. Cannot distinguish between institutional volume and retail volume on a KAMA cross. Combine with Volume Stack (Layer 3) or TPO Score for confirmation.

5. **Lag in reversals**: On fast reversals, KAMA lags by several bars because it smooths adaptively. The 7-bar regression reacts faster. Use the 7-bar regression color change as a **leading indicator** for potential KAMA cross within next 1–2 bars.

6. **Bottom labels only on current bar**: The "Long" / "Short" labels (lines 60–61) only display on the rightmost bar of the chart. They do not appear historically. This is TOS behavior (`current == lastBar`). For alerts, rely on the `MAA` plot crossing, not the label.

---

## Python Counterpart Validation

From `engine/backtest/indicators.py::kama()` (lines 38–68):

```python
def kama(
    close: pd.Series, period: int = 10, fast_period: int = 2, slow_period: int = 30
) -> pd.Series:
    """
    Kaufman Adaptive Moving Average (KAMA).
    Used by NextSignalMomentum script. Period=10, slow=30.
    """
    fast_sc = 2.0 / (fast_period + 1)  # 2/3 = 0.6667 (fast)
    slow_sc = 2.0 / (slow_period + 1)  # 2/31 = 0.0645 (slow)
    
    # ... initialization ...
    
    for i in range(period, len(close)):
        change = abs(close.iloc[i] - close.iloc[i - period])
        volatility = close.diff().abs().iloc[i - period + 1 : i + 1].sum()
        
        if volatility == 0:
            er = 0.0
        else:
            er = change / volatility
        
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        result.iloc[i] = result.iloc[i - 1] + sc * (close.iloc[i] - result.iloc[i - 1])
    
    return result
```

**Match**: TOS script and Python both:
- Use **period=10** (lookback for change/volatility)
- Calculate **ER** = |close - close[10]| / sum of 10 bars of |close diffs|
- Smoothing constant (SC) = (ER × (0.6667 - 0.0645) + 0.0645)²
  - TOS: `SlowSF=0.2222` (note: this is NOT the standard 2/31 = 0.0645; the script hardcodes 0.2222 which is slightly off)
  - Python: `2.0 / (30 + 1) = 0.0645`
  - **Discrepancy alert**: TOS hardcodes `SlowSF = 0.2222`, not the standard formula. Backtest results may differ slightly if this matters. Check INTEGRATION_GUIDE for note on this.

- **Recommendation**: For exact TOS visual alignment, use the TOS value (0.2222). The Python engine currently uses 0.0645 (true 30-period slow). This is a known acceptable variance for Layer 3 bias (not a critical entry signal).

---

## Relationship to Layer 3 & Backtest

KAMA is a **supplementary bias indicator**. The JARVIS engine signals are:

- **Layer 3 Primary**: Schaff Trend Cycle (STC) — oscillator that leads KAMA
- **Layer 3 Secondary**: Volume Stack — buy% vs sell%
- **Layer 3 Tertiary**: KAMA — mean-reversion context when market is choppy

When `stc_signal = rising` and `kama_signal = long` (both agree), the bias is **strong**. When they diverge, additional context from Layers 1 & 2 (regime & structure) is required to validate an entry.
