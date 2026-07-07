# AA_CoreySFv2STUDY — ThinkScript Study

**File**: `thinkorswim-scripts/AA_CoreySFv2STUDY.ts`  
**Author**: Corey Surles (@coreysurles)  
**JARVIS Layer**: 2 Structure (gap-fill bias)  
**Status**: Ported (Phase 2, commit pending) — `engine/backtest/singlefinder.py::compute_single_prints`  
**Panel**: Upper (study)

## Purpose

Singlefinder v2 identifies "single prints" — price levels visited only once, creating gaps in the TPO (Time Price Opportunity) profile. Bullish singles (pink lines below price) and bearish singles (orange lines above price) act as unfilled gap targets; price is magnetically drawn to fill these voids. Fail dots (price bars that attempt but fail to hold above/below a single) mark rejection points. Complements Layer 2 structure by highlighting imbalances and gap-fill trade setup zones.

## JARVIS Mapping

**Orphan Status**: No Python equivalent in `engine/agents/` or `engine/backtest/`. Port planned for Phase 2 (future session). Currently used by human traders for gap-fill bias and imbalance targeting; JARVIS imports single levels via manual observation or snapshot.

**Synergy with Pipeline**:
- Layer 2 Structure (pipeline.py:538–585): Hidden Pivots + Rangefinder identify initial balance; Singlefinder adds gap-fill confirmation (unfilled singles = price imbalance targets)
- Bias Layering (pipeline.py:348–368): Gap-fill bias feeds into time-of-day confluent re-entries. Example: if MES has unfilled bullish single at 4500, and time-filter allows long, that level becomes support for pyramid scaling.
- Signal: Fail dots (pink/orange dots at prior single level) trigger opposite-direction rejection signals.

**Integration Gotcha**: Single detection logic relies on `high[1] < low[-1]` and `high > low[-1]` (true gap, no overlap). Stocks with wide gaps gap easily; tight, 24hr futures like MES rarely show clean singles on intraday. Recommend daily+ timeframes or wide-ranging days.

## TOS Inputs (Configuration Table)

| Input | Default | Purpose | Notes |
|-------|---------|---------|-------|
| `ShowExtensions` | yes | Extend single lines to right chart edge | Horizontal lines forward-projected |
| `ShowArrows` | yes | Up/down arrows on single-print candles | Pink=bullish, Orange=bearish |
| `ShowLabels` | yes | "Bull Single Filled/Unfilled" status label | Real-time fill tracking |
| `showGaps` | yes | Require true gap (no price overlap) | If no: allow single within range |
| `ShowFailDots` | yes | Plot fail dots at prior single levels | Rejection markers; same colors as fail line |
| `ShowClouds` | no | Shade regions between single pairs | Clutter; off by default |

## Visual Elements

- **Bullish Singles (Pink)**: Horizontal lines at `low[-1]` and `high[1]` when `high[1] < low[-1]` (gap up). Two lines define the single-print gap.
- **Bearish Singles (Orange)**: Horizontal lines at `high[-1]` and `low[1]` when gap down.
- **Extension Lines**: Same colors, extended rightward if `ShowExtensions=yes`. Labels update: "Bull Single Filled" (if `close < bullExt`), "Unfilled" (if above).
- **Fail Dots**: 
  - **Bullish Fail (pink dot)** at `high[2]`: previous bar high rejected as support (bull attempt failed, turned back down)
  - **Bearish Fail (orange dot)** at `low[2]`: previous bar low rejected as resistance (bear attempt failed, turned back up)
  - Plot style: `PaintingStrategy.LINE_VS_POINTS` (line + dots at bar closes)
- **Fail Lines**: Horizontal lines at fail levels (pink/orange), drawn alongside fail dots for clarity.
- **Clouds** (optional): Shaded regions between bullExt/bullExt2 (pink) or bearExt/bearExt2 (orange) if `ShowClouds=yes`. Usually disabled (visual noise).

## Install

1. Open ThinkOrSwim → **Aggregated Charts** tab
2. **Studies** → **Edit Studies** → **Add Study**
3. Select **AA_CoreySFv2STUDY** from custom study list
   - If not visible: import `.ts` file via **Manage > Import Shared Study**
4. **Configure Inputs** (minimal setup):
   - `ShowExtensions: YES` (default)
   - `ShowArrows: YES` (visual confirmation)
   - `ShowFailDots: YES` (rejection detection)
   - `showGaps: YES` (strict single definition)
5. Apply to chart. If no singles appear: check that chart has true price gaps (common on daily+ timeframes; rare intraday on tight instruments like MES).

## Alerts

Single-finder v2 does not have built-in alert triggers in the study code. **Manual alert setup**:
- Use Study Alert: Set threshold on `bearSingleArrow` or `bullSingleArrow` == 1
- Or: Set price alert at `bullExt` or `bearExt` extension levels for gap-fill confirmation

## Known Limits / Gotchas

- **Gap Detection Strictness**: `showGaps=yes` requires zero price overlap between consecutive ranges. Stocks gap easily; MES/NQ 5-min/hourly rarely shows clean singles. **Recommendation**: Use daily timeframe or wide-range days (ATR > 2×).
- **Fail Dot Logic Bug**: `bullf` triggers when `open > high[2] and low < high[2]`. On thin data, `high[2]` may not be the true support level (especially if chart is zoomed). **Workaround**: Manual visual confirmation of fail dots; don't rely on fail alerts alone.
- **Extension Color Static**: If `dynamicClouds=no` (default), clouds stay pink/orange. Setting `dynamicClouds=yes` swaps to green/red (dynamic polarity), but this contradicts the single polarity. **Best practice**: Leave `dynamicClouds=no`, ignore clouds if enabled.
- **No Multi-Timeframe Sync**: Each timeframe shows its own singles independently. Daily singles ≠ 1H singles ≠ 5-min singles. Align manually or use multiple chart tabs.
- **Fail Dots Disappear on Pullback**: Once a fail bar closes and price moves away, the fail dot vanishes from live charts (older bars plot fine). Not a bug — expected behavior.

## References

- **Author**: Corey Surles (coreysurles on ThinkorSwim, X/Twitter @coreysurles)
- **Related**: AA_CoreyRFv2STUDY (range/expansion structure, often plotted alongside SF for gap-fill + range confluence)
- **Python Phase 2 Port**: Pending — would require gap detection logic (`high[1] < low[-1]` parity), horizontal line plotting, and fail-bar detection. Estimated ~200 lines Python + tests.
