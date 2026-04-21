# Keltner Channel 3.0x — ThinkScript Study

**File**: `shared_shared_shared_shared_kelt_3.01STUDY.ts`

**Author**: JP (original keltner_multi_timeframe.ts, Nov 2018) / 3.0x factor variant

**JARVIS Layer**: 4 Entry (Regime Fade) + 1 Regime Classifier (Extreme Extension)

**Status**: Ported to Python `engine/backtest/indicators.py::keltner_channels`

**Panel**: Upper (price chart overlay)

---

## Purpose

The **Keltner Channel 3.0x** identifies **extreme price extensions** relative to the 20-period SMA. When price touches or exceeds the 3.0x band, it signals **exhaustion and potential reversal**—a critical regime condition called **FADE_EXTREME** in JARVIS.

This is the most conservative Keltner variant. It is **NOT** a primary entry tool; instead, it acts as a **regime classifier and counter-trend fade trigger**:

- **3.0x band touch** = Extreme extension. Market is over-stretched. Look for counter-trend entries.
- **Close above/below 3.0x** = Alert the engine to activate FADE_EXTREME regime (reduce trend-following weight, increase mean-reversion weight).

Complement this with the dual-factor **1.5x/2.0x OB Omega** variant for a complete extension ladder.

---

## JARVIS Mapping

In the JARVIS 5-layer framework, the 3.0x Keltner serves dual roles:

### Primary Role: FADE_EXTREME Regime Trigger

| JARVIS Signal | TOS Equivalent | Interpretation |
|---|---|---|
| `FADE_EXTREME` regime active | Price crosses 3.0x band (Upper_Band or Lower_Band) | Market is over-extended. Deactivate trend entries. Prepare counter-trend fades |
| `kelt_3x_upper_touch` | Close >= Upper_Band this bar | Bull exhaustion signal. Potential short entry from resistance |
| `kelt_3x_lower_touch` | Close <= Lower_Band this bar | Bear exhaustion signal. Potential long entry from support |

### Secondary Role: Multi-Timeframe Filter

The 3.0x band provides a **regime anchor** across timeframes:
- If 1h price is above 3.0x on daily chart, the daily trend is extremely extended — expect pullback (reduce longs)
- If 1h price is below 3.0x on daily chart, the daily trend has room to extend (can hold longs longer)

**Critical**: FADE_EXTREME is **NOT** a standalone entry signal. It is a **regime gate**. Entry logic is:
```
IF regime == FADE_EXTREME:
    ENTRY_NOW only on counter-trend signals (short if price > 3x upper, long if price < 3x lower)
ELSE:
    ENTRY_NOW on trend-following signals
```

---

## TOS Inputs (Configurable Parameters)

| Parameter | Default | JARVIS Value | Notes |
|---|---|---|---|
| `iAggregationPeriod` | AggregationPeriod.FIVE_MIN | 5m | Change to HOUR, DAY for different timeframes. **Match your chart TF** |
| `iHideMidLine` | YES | YES | Toggle to hide the SMA 20 basis line (Avg) |
| `iDisplace` | 0 | 0 | Shift bands forward/backward by N bars. Leave at 0. |
| `iFactor` | 3.0 | 3.0 | **DO NOT CHANGE.** This is the signature 3x multiplier |
| `iLength` | 20 | 20 | SMA period. Matches OB Omega variant |
| `iPrice` | CLOSE | CLOSE | Price source. CLOSE recommended |
| `iAvgType` | AverageType.SIMPLE | SMA | Basis type. Must be SMA |
| `iTrueRangeAvgType` | AverageType.SIMPLE | SMA | TR smoothing. Must be SMA |

---

## Visual Elements

**Lines**:
- **Upper_Band** (3.0x factor): Upper extreme level. Price here = bull exhaustion
- **Lower_Band** (3.0x factor): Lower extreme level. Price here = bear exhaustion
- **Avg** (hidden by default): SMA 20 basis. Unhide `iHideMidLine` to see

**Colors** (default TOS scheme):
- Upper_Band: Blue
- Lower_Band: Blue
- Avg: Gray dashed (if unhidden)

**No clouds or labels** on this variant — it is minimal/clean by design.

---

## Install

### Step 1: Import the Study
1. Open ThinkOrSwim
2. Go to **Studies > Edit Studies > Create**
3. Paste the entire contents of `shared_shared_shared_shared_kelt_3.01STUDY.ts`
4. Click **OK** and name it "Keltner 3x"

### Step 2: Add to Chart
1. Open a chart at **any 5m/15m/1h/daily aggregation** (matches your trading TF)
2. Click **Studies > Add Study > My Studies > Keltner 3x**
3. Verify inputs:
   - `iAggregationPeriod` = match your chart timeframe (e.g., HOUR for 1h chart)
   - `iHideMidLine` = YES (cleaner, but unhide to debug basis support)
   - `iFactor` = 3.0 (non-negotiable)

### Step 3: Create FADE_EXTREME Alert
Create an alert that fires when price crosses the 3.0x band:
1. Right-click the chart at the Upper_Band line
2. Select **Add Alert > Condition: Alert when close > Upper_Band**
3. Set sound to **Ring** (high priority)
4. Enable **Email** + **Push notification**
5. Repeat for Lower_Band with **Alert when close < Lower_Band**

---

## Alerts

| Signal | TOS Condition | Action | Priority |
|---|---|---|---|
| Bull exhaustion (3x upper) | Close crosses above Upper_Band this bar | Exit longs OR prepare fade short | **CRITICAL** |
| Bear exhaustion (3x lower) | Close crosses below Lower_Band this bar | Exit shorts OR prepare fade long | **CRITICAL** |
| Approaching 3x (bull) | Close within 0.5% of Upper_Band | Reduce longs. Tighten stops. | Medium |
| Approaching 3x (bear) | Close within 0.5% of Lower_Band | Reduce shorts. Tighten stops. | Medium |

---

## Known Limits / Gotchas

1. **Aggregation Mismatch (Critical)**: This study auto-aggregates to the period you specify in `iAggregationPeriod`. If your chart is 1h but the input is 5m, the band will recalculate every 5-min bar and be noisy. **Always match**: chart TF = `iAggregationPeriod`.

2. **NOT a Primary Entry Tool**: Do NOT enter on 3x band alone. Use it as:
   - A regime flip (switch from TRENDING to FADE_EXTREME)
   - A counter-trend fade signal only (short when price > upper, long when price < lower)
   - A confirmation for existing longs/shorts (take profits here)

3. **Extreme = Rare**: The 3.0x band is touched infrequently. On 1h charts, it typically appears 1–3 times per week. If you see it daily, either:
   - Your aggregation is set too tight (e.g., 5m on a daily chart)
   - Volatility has spiked (market in panic mode)

4. **Basis Line Hidden by Default**: The Avg (SMA 20) is hidden to reduce clutter. Unhide it via `iHideMidLine = NO` if you want to:
   - See the actual 3x distance visually
   - Use the 20-SMA as a dynamic support/resistance
   - Debug a signal that looks off

5. **Compare to 1.5x/2.0x OB Omega**:
   - 1.5x = Moderate extension (entry ladder)
   - 2.0x = Significant extension (primary entry)
   - 3.0x = Extreme extension (fade/exit zone)
   
   See `ob_omega_keltner_5m.md` for the dual-band setup. The 3.0x should sit **outside** the typical trading range.

6. **Fade Reversals on 3x Are NOT Guaranteed**: Extreme extension often means **continued extension**. The 3.0x band identifies risk, but price can push beyond it in panic/euphoria. Use 3.0x as a **regime change signal**, not a reversal guarantee. Pair with momentum indicators (STC, MACD) for confirmation.

---

## Relationship to Engine

The Python counterpart is `engine/backtest/indicators.py::keltner_channels(factor=3.0)`:

```python
def keltner_channels(
    close: pd.Series, high: pd.Series, low: pd.Series, 
    sma_len: int = 20, atr_factor: float = 3.0
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (upper, basis, lower) for 3.0x factor."""
```

The JARVIS engine uses this to compute the **FADE_EXTREME regime condition** at `engine/agents/pipeline.py:356-379`:

```python
if kelt_3x_upper_touch or kelt_3x_lower_touch:
    regime = FADE_EXTREME
    # Reduce trend entry weight, increase mean-reversion weight
```

---

**Status**: Production ported. Python counterpart verified in `engine/backtest/indicators.py`. Multi-timeframe support live.
