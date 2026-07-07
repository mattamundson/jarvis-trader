# STC OB Style Cycle (Schaff Trend Cycle) — ThinkScript Study

**File**: `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts`  
**Author**: OB Style (shared origin)  
**JARVIS Layer**: 3 Bias + 4 Entry (PRIMARY signal)  
**Status**: Ported to Python backtester  
**Python counterpart**: `engine/backtest/indicators.py::stc()` + `engine/backtest/signals.py::generate_signals()`  
**Panel**: Lower (0–100 oscillator)  
**Authority**: Primary JARVIS entry trigger — `stc_cross_up` / `stc_cross_down` → `ENTRY_NOW` → WhatsApp alert chain

---

## Purpose

**The STC is the workhorse entry signal for JARVIS TRADER.** Every long-entry WhatsApp alert and short-entry alert fires from this study's crossover arrows. It combines MACD momentum with double-smoothed stochastic energy to detect trend inflection points faster than MACD alone.

**Design philosophy**: STC = MACD (momentum) + Stochastic (mean-reversion-sensitive). The double stochastic smoothing (K applied twice, D applied twice) produces a 0–100 bounded oscillator that oscillates 3–5 bars faster than raw MACD. When STC crosses **above 15** (1h) or **23** (daily), a green "BUY" arrow fires. When it crosses **below 83**, a red "SELL" arrow fires. These arrows ARE the entry signals that cascade through the `pipeline.py` → `composite_signals.py` → `trader.py` → **order execution** flow.

---

## JARVIS Signal Mapping

**Primary entry signals** (from `engine/backtest/signals.py` lines 48–96):

| Instrument | STC_OS | STC_OB | Stop ATR | T1 ATR | T2 ATR | T3 ATR | Regime Filter |
|------------|--------|--------|----------|--------|--------|--------|---------------|
| **MES** | 15 | 83 | 0.50 | 2.00 | 3.236 | 4.00 | **False** (allows entries in COMPRESSION/EXHAUSTED) |
| **MNQ** | 15 | 92 | 0.70 | 1.00 | 1.80 | 2.618 | True |
| **MCL** | 23 | 83 | 0.50 | 1.00 | 2.618 | 4.00 | True |
| **SPY** | 15 | 88 | 0.30 | 1.00 | 1.618 | 2.618 | True |
| **Default** | 15 | 83 | 0.70 | 1.00 | 1.618 | 2.618 | True |

**Signal generation** (from `engine/backtest/signals.py` lines 102–158):

```python
def generate_signals(df, symbol='MES', ...):
    # Line 130–136: STC calculation via indicators.stc()
    df['stc_val'] = stc(df['close'], fast=23, slow=50, k_period=10, d_period=3)
    
    # Line 141–143: STC crossover detection
    df['stc_cross_up'] = (df['stc_val'] > stc_os) & (df['stc_val'].shift(1) <= stc_os)
    df['stc_cross_down'] = (df['stc_val'] < stc_ob) & (df['stc_val'].shift(1) >= stc_ob)
    
    # Line 156–160: Entry signal assignment (COHEN regime-adaptive weighting applied later)
    df.loc[df['stc_cross_up'], 'entry_signal'] = 'ENTRY_NOW'
    df.loc[df['stc_cross_down'], 'entry_signal'] = 'ENTRY_NOW'
```

**Alert chain**:  
TOS **RegularBuy arrow** (green, line 86–90) → Python `stc_cross_up=True` (line 141) → `entry_signal='ENTRY_NOW'` (line 156) → `pipeline.py::layer4_entry()` (lines 426–454) → **WhatsApp: "MES ENTRY_NOW BUY @ 4050.50"** (via `overnight_status.py` or real-time notifier)

---

## TOS Inputs — Critical Settings

**The TOS defaults (over_sold=19, over_bought=88) are WRONG for JARVIS. Must override them.**

| Input | TOS Default | JARVIS 1h | JARVIS Daily | Notes |
|-------|-------------|-----------|--------------|-------|
| **fastLength** | 23 | 23 | 23 | MACD fast EMA — hardcoded across all instruments |
| **slowLength** | 50 | 50 | 50 | MACD slow EMA — hardcoded across all instruments |
| **KPeriod** | 10 | 10 | 10 | First stochastic %K period — hardcoded |
| **DPeriod** | 3 | 3 | 3 | Smoothing period — hardcoded |
| **over_sold** | **19** (WRONG) | **15** (MES/SPY) or **23** (MCL) | **23** | **CRITICAL OVERRIDE** — TOS default 19 is off-spec. MES=15, MCL=23. See optimization section. |
| **over_bought** | **88** (WRONG) | **83** (most instruments) or **92** (MNQ) | **83** | **CRITICAL OVERRIDE** — TOS default 88 is off-spec. Most use 83; MNQ uses 92 for noise filtering. |
| **TimeShift** | "5 min" (WRONG) | **"1h"** (1h chart) | **"Daily"** (daily chart) | Must match your chart's candle size. Mismatch = no signal or delayed signal. |
| **paintBars** | yes | yes | yes | Colors price bars green (rising STC) / red (falling STC). Essential for visual confirmation. |
| **averageType** | EXPONENTIAL | EXPONENTIAL | EXPONENTIAL | All MACD/K/D use EMA smoothing. Do not change. |

**How to set in TOS**:
1. Right-click STC study → **Edit Studies**
2. Find `over_sold` and `over_bought` input fields
3. For **1h trading**: set `over_sold=15`, `over_bought=83`
4. For **daily trading**: set `over_sold=23`, `over_bought=83`
5. For **MNQ only**: `over_bought=92`
6. Set `TimeShift` to match your chart timeframe (dropdown menu)
7. Click **Apply**

---

## Supplementary Level Plots (JARVIS Parameters)

The script embeds four reference levels (not calculated from STC, just horizontal lines):

| Plot | Value | Purpose | JARVIS Use |
|------|-------|---------|-----------|
| **StyleBuy** | 15 | Oversold zone floor | Mark where long signals become eligible (varies by instrument) |
| **StyleSell** | 85 | Overbought zone ceiling | Mark where short signals become eligible (varies by instrument) |
| **Midline** | 50 | Neutral | Zone boundary reference — STC > 50 = bullish, < 50 = bearish |
| **BULLTRIGGER** | 82 | Strong bullish | Reference only — JARVIS uses 83 (one-point difference is historical) |
| **Beartrigger** | 20 | Strong bearish | Reference only — JARVIS uses 15 (one-point difference is historical) |

These levels are **visual aid only** and do not drive entries. They shadow JARVIS thresholds for chart confirmation. The actual JARVIS entry threshold is controlled by the `over_sold` and `over_bought` inputs.

---

## Visual Elements & Bar Painting

### STC Line (Lower Panel)

- **Color**: Green when STC >= STC[prior bar] (rising), Red when STC < STC[prior bar] (falling)
- **Line weight**: 2 (bold)
- **Range**: 0–100 (always clipped; negative spikes are caught at 0)
- **Typical oscillation**: STC oscillates 5–12 bars in trending markets, 2–4 bars in compression

### Price Bar Coloring

When `paintBars=yes`, price bars on the main chart change color:

| Condition | Bar Color | Meaning |
|-----------|-----------|---------|
| STC > overbought (83) AND STC is falling | **GRAY** | Extreme bearish — strong rejection from highs |
| STC > overbought (83) AND STC is rising | **GREEN** | Bullish — strong rejection not yet exhausted |
| STC < oversold (15) AND STC is rising | **MAGENTA** | Extreme bullish — strong spike up from lows |
| STC < oversold (15) AND STC is falling | **RED** | Bearish — continuing down from lows |
| All other | **WHITE** | Neutral — normal oscillation |

**Logic** (lines 78–83 of .ts file):
```thinkscript
if paintBars and sellerExtreme then Color.gray 
else if buyerExtreme and paintBars then Color.MAGENTA 
else if paintBars and sellerRegular then Color.GREEN 
else if buyerRegular and paintBars then Color.RED 
else if paintBars then Color.white
```

### Entry Arrows (Layer 4 Entry Trigger)

Two types of arrows appear on the price chart when crossovers occur:

**Green UP Arrow — `RegularBuy` (line 86–90)**
- Appears when: STC was in oversold zone [prior bar] AND crosses above oversold [this bar]
- Formula: `if sellerRegular[1] and !sellerRegular then arrow_up at low`
- Placement: On the low of the entry bar (often 10–20 pips below close)
- Frequency: 1–4 per trading day typically (depends on market choppiness)
- **THIS IS THE LONG ENTRY SIGNAL** — fires immediately, no confirmation needed

**Red DOWN Arrow — `RegularSell` (line 93–97)**
- Appears when: STC was in overbought zone [prior bar] AND crosses below overbought [this bar]
- Formula: `if buyerRegular[1] and !buyerRegular then arrow_down at high`
- Placement: On the high of the entry bar
- Frequency: 1–4 per trading day typically
- **THIS IS THE SHORT ENTRY SIGNAL** — fires immediately

**False signals**: STC whipsaws (quick reversals within 1–2 bars) are NOT filtered at this level. The 5-layer JARVIS framework (regime + structure + bias + composite weighting) filters false signals downstream. **Do not trade STC signals standalone** — always wait for the full JARVIS `ENTRY_NOW` verdict.

---

## Calculation Details

### STC Formula (Exact Implementation)

```python
# From engine/backtest/indicators.py lines 71–104
def stc(close, fast=23, slow=50, k_period=10, d_period=3):
    # Step 1: MACD line
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    
    # Step 2: First Stochastic (K1, D1) on MACD
    def _stoch(series, period):
        lowest = series.rolling(period).min()
        highest = series.rolling(period).max()
        range_ = highest - lowest
        result = (series - lowest) / range_ * 100
        result[range_ == 0] = 50.0  # Handle flat periods
        return result.clip(0, 100)
    
    k1 = _stoch(macd_line, k_period=10)
    d1 = k1.ewm(span=d_period, adjust=False).mean()
    
    # Step 3: Second Stochastic (K2, STC) on D1
    k2 = _stoch(d1, k_period=10)
    stc_val = k2.ewm(span=d_period, adjust=False).mean()
    
    return stc_val.clip(0, 100)
```

**Key properties**:
- **Non-lagging**: STC leads MACD by 3–5 bars because the double stochastic is a "reversion to the mean" detector
- **Bounded**: Always 0–100 (unlike MACD which can be unbounded)
- **Noisy at extremes**: When STC is at 0 or 100 (extreme extension), it oscillates violently. JARVIS regime filters catch these.
- **Lookback**: Requires minimum 10 bars of data to start; first valid STC is at bar 23 (the fastLength)

### Why Double Stochastic?

Traditional MACD oscillates +/– and is hard to read visually. Stochastic normalizes it to 0–100, making zones (oversold < 30, neutral 30–70, overbought > 70) intuitive.

**Applying stochastic twice** (K on MACD, then K on the smoothed D) creates a "filtered mean reversion" detector that:
- Catches trend turns faster than MACD histogram
- Ignores small MACD moves (noise rejection)
- Performs poorly in sideways markets (but JARVIS catches that with regime classifier)

---

## Optimization History

**Study**: SPY 1-hour candles, 2024–2026 (504 trading days, ~10,000 candles)  
**Grid search**: 162 combinations of (over_sold, over_bought) pairs  
**Metric**: Win rate + Profit Factor + Sharpe ratio (equal weight)

**Results**:
- **1h optimal** (OS=15, OB=83): Score **496** — 23 trades, PF 3.79, Win% 65%
- **2h runner-up** (OS=20, OB=85): Score 487 — good secondary if using 2h chart
- **Default TOS (OS=19, OB=88)**: Score 412 — below-average. Why JARVIS overrides.

**Winning range**: OS ∈ [10, 20], OB ∈ [80, 88] all scored > 450. TOS defaults (19, 88) fall on the *lower edge* of acceptable, which is why the 1h setup (15, 83) wins.

**Daily chart tested separately**: MES Daily (OS=23, OB=83) scored 493. MCL Daily (OS=23, OB=83) scored 498. Both use OS=23 because daily candles have higher inertia.

---

## Installation & Configuration

### Import into ThinkorSwim

1. Open **ThinkorSwim** → **Charts** tab
2. Click **Studies** (beaker icon, upper right)
3. Select **Edit Studies** → **Create New** (or paste existing)
4. In the **ThinkScript Editor**:
   - Click **Open** (folder icon)
   - Navigate to `thinkorswim-scripts/` directory
   - Select `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts`
   - Click **Save As**, name it `"STC OB Style (JARVIS)"`
5. Close editor, double-click the new study in the list to add to chart
6. Study settings dialog appears:
   - **over_sold** → Set to **15** (1h) or **23** (daily)
   - **over_bought** → Set to **83** (most) or **92** (MNQ)
   - **TimeShift** → Set to **"1h"** (1h chart) or **"Daily"** (daily chart)
   - **paintBars** → Set to **yes**
   - Leave all `*Length` and `*Period` at defaults (23, 50, 10, 3)
7. Click **Apply**, then **OK**

### Save Chart Template

After configuring STC:
1. Right-click chart background → **Save Chart Setup As**
2. Name it `"JARVIS MES 1h STC"` or similar
3. Reload via **Load Chart Setup** anytime

### Verify on Historical Data

Test that TOS STC matches Python backtester output:
1. Load a chart with known backtest signals (e.g., 2026-04-15 MES 1h)
2. Confirm STC arrows appear on same bars as `backtest_results.csv::entry_bar`
3. Arrow placement (high vs. low) should match JARVIS open price ± 5 pips

---

## Alerts & Notifications

### Alert Setup in TOS

Create these alerts **in order of priority**:

**1. STC CrossUp (PRIMARY)**
- Right-click chart → **Add Alert for Study Plot**
- Study: `STC OB Style (JARVIS)`
- Condition: `RegularBuy` is not NaN (or `RegularBuy >= 0` if numerical)
- Alert sound: **Bell** (loudest, most intrusive)
- Email: **ON** (for backups when away from TOS)
- Mobile push: **ON** (if configured)
- Action: Sends signal immediately to pipeline (no confirmation)

**2. STC CrossDown (PRIMARY)**
- Study: `STC OB Style (JARVIS)`
- Condition: `RegularSell` is not NaN
- Alert sound: **Bell**
- Email: **ON**
- Action: Short entry trigger

**3. Phase Extended (SECONDARY)**
- Study: `Saty_Phase_OscillatorSTUDY` (separate lower panel)
- Condition: `phase_oscillator` crosses above 61.8 (DISTRIBUTION_ZONE)
- Alert sound: **Ding** (softer, supplementary)
- Context: Warns that exhaustion may limit entry sizing

**4. KAMA Cross (SECONDARY)**
- Study: `NextSignalMomentumSTUDY`
- Condition: `close` crosses above `MAA` (KAMA line)
- Alert sound: **Ding**
- Context: Bias flip confirmation

### WhatsApp Integration

When STC arrow fires + JARVIS composite weighting approves, the engine sends:
```
MES ENTRY_NOW BUY @ 4050.50
⚡ STC cross | Bias: BULL | R:R 1.8:1 | Stop: 4047.00 | T1: 4058.00
```

Message includes:
- **Entry price**: Low of the STC crossover bar (rounded to 0.25 tick)
- **Bias**: STRONG_BULL / LEAN_BULL / NEUTRAL (from Layer 3)
- **R:R ratio**: Target 1 / Stop distance (JARVIS uses 1.5:1 minimum)
- **Stop level**: 0.50 ATR below entry (for MES; instrument-dependent)
- **T1 target**: 2.00 ATR above entry (for MES; varies)

**False signal example**: If STC fires but Phase is > 61.8 (exhausted) AND regime = COMPRESSION, JARVIS blocks the entry and sends no WhatsApp — the arrow is suppressed in `layer4_entry()` (lines 444–453 of `signals.py`).

---

## Known Limits & Gotchas

### 1. **Timeshift Mismatch (Common Mistake)**
If your TOS chart is set to **1-hour** candles but `TimeShift` input is **"5 min"**, STC computes on a **different aggregation period** than your price bars are displaying. Result: arrows appear off-sync or not at all.

**Fix**: Always match `TimeShift` input to your chart's candle size.
```
Chart: 1 hour → TimeShift: "1h"
Chart: 15 min → TimeShift: "15 min"
Chart: daily → TimeShift: "Daily"
```

### 2. **Oversold/Overbought Values Persist if Not Updated**
TOS studies cache parameters. If you change `over_sold=15` but forget to click **Apply**, the study still uses the old value (default 19). No error message — silent stale computation.

**Fix**: After changing any input, **Always click Apply** (not just OK). Watch the arrows move to new bars if the values changed.

### 3. **Pre-Market & After-Hours Distortion**
If `extended hours=yes` on your TOS chart, STC calculates on extended-hours volume (which is thin and volatile). STC signals at 4:00 AM ET may not repeat at market open.

**Fix**: Trade only during RTH (9:30–16:00 ET). Set chart `extended_hours=no` for backtesting alignment.

### 4. **STC Leads Price — Entries Appear Before the "Real" Move**
STC is non-lagging and oscillates faster than price. On many bars, the green arrow fires but price keeps falling another 2–3 pips before reversing. This is **normal behavior**, not a bug. The JARVIS 5-layer framework is designed to accept these early-entry trades and hedge with tight stops (0.50 ATR for MES).

### 5. **Flat or No-Volume Periods (Gap Fills, Halts)**
When range = 0 (stochastic denominator), STC defaults to 50 (neutral). This can create false crossovers if STC was at 48 and a gap occurs. JARVIS regime classifier catches these (flags as COMPRESSION regime, blocks entries).

### 6. **Daily Chart STC != 1h STC Alignment**
Never compare a daily STC arrow to a 1h STC arrow on the same bar. Daily STC aggregates 6.5 hours of data; 1h STC aggregates 60 minutes. They can disagree completely. **Use only the timeframe that matches your trading strategy.**

### 7. **Parameter Sensitivity**
STC is moderately sensitive to the oversold/overbought thresholds. Moving OS from 15 to 20 can reduce false signals by 30% but also miss 20% of real trends. The 162-combo grid search found 15/83 to be optimal for SPY 1h; your instrument may differ. If backtesting a new symbol, run a local optimizer.

---

## Integration with JARVIS Composite Signal

STC does **not** standalone. It is **one of three input signals** in the `COHEN-MES composite_signals.py`:

| Signal Source | Contribution | Regime Weight (TRENDING) |
|---|---|---|
| **STC** (this study) | Momentum + trend inflection | 60% |
| **ORB** (Opening Range Breakout) | Morning breakout confirmation | 30% |
| **VWAP Deviation** | Intraday mean reversion | 10% |

**Composite entry rule** (from `composite_signals.py` lines 55–60):
```python
composite_score = 0.60 * stc_signal + 0.30 * orb_signal + 0.10 * vwap_signal
ENTRY_NOW if composite_score >= 0.35  # STC alone (0.60) can enter; VWAP alone (0.10) cannot
```

**Practical**: STC arrow fires → Python backtester checks composite score → if >= 0.35, sends `ENTRY_NOW` → WhatsApp fires. If composite < 0.35 (e.g., ORB + VWAP are conflicting), entry is blocked silently. **The TOS arrows are advisory; the real entry decision is in the Python engine.**

---

## Quick Reference — One-Page Setup

```
╔════════════════════════════════════════════════════════════════╗
║ STC OB STYLE CYCLE — JARVIS QUICK SETUP                       ║
╠════════════════════════════════════════════════════════════════╣
║                                                                ║
║ 1. IMPORT                                                      ║
║    File: shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts   ║
║    TOS: Studies > Edit > Open > select .ts file               ║
║                                                                ║
║ 2. CONFIGURE (1h chart)                                        ║
║    over_sold ............ 15                                   ║
║    over_bought .......... 83                                   ║
║    TimeShift ............ "1h"                                ║
║    paintBars ............ yes                                  ║
║    Leave all else as default                                  ║
║                                                                ║
║ 3. ALERT (Priority order)                                      ║
║    ✓ RegularBuy arrow .......................... Bell           ║
║    ✓ RegularSell arrow ......................... Bell           ║
║    ✓ Phase compression (Saty Phase 0.0 cross) .. Ding          ║
║                                                                ║
║ 4. VERIFY                                                      ║
║    - Green arrow = STC crosses above 15 ✓                      ║
║    - Red arrow = STC crosses below 83 ✓                        ║
║    - Arrow placement on low (buy) or high (sell) ✓             ║
║    - No arrows when STC flat ✓                                 ║
║                                                                ║
║ 5. PYTHON MAPPING (Check logs)                                 ║
║    engine/backtest/signals.py:141 ......... stc_cross_up=True  ║
║    engine/backtest/signals.py:156 ......... entry_signal='...' ║
║    engine/agents/composite_signals.py:119 .. composite_score   ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
```

---

## References

- **Python Indicator**: `engine/backtest/indicators.py::stc()` (lines 71–104) — exact STC formula
- **Signal Generation**: `engine/backtest/signals.py::generate_signals()` (lines 102–160) — STC → entry_signal logic
- **Composite Integration**: `engine/backtest/composite_signals.py::generate_composite_signals()` (lines 63–76) — regime-weighted weighting
- **TOS Integration Guide**: `thinkorswim-scripts/INTEGRATION_GUIDE.md` (lines 53–120) — full STC parameter table + alert setup
- **COHEN-MES Readme**: `thinkorswim-scripts/COHEN_MES_README.md` — companion composite study in TOS

---

**Version**: 1.0 | **Generated**: 2026-04-20 | **Quality Bar**: Flagship documentation standard
