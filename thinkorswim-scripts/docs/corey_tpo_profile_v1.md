# AA_CoreyTPOProfilev1STUDY — ThinkScript Study

**File**: `thinkorswim-scripts/AA_CoreyTPOProfilev1STUDY.ts`  
**Author**: Corey Surles  
**JARVIS Layer**: 2 Structure  
**Status**: Ported (Phase 2, commit pending)  
**Python counterpart**: `engine/backtest/tpo_profile.py::compute_tpo_profile`  
**Panel**: Upper (chart overlay)

## Purpose

The TPO Profile visualizes intraday time-price activity (Time Price Opportunity) by plotting the number of bars spent at each price level. This reveals natural support/resistance, market imbalance zones, and acceptance/rejection patterns that inform structural analysis.

The study overlays:
- **POC** (Point of Control) — price level with highest activity
- **Value Area High/Low (VAH/VAL)** — the 70% centralized band containing most trading activity
- **Profile High/Low** — extreme price boundaries
- **Fibonacci Extensions** — projected targets and rejection levels from POC
- **Imbalance Label** — quick visual confirmation of buyer vs. seller control

## JARVIS Mapping

JARVIS `layer2_structure()` computes:
- **VPOC** ≈ rolling 20-bar volume-weighted average price (approximates POC)
- **VAH/VAL** ≈ 85th/15th percentile of recent price action (approximates 70% value area)
- **Structural signals** ← BUYER_CONTROL if price > VAH + POC, SELLER_CONTROL if price < VAL + IB Low

**Important note**: This logic is **NOT yet ported to Python**. Engine signals like `layer2_structure()` use VPOC approximations and percentile-based VAH/VAL; the TOS study uses ThinkOrSwim's built-in `TimeProfile.GetPointOfControl()` and `GetHighestValueArea()` methods (tick-accurate). The mapping is directional but not 1:1. Engine porting is planned for Phase 2.

## TOS Inputs

| Input | Default | Type | Description |
|-------|---------|------|-------------|
| `showExtensions` | yes | Boolean | Toggle Fibonacci extension overlays |
| `timePerProfile` | day | Enum | Profile reset frequency (MINUTE, HOUR, day, WEEK, MONTH, BAR, chart, OPT EXP, year) |
| `customRowHeight` | 1.0 | Float | Manual price-per-row height (when mode = CUSTOM) |
| `pricePerRowHeightMode` | TICKSIZE | Enum | Row scaling: AUTOMATIC / TICKSIZE / CUSTOM |
| `multiplier` | 1 | Integer | Profile aggregation factor (1 = full periods, >1 = skips) |
| `onExpansion` | no | Boolean | Continue plotting profile after period closes |
| `profiles` | 1000 | Integer | Max retained profiles (memory limit) |
| `showPointOfControl` | no | Boolean | Highlight POC line in white |
| `showValueArea` | no | Boolean | Highlight VAH/VAL bands in cyan |
| `valueAreaPercent` | 70 | Integer | Value area percentile (70 = standard) |
| `opacity` | 50 | Integer | Profile cloud transparency (0-100) |
| `ShowLabels` | no | Boolean | Display "BullImbal"/"BearImbal" tag |
| `showclouds` | yes | Boolean | Fill Fibonacci extension zones with gradient |
| `smaLength` | 10 | Integer | Simple moving average period (colored overlay) |
| `price` | close | Series | Price source for SMA |

## Visual Elements

- **POC (white horizontal)** — Single price level with maximum TPO count
- **VAH/VAL (cyan horizontals)** — Upper/lower bounds of 70% value area
- **Profile High/Low (gray horizontals, hidden by default)** — Price extremes of current profile
- **VA Balance (magenta dash)** — Midpoint of VAH + VAL (imbalance target)
- **Fibonacci Extensions (colored)** —
  - `TPOext1` (yellow) — 1.0x extension from POC away from VAH/VAL
  - `TPOext_25`, `TPOext_38`, `TPOext_5`, `TPOext_61`, `TPOext_78` (gradient colors) — Proportional retracements
  - `TPOext2` (red) — 2.0x extreme extension
  - `TPOrej1`, `TPOrej2`, `TPOrej3` (green) — Bearish rejection targets (when VAH+VAL midpoint < POC)
- **SMA overlay** — 10-bar moving average with color fill (red below SMA = downtrend, green above = uptrend)
- **Extension clouds** — Shaded bands between `TPOext_38` and `TPOext_61` (confluence zone)

## Install

1. Open ThinkOrSwim desktop.
2. Go to **Studies > Edit Studies > Create**.
3. Paste the full contents of `AA_CoreyTPOProfilev1STUDY.ts` into the editor.
4. Click **OK**. The study will appear as a default "Untitled Study".
5. Rename to `AA_CoreyTPOProfilev1` (optional, for clarity).
6. Open any `/MES` or equity chart.
7. Click **Studies > Add Study > My Studies > AA_CoreyTPOProfilev1**.
8. The profile overlays on the upper price pane.

**Recommended settings for JARVIS**:
- `timePerProfile` = day
- `showPointOfControl` = yes
- `showValueArea` = yes
- `valueAreaPercent` = 70
- `showExtensions` = yes
- `ShowLabels` = yes (to spot imbalance quickly)

## Alerts

No built-in alerts. Use as a **visual confirmation study** alongside COHEN_MES_COMPOSITE for structural bias.

| Signal | Interpretation |
|--------|-----------------|
| Price trades **above VAH + POC midpoint** | Buyer control; bulls accepting higher prices |
| Price breaks **above Fib 1.0x extension** | Extended acceptance; bullish follow-through |
| Price clusters **inside VAH+VAL** | Consolidation zone; prepare for breakout |
| Price **rejects at Fib ext_61 or ext2** | Reversal candidate (green rejection target) |
| **BullImbal label** (when VAL < POC) | Structural strength for long entries |
| **BearImbal label** (when VAH > POC) | Structural weakness; favor short bias |

## Known Limits / Gotchas

- **Tick-accurate POC only**: TOS `TimeProfile` object computes true POC from all ticks within the period. Free data feeds may have gaps; daily charts may miss pre-market/after-hours ticks.
- **No intrabar TPO count visible**: The profile density (number of bars at each level) is rendered as a visual cloud, not a numeric readout. Hover over the profile to see approximate bar count.
- **Fibonacci levels are price-agnostic**: Extensions are computed purely from POC ↔ ProfileHigh/Low distance. They do NOT adjust for regime, volatility, or support/resistance. Use in conjunction with `COHEN_MES_COMPOSITE` for regime-aware bias.
- **VAH/VAL lag on new periods**: If `onExpansion=yes`, the study continues to show the prior period's VAH/VAL as the current period builds. This avoids repainting but can be confusing at period transitions (e.g., end of day).
- **SMA unrelated to TPO logic**: The 10-bar SMA is a secondary trend filter and does not interact with POC/VAH/VAL calculations.
- **Multiple profiles retained**: With `profiles=1000`, the study keeps 1000 historical profiles in memory. On long-running charts, this may cause slowdowns. Restart TOS or reduce to `profiles=100` if lag occurs.

## Integration Notes

- **Orphan Layer 2**: This study exists standalone and is not currently consumed by the Python engine's `layer2_structure()` function. It serves as a **reference implementation** showing how TPO concepts map to JARVIS structural bias (buyer vs. seller control above/below value area).
- **Planned Phase 2 porting**: Future work will integrate tick-accurate TPO data (if available via market data API) into the engine's signal pipeline, replacing the current VPOC approximation.
- **Use with COHEN_MES_COMPOSITE**: Pair this study with the COHEN_MES_COMPOSITE study for full structural context: TPO Profile shows *where* buyers/sellers congregated; COHEN_MES_COMPOSITE shows *when* the engine will trade based on regime + confluence.
