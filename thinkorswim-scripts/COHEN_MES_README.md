# COHEN-MES Composite Strategy — ThinkOrSwim Studies

Two companion studies that replicate the JARVIS TRADER COHEN-MES composite signal
engine on a ThinkOrSwim chart. Together they provide visual confirmation of
automated engine signals.

## Files

| File | Type | Pane |
|------|------|------|
| `COHEN_MES_COMPOSITE.ts` | Price overlay | Upper (chart) |
| `COHEN_MES_STC_SUB.ts` | STC oscillator | Lower (sub-pane) |

## Installation

### 1. Import into ThinkOrSwim

1. Open ThinkOrSwim desktop.
2. Go to **Setup > Open Shared Item**.
3. Alternatively, paste the script manually:
   - Click **Studies > Edit Studies > Create**.
   - Name it `COHEN_MES_COMPOSITE` (or `COHEN_MES_STC_SUB`).
   - Paste the entire `.ts` file contents into the editor.
   - Click **OK**.

### 2. Add to Chart

1. Open a **/MES** chart set to **1-hour** aggregation (the primary timeframe).
2. Click **Studies > Add Study > My Studies > COHEN_MES_COMPOSITE**.
3. Click **Studies > Add Study > My Studies > COHEN_MES_STC_SUB**.
4. The upper study appears on the price chart; the STC study appears as a lower sub-pane.

### 3. Recommended Chart Setup

- Symbol: `/MES` (or `/ES`)
- Timeframe: 1 hour (primary), 15-min or daily for confirmation
- Chart style: Candlestick
- Extended hours: ON (to see pre-market ORB context)

## Study Descriptions

### COHEN_MES_COMPOSITE (Upper Study)

The price overlay combines three independent signal sources with regime-adaptive
weighting, mirroring `engine/backtest/composite_signals.py`.

**Visual Elements:**

- **VWAP Line** (cyan) — Session VWAP with ATR-based bands
  - Upper band (red dashed) = VWAP + 2.5 x ATR(14)
  - Lower band (green dashed) = VWAP - 2.5 x ATR(14)
  - Cloud fill between bands and VWAP for quick visual reference

- **ORB Levels** (orange dashed) — Opening Range high/low
  - Computed from first 30 minutes of RTH (9:30-10:00 ET)
  - Displayed only after the ORB period completes
  - Amber cloud fill between ORB high and low

- **EMA Ribbon** (optional, off by default) — 8/21/34 EMAs
  - Toggle `show_ema_ribbon` input to display

- **Entry Arrows**
  - Green UP arrow = composite LONG entry (score >= 0.35)
  - Red DOWN arrow = composite SHORT entry (score >= 0.35)
  - Gray triangles = signal blocked by VOLATILE regime

- **Signal Source Bubbles** — On entry bars, small labels show which
  signals contributed: "STC", "ORB", "VWAP"

- **Labels** (upper left)
  - Regime: TRENDING BULL / TRENDING BEAR / RANGING / VOLATILE
  - ATR value and normalized ATR percentage
  - Composite score (green if bullish, red if bearish)

**Inputs:**

| Input | Default | Description |
|-------|---------|-------------|
| `atr_length` | 14 | ATR calculation period |
| `band_mult` | 2.5 | VWAP band multiplier |
| `orb_minutes` | 30 | Opening Range duration (minutes from 9:30) |
| `show_vwap` | yes | Toggle VWAP and bands |
| `show_orb` | yes | Toggle ORB levels |
| `show_regime_label` | yes | Toggle regime/score labels |
| `show_signal_arrows` | yes | Toggle entry arrows |
| `show_ema_ribbon` | no | Toggle 8/21/34 EMA ribbon |
| `entry_threshold` | 0.35 | Minimum composite score for entry |

### COHEN_MES_STC_SUB (Lower Study)

The Schaff Trend Cycle oscillator provides momentum confirmation. STC combines
MACD with double Stochastic smoothing to produce a fast-cycling 0-100 oscillator
that typically leads MACD by several bars.

**Visual Elements:**

- **STC Line** — Color-coded oscillator
  - Green when <= 30 (oversold zone)
  - Red when >= 70 (overbought zone)
  - Yellow when between 30-70 (neutral)

- **Signal Line** (gray dashed) — 5-period EMA of STC for crossover detection

- **Reference Lines**
  - OB at 83 (red dashed) — overbought threshold
  - OS at 15 (green dashed) — oversold threshold
  - Mid at 50 (dark gray) — neutral reference

- **Histogram** — STC deviation from 50, colored by momentum direction

- **Cross Arrows**
  - Green UP arrow when STC crosses above 15 from below (bullish ignition)
  - Red DOWN arrow when STC crosses below 83 from above (bearish ignition)

- **Labels**
  - STC value with color coding
  - State label: OVERSOLD / OVERBOUGHT / BULLISH / BEARISH
  - Divergence alerts: BULL DIV / BEAR DIV

**Inputs:**

| Input | Default | Description |
|-------|---------|-------------|
| `fast_length` | 23 | MACD fast EMA period |
| `slow_length` | 50 | MACD slow EMA period |
| `stc_length` | 10 | Stochastic lookback period |
| `smooth_factor` | 3.0 | Exponential smoothing factor |
| `ob_level` | 83 | Overbought threshold |
| `os_level` | 15 | Oversold threshold |
| `show_labels` | yes | Toggle info labels |
| `show_histogram` | yes | Toggle momentum histogram |

## Signal Interpretation

### Composite Entry Logic

The composite system scores each bar using regime-adaptive weights:

| Regime | STC Weight | ORB Weight | VWAP Weight | Behavior |
|--------|-----------|-----------|-------------|----------|
| TRENDING | 0.60 | 0.30 | 0.10 | Momentum-driven entries |
| RANGING | 0.50 | 0.20 | 0.30 | Mean-reversion emphasis |
| VOLATILE | 0.00 | 0.00 | 0.00 | No entries (sit out) |

An entry fires when the weighted score >= 0.35. This means:
- STC alone in TRENDING regime (0.60) can trigger an entry
- STC alone in RANGING regime (0.50) can trigger an entry
- VWAP alone (0.30 max) cannot trigger — needs at least one other signal
- ORB alone (0.30 max) cannot trigger — needs at least one other signal
- Any two signals agreeing will always exceed the threshold

### High-Confidence Setups

1. **Triple Confluence** — All three signals agree. Composite score = 1.00.
   Highest probability. Look for STC crossing OS/OB level + ORB break + VWAP
   bounce all on the same bar.

2. **STC + ORB Breakout** (TRENDING) — Score = 0.90. Strong momentum entry.
   Best during the 10:00-11:00 ET window when ORB breaks are most reliable.

3. **STC + VWAP Reversion** (RANGING) — Score = 0.80. Mean reversion with
   momentum confirmation. Best during 11:00-15:00 ET afternoon session.

### Regime Awareness

- **TRENDING**: EMA 8 > 21 > 34 (bull) or 8 < 21 < 34 (bear), ATR < 2% of price.
  Favor breakout entries. Let winners run.
- **RANGING**: EMAs not stacked, ATR < 2%. Favor VWAP reversion. Take profits at
  VWAP or opposite band.
- **VOLATILE**: ATR > 2% of price. NO ENTRIES. Gray triangle markers show where
  signals were blocked. Wait for regime shift.

## Relationship to Engine

These studies are a visual approximation of the Python engine signals. Key differences:

- Engine uses the full 5-layer regime filter; TOS uses a simplified 3-state classifier
- Engine STC uses exact Schaff algorithm; TOS sub-pane uses the same double-stochastic
- Engine can look at volume profile and order flow; TOS uses price-only signals
- Engine applies R:R filtering (min 1.5:1); TOS shows all qualifying signals

Use these studies for **visual confirmation** and discretionary context.
The engine remains the primary signal source for automated execution.
