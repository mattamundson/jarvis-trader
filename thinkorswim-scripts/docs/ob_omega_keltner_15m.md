# OB Omega Keltner (15M) — ThinkScript Study

**File**: `shared_shared_OB_OMEGA_15m7STUDY.ts`  
**Author**: Maverick & Renegade (OB Style)  
**JARVIS Layer**: 4 Entry  
**Status**: Ported  
**Python counterpart**: `engine/backtest/indicators.py::keltner_channels`  
**Panel**: Upper (price overlay)

---

## Purpose

The OB Omega Keltner 15M study is the 15-minute variant of the dual-band Keltner Channels visualization. It plots horizontal reference levels based on volatility (ATR) to identify moderate and significant price extensions. The inner band (1.5× ATR) signals moderate extension; the outer band (2.0× ATR) signals significant extension.

This variant defaults to **15-minute aggregation**, making it suitable for fast swing trades, scalping, or intraday breakout strategies on 15M charts.

---

## JARVIS Mapping

**Layer 4 entry timing** uses Keltner band breaches to validate momentum moves:

- **Inner band (1.5x)** touch = moderate extension. Price reaching this level in a trending regime indicates momentum is picking up — potential entry or continuation signal.
- **Outer band (2.0x)** touch = significant extension. Strong move confirmation; consider taking partial profits or tightening stops.
- **Price between basis and 1.5x** = normal bull trend. No special entry signal.
- **Price below basis** = trend weakness or mean reversion zone.

The 15M variant captures faster price action than the 1H or 5M versions, suiting traders who scalp or hold positions for 30M–2H duration.

---

## TOS Inputs (Configuration Table)

| Parameter | Input Name | Default | Notes |
|-----------|------------|---------|-------|
| Aggregation Period | `period` | `FIFTEEN_MIN` | Calculates bands from 15-minute bars. Keep this default for 15M chart trading. Override to `THIRTY_MIN` or `HOUR` if using 15M chart to see multi-timeframe levels. |
| Inner Factor | `factor` | `1.5` | Multiplier for ATR to create inner band. Matches JARVIS. |
| Outer Factor | `factor2` | `2.0` | Multiplier for ATR to create outer band. Matches JARVIS. |
| SMA Length | `length` | `20` | Period for the 20-bar simple moving average (basis). Same as 5M variant. |
| Line Length | `lineLength` | `50` | Number of bars to project the lines rightward. Increase to extend further. |
| Show Labels | `ShowLabel` | `YES` | Toggles chart bubbles showing timeframe context. |
| Show Cloud | `ShowCloud` | `YES` | Toggles gray cloud between bands and MACD primer cloud. |
| Show "Closed Door" | `ShowClosedDoor` | `NO` | Toggles MACD-dependent cloud (advanced visualization). |

---

## Visual Elements

### Horizontal Level Lines

- **Avg** (dashed gray line) — 20-bar SMA. The basis around which price oscillates.
- **Upper_Band1** (thin solid, color 2) — Basis + (1.5 × ATR). Inner upper band.
- **Lower_Band1** (thin solid, color 2) — Basis − (1.5 × ATR). Inner lower band.
- **Upper_Band2** (thin solid, color 3) — Basis + (2.0 × ATR). Outer upper band.
- **Lower_Band2** (thin solid, color 3) — Basis − (2.0 × ATR). Outer lower band.

### Chart Bubbles (Labels)

At the right edge of the chart:
- "15min Top" / "15min Bottom" — Inner/outer bands from 15-minute bars
- If `period = THIRTY_MIN`, bubbles show "30min Top" / "30min Bottom"
- If `period = HOUR`, bubbles show "1hr Top" / "1hr Bottom"

All labels use sand color (RGB 255, 204, 102).

### Cloud Shading

- **Gray cloud** — Between outer and inner bands, upper and lower regions. Highlights the extended zone.
- **MACD Primer cloud** (magenta, conditional) — Appears when MACD histogram < 0 (bearish phase), warning of momentum weakness.

---

## Installation & Configuration for 15M Trading

### Step 1: Import Study

1. Open ThinkOrSwim → **Charts**
2. Click **Studies** (beaker) → **Edit Studies**
3. Click the code/script icon (`</>`) for ThinkScript Editor
4. Click **Open** and select `shared_shared_OB_OMEGA_15m7STUDY.ts`
5. Click **Save As** → Name it `OB Omega Keltner 15M`
6. Close editor

### Step 2: Add to Chart

1. In **Edit Studies**, find your newly saved study
2. Double-click to add it to the chart
3. Bands should appear on your price chart

### Step 3: Configure for 15M Trading

1. Right-click the **OB Omega Keltner 15M** study → **Edit Studies**
2. Configure:
   - `period` = `AggregationPeriod.FIFTEEN_MIN` (default; keep unless doing multi-timeframe)
   - `factor` = `1.5` (keep)
   - `factor2` = `2.0` (keep)
   - `length` = `20` (keep)
   - `ShowLabel` = `YES` (keep)
   - `ShowCloud` = `YES` (keep)
3. Click **Apply** → **OK**

Labels will now show "15min Top" / "15min Bottom".

### Multi-Timeframe Overlay on 15M Chart

To see 1-hour levels projected onto a 15-minute chart for confluence signals:

1. Add the study twice to the chart:
   - First instance: `period = FIFTEEN_MIN` (color as blue)
   - Second instance: `period = HOUR` (color as red or orange)
2. The two band sets will overlap, showing where 15M and 1H bands align — these confluences are high-probability zones.

---

## Alerts & Trading Signals

### Alert Setup (Optional)

1. Right-click chart → **Add Alert for Study Plot**
2. **Inner band breach (up)**: `Upper_Band1` crosses above. Sound: Ding.
3. **Outer band breach (up)**: `Upper_Band2` crosses above. Sound: Bell.
4. **Inner band breach (down)**: `Lower_Band1` crosses below. Sound: Ding.
5. **Outer band breach (down)**: `Lower_Band2` crosses below. Sound: Bell.

### Trading Zones (15M Chart)

| Price Zone | Signal | Action |
|-----------|--------|--------|
| Touching inner band (1.5x) in bull regime | Momentum push | Entry or add to long |
| Touching outer band (2.0x) in bull regime | Strong extension | Take 50% profits, move stop up |
| Between basis and inner band | Normal trend | Hold, no action |
| Price below basis for 2+ bars | Trend weakness | Exit longs, consider shorts |
| Price above outer band (2.0x) for 3+ bars | Exhaustion warning | Expect pullback or reversal |

---

## Key Differences from 5M Variant

The **5M and 15M scripts are identical in logic** — they use the same Keltner algorithm and produce the same band calculations. The only difference is the default `period` setting:

- **5M script**: `period = FIFTEEN_MIN` (default, but typically overridden to `HOUR` for 1H trading)
- **15M script**: `period = FIFTEEN_MIN` (default, suitable as-is for 15M trading)

**When to use which**:
- **15M script** → Trading a 15-minute chart with 15-minute band references
- **5M script** → Trading a 5-minute chart, or a 1-hour chart with 1-hour bands
- Both → Same Python function (`keltner_channels`) in the engine

---

## Known Limits & Gotchas

### Aggregation Period Mismatch

If you view a 15-minute chart with `period = HOUR` set, the bands will be calculated from 1-hour bars but plot on 15-minute candles. This is useful for multi-timeframe analysis but can look visually "off" if you expect the bands to align with every candle. The calculation is correct; the visual offset is intentional.

### MACD Primer Cloud

The magenta cloud warns of bearish momentum but is not a hard stop signal. Price can continue rallying on mean reversion or risk-on sentiment. Use as context only.

### Line Projection and Clutter

If `lineLength = 50` extends too far into the future, reduce it to 20–30 to minimize visual clutter on busy charts.

### 3.0x Keltner (Extreme Extension)

For exhaustion/fade signals, use the separate 3.0x Keltner script. See `docs/keltner_3x.md`.

---

## Comparison with 5M Variant

| Feature | 5M Script | 15M Script |
|---------|-----------|-----------|
| Default `period` | `FIFTEEN_MIN` (typically overridden to `HOUR`) | `FIFTEEN_MIN` (suitable as-is) |
| Best for | 1H trading or multi-timeframe on 5M charts | 15M trading; fast scalps |
| Band responsiveness | Faster (if period=5M) or aligned with 1H (if overridden) | Fast, matches 15M chart |
| MACD cloud | Same (conditional on MACD histogram) | Same |
| Logic | Identical | Identical |

Choose based on your chart timeframe and trading horizon, not the script name.

---

## Related Documentation

- **INTEGRATION_GUIDE.md** — Full 5-layer JARVIS framework. Layer 4 entry thresholds and examples.
- **ob_omega_keltner_5m.md** — 5M variant documentation (nearly identical logic, different default period).
- **keltner_3x.md** — Extreme extension (3.0x) variant for exhaustion signals.
- **engine/backtest/indicators.py** — Python `keltner_channels()` source code.

---

*Last updated: 2026-04-20*
