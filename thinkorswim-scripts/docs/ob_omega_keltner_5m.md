# OB Omega Keltner (5M) — ThinkScript Study

**File**: `shared_shared_OB_OMEGA_5mSTUDY.ts`  
**Author**: Maverick & Renegade (OB Style)  
**JARVIS Layer**: 4 Entry  
**Status**: Ported  
**Python counterpart**: `engine/backtest/indicators.py::keltner_channels`  
**Panel**: Upper (price overlay)

---

## Purpose

The OB Omega Keltner study plots dual-band Keltner Channels on your chart as horizontal reference levels. It visualizes two volatility-based support/resistance zones — an inner band (1.5× ATR) for moderate extension detection and an outer band (2.0× ATR) for significant extension detection.

The script embeds a MACD primer cloud to help identify directional momentum phases. All bands project forward as horizontal lines, labeled by aggregation period ("1hr Top", "Daily Bottom", etc.), making multi-timeframe structure visible at a glance.

---

## JARVIS Mapping

The OB Omega Keltner script feeds directly into **Layer 4 entry timing** logic:

- **Inner band (1.5x)** breach = moderate extension signal. Price touching this level in a trending market suggests momentum continuation opportunity.
- **Outer band (2.0x)** breach = significant extension signal. JARVIS treats outer band breaches as confirmed strong moves — potential partial profit-taking zones.
- **3.0x variant** (separate script `shared_shared_shared_shared_kelt_3.01STUDY.ts`) = extreme extension. When price touches 3.0× band, the engine flags `FADE_EXTREME` regime condition, signaling potential reversal or overbought exhaustion.

**Typical entry flow**:
1. Monitor price for inner band (1.5x) approach in trending regime
2. Confirm with Layer 3 bias (STC, KAMA) to validate direction
3. Inner band touch = moderate extension, consider entry on pullback or continuation
4. Outer band (2.0x) touch = strong extension, take profits or tighten stops
5. Price between basis and 1.5x upper = normal bull trend; no special signal

---

## TOS Inputs (Configuration Table)

| Parameter | Input Name | Default | Notes |
|-----------|------------|---------|-------|
| Aggregation Period | `period` | `FIFTEEN_MIN` (study default, override to `HOUR` for 1h trading) | Controls which timeframe the Keltner bands are calculated from. Set to `HOUR` for 1-hour chart trading. |
| Inner Factor | `factor` | `1.5` | Multiplier for ATR to create inner band. Matches JARVIS `keltner_channels(atr_factor=1.5)`. |
| Outer Factor | `factor2` | `2.0` | Multiplier for ATR to create outer band. Matches JARVIS `keltner_channels(atr_factor=2.0)`. |
| SMA Length | `length` | `20` | Period for the 20-bar simple moving average (basis line). Exact match to JARVIS. |
| Line Length | `lineLength` | `50` | Number of bars to project the horizontal level lines rightward. Increase to extend further into future bars. |
| Show Labels | `ShowLabel` | `YES` | Toggles chart bubbles ("1hr Top", "Daily Bottom") on the right edge of the chart. |
| Show Cloud | `ShowCloud` | `YES` | Toggles gray cloud shading between inner and outer bands. Also toggles MACD primer cloud (magenta conditional shading). |
| Show "Closed Door" | `ShowClosedDoor` | `NO` | Toggles MACD-dependent cloud (clouds appear only when MACD histogram is negative — bearish "closed door"). Advanced visualization. |

---

## Visual Elements

### Horizontal Level Lines

- **Avg** (dashed gray line) — 20-bar simple moving average of close. This is the **basis** of the channel. Price oscillates around this central level.
- **Upper_Band1** (thinner solid line, color 2) — Basis + (1.5 × ATR). Inner upper band. First resistance zone.
- **Lower_Band1** (thinner solid line, color 2) — Basis − (1.5 × ATR). Inner lower band. First support zone.
- **Upper_Band2** (thinner solid line, color 3) — Basis + (2.0 × ATR). Outer upper band. Second resistance zone; strong extension marker.
- **Lower_Band2** (thinner solid line, color 3) — Basis − (2.0 × ATR). Outer lower band. Second support zone; strong extension marker.

### Chart Bubbles (Labels)

At the right edge of the chart (20 bars ahead), labeled bubbles identify the timeframe context:
- "1hr Top" / "1hr Bottom" — Inner bands from 1-hour aggregation
- "4hr Top" / "4hr Bottom" — 4-hour bands (if aggregation period is set to 4H)
- "Daily Top" / "Daily Bottom" — Daily bands
- Similar for Weekly, Monthly

Label color is sand (RGB 255, 204, 102).

### Cloud Shading

Two conditional cloud layers create visual separation:

1. **Gray cloud** (between outer and inner bands) — Shades the space between Upper_Band2 ↔ Upper_Band1 (upper half) and Lower_Band1 ↔ Lower_Band2 (lower half). Highlights the extended zone.
2. **MACD Primer cloud** (magenta, conditional on MACD histogram sign):
   - When MACD histogram > 0 (bullish), no magenta cloud.
   - When MACD histogram < 0 (bearish), magenta cloud fills the space between the bands, warning of bearish momentum.

---

## Installation & Configuration for 1H Trading

### Step 1: Import Study

1. Open ThinkOrSwim → **Charts** tab
2. Click **Studies** (beaker icon) → **Edit Studies**
3. Click the code/script icon (`</>`) to open the ThinkScript Editor
4. Click **Open** (folder) and select `shared_shared_OB_OMEGA_5mSTUDY.ts`
5. Click **Save As** → Name it `OB Omega Keltner 5M`
6. Close the editor

### Step 2: Add to Chart

1. In **Edit Studies** dialog, find your newly saved study
2. Double-click (or click the `+` button) to add it to the chart
3. The study should appear on your price chart with horizontal lines

### Step 3: Configure for 1H Trading

1. Right-click the **OB Omega Keltner 5M** study on the chart → **Edit Studies**
2. Set these parameters:
   - `period` = `AggregationPeriod.HOUR` (NOT the default `FIFTEEN_MIN`)
   - `factor` = `1.5` (keep default)
   - `factor2` = `2.0` (keep default)
   - `length` = `20` (keep default)
   - `ShowLabel` = `YES` (keep default)
   - `ShowCloud` = `YES` (keep default)
3. Click **Apply** → **OK**

The bands will now recalculate using 1-hour OHLC data instead of 5-minute, and labels will show "1hr Top" / "1hr Bottom".

---

## Alerts & Trading Signals

### Alert Setup (Optional)

To receive audio/email notifications when price breaches the bands:

1. Right-click the chart → **Add Alert for Study Plot**
2. **Inner band breach (bullish)**: Select `Upper_Band1` plot. Condition: **"crosses above"**. Sound: Ding.
3. **Outer band breach (bullish)**: Select `Upper_Band2` plot. Condition: **"crosses above"**. Sound: Bell.
4. **Inner band breach (bearish)**: Select `Lower_Band1` plot. Condition: **"crosses below"**. Sound: Ding.
5. **Outer band breach (bearish)**: Select `Lower_Band2` plot. Condition: **"crosses below"**. Sound: Bell.

### Manual Signal Interpretation

Watch for these price action patterns:

| Price Zone | Signal | Action |
|-----------|--------|--------|
| Price touches inner band (1.5x) in bullish regime | Moderate extension | Consider entry or tighten stop |
| Price touches outer band (2.0x) in bullish regime | Significant extension | Take partial profits (50%) |
| Price between basis and inner band (1.5x) | Normal trend | Hold position, no special action |
| Price below basis | Trend weakness | Consider exiting longs or adding shorts |
| Price above outer band (2.0x) for extended bars | Potential exhaustion | Watch for reversal, don't chase |

---

## Known Limits & Gotchas

### MACD Primer Cloud Interpretation

The magenta cloud (MACD histogram < 0) is a **directional bias indicator**, not a hard entry/exit signal. It warns that momentum is bearish, but price can still trend higher on mean reversion or reversal setups. Use it as context, not confirmation alone.

### Aggregation Period Must Match Chart

If you set `period = AggregationPeriod.HOUR` but are viewing a 5-minute chart, the bands will reference 1-hour bars but plot on your 5-minute price candles. This creates a visual mismatch but is actually useful for multi-timeframe analysis — you see 1-hour levels on a 5-minute chart.

For a 5-minute trading chart, set `period = AggregationPeriod.FIVE_MIN` or `AggregationPeriod.FIFTEEN_MIN` to align bands with your candles.

### 3.0x Keltner Variant

For extreme extension detection (JARVIS `FADE_EXTREME` regime), use the separate script `shared_shared_shared_shared_kelt_3.01STUDY.ts` with `iFactor = 3.0`. See `docs/keltner_3x.md` for full documentation. The two scripts can be added to the same chart for layered band visualization.

### Line Projection Length

The `lineLength = 50` parameter controls how far forward the bands project. If you're trading with a very small window or want to reduce visual clutter, reduce this value. The bands will still calculate correctly; they just won't extend as far into the future.

---

## Related Documentation

- **INTEGRATION_GUIDE.md** — Full mapping of all 34 TOS studies to the JARVIS 5-layer framework. See Layer 4 — Entry Timing section for Keltner channel thresholds.
- **keltner_3x.md** — Documentation for the extreme extension (3.0×) variant.
- **engine/backtest/indicators.py** — Source code for `keltner_channels()` function (Python reference).

---

*Last updated: 2026-04-20*
