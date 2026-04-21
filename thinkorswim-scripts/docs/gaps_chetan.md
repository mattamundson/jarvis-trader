# GAPS_Chetan — ThinkScript Study

**File**: `thinkorswim-scripts/GAPS_Chetan1STUDY.ts`  
**Author**: Chetan  
**JARVIS Layer**: Layer 2 (Structure Map — supplementary)  
**Status**: Ported (Phase 2, commit pending)  
**Python counterpart**: `engine/backtest/gaps_chetan.py::compute_chetan_gaps`  
**Panel**: Upper

---

## Purpose

Alternative gap-finder that identifies intraday price gaps using cross-asset divergence (HYG vs SPX correlation) and assigns price bar colors based on gap magnitude thresholds. Provides supplementary confirmation of market structure imbalance.

**JARVIS role**: Layer 2 context — use alongside **Corey Gapfinder v1** for dual confirmation. Detects overnight structural gaps; persisting unfilled gaps act as support/resistance magnets. Chetan's version emphasizes **cross-asset correlation** (high-yield bonds vs SPX) as a divergence signal for gap validity.

---

## JARVIS Mapping

| Signal | Condition | Implication |
|--------|-----------|-------------|
| Divergence setup | HYG 2-bar change < 0 AND SPX 2-bar change > 0 | Yield weakness + equity strength = early gap candidate |
| Gap Down (0.10+) | Prior low - current high ≥ 0.10 pts | Bearish intraday reversal; cyan price color |
| Gap Up (0.10+) | Current low - prior high ≥ 0.10 pts | Bullish intraday reversal; orange price color |
| Neutral | Gap < 0.10 pts | Gray price color (no structural signal) |

---

## TOS Inputs

| Input | Default | Type | Notes |
|-------|---------|------|-------|
| `hyg_diff` | `close("HYG")[2]` | Price calculation | 2-bar change in HYG (high-yield bonds) |
| `spx_diff` | `close("SPX")[2]` | Price calculation | 2-bar change in SPX (broad market) |
| Gap threshold | 0.10 | Fixed threshold | Minimum gap size to trigger color assignment |

**Note**: Study uses **external symbols** (HYG, SPX, VIX, /VX). Ensure data feeds are available on your chart symbol's exchange; gaps may not display if cross-asset prices are unavailable.

---

## Visual Elements

- **CYAN Price Bars** — Gap down detected (low[1] - high > 0.10 pts)
- **ORANGE Price Bars** — Gap up detected (high[1] - low < 0.10 pts)
- **GRAY Price Bars** — No significant gap (within 0.10 pt tolerance)

Alternative logic (commented out in code) monitors **VIX vs /VX correlation** for volatility gaps — useful for option sellers and mean-reversion traders.

---

## Install

1. Open ThinkOrSwim → **Studies > Edit Studies > Create**
2. Paste contents of `GAPS_Chetan1STUDY.ts`
3. Name: `GAPS Chetan`
4. Click **OK**, then add to upper price chart
5. Study applies bar color assignment automatically

---

## Alerts

| Alert Type | Condition | Setup |
|---|---|---|
| Gap Down start | CYAN bar appears | Right-click chart → **Add Alert for Study Plot** → Watch for color change to CYAN |
| Gap Up start | ORANGE bar appears | Monitor for color change to ORANGE |
| Confluence with VWAP | Gap zone + VWAP touch | Manual: Check if current VWAP levels align with unfilled gap zones |

---

## Known Limits / Gotchas

1. **Cross-asset dependency**: Requires real-time HYG, SPX, VIX data. If feeds are delayed or unavailable, divergence logic fails silently (no color assigned).
2. **Threshold is fixed** at 0.10 pts — cannot be adjusted via inputs. May miss small gaps on thinly-traded symbols; may over-trigger on liquid symbols with normal spreads.
3. **Not a gap-fill tracker** — unlike Corey Gapfinder, this script does **not** draw horizontal lines showing unfilled gap zones. Color is episodic (only on the gap bar itself).
4. **Commented VIX logic** — original code includes unused `/VX vs VIX` divergence branch. Uncomment if researching volatility-regime gaps.
5. **No ATR normalization** — 0.10 pt threshold is absolute, not scaled to volatility. Use on stable, liquid symbols (ES, NQ, /MES) only.

---

## Complementary Studies

- **Corey Gapfinder v1** — Primary gap-finder with persistent zone tracking
- **Saty ATR Levels** — Volatility-normalized gap sizing context
- **AA_CoreyRFv2** — Rangefinder; detects expansion gaps separately
