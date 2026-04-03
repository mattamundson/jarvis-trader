# COHEN-MES Composite Strategy — TOS Installation Guide
# Task A4 — JARVIS TRADER 2026-04-02

Two companion ThinkScript studies implement the COHEN-MES composite signal visually
on a ThinkOrSwim chart, mirroring `engine/backtest/composite_signals.py`.

## Files

| File | Pane | Purpose |
|------|------|---------|
| `COHEN_MES_COMPOSITE.ts` | Upper (price chart) | STC proxy + ORB + VWAP overlay with regime labels, composite arrows, stop/target lines |
| `COHEN_MES_STC_SUB.ts` | Lower (sub-pane) | True Schaff Trend Cycle oscillator with OS=15 / OB=83, divergence alerts |

---

## Step-by-Step Import into ThinkOrSwim Desktop

### Method A — Manual Paste (Recommended)

1. Open ThinkOrSwim Desktop.
2. Navigate to **Studies > Edit Studies**.
3. Click **Create** (bottom left of the Studies dialog).
4. In the Name field, type: `COHEN_MES_COMPOSITE`
5. Delete any placeholder code in the editor.
6. Open `COHEN_MES_COMPOSITE.ts` in a text editor, select all, copy.
7. Paste into the TOS ThinkScript editor.
8. Click **OK** to save.
9. Repeat steps 3-8 for `COHEN_MES_STC_SUB.ts`, naming it `COHEN_MES_STC_SUB`.

### Method B — Import via Shared Link

ThinkOrSwim supports importing studies via a URL-encoded `thinkscript://` link.
This format is not generated here, but if you export the study from TOS after
creating it via Method A, you can share it via **Studies > Share Study**.

---

## Adding the Studies to a Chart

1. Open a `/MES` chart (or `/ES` for full-size).
2. Set the aggregation period to **1 hour** (the primary validated timeframe).
3. Set Chart Style to **Candlestick**.
4. Enable **Extended Hours** for pre-market ORB context (optional but recommended).

### Add COHEN_MES_COMPOSITE (upper overlay)

- Click **Studies > Add Study > My Studies > COHEN_MES_COMPOSITE**
- This overlays directly on the price chart.

### Add COHEN_MES_STC_SUB (lower pane)

- Click **Studies > Add Study > My Studies > COHEN_MES_STC_SUB**
- TOS will automatically create a lower sub-pane for this study.

---

## Study Inputs — COHEN_MES_COMPOSITE

Open via **Studies > Edit Studies > COHEN_MES_COMPOSITE > Inputs tab**.

| Input | Default | Description |
|-------|---------|-------------|
| `atr_length` | 14 | ATR calculation period (Wilder's smoothing) |
| `band_mult` | 1.5 | VWAP band width in ATR multiples |
| `orb_minutes` | 30 | Opening Range duration from 9:30 ET |
| `atr_stop_mult` | 0.70 | Stop distance as ATR multiple |
| `atr_target_mult` | 1.50 | T1 target distance as ATR multiple |
| `adx_trend_threshold` | 25 | Minimum ADX for TRENDING regime classification |
| `show_stop_target` | yes | Toggle stop/target horizontal lines |
| `show_vwap` | yes | Toggle VWAP and ATR bands |
| `show_orb` | yes | Toggle ORB high/low levels |
| `show_regime_label` | yes | Toggle regime/ADX/ATR/score labels |
| `show_signal_arrows` | yes | Toggle all entry arrows |
| `show_ema_ribbon` | no | Toggle 8/21/34 EMA ribbon (optional) |
| `entry_threshold` | 0.35 | Minimum composite score for entry |

## Study Inputs — COHEN_MES_STC_SUB

| Input | Default | Description |
|-------|---------|-------------|
| `fast_length` | 23 | MACD fast EMA period |
| `slow_length` | 50 | MACD slow EMA period |
| `stc_length` | 10 | Stochastic smoothing lookback |
| `smooth_factor` | 3.0 | Exponential smoothing factor |
| `ob_level` | 83 | Overbought threshold |
| `os_level` | 15 | Oversold threshold |
| `show_labels` | yes | Toggle info labels |
| `show_histogram` | yes | Toggle momentum histogram |

---

## Visual Reference — What You Will See

### Upper Chart (COHEN_MES_COMPOSITE)

**Lines and Levels:**
- Cyan line: Session VWAP
- Red dashed: VWAP + 1.5x ATR (upper band)
- Green dashed: VWAP - 1.5x ATR (lower band)
- Green medium-dashed horizontal: ORB High (first 30-min candle high)
- Red medium-dashed horizontal: ORB Low (first 30-min candle low)
- Red long-dashed: Active stop level (0.70x ATR from entry)
- Green long-dashed: Active T1 target (1.50x ATR from entry)

**Arrows:**
- Large green UP arrow: Composite LONG entry (2+ signals OR score >= 0.35)
- Large red DOWN arrow: Composite SHORT entry
- Small green UP arrow: ORB breakout long (price crosses above ORB High)
- Small red DOWN arrow: ORB breakout short (price crosses below ORB Low)
- Gray triangle: Signal blocked by VOLATILE regime

**Bubbles on Entry Bars:**
- "STC" = MACD crossover signal contributed
- "ORB" = Opening range breakout contributed
- "VWAP" = VWAP band reversion contributed
- "STP -X.XX" = Stop level distance at entry
- "T1 +X.XX" = T1 target distance at entry

**Labels (upper left, left to right):**
- Regime state: TRENDING BULL / TRENDING BEAR / RANGING / VOLATILE — NO ENTRIES
- ADX value (green if > 25, gray if below)
- ATR value and normalized ATR percentage
- Composite score and signal count: "Score: 0.60  Sigs:2"

### Lower Sub-Pane (COHEN_MES_STC_SUB)

- Colored STC line: green (oversold <= 30), yellow (neutral), red (overbought >= 70)
- Gray dashed signal line: 5-period EMA of STC
- Red dashed reference at 83 (OB level)
- Green dashed reference at 15 (OS level)
- Dark gray dashed at 50 (midpoint)
- Dark red cloud above 83, dark green cloud below 15
- Histogram: STC deviation from 50, green/dark-green (bullish) or red/dark-red (bearish)
- Green UP arrow: STC crosses above 15 (bullish ignition signal)
- Red DOWN arrow: STC crosses below 83 (bearish ignition signal)
- Labels: STC value, state (OVERSOLD/OVERBOUGHT/BULLISH/BEARISH), divergence alerts

---

## Regime Logic (How TRENDING is Classified)

Unlike the original EMA-only approach, Task A4 uses a dual gate:

1. **50 EMA vs 200 EMA**: EMA50 > EMA200 = bull context; EMA50 < EMA200 = bear context
2. **ADX > 25**: Trend must have momentum — ADX below 25 classifies as RANGING regardless
   of EMA position
3. **Normalized ATR > 2%**: ATR exceeding 2% of price overrides to VOLATILE (no entries)

This means TRENDING BULL requires: ADX > 25 AND EMA50 > EMA200 AND ATR < 2% of price.

---

## Composite Entry Logic

| Regime | STC Weight | ORB Weight | VWAP Weight |
|--------|-----------|-----------|-------------|
| TRENDING | 0.60 | 0.30 | 0.10 |
| RANGING | 0.50 | 0.20 | 0.30 |
| VOLATILE | 0.00 | 0.00 | 0.00 |

Entry fires when: `weighted_score >= 0.35` **OR** `signal_count >= 2`, AND NOT volatile.

Conflict resolution: if both long and short qualify simultaneously, the higher-scoring
direction wins.

---

## Known ThinkScript Limitations

1. **STC proxy in upper study**: The upper study uses MACD(12,26,9) crossover as a
   proxy for the STC signal. The true Schaff Trend Cycle is in the sub-pane study only.
   The MACD proxy fires more frequently and earlier than the true STC OS/OB level crosses.
   For the most accurate STC signal, use the sub-pane and observe the OS=15/OB=83 arrows.

2. **Stop/target lines do not auto-close**: The `activeSignal` rec variable tracks the
   last signal direction indefinitely. The stop and target lines will remain on the chart
   after the trade is over. They reset only when an opposite signal fires. This is a
   ThinkScript architectural limitation — true "exit on stop/target hit" logic requires
   a ThinkScript Strategy (not a Study), which cannot be overlaid on price.

3. **ORB on 1-hour charts**: On 1-hour aggregation, `SecondsFromTime` precision is
   limited. The ORB opening range (first 30 minutes) will capture roughly the 9:30 bar.
   For more precise 30-min ORB, load the study on a 15-min or 5-min chart.

4. **VWAP resets daily**: TOS `vwap()` built-in resets each session. On extended-hours
   charts, VWAP starts from the overnight open, not 9:30 ET. If this matters, disable
   extended hours on the chart while using this study.

5. **ADX warm-up**: The 200-period EMA and ADX calculation require roughly 200+ bars
   of history to stabilize. On shorter lookback windows (e.g., first few weeks of data),
   regime classification may be inaccurate.

6. **`rthEnd = rthStart + orb_minutes`**: ThinkScript time arithmetic uses HHMM format
   literally. `0930 + 30 = 0960` which TOS interprets correctly as 10:00 in most cases,
   but edge cases around hour boundaries (e.g., 0945 + 30 = 0975) may misfire. The
   default 30-minute window from 9:30 (producing 0960 → 10:00) is tested and correct.

7. **No trade execution**: These are Studies, not Strategies. They provide visual signals
   only. Automated execution runs through the JARVIS engine (port 8010), not TOS.

---

## Relationship to JARVIS Engine

These studies provide **visual confirmation** of engine signals. Key differences:

| Feature | TOS Study | JARVIS Engine |
|---------|-----------|--------------|
| Regime filter | 3-state (simplified) | 5-layer (full) |
| STC | True STC in sub-pane; MACD proxy in upper | Full Schaff algorithm |
| Volume profile | Not available | Incorporated |
| R:R filter | Not applied (all signals shown) | Min 1.5:1 enforced |
| ORB source | Price data only | Confirmed with volume |
| Execution | Visual only | Automated via IB Gateway |

Use the TOS chart for context and manual discretionary confirmation.
The engine remains the primary signal source for automated trading.
