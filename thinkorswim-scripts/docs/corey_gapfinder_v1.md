# Corey Gapfinder v1 — ThinkScript Study

**File**: `thinkorswim-scripts/AA_CoreyGapfinderv1STUDY.ts`  
**Author**: Corey Surles  
**JARVIS Layer**: Layer 2 (Structure Map)  
**Status**: Ported (Phase 2, commit pending)  
**Python counterpart**: `engine/backtest/gapfinder.py::compute_gaps`  
**Panel**: Upper  

---

## Purpose

Identifies and marks overnight open-to-close gaps on price. Unfilled gaps act as price magnets and signal structural imbalance.

**JARVIS role**: Supplementary Layer 2 context. An unfilled gap **above** current price = resistance to respect before initiating longs. An unfilled gap **below** = support bounce target. Gaps extend rightward across the chart until price fills them, providing persistent visual confirmation of market structure.

---

## JARVIS Mapping

| Signal | Condition | Implication |
|--------|-----------|-------------|
| Gap Down (red lines) | Prior close > current open | Bearish overnight rejection; zone extends right until filled |
| Gap Up (green lines) | Prior close < current open | Bullish overnight acceptance; zone extends right until filled |
| Gap fill | Price re-enters gap zone | Imbalance resolved; potential reversal or continuation |

Gaps that persist for 2+ days often become **support/resistance zones** and are confluent with POC (Point of Control) from Layer 2 TPO Profile.

---

## TOS Inputs

| Input | Default | Type | Notes |
|-------|---------|------|-------|
| `showArrows` | no | Boolean | Overlay up/down directional arrows at gap bars (optional) |
| `showClouds` | no | Boolean | Shade the gap zones with color clouds (optional) |
| `GapDownStart` | close | Price field | Reference price for gap-down bar (default: prior close) |
| `GapDownEnd` | open | Price field | Lower bound of gap-down zone (default: current open) |
| `GapUpStart` | close | Price field | Reference price for gap-up bar (default: prior close) |
| `GapUpEnd` | open | Price field | Upper bound of gap-up zone (default: current open) |

**Recommended defaults**: Leave all at defaults unless you need custom gap definitions (e.g., high-to-low gap).

---

## Visual Elements

- **Gap Down Zone** — Two red horizontal lines:
  - Upper line (GDS): Prior close price (red, 3pt weight)
  - Lower line (GDE): Current open price (red, 3pt weight)
  - Extends rightward across all future bars until the zone is filled
  - Lines stay visible even when new gaps form

- **Gap Up Zone** — Two green horizontal lines:
  - Upper line (GUS): Current open price (green, 3pt weight)
  - Lower line (GUE): Prior close price (green, 3pt weight)
  - Extends rightward until filled

- **Optional Arrows** (when `showArrows=yes`):
  - Red DOWN arrow at top of gap-down bar
  - Green UP arrow at bottom of gap-up bar

- **Optional Clouds** (when `showClouds=yes`):
  - Green shading between GUS/GUE (gap-up zone)
  - Red shading between GDS/GDE (gap-down zone)

---

## Install

1. Open ThinkOrSwim → **Studies > Edit Studies > Create**
2. Paste contents of `AA_CoreyGapfinderv1STUDY.ts`
3. Name: `Corey Gapfinder v1`
4. Click **OK**, then add to upper price chart
5. (Optional) In study settings, enable `showClouds=yes` for visual clarity

---

## Alerts

| Alert | Trigger | TOS Condition |
|-------|---------|---|
| Gap fill up | Price crosses **above** GDS line | `close` crosses above GDS plot value |
| Gap fill down | Price crosses **below** GUE line | `close` crosses below GUE plot value |
| New gap formed | Gap-down or gap-up bar appears | Monitor label changes or arrow appearance |

Create alerts in **MarketWatch > Alerts > Create Alert** using the plot values as thresholds.

---

## Known Limits / Gotchas

- **Extended lines only persist once per gap** — After the gap is filled, the horizontal extensions disappear. Use TPO profile for longer-term support/resistance.
- **Gap on first bar of chart** — If a gap occurs on the first visible bar, the prior close may be off-screen; visually verify against the previous session's close.
- **Pre-market gaps** — The script uses standard open (9:30 ET) as the reference. If trading extended hours, check manually for pre-market gaps.
- **No automation** — Alerts must be set manually per gap level; the script does not auto-alert on gap fill.
- **No Python counterpart** — This is a visual-only Layer 2 supplement. Gap-fill logic is not in the JARVIS engine; rely on manual spot-checks against the TOS chart.

