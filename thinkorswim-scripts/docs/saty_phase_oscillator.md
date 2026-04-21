# Saty Phase Oscillator — ThinkScript Study

**File**: `Saty_Phase_OscillatorSTUDY.ts`  
**Author**: Saty Mahajan  
**JARVIS Layer**: Layer 1 Regime  
**Status**: Ported  
**Python counterpart**: `engine/backtest/indicators.py::phase_oscillator`  
**Panel**: Lower (sub-pane)

## Purpose

The Phase Oscillator measures price momentum relative to the 21-period EMA, normalized by 3× ATR, and outputs a score from -100 to +100. It answers: **Is price extended (extreme), compressed (tight), or neutral?** JARVIS uses the oscillator to detect:

- **Bullish/Bearish phases** (±23.6 thresholds): directional strength
- **Extended phases** (±61.8 thresholds): exhaustion signals, potential reversal zones
- **Compression** (magenta coloring): low-volatility consolidation before breakouts

Unlike directional indicators (MACD, RSI), the Phase Oscillator isolates *relative position to value*, making it ideal for mean-reversion confirmation and fade-extreme regime identification.

## JARVIS Mapping

The script implements the Phase Oscillator formula from `engine/backtest/indicators.py::phase_oscillator`:

**Formula**: `phase = (close - ema_21) / (3 × atr_14) × 100`

All parameters are **hardcoded** (no inputs to adjust):
- EMA period: **21** (pivot EMA for value baseline)
- ATR period: **14** (Wilder's standard, matches ATR Levels script)
- Bollinger Bands: **21-period, 2.0 std dev** (used for compression detection)

**JARVIS Regime Integration**:
- `phase >= 61.8`: Extended up zone → potential EXHAUSTED regime condition
- `phase <= -61.8`: Extended down zone → potential EXHAUSTED regime condition
- `phase > 23.6`: Bullish phase (above neutral, rising)
- `phase < -23.6`: Bearish phase (below neutral, falling)
- `is_compression = 1` (magenta): Bollinger Bands narrower than ATR bands → COMPRESSION regime

The compression signal directly drives JARVIS layer-1 regime classification and is used alongside the ATR Levels EMA ribbon for regime confirmation.

## TOS Inputs

| Input | JARVIS Value | Notes |
|---|---|---|
| (None — all hardcoded) | N/A | All parameters are hardcoded in the script. No adjustments needed. |

**Hardcoded parameters** (do not change):
| Parameter | Value | Source |
|---|---|---|
| `ExpAverage(close, 21)` | 21 | Pivot EMA (JARVIS ribbon middle line) |
| `ATR()` | 14 | Wilder's ATR for normalization |
| `STDev(close, 21)` | 21 | Bollinger Bands length |
| `BB std multiplier` | 2.0 | Standard Bollinger deviation |
| Phase formula divisor | `3.0 * ATR()` | Constant scaling factor |

## Visual Elements

**Oscillator Line** (thick, 2px):
- **Green coloring**: When `phase_oscillator >= 0` (above EMA, bullish bias)
- **Red coloring**: When `phase_oscillator < 0` (below EMA, bearish bias)
- **Magenta coloring**: When `is_compressed = 1` (Bollinger compression; overrides green/red)
- Range: -100 to +100 (clipped; rare to see extremes on liquid instruments)

**Horizontal Reference Lines**:
- **100.0 (light gray, dashed)**: Extended up zone ceiling
- **61.8 (gray, dashed)**: Extended up threshold (distribution zone) — JARVIS exhaustion trigger
- **23.6 (dark gray, dashed)**: Bullish/neutral boundary
- **0.0 (center)**: EMA level (implied, not plotted)
- **-23.6 (dark gray, dashed)**: Bearish/neutral boundary
- **-61.8 (gray, dashed)**: Extended down threshold (accumulation zone) — JARVIS exhaustion trigger
- **-100.0 (light gray, dashed)**: Extended down zone floor

**Compression Indicator** (thin line at 0):
- **Magenta** when compression is active (`is_compressed = 1`)
- **Dark gray** when no compression
- Thickness: 2px for high visibility

**Labels** (upper left of lower panel):
- "Compression " (magenta text) appears only when `compression_tracker == 1`
- Disappears instantly when compression ends (clean, non-cluttering design)

## Install

1. **Open ThinkOrSwim** desktop.
2. Go to **Charts** tab.
3. Click **Studies** → **Edit Studies**.
4. Click the code bracket (`</>`) to open **ThinkScript Editor**.
5. Click **Open** and select `thinkorswim-scripts/Saty_Phase_OscillatorSTUDY.ts`.
6. Click **Save As** and name it "Saty Phase Oscillator".
7. Close the editor.
8. Back in **Edit Studies**, find "Saty Phase Oscillator" and click **+**.
9. A parameters dialog appears with only one input: `show_labels` (default: yes).
   - Leave `show_labels = yes` to see the "Compression" label when it fires.
10. Click **Apply**, then **OK**.
11. The oscillator appears as a lower sub-pane below your price chart, with reference lines and the magenta compression indicator.

## Alerts

Create these alerts in TOS (**Right-click → Add Alert for Study Plot**):

| Signal | Alert Condition | Sound | Use |
|---|---|---|---|
| Phase Extended Up | `phase_oscillator` crosses above 61.8 | Ding | Price overextended — potential exhaustion, watch for reversal |
| Phase Extended Down | `phase_oscillator` crosses below -61.8 | Ding | Price overextended downside — setup for bounce/fade-extreme entry |
| Compression Active | `is_compressed` changes to 1 | Ding (optional) | Volatility contraction — expect breakout soon after compression ends |
| Bullish Phase | `phase_oscillator` crosses above 23.6 | (optional) | Momentum shifting upward — supporting bullish entries |
| Bearish Phase | `phase_oscillator` crosses below -23.6 | (optional) | Momentum shifting downward — supporting bearish entries |

## Known Limits / Gotchas

- **All Parameters Hardcoded**: Unlike ATR Levels (which has configurable inputs), the Phase Oscillator has **zero adjustable parameters**. If you need different EMA/ATR/BB periods, you must edit the source `.ts` file directly. For JARVIS alignment, do not change these values.

- **Compression Definition**: Compression detects **Bollinger Band width** vs. **ATR band width** (see lines 43–53 of the .ts file). It is NOT based on the phase value itself; it is a separate volatility check. High phase values with expanding bands = not compressed.

- **Magenta Overrides Color**: When compression is active, the oscillator line turns magenta regardless of its bullish/bearish value. This is intentional — compression state takes visual priority.

- **Lag on Compression Toggle**: The compression signal has a 1-bar lookback (`expansion_zone` check at line 52), so compression may trail the actual volatility contraction by 1–2 bars. This is by design to filter false signals.

- **Early Morning Data**: The first 21–50 bars of the trading day have incomplete EMA and Bollinger data. Oscillator values before 10:00 AM ET may be unreliable. Wait for 30+ bars of data (roughly 30 min on 1m charts, 1.5 hours on 5m charts).

- **Weekend/Gap Days**: On Monday or after a gap, the 21-period EMA resets from the new close, not the prior-week close. Phase values can jump ±20–30 points on open gaps. This is expected and not a malfunction.

- **Not a Momentum Only Tool**: The Phase Oscillator is **NOT** a buy/sell oscillator by itself (like RSI). It is a regime classifier. Use it in conjunction with STC (Layer 3 Bias) and the ATR Levels EMA ribbon (Layer 1 regime) for entry signals.

- **Intraday vs. Daily**: The oscillator works on any timeframe. However, JARVIS uses it on 1h charts (primary) and daily charts (confirmation). On 5m or 15m intraday charts, the oscillator can be noisy due to volatility spikes; apply additional filtering (e.g., wait for 2 consecutive bars in the same zone before acting).
