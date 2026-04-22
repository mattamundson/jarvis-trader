# AA_CoreyTscorev2STUDY — ThinkScript Study

**File**: `thinkorswim-scripts/AA_CoreyTscorev2STUDY.ts`  
**Author**: Corey Surles  
**JARVIS Layer**: 2 Structure  
**Status**: Ported (Phase 2, commit pending)  
**Python counterpart**: `engine/backtest/tpo_score.py::compute_tpo_score`  
**Panel**: Lower (sub-pane indicator)

## Purpose

The TPO Score quantifies price position relative to Point of Control (POC), Value Area High/Low (VAH/VAL), and the imbalance midpoint into a single numeric signal. A positive score indicates buyers in control; a negative score indicates sellers in control. The study combines five sub-scores (VAH distance, VAL distance, POC distance, imbalance distance, and absolute value area balance) into a composite metric for quick structural assessment.

## JARVIS Mapping

JARVIS `layer2_structure()` interprets buyer/seller control as:
- **BUYER_CONTROL** — price > VAH AND price > POC (structural strength)
- **SELLER_CONTROL** — price < VAL AND price < POC (structural weakness)
- **NEUTRAL_STRUCTURE** — inside value area or mixed signals

The TOS study's TPO Score directly maps to this logic:
- **Score > close** = Positive (green) = Buyers in control
- **Score = close** = Neutral (yellow) = Balance/consolidation
- **Score < close** = Negative (pink/magenta) = Sellers in control

**Important note**: This logic is **NOT yet ported to Python**. The TOS study computes scores based on tick-accurate VAH/VAL (via ThinkOrSwim's `TimeProfile` API). The engine uses percentile-based approximations (85th/15th percentile of rolling 20-bar highs/lows). The signals are directionally aligned but not numerically equivalent. Engine integration is planned for Phase 2.

## TOS Inputs

| Input | Default | Type | Description |
|-------|---------|------|-------------|
| `pricePerRowHeightMode` | TICKSIZE | Enum | Row scaling: AUTOMATIC / TICKSIZE / CUSTOM |
| `customRowHeight` | 1.0 | Float | Manual price-per-row when mode = CUSTOM |
| `timePerProfile` | day | Enum | Profile reset: MINUTE, HOUR, day, WEEK, MONTH, BAR, chart, OPT EXP, year |
| `multiplier` | 1 | Integer | Profile aggregation (1 = full, >1 = skip periods) |
| `onExpansion` | no | Boolean | Continue scoring after period closes |
| `profiles` | 1000 | Integer | Max retained profiles |
| `showPointOfControl` | no | Boolean | Show POC in yellow (visual reference) |
| `showValueArea` | no | Boolean | Show VAH/VAL (visual reference) |
| `valueAreaPercent` | 70 | Integer | Value area percentile |
| `opacity` | 50 | Integer | Cloud transparency |
| `showMovingAvgs` | no | Boolean | Overlay 3/8/13 EMAs and SMA |
| `showLabels` | yes | Boolean | Display structural state labels |
| `showLabels1` | yes | Boolean | Display TPO Score + POC + Value Area labels |
| `showLabels2` | yes | Boolean | Display profile target/pass-fail labels |
| `showClouds` | no | Boolean | Fill Fibonacci extension zones |
| `showTargets` | no | Boolean | Show extension target zones |
| `scorePositiveColor` | 6 (green) | Integer | Color code for positive scores |
| `scoreNegativeColor` | 5 (pink) | Integer | Color code for negative scores |

## Visual Elements

- **Price line (white dash)** — Current close, reference baseline
- **POC (yellow dot)** — Point of control marker
- **VAH/VAL (cyan horizontals)** — Value area bounds (visual guides, often hidden)
- **Profile High/Low (magenta horizontals)** — Period extremes (visual guides)
- **VA Balance (pink dash)** — Midpoint of VAH + VAL (imbalance target)

**Lower sub-pane plots:**

- **TPO Score line** — Composite metric (green if > close, pink if < close, yellow if = close)
  - Computed as: `scorevah + scoreval + scorepoc + scorevabal + scoreimbal + close`
  - Colorized by result: green for buyer control, pink for seller control
  
- **Moving averages** (optional) — 3-bar SMA, 8/13-bar EMAs with color coding

**Labels (always shown unless disabled):**

1. **Bear/Bull Imbalance Label** — "BearImbal" (pink) when VAH+VAL midpoint > POC; "BullImbal" (green) when midpoint < POC
2. **TPO Score State** — "Positive" (green) | "Neutral" (blue) | "Negative" (pink) | "N/A"
3. **Balance Position** — "Sellers offsides above X" | "Buyers offsides below Y" | "Balance flat at Z" (shows nearest tick value)
4. **POC Control** — "Buyers in Control above X" | "Sellers in Control below Y" (shows POC price, rounded to tick)
5. **Value Area Position** — "Price is inside/above/below Value" + nearest VAH/VAL reference price
6. **Profile Targets** — "This profile targets [ext1] fail targets [rej2]" (entry/exit price levels)
7. **Pass/Fail Status** — "This profile is successful" | "This profile is failed" | "Targets are still Open"

## Install

1. Open ThinkOrSwim desktop.
2. Go to **Studies > Edit Studies > Create**.
3. Paste the full contents of `AA_CoreyTscorev2STUDY.ts` into the editor.
4. Click **OK**. The study will appear as a default "Untitled Study".
5. Rename to `AA_CoreyTscorev2` (optional).
6. Open any `/MES` or equity chart.
7. Click **Studies > Add Study > My Studies > AA_CoreyTscorev2**.
8. The study appears as a lower sub-pane indicator.

**Recommended settings for JARVIS**:
- `timePerProfile` = day
- `showPointOfControl` = yes
- `showLabels` = yes
- `showLabels1` = yes
- `showLabels2` = yes (to track profile success/failure)
- `scorePositiveColor` = 6 (green for buyer control)
- `scoreNegativeColor` = 5 (pink for seller control)

## Alerts

No built-in alerts. Use as a **real-time scoreboard** for structural bias and profile success/failure.

| Label/Signal | Interpretation |
|--------------|-----------------|
| **"TPO Score is Positive"** (green) | Buyers in control; structural strength; favor long bias |
| **"TPO Score is Negative"** (pink) | Sellers in control; structural weakness; favor short bias |
| **"Buyers in Control above X"** | Price above POC; bullish structural support at X |
| **"Sellers in Control below Y"** | Price below POC; bearish structural resistance at Y |
| **"Price is above Value"** | Price accepted above VAH; extended strength |
| **"Price is below Value"** | Price accepted below VAL; extended weakness |
| **"Price is inside Value"** | Consolidation; prepare for breakout |
| **"This profile is successful"** | Profile extended beyond first extension target; momentum active |
| **"This profile is failed"** | Price rejected back inside value area; range-bound |
| **"Targets are still Open"** | Profile structure uncertain; monitor next bar for confirmation |

## Known Limits / Gotchas

- **Score is not directional**: The computed score mixes distance metrics (VAH offset + VAL offset + POC offset + balance offset + imbalance sign). A **high positive score** does not guarantee bullish momentum; it indicates cumulative buyer positioning. Use with `COHEN_MES_COMPOSITE` for regime/momentum context.

- **Tick-size sensitivity**: The score is scaled by `ticsize`, which adapts for low-priced (<$500) and high-priced (>$500) instruments. On `/MES`, ticsize = 0.25 * 4 = 1.0. Scores will differ across symbols.

- **Pass/Fail logic is deterministic, not predictive**: A "successful" profile means price moved beyond the first extension target. This does NOT predict future direction. The label is retrospective confirmation, useful for backtesting bias but not forward signal.

- **VAH/VAL lag on intraday transitions**: If `onExpansion=yes`, the study continues showing the prior period's VAH/VAL midpoint until the next period closes. This avoids repainting but can mask structural shifts near period boundaries.

- **Multiple profiles in memory**: With `profiles=1000`, long-running charts may accumulate many historical profiles, causing lag. Reduce to `profiles=100` if performance suffers.

- **Labels are redundant**: The study displays 7 overlapping labels. They are all derived from the same 5 sub-scores (scorevah, scoreval, scorepoc, scorevabal, scoreimbal). Disable `showLabels`, `showLabels1`, `showLabels2` individually to reduce clutter.

## Integration Notes

- **Orphan Layer 2**: Like TPO Profile, this study is NOT yet integrated into the Python engine. It serves as a **reference implementation** for how structural scoring can be derived from POC/VAH/VAL metrics.

- **Engine approximation gap**: The engine's `layer2_structure()` uses simpler binary checks (price > VAH = BUYER_CONTROL; price < VAL = SELLER_CONTROL). The TOS study uses a continuous composite score, which is richer but harder to port without tick-accurate data.

- **Planned Phase 2 porting**: When the engine gains access to tick-level profile data, this TPO Score logic will replace the current structural signal with a numeric confidence metric (0.0–1.0) instead of discrete BUYER/SELLER/NEUTRAL states.

- **Use with COHEN_MES_COMPOSITE + TPO Profile**: Pair this lower-pane indicator with the upper-pane TPO Profile study and the composite study for full context:
  - TPO Profile (upper) = *where* price congregated (levels)
  - TPO Score (lower) = *what the structure says* (positive/negative bias)
  - COHEN_MES_COMPOSITE (upper) = *when to trade* (regime + entry thresholds)
