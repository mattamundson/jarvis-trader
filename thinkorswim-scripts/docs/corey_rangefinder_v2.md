# AA_CoreyRFv2STUDY — ThinkScript Study

**File**: `thinkorswim-scripts/AA_CoreyRFv2STUDY.ts`  
**Author**: Corey Surles (@coreysurles)  
**JARVIS Layer**: 2 Structure + 4 Entry confirmation  
**Status**: Ported (Phase 2, commit pending) — `engine/backtest/rangefinder.py::compute_rangefinder`  
**Panel**: Upper (study)

## Purpose

Range Finder v2 is a dynamic volume profile that resets on each range expansion, identifying price imbalances and structural support/resistance. It plots point-of-control (POC), value area high/low (VAH/VAL), and Fibonacci extensions (38.2%–200%+) from the range midpoint. The control zone (38.2%–61.8% band) highlights balance areas. Range expansion arrows (green up, red down) signal new directional bias initiation. Acts as Layer 2 structure confirmation and Layer 4 entry context.

## JARVIS Mapping

**Orphan Status**: No Python equivalent in `engine/agents/` or `engine/backtest/`. Port planned for Phase 2 (future session). Currently used by human traders reading TOS charts; JARVIS imports range high/low + extensions via manual observation or snapshot.

**Synergy with Pipeline**:
- Layer 2 Structure (pipeline.py:538–585): Hidden Pivots + Rangefinder identify initial balance (IB) and first expansion (FE) targets
- Layer 4 Entry (pipeline.py:348–368): Time-of-day filter gates entries; Rangefinder extensions act as price imbalance magnets (unfilled gaps pull price back)
- Signal: RF midpoint anchors VAL/VAH for confluent re-entries post-breakout failure

**Integration Gotcha**: VP (VolumeProfile) calculation resets only on `exHigh == 1` (expansion event), NOT on bar/minute/hour. If `timePerProfile=RFinder`, chart must show clear range breaks or VP will hang.

## TOS Inputs (Configuration Table)

| Input | Default | Purpose | Notes |
|-------|---------|---------|-------|
| `showVP` | no | Toggle volume profile visibility | Overlays on candles; off by default for clarity |
| `showExtensions` | yes | Fibonacci extensions (0.25×–2×+custom) | Extends beyond RangeHigh/RangeLow |
| `showRfClouds` | yes | Shaded clouds between extension levels | Green=below balance, Red=above |
| `showRfBiasClouds` | yes | RF midpoint to bias line clouds | Highlights balance region |
| `showRfBalance` | yes | TPO value area balance (VAH/VAL midpt) | Yellow horizontal line |
| `showRfValue` | no | VAH/VAL individually | Cyan lines; often redundant with balance |
| `showControlZone` | yes | 38.2%–61.8% band (Fibonacci control) | Magenta zone — KEY for entry confluence |
| `showTpoExtensions` | no | TPO-based Fibonacci (0.5×–2×) | Rarely used; separate from RF extensions |
| `showTpoClouds` | no | TPO cloud shading | Clutter; off by default |
| `showProfileHiLo` | no | Profile high/low | Noise for most timeframes |
| `showArrows` | yes | Range expansion arrows (green/red) | Triggers signal confirmation |
| `showLabels` | yes | Range bias status labels ("BullImbal", etc) | Real-time balance assessment |
| `timePerProfile` | RFinder | VP reset trigger | RFinder=expansion, DAY=daily reset, HOUR=hourly, etc |
| `pricePerRowHeightMode` | TICKSIZE | VP height granularity | AUTOMATIC adapts; CUSTOM=0.25 (MES default) |
| `customRowHeight` | 0.25 | Manual row height (if CUSTOM mode) | 0.25 ticks = 2.5 points for MES |
| `multiplier` | 1 | VP scaling | 1=normal; >1 increases sensitivity |
| `showArrows` | yes | Range expansion arrows | Green=up break, Red=down break |
| `opacity` | 50 | VP fill transparency (0–100) | 50=semi-opaque |
| `showSma` | no | 10-period SMA overlay | Green/Red based on close vs SMA |

## Visual Elements

- **POC (Point of Control)**: White horizontal at highest volume price within range
- **VAH/VAL**: Cyan lines — top/bottom of 70% volume band (value area)
- **Range High/Low**: Magenta horizontals on expansion candles
- **Fibonacci Extensions**: 
  - **0.25×, 0.5×, 0.618× (control zone), 0.786×**: Color-coded as Green (bullish retest) or Red (bearish extension)
  - **1.0×–2.0×**: Primary targets; yellow=100%, magenta=extension
  - **Custom (3×–8×)**: Rarely plot; line 262 hides by default
- **Arrows**: Green up arrow on range top break + supporting candles; Red down arrow on weak top-break close
- **Imbalance Label**: Real-time status: "BullImbal" (price above balance, bullish), "BearImbal" (bearish setup), "BullFailing" (unable to hold above balance), "BearFailing" (stalling below balance)
- **Bias Clouds**: Magenta shaded region from RF entry point to range midpoint (directional bias anchor)

## Install

1. Open ThinkOrSwim → **Aggregated Charts** tab
2. **Studies** → **Edit Studies** → **Add Study**
3. Select **AA_CoreyRFv2STUDY** from custom study list
   - If not visible: import `.ts` file via **Manage > Import Shared Study**
4. **Configure Inputs**:
   - `showExtensions: YES` (default)
   - `showControlZone: YES` (key for entry confluence)
   - `showArrows: YES` (expansion signals)
   - `timePerProfile: RFinder` (critical — resets on expansion only)
5. Apply to chart. If VP doesn't render: check that chart has visible range expansions and `timePerProfile ≠ CHART` mode.

## Alerts

| Alert Type | Trigger | Use Case |
|------------|---------|----------|
| `exHigh == 1` | Range top break detected | Manual escalation; "RF has started a bias" sound |
| `exHigh[1] == 1` | Midpoint bias candle | Precision entry; "Midpoint Bias" audio |

Both fire if `alerts=yes` (default: no). Enable in Input dialog.

## Known Limits / Gotchas

- **VP Calculation Lag**: VolumeProfile object rebuilds only on range reset (`exHigh` true). If charts are narrow (few expansions), VP lags real price action by bars. **Workaround**: Use 1H or wider; MES 5-min is too noisy.
- **Control Zone Color**: Magenta lines (38.2%/61.8%) overlap with Range High/Low color. Easy to confuse. **Best practice**: Use `showLabels=yes` to see real-time zone name ("Control Zone 4485–4510" for MES).
- **Expansion Arrows False Positives**: Arrow fires on `exHigh==1 && secBar==1`, but `secBar` (secondary bar confirmation) is volatile on thin data. **False alarms on 1-min MES common**. Recommend 5-min+ or manual visual confirmation.
- **TPO vs RF Clouds**: Both `showRfClouds` and `showTpoClouds` can render. They use different baselines (RF midpoint vs TPO profile high/low). Don't enable both simultaneously unless you understand the difference.
- **Custom Extension (line 37)**: `customExtension=9` (9× range) rarely filled. Useful for extreme markets only. Hidden by default (`hideCustomExt=yes`).
- **Resets Without Breaks**: If chart shows no range break (flat consolidation), VP shows prior range's profile indefinitely. Not a bug — shows lack of expansion opportunity.

## References

- **Author**: Corey Surles (coreysurles on ThinkorSwim, X/Twitter @coreysurles)
- **Related**: AA_CoreySFv2STUDY (single-print detector, complementary Layer 2 structure)
- **Python Phase 2 Port**: Pending — would require `VolumeProfile`-equivalent (scipy.stats histogram + manual POC/VAH/VAL calculation)
