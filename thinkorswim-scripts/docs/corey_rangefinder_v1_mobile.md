# Corey Rangefinder v1 Mobile — ThinkScript Study

> **DEPRECATED**: Use `corey_rangefinder_v2.md` instead. This variant is kept for historical reference only.

**File**: `thinkorswim-scripts/AA_CoreyRFv1MobileSTUDY.ts`  
**Author**: Corey Surles  
**JARVIS Layer**: Layer 2 (Structure Map)  
**Status**: Deprecated  
**Python counterpart**: None  
**Panel**: Upper  

---

## Purpose

Legacy mobile-optimized variant of Rangefinder that detects range expansions and plots extension targets. The v2 rewrite (`corey_rangefinder_v2.md`) supersedes this with better control-zone logic and cleaner target visualization.

This doc exists for backward compatibility only. Do not use for new chart setups — migrate to v2.

---

## JARVIS Mapping

| Signal | Condition | Implication |
|-------|-----------|-------------|
| Range expansion | New high > prior high AND new low < prior low | Volatility breakout; target extensions fire |
| Expansion target levels | 0.382, 0.50, 0.618, 0.786, 1.0, 2.0× of range | Profit-taking zones and extremity markers |
| Rejection levels | -0.5, -1.0, -3.0× (mirrored below midpoint) | Pullback targets if expansion reverses |

v1 Mobile plots fewer extension levels than v2 to keep the chart clutter-free on smaller screens.

---

## TOS Inputs

| Input | Default | Type | Notes |
|-------|---------|------|-------|
| `showExtensions` | yes | Boolean | Extend targets rightward across chart |
| `showBubblesRange` | no | Boolean | Label bubble values on chart (verbose) |
| `showArrows` | yes | Boolean | Up/down arrows on expansion triggers |

**Recommended**: Leave defaults. Disable `showBubblesRange` unless debugging target levels.

---

## Visual Elements

- **Range Trigger Lines** (red dashed):
  - Horizontal levels marking the high and low of the triggering expansion bar

- **Extension Targets** (thin lines, multiple colors):
  - Yellow (1.0x, entry reference)
  - Magenta (0.382, 0.50, 0.618 ratios)
  - Cyan (0.786 ratio)
  - Red (2.0x extreme extension)
  - White (rejection levels: -0.5, -1.0, -3.0x)

- **Arrows** (optional):
  - Green UP arrow on expansion bar when conditions met
  - Red DOWN arrow on contraction bar

---

## Install

1. Open ThinkOrSwim → **Studies > Edit Studies > Create**
2. Paste contents of `AA_CoreyRFv1MobileSTUDY.ts`
3. Name: `Corey Rangefinder v1 Mobile`
4. Click **OK**, add to upper price chart
5. In study settings, set `showExtensions=yes` and `showArrows=yes`

**Before deploying**: Verify against a v2 chart to confirm you need the mobile variant. Most users should use v2.

---

## Alerts

| Alert | Trigger |
|-------|---------|
| Expansion detected | `expandTriggerHigh` or `expandTriggerLow` plot appears (not NaN) |
| Target hit | Price crosses target extension level |

---

## Known Limits / Gotchas

- **Fewer target levels than v2** — Only major ratios plotted to reduce mobile clutter. v2 adds control-zone shading.
- **No range context** — v1 does not highlight the "control zone" (38.2–61.8% of range from POC) that v2 uses to filter false breakouts.
- **Extension lines accumulate** — Multiple overlapping expansions create visual noise; clean chart regularly or move to v2 with control-zone gating.
- **Arrow color logic simplified** — Less sophisticated secondary confirmation vs. v2's bar-structure analysis.

---

## Migration

To upgrade from v1 Mobile to v2:

1. Remove this study from chart
2. Import `AA_CoreyRFv2STUDY.ts`
3. Set inputs: `showExtensions=yes`, `showRfClouds=yes`, `showControlZone=yes`, `showArrows=yes`
4. Adjust target colors per preference (v2 defaults are more readable)
5. No parameter recalibration needed — targets use same logic

See `corey_rangefinder_v2.md` for full feature set.

