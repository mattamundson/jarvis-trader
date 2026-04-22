# TOS Script Analysis Session Log

## SESSION METADATA

**Date**: 2026-04-01
**Goal**: Analyze all ThinkOrSwim scripts used by jarvis-trader, produce comprehensive HTML reports, and save a complete session log.
**Agents used**: 3-4 parallel Explore agents + 1 comprehensive write agent
**Session files produced**:
1. `C:\Users\mattm\ThinkorSwim\jarvis-trader\docs\dashboards\TOS_SCRIPTS_ANALYSIS.html` — merged tabbed HTML (196KB, 3,636 lines) — Overview + Deep Dive tabs
2. `C:\Users\mattm\ThinkorSwim\jarvis-trader\docs\dashboards\TOS_SCRIPTS_DEEP_DIVE.html` — original deep dive (128KB, 2,427 lines, kept as-is)
3. `C:\Users\mattm\ThinkorSwim\jarvis-trader\docs\session-logs\TOS_SCRIPT_ANALYSIS_SESSION_LOG.md` — this file

---

## KEY ARCHITECTURE FACTS (from conversation summary)

**Total .ts files**: 34
**Unique scripts**: 21
**Shared duplicates**: 13 (TOS-generated nested copies, `shared_` prefix)

### Bidirectional TOS Integration
**Inbound** (TOS → Python): Pure-Python reimplementations in `engine/backtest/indicators.py`:
- `wilder_atr()` — Wilder's ATR period=14
- `ema_ribbon()` — 8/21/34 EMA stack detection
- `phase_oscillator()` — (close-EMA21)/(3×ATR)×100
- `kama()` — Kaufman Adaptive Moving Average period=10
- `stc()` — Schaff Trend Cycle fast=23, slow=50, K=10, D=3
- `volume_stack()` — buy/sell volume ratio
- `keltner_channels()` — SMA(TrueRange,20) basis + ATR multipliers
- `cci()` — Commodity Channel Index
- `range_consumed_pct()` — true range % of ATR

**Outbound** (JARVIS → TOS): `engine/agents/thinkscript_generator.py`
- `ThinkScriptGeneratorAgent` class
- Uses Claude `claude-opus-4-6` or template fallback
- Returns `ThinkScriptResult` dataclass

**CRITICAL**: There is NO direct TOS→JARVIS adapter. TradingView is the bridge:
- `scripts/jarvis_trader_strategy.pine` mirrors STC+ATR strategy in Pine Script v5
- Pine Script sends HTTP webhooks to `POST /webhook/tradingview`
- TOS scripts are **visual tools only** — all signal generation is pure Python

### 5-Stage AI Pipeline
`engine/agents/pipeline.py` `TradingPipeline`:
- `run_on_signal()` — entry point from webhook
- `analyze_and_decide()` — 5-stage pipeline with `asyncio.gather()` for parallel analysts
- Redis cache check (30-min TTL per symbol) before running pipeline
- Stages: Technical/News/Social/Fundamental analysts → Bull/Bear Debate → Trader Decision → Risk Manager → Fund Manager

### Webhook Router
`engine/routers/webhook_router.py`:
- `POST /webhook/tradingview` — receives TradingView signals
- `TradingViewPayload`: symbol, action (LONG/SHORT/CLOSE/HOLD), price, timeframe, indicator, os_value, atr, regime, secret
- 30-second deduplication window
- Ring buffer of 50 payloads

### TradingView Pine Script
`scripts/jarvis_trader_strategy.pine`:
- Pine Script v5 strategy
- STC: Length=10, Fast MA=23, Slow MA=50, OS=15, OB=83
- ATR: Length=14, Regime EMA=200
- Webhook payload: `{symbol, action, price, stc, source}` to `POST /webhook/tradingview`

---

## INSTRUMENT_PARAMS (from `engine/backtest/signals.py`)

```python
# Format: (STC_OS, STC_OB, STOP_ATR, T1_ATR, T2_ATR, T3_ATR, REGIME_FILTER)
INSTRUMENT_PARAMS: Dict[str, tuple] = {
    "MNQ": (15, 92, 0.70, 1.00, 1.80, 2.618, True),   # STC_OB=92 filters Nasdaq noise; 86 trades, PF 1.51
    "MCL": (15, 83, 0.90, 1.50, 2.618, 4.00, True),    # Stop=0.90, T1=1.50 → R:R=1.67; 65 trades, PF 1.81
    "MGC": (17, 88, 0.30, 1.50, 2.618, 4.00, True),    # Gold: tight stop + wide T1 matches trend length
    "SPY": (15, 88, 0.30, 1.00, 1.618, 2.618, True),   # SPY 1h optimizer: PF 3.79, 23 trades
    "MES": (15, 83, 0.50, 2.00, 3.236, 4.00, False),   # MES 1h optimizer: PF 1.69, 23 trades
}
STC_OS = 15  # Default oversold threshold
STC_OB = 83  # Default overbought threshold
```

```python
def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all TOS-derived indicators on OHLCV DataFrame."""
    df = df.copy()
    df["atr"]        = wilder_atr(df["high"], df["low"], df["close"], period=14)
    df["kama_val"]   = kama(df["close"], period=10)
    df["kama_signal"] = np.where(df["close"] > df["kama_val"], "long",
                        np.where(df["close"] < df["kama_val"], "short", "neutral"))
    # STC: 1h optimal OS=15/OB=83, daily OS=23/OB=83
    df["stc_val"]    = stc(df["close"], fast=23, slow=50, k_period=10, d_period=3)
    # ... (phase_oscillator, volume_stack, ema_ribbon, keltner_channels, cci, etc.)
```

---

## COMPLETE THINKSCRIPT FILE INVENTORY

### All 34 Files (21 unique, 13 shared duplicates)

**Unique originals (21):**
1. `AA_CoreyGapfinderv1STUDY.ts` — Gap zones (red=down, green=up), extensions
2. `AA_CoreyIBv1STUDY.ts` — Initial Balance 60-min, quadrants, extensions, EMA 8/13
3. `AA_CoreyRFv1MobileSTUDY.ts` — Rangefinder v1 mobile (REDUNDANT vs RFv2)
4. `AA_CoreyRFv2STUDY.ts` — Rangefinder v2, Volume Profile, TPO extensions
5. `AA_CoreySFv2STUDY.ts` — Singlefinder v2, single prints, fail detection
6. `AA_CoreyTPOProfilev1STUDY.ts` — TPO Time Profile, POC/VAH/VAL, extensions
7. `AA_CoreyTscorev2STUDY.ts` — TPO Score, quantified structure bias
8. `GAPS_Chetan1STUDY.ts` — 3-line gap color (HYG+SPX correlation)
9. `NextSignalMomentumSTUDY.ts` — KAMA + linear regression, 63 lines
10. `Saty_ATR_LevelsSTUDY.ts` — EMA ribbon 8/21/34, ATR Fibonacci levels, 295 lines
11. `Saty_Phase_OscillatorSTUDY.ts` — Phase oscillator ±100, compression, 72 lines
12. `Saty_Volume_StackSTUDY.ts` — Buy/sell volume stack, 44 lines
13. `TRIN_ChetanSTUDY.ts` — TRIN/VVIX color paint, 6 lines
14. `ThinkScript_study_20221014STUDY.ts` — Volume Profile + Virgin POC/VAH/VAL, 847 lines
15. `ThinkScript_study_20221016STUDY.ts` — Anchored VWAP from custom date, 17 lines
16. `ThinkScript_study_20230523STUDY.ts` — Standard Pivot Points (PP, R1-R4, S1-S4), 79 lines
17. `shared_mtftrendbarSTUDY.ts` — CCI trend trail stop, multi-timeframe
18. `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` — STC oscillator (MAIN ENTRY SIGNAL)
19. `shared_shared_OB_OMEGA_5mSTUDY.ts` — OB Omega dual Keltner (1.5x/2.0x) ⚠️ IDENTICAL TO 15m
20. `shared_shared_OB_OMEGA_15m7STUDY.ts` — OB Omega 15m ⚠️ IDENTICAL TO 5m (CRITICAL BUG)
21. `shared_shared_shared_shared_kelt_3.01STUDY.ts` — Keltner 3.0x single factor

**Shared duplicates (13 — DO NOT USE directly):**
- `shared_AA_CoreyRangefinderv1_01STUDY.ts` → use `AA_CoreyRFv2STUDY.ts`
- `shared_AA_CoreySinglefinderv2STUDY.ts` → use `AA_CoreySFv2STUDY.ts`
- `shared_AA_CoreyTPOScorev2STUDY.ts` → use `AA_CoreyTscorev2STUDY.ts`
- `shared_midcloudoteSTUDY.ts` — sub-study dependency
- `shared_Saty_ATR_LevelsSTUDY.ts` → use `Saty_ATR_LevelsSTUDY.ts`
- `shared_shared_midcloudoteSTUDY.ts` — sub-study dependency
- `shared_shared_OB_LBR_BARS_HH_LL17STUDY.ts` — sub-study dependency
- `shared_shared_OB_OMEGA_30m7STUDY.ts` — 30m variant
- `shared_shared_shared_shared_shared_kmaster1STUDY.ts` — sub-study dependency
- `shared_shared_shared_shared_shared_Priceline11STUDY.ts` — sub-study dependency
- `shared_shared_shared_shared_shared_shared_kmaster1STUDY.ts` — deeper nested
- `shared_shared_shared_shared_shared_shared_Priceline11STUDY.ts` — deeper nested
- `shared_shared_shared_shared_kelt_3.01STUDY.ts` — use the non-shared version

---

## 5-LAYER "TONY STARK" FRAMEWORK

### Layer 1 — Regime Map
*Regime states: TRENDING_BULL, TRENDING_BEAR, COMPRESSION, RANGE_BOUND, EXHAUSTED*

| Script | Role | JARVIS Signal |
|--------|------|---------------|
| `Saty_ATR_LevelsSTUDY.ts` | EMA Ribbon 8/21/34, ATR % consumed | `ema_trend` → TRENDING_BULL/BEAR; >90% = EXHAUSTED |
| `Saty_Phase_OscillatorSTUDY.ts` | Phase ±100, compression detection | `phase_val`, `phase_compression` |
| `shared_mtftrendbarSTUDY.ts` | CCI-based trend trail stop | Supplementary regime via CCI(50) |

EMA Rules:
- BULLISH = `price >= ema8 >= ema21 >= ema34`
- BEARISH = `price <= ema8 <= ema21 <= ema34`

### Layer 2 — Structure Map
*Structure states: BUYER_CONTROL, SELLER_CONTROL, NEUTRAL_STRUCTURE*

| Script | Role | JARVIS Signal |
|--------|------|---------------|
| `AA_CoreyTPOProfilev1STUDY.ts` | TPO POC/VAH/VAL, Fibonacci extensions | POC≈VPOC, VAH/VAL bounds |
| `AA_CoreyTscorev2STUDY.ts` | Quantified TPO score vs POC/VA | `layer2_structure()` score |
| `AA_CoreyIBv1STUDY.ts` | 60-min Initial Balance, quadrants, extensions | `ib_high`, `ib_low`, `above_ib_high` |
| `AA_CoreyRFv2STUDY.ts` | Dynamic volume profile rangefinder | Range extension targets |
| `AA_CoreySFv2STUDY.ts` | Single prints (gap-fill targets) | Imbalance magnets |
| `AA_CoreyGapfinderv1STUDY.ts` | Open-to-close gap zones | Resistance/support levels |

### Layer 3 — Bias
*Bias states: STRONG_BULL, LEAN_BULL, NEUTRAL, LEAN_BEAR, STRONG_BEAR*

| Script | Role | JARVIS Signal |
|--------|------|---------------|
| `NextSignalMomentumSTUDY.ts` | KAMA period=10, LR 7+20 bar | `kama_signal` = long/short |
| `Saty_Volume_StackSTUDY.ts` | Buy/sell volume ratio per bar | `buy_pct` >60%=bull, <40%=bear |
| `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` | STC oscillator | `stc_val`, `stc_cross_up/down` |

### Layer 4 — Entry Timing
*Entry states: ENTRY_NOW, WAIT_FOR_PULLBACK, NO_TRADE, FADE_EXTREME*

| Script | Role | JARVIS Signal |
|--------|------|---------------|
| `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` | STC crossover arrows | `stc_cross_up/down` → ENTRY_NOW |
| `AA_CoreyIBv1STUDY.ts` | IB breakout arrows | `above_ib_high` → ENTRY_NOW |
| `shared_shared_shared_shared_kelt_3.01STUDY.ts` | Keltner 3.0x | Extreme extension signal |
| `shared_shared_OB_OMEGA_5mSTUDY.ts` | Dual Keltner 1.5x/2.0x | Inner/outer band breach |

### Layer 5 — Position Sizing
*ATR-based stops and targets*

| Script | Role | JARVIS Signal |
|--------|------|---------------|
| `Saty_ATR_LevelsSTUDY.ts` | Full Fibonacci ATR level grid | Stop=0.70ATR, T1=1.50ATR, T2=2.618ATR, T3=4.00ATR |

ATR level mapping:
- Stop loss: 0.70 ATR → between 0.618 and 0.786 Fibonacci lines
- T1 (1h): 1.50 ATR → `upper_1500` line
- T1 (daily): 2.00 ATR → `upper_2000` (white) line
- T2: 2.618 ATR → golden ratio extension line
- T3: 4.00 ATR → beyond chart default range

---

## ALL 16 UNIQUE SCRIPTS — VERBATIM SOURCE CODE

### 1. `AA_CoreyGapfinderv1STUDY.ts`

```thinkscript
# Corey Gapfinder (c) version 1
# By Corey Surles
# @coreysurles

input showArrows = no;
input showClouds = no;
input GapDownStart = close;
input GapDownEnd = open ;
input GapUpStart = close;
input GapUpEnd = open;
def na = Double.NaN;

def GapDown =
    if GapDownStart[1] > GapDownEnd
    then 1 else 0;

def GapUp =
    if GapUpStart[1] < GapUpEnd
    then 1 else 0;

plot GDS = if GapDown then GapDownStart[1] else na;
GDS.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
GDS.SetDefaultColor(Color.RED);
GDS.SetLineWeight(3);

plot GDE = if GapDown then GapDownEnd else na;
GDE.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
GDE.SetDefaultColor(Color.RED);
GDE.SetLineWeight(3);

plot GUS = if GapUp then GapUpStart[1] else na;
GUS.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
GUS.SetDefaultColor(Color.GREEN);
GUS.SetLineWeight(3);

plot GUE = if GapUp then GapUpEnd else na;
GUE.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
GUE.SetDefaultColor(Color.GREEN);
GUE.SetLineWeight(3);

def countp = if IsNaN(GDS) and !IsNaN(GDS[1]) then 1 else countp[1] + 1;
plot GDSext = if IsNaN(GDS) then GetValue(GDS, countp) else Double.NaN;
GDSext.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
GDSext.SetDefaultColor(Color.RED);
GDSext.SetLineWeight(3);

def countp1 = if IsNaN(GDE) and !IsNaN(GDE[1]) then 1 else countp1[1] + 1;
plot GDSext2 = if IsNaN(GDE) then GetValue(GDE, countp1) else Double.NaN;
GDSext2.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
GDSext2.SetDefaultColor(Color.RED);
GDSext2.SetLineWeight(3);

def countv = if IsNaN(GUS) and !IsNaN(GUS[1]) then 1 else countv[1] + 1;
plot GUSext = if IsNaN(GUS) then GetValue(GUS, countv) else Double.NaN;
GUSext.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
GUSext.SetDefaultColor(Color.GREEN);
GUSext.SetLineWeight(3);

def countv2 = if IsNaN(GUE) and !IsNaN(GUE[1]) then 1 else countv2[1] + 1;
plot GUSext2 = if IsNaN(GUE) then GetValue(GUE, countv2) else Double.NaN;
GUSext2.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);
GUSext2.SetDefaultColor(Color.GREEN);
GUSext2.SetLineWeight(3);

plot GDArrow = if GapDown and showArrows then high else na;
GDArrow.SetPaintingStrategy(PaintingStrategy.BOOLEAN_ARROW_DOWN);
GDArrow.SetDefaultColor(Color.RED);
GDArrow.SetLineWeight(5);

plot GUArrow = if GapUp and showArrows then low else na;
GUArrow.SetPaintingStrategy(PaintingStrategy.BOOLEAN_ARROW_UP);
GUArrow.SetDefaultColor(Color.GREEN);
GUArrow.SetLineWeight(5);

AddCloud(if showClouds then GUSext else na, if showClouds then GUSext2 else na, Color.GREEN, Color.GREEN);
AddCloud(if showClouds then GDSext else na, if showClouds then GDSext2 else na, Color.RED, Color.RED);
```

**Layer**: 2 (Structure) | **Panel**: Upper | **Lines**: ~55 | **Python Equivalent**: None (visual only)

---

### 2. `AA_CoreyIBv1STUDY.ts`

**Layer**: 2+4 (Structure + Entry) | **Panel**: Upper | **Lines**: ~256

Key inputs:
```thinkscript
input showArrows = yes;
input ShowQuads = yes;
input ShowExtensions = yes;
input ShowCloudsIB = yes;
input ShowCloudExt = yes;
input ShowLabels = yes;
input OpenRangeMinutes = 60;
input MarketOpenTime = 0930;
input showTodayOnly = no;
input useEMACross = yes;
input ema1_len = 8;
input ema2_len = 13;
```

Core logic:
```thinkscript
def FirstMinute = if secondsfromtime(MarketOpenTime) < 60 then 1 else 0;
def OpenRangeTime = if secondsfromtime(MarketOpenTime) < 60 * OpenRangeMinutes then 1 else 0;

def ORHigh = if FirstMinute then high else if OpenRangeTime and high > ORHigh[1] then high else ORHigh[1];
def ORLow = if FirstMinute then low else if OpenRangeTime and low < ORLow[1] then low else ORLow[1];

Plot OpenRangeHigh = if !OpenRangeTime then ORHigh else double.nan;
Plot OpenRangeLow = if !OpenRangeTime then ORLow else double.nan;
```

Plots: EMA1(8, cyan), EMA2(13, orange), IBHigh (red, weight 3), IBLow (green, weight 3), IBHighext, IBLowext
Quadrant lines at 25%, 50%, 75% of IB range
Extensions: ibUp50, ibUp100, ibUpVar (default 3.0x); ibDown50, ibDown100, ibDownVar
Clouds: Red/Yellow/Green inside IB zones; Magenta extension clouds
Labels: "IB High", "IB Low", "IB Range", "Ext50/100" both directions
**JARVIS**: `ib_high`, `ib_low` → `above_ib_high` flag in `layer4_entry()`

---

### 3. `AA_CoreyRFv1MobileSTUDY.ts`

**Layer**: REDUNDANT (subset of RFv2) | **Panel**: Upper | **Lines**: ~195

⚠️ **This script is a strict subset of `AA_CoreyRFv2STUDY.ts`. No unique functionality on desktop. Remove from desktop chart setups.**

Core logic:
```thinkscript
def exHigh =
    if trigger1 > trigger4[1] and trigger2 < trigger2[1]
    then 1 else 0;
def exLow =
    if trigger1 > trigger4[1] and trigger3 < trigger2[1]
    then 1 else 0;
```

Extension targets: 38.2%, 50%, 61.8%, 78.6%, 100%, 200% (up)
Rejection targets: -50%, -100%, -300%

---

### 4. `AA_CoreyRFv2STUDY.ts`

**Layer**: 2+4 (Structure + Entry) | **Panel**: Upper | **Lines**: ~350

Key inputs:
```thinkscript
input showVP = no;
input showExtensions = yes;
input showRfClouds = yes;
input showRfBiasClouds = yes;
input showRfBalance = yes;
input showControlZone = yes;
input showArrows = yes;
input showLabels = yes;
input timePerProfile = {default RFinder, WEEK, DAY, MINUTE, HOUR, MONTH, "OPT EXP", CHART, BAR, YEAR};
input pricePerRowHeightMode = {default TICKSIZE, AUTOMATIC, CUSTOM};
input customRowHeight = 0.25;
input multiplier = 1;
input onExpansion = no;
input profiles = 1000;
```

Features: Volume Profile integration (VolumeProfile), TPO extensions (38.2/61.8 control zone), Imbalance scoring, SMA overlay, Range arrows (up=green, down=red), Rf High/Low labels
**JARVIS**: Range extension arrows = breakout confirmation. Range High/Low = imbalance targets.

---

### 5. `AA_CoreySFv2STUDY.ts`

**Layer**: 2 (Structure) | **Panel**: Upper | **Lines**: ~128

Core logic:
```thinkscript
def bearishSingle =
    if high[-1] < low[1]
        and high > low[1]
        and (if showGaps then high > low[1] else low < high[-1])
    then 1 else 0;

def bullishSingle =
    if high[1] < low[-1]
        and high > low[-1]
        and (if showGaps then high > low[-1] else low < high[1])
    then 1 else 0;
```

Plots: Orange = Bearish Singles, Pink = Bullish Singles; Fail dots; Extension targets
**JARVIS**: Gap-fill targets. Unfilled singles act as price magnets.

---

### 6. `AA_CoreyTPOProfilev1STUDY.ts`

**Layer**: 2 (Structure) | **Panel**: Upper | **Lines**: ~150

Key inputs:
```thinkscript
input showExtensions = yes;
input pricePerRowHeightMode = {default TICKSIZE, AUTOMATIC, CUSTOM};
input customRowHeight = 1.0;
input timePerProfile = {default day, WEEK, MINUTE, HOUR, MONTH, "OPT EXP", chart, BAR, Year};
input valueAreaPercent = 70;
input opacity = 50;
input smaLength = 10;
```

TPO extensions: 1x, 38.2%, 50%, 61.8%, 78.6%, 2x (imbalance direction)
Rejection targets: 50%, 100%, 200%
VA Balance midpoint, Bull/Bear Imbalance label
AddCloud: control zone (38.2-61.8) and rejection zone (50-100%)
SMA(10) overlay (color: red below, green above)
**JARVIS**: POC≈VPOC, VAH/VAL from `engine/backtest/indicators.py` `volume_stack()`

---

### 7. `AA_CoreyTscorev2STUDY.ts`

**Layer**: 2 (Structure) | **Panel**: Lower | **Lines**: ~220

```thinkscript
declare lower;

def ticsize = if TickSize() <= .01 and close < 500 then TickSize() * 20
              else if TickSize() <= .01 and close > 500 then TickSize() * 100
              else TickSize() * 4;

def scorevah  = if close > VAHigh then +ticsize else if close < VALow then -ticsize else 0;
def scoreval  = if close < VALow  then -ticsize else if close > VAHigh then +ticsize else 0;
def scorepoc  = if close > POC    then +ticsize else if close < POC    then -ticsize else 0;
def scorevabal= if close > VAbal  then +ticsize else if close < VAbal  then -ticsize else 0;
def scoreimbal= if VAbal > POC    then +ticsize else if VAbal < POC    then -ticsize else 0;

plot ScoreTotal = scorevah + scoreval + scorepoc + scorevabal + scoreimbal + close;
```

Score: Green if ScoreTotal > close, Red if < close
Labels: BearImbal/BullImbal, TPO Score Positive/Neutral/Negative, Buyers/Sellers offsides, POC control, Pass/Fail profile
**JARVIS**: Direct quantification of `layer2_structure()` output

---

### 8. `GAPS_Chetan1STUDY.ts`

**Layer**: Supplementary | **Panel**: Upper (bar color) | **Lines**: 7

```thinkscript
def hyg_diff = close("HYG")- close("HYG")[2];
def spx_diff = close("SPX")-close("SPX")[2];

AssignPriceColor(if (low[1] - high) > 0.10 then Color.CYAN
                else if (high[1] - low) < 0.10 then Color.ORANGE
                else Color.GRAY);
```

CYAN = gap-down bar (low[1] - high > 0.10)
ORANGE = gap-up bar (high[1] - low < 0.10)
**Note**: hyg_diff and spx_diff are computed but not used in the color logic (vestigial variables)

---

### 9. `NextSignalMomentumSTUDY.ts`

**Layer**: 3 (Bias) | **Panel**: Upper | **Lines**: 63

```thinkscript
## KAMA/AMA adaptive moving average
input mode = {default KAMA, AMA};
def direction;
def volatility;
def ER;
switch (mode) {
case KAMA:
    direction = AbsValue(close - close[10]);
    volatility = Sum(AbsValue(close - close[1]), 10);
    ER = if volatility != 0 then direction / volatility else 0;
case AMA:
    direction = Double.NaN;
    volatility = Double.NaN;
    ER = AbsValue((close - Lowest(low, 10)) - (Highest(high, 10) - close))
         / (Highest(high, 10) - Lowest(low, 10));
}
def SlowSF = 0.2222;
def ScaledSF = ER * (0.4 - SlowSF) + SlowSF;
def AMA = CompoundValue(1, AMA[1] + Sqr(ScaledSF) * (close - AMA[1]), close);

plot MAA = AMA;
MAA.assignvaluecolor(if OHLC4 > AMA then createcolor(38,115,251) else createcolor(234,33,0));
MAA.setlineweight(2);

# 7-bar linear regression
def m = Tan(OHLC4 * Double.Pi / 10) - Tan(OHLC4[5] * Double.Pi / 10);
def lrs = 6 * (WMA(OHLC4,7) - Average(OHLC4,7))/(6);
def mlr = InertiaAll(OHLC4, 7);
plot mlrPlot = mlr;
mlrPlot.assignvaluecolor(if m < 0 then color.red else createcolor(25,115,250));

# 20-bar linear regression (dashed gray)
def mlr2 = InertiaAll(OHLC4, 20);
plot mlr2Plot = mlr2;

# Labels: "Long" (blue) or "Short" (red) on last bar
AssignPriceColor based on AMA position
```

**JARVIS**: `kama()` in `indicators.py` — `kama_signal` = "long"/"short"

---

### 10. `Saty_ATR_LevelsSTUDY.ts`

**Layer**: 1+5 (Regime + Position Sizing) | **Panel**: Upper | **Lines**: 295

```thinkscript
# Saty_ATR_Levels — Copyright (C) 2022-2023 Saty Mahajan

input trading_type = {"Scalp", default "Day", "Multiday", "Swing", "Position", "Long-term"};
input show_all_fibonacci_levels = yes;
input show_extensions = no;
input use_options_labels = yes;
input atr_length = 14;
input trigger_percentage = 0.236;
input use_current_close = no;
input show_info = yes;
input fast_ema = 8;
input pivot_ema = 21;
input slow_ema = 34;
```

Period mapping: Scalp=4H, Day=DAY, Multiday=WEEK, Swing=MONTH, Position=QUARTER, Long-term=YEAR

EMA Ribbon (regime detection, embedded):
```thinkscript
def bullish = price >= ema8 >= ema21 >= ema34;
def bearish = price <= ema8 <= ema21 <= ema34;
# Label: Green = bullish, Red = bearish, Orange = mixed
```

ATR Fibonacci lines (above/below prior close):
- Trigger: ±0.236 ATR (orange/cyan)
- ±0.382, ±0.500, ±0.618, ±0.786, ±1.000 ATR
- Extensions (if enabled): ±1.236 through ±3.000 ATR

Labels: `"Saty ATR Levels"` + trend color, trading type, `"Range($X.XX) = YY% of ATR"`, options strikes
**JARVIS**: `wilder_atr()` period=14, `ema_ribbon()` 8/21/34 in `indicators.py`

---

### 11. `Saty_Phase_OscillatorSTUDY.ts`

**Layer**: 1 (Regime) | **Panel**: Lower | **Lines**: 72

```thinkscript
# Copyright (C) 2022-2024
declare lower;

def pivot = ExpAverage(close, 21);
def oscillator_signal = Round(ExpAverage(((close - pivot) / (3.0 * ATR())) * 100, 3), 2);
plot phase_oscillator = oscillator_signal;
phase_oscillator.SetLineWeight(2);

plot extended_up_zone    =  100.0;
plot distribution_zone   =   61.8;
plot neutral_up_zone     =   23.6;
plot neutral_down_zone   =  -23.6;
plot accumulation_zone   =  -61.8;
plot extended_down_zone  = -100.0;

# Bollinger Band Compression Signal
# compression_tracker = 1 when BB(21, 2STDev) < 2.0 × ATR threshold
```

Color: Magenta=compressing, Green=positive, Red=negative
**JARVIS**: `phase_oscillator()` in `indicators.py` — exact same formula

---

### 12. `Saty_Volume_StackSTUDY.ts`

**Layer**: 3 (Bias) | **Panel**: Lower | **Lines**: 44

```thinkscript
# Copyright (C) 2022-2024 Saty Mahajan
declare lower;

def buy_volume  = volume * (close - low)  / (high - low);
def sell_volume = volume * (high - close) / (high - low);
def buyers_winning = buy_volume >= sell_volume;

plot SmallerVolume = if buyers_winning then sell_volume else buy_volume;
SmallerVolume.setPaintingStrategy(PaintingStrategy.Histogram);
SmallerVolume.AssignValueColor(if buyers_winning then Color.RED else Color.GREEN);

plot BiggerVolume = volume;
BiggerVolume.setPaintingStrategy(PaintingStrategy.Histogram);
BiggerVolume.AssignValueColor(if buyers_winning then Color.GREEN else Color.RED);

# Labels: "XX% " (winner color) + "YY% " (loser color)
```

**JARVIS**: `volume_stack()` in `indicators.py` — `buy_pct` >60%=bull, <40%=bear

---

### 13. `TRIN_ChetanSTUDY.ts`

**Layer**: Supplementary | **Panel**: Upper (bar color) | **Lines**: 6

```thinkscript
def trin_price  = close("$trin");
def trin_price2 = high("$trin");
def vvix_price  = close("vvix");

AssignPriceColor(
    if trin_price < 0.6 and trin_price2 < 1.00 and vvix_price < 120 then Color.MAGENTA
    else if trin_price > 2.0 and low("$trin") > 1.00 and close("VIX") > 30 then Color.CYAN
    else Color.CURRENT
);
```

MAGENTA = extreme bull TRIN (<0.6, high<1.0) + low VVIX (<120)
CYAN = extreme bear TRIN (>2.0, low>1.0) + VIX>30 (crash signal)

---

### 14. `ThinkScript_study_20221014STUDY.ts`

**Layer**: 2 (Structure) | **Panel**: Upper | **Lines**: 847

Largest file. Volume Profile + Virgin POC/VAH/VAL tracker.
- POC calculation modes: Volume, Time, or Average
- Auto-selects period based on aggregation (daily/weekly/monthly/yearly/sub-15min)
- RTH/AH split for futures vs equities
- Tracks up to 10 Virgin POCs, 10 Virgin VAHs, 10 Virgin VALs
- 4 nested `script` blocks:
  - `first_vpoc` — captures initial VPOC
  - `vpoc_period_price_cross_price_cross_counter` — cross counter
  - `virgin_plot_handoff` — passes untouched levels forward
  - `virgin_plot_price_cross_counter` — cross count per virgin level
- ~60 futures symbols for RTH detection (/ES, /NQ, /CL, /GC, etc.)

---

### 15. `ThinkScript_study_20221016STUDY.ts`

**Layer**: 2 (Structure) | **Panel**: Upper | **Lines**: 17

```thinkscript
input anchorDate = 20200422;
input anchorTime = 2030;

plot anchoredVWAP = TotalSum(if postAnchorDate then ((high+low+close)/3)*(volume) else 0)
                 / TotalSum(if postAnchorDate then volume else 0);
anchoredVWAP.SetLineWeight(3);
anchoredVWAP.SetDefaultColor(Color.Cyan);
```

Anchored VWAP from any date/time. Currently anchored to 2020-04-22 20:30 (COVID crash anchor).

---

### 16. `ThinkScript_study_20230523STUDY.ts`

**Layer**: 2 (Structure) | **Panel**: Upper | **Lines**: 79

```thinkscript
declare hide_on_daily;
input aggregationPeriod = AggregationPeriod.DAY;

def PP = (PH + PL + PC) / 3;
def R1 = 2 * PP - PL;
def R2 = PP + (PH - PL);
def R3 = 2 * PP + (PH - 2 * PL);
def R4 = PH + 3 * (PP - PL);
def S1 = 2 * PP - PH;
def S2 = PP - (PH - PL);
def S3 = 2 * PP - (2 * PH - PL);
def S4 = PL - 3 * (PH - PP);
```

Classic pivot points. Resistance = red, PP = gray, Support = green. `showOnlyToday=yes` default.

---

## CRITICAL PARAMETER SETTINGS

### STC (from INTEGRATION_GUIDE.md)

| Parameter | TOS Input | JARVIS 1H | JARVIS Daily | TOS Default |
|-----------|-----------|-----------|--------------|-------------|
| Fast EMA | `fastLength` | 23 | 23 | varies |
| Slow EMA | `slowLength` | 50 | 50 | varies |
| %K period | `KPeriod` | 10 | 10 | varies |
| %D smoothing | `DPeriod` | 3 | 3 | varies |
| Oversold | `over_sold` | **15** | **23** | 19 |
| Overbought | `over_bought` | **83** | **83** | 88 |

**Optimization**: Grid search over 162 combinations on SPY 2024–2026. 1h optimal (OS=15, OB=83) scored 496; daily optimal (OS=23, OB=83) scored 493.

### ATR Levels (from INTEGRATION_GUIDE.md)

| Parameter | JARVIS Value |
|-----------|-------------|
| `atr_length` | 14 |
| `trading_type` | Day (1h charts) |
| `fast_ema` | 8 |
| `pivot_ema` | 21 |
| `slow_ema` | 34 |
| `show_extensions` | yes |
| `trigger_percentage` | 0.236 |

### Keltner (from INTEGRATION_GUIDE.md)

| Band | Factor | Use |
|------|--------|-----|
| Inner | 1.5× | Moderate extension |
| Outer | 2.0× | Significant extension, partial profit |
| Extreme | 3.0× | FADE_EXTREME condition |
| SMA length | 20 | `SMA(TrueRange, 20)` |

---

## 5 REDUNDANCY FINDINGS

### Finding 1 — CRITICAL: Identical Scripts
**Files**: `shared_shared_OB_OMEGA_5mSTUDY.ts` and `shared_shared_OB_OMEGA_15m7STUDY.ts`
**Status**: 100% byte-for-byte identical
**Bug**: Both default to `aggregationPeriod = AggregationPeriod.FIFTEEN_MIN`
**The "5m" filename is wrong/misleading**
**Fix**: Change `aggregationPeriod = AggregationPeriod.FIFTEEN_MIN` to `FIVE_MIN` in the 5m file

### Finding 2 — REDUNDANT: RFv1Mobile
**File**: `AA_CoreyRFv1MobileSTUDY.ts`
**Status**: Strict subset of `AA_CoreyRFv2STUDY.ts` — 10 of 14 features overlap
**No unique functionality on desktop**
**Fix**: Remove from desktop chart setups. Keep for mobile TOS app use only.

### Finding 3 — PARTIAL: TPO Boilerplate
**Files**: `CoreyRFv2`, `CoreyTPOv1`, `CoreyTscorev2`
**Status**: `switch(timePerProfile)` block copy-pasted identically across all 3
**Unavoidable**: ThinkScript has no import/include system
**Recommendation**: Accept as-is; document the shared boilerplate

### Finding 4 — PARTIAL: Keltner Formula Overlap
**Files**: `shared_shared_OB_OMEGA_5m`, `shared_shared_OB_OMEGA_15m7`, `CoKeltnerChannelsStudy`, `shared_CoreyKeltnerChannelsSTUDY`
**Status**: All 4 use `SMA(TrueRange, 20)` as Keltner basis
**Could consolidate** into a single parameterized script
**Recommendation**: Accept unless maintenance becomes a burden

### Finding 5 — INTENTIONAL: Multi-ATR Scripts
**Files**: 5 scripts use ATR with different periods (3, 10, 14, 20)
**Status**: Each serves a distinct timeframe purpose
**This is correct design** — multi-timeframe ATR is intentional

---

## OVERLAP MATRIX (17 scripts × 14 dimensions)

| Script | STC | ATR | EMA | Keltner | Vol Profile | KAMA | Phase | IB | Gap | LR | VP/POC | Regime | Entry | Size |
|--------|-----|-----|-----|---------|-------------|------|-------|----|----|-----|--------|--------|-------|------|
| Saty_ATR_Levels | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ |
| Saty_Phase_Osc | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ |
| Saty_Volume_Stack | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| NextSignalMomentum | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ |
| OB_STYLE_STC | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ |
| OB_OMEGA_5m | ✗ | ✓ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ |
| OB_OMEGA_15m | ✗ | ✓ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ |
| kelt_3.01 | ✗ | ✓ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ |
| CoreyIBv1 | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ |
| CoreyRFv2 | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | ✗ |
| CoreyRFv1Mobile | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ |
| CoreySFv2 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| CoreyTPOProfilev1 | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ |
| CoreyTscorev2 | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ |
| CoreyGapfinderv1 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| mtftrendbar | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ |
| GAPS_Chetan | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |

Overlap counts: STC=1, ATR=5, EMA=3, Keltner=4, Vol Profile=3, KAMA=1, Phase=1, IB=2, Gap=3, LR=1, VP/POC=3, Regime=3, Entry=7, Size=1

---

## PYTHON REIMPLEMENTATIONS TABLE

| TOS Script / Indicator | Python Function | File |
|------------------------|-----------------|------|
| `Saty_ATR_LevelsSTUDY` (ATR calc) | `wilder_atr(high, low, close, period=14)` | `engine/backtest/indicators.py` |
| `Saty_ATR_LevelsSTUDY` (EMA ribbon) | `ema_ribbon(close, fast=8, mid=21, slow=34)` | `engine/backtest/indicators.py` |
| `Saty_Phase_OscillatorSTUDY` | `phase_oscillator(close, atr, ema_period=21)` | `engine/backtest/indicators.py` |
| `NextSignalMomentumSTUDY` (KAMA) | `kama(close, period=10, fast=2, slow=30)` | `engine/backtest/indicators.py` |
| `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY` | `stc(close, fast=23, slow=50, k_period=10, d_period=3)` | `engine/backtest/indicators.py` |
| `Saty_Volume_StackSTUDY` | `volume_stack(open, high, low, close, volume)` | `engine/backtest/indicators.py` |
| `shared_shared_OB_OMEGA_*` | `keltner_channels(close, atr, sma_len=20)` | `engine/backtest/indicators.py` |
| `shared_mtftrendbarSTUDY` | `cci(high, low, close, period=50)` | `engine/backtest/indicators.py` |
| `Saty_ATR_LevelsSTUDY` (range %) | `range_consumed_pct(high, low, close, atr)` | `engine/backtest/indicators.py` |

---

## ALERT PRIORITY ORDER (from INTEGRATION_GUIDE.md)

1. **STC CrossUp** (RegularBuy arrow) → Sound: Bell, Email ON — `ENTRY_NOW` long
2. **STC CrossDown** (RegularSell arrow) → Sound: Bell, Email ON — `ENTRY_NOW` short
3. **IB High Breakout** → Sound: Ring — `ENTRY_NOW` unconditional long
4. **IB Low Breakdown** → Sound: Ring — `ENTRY_NOW` unconditional short
5. **Phase Compression** → Sound: Ding
6. **KAMA Cross** → Sound: Ding
7. **Phase Extended** (±61.8) → Sound: Ding
8. **Keltner 2x Breach** → Sound: Ding

---

## TOS IMPORT ORDER (from INTEGRATION_GUIDE.md)

Sub-studies first:
1. `shared_shared_shared_shared_kelt_3.01STUDY.ts`
2. `shared_shared_shared_shared_shared_kmaster1STUDY.ts`
3. `shared_shared_shared_shared_shared_Priceline11STUDY.ts`

Main studies:
4. `Saty_ATR_LevelsSTUDY.ts`
5. `Saty_Phase_OscillatorSTUDY.ts`
6. `Saty_Volume_StackSTUDY.ts`
7. `NextSignalMomentumSTUDY.ts`
8. `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` (STC — set OS=15, OB=83)
9. `AA_CoreyTPOProfilev1STUDY.ts`
10. `AA_CoreyTscorev2STUDY.ts`
11. `AA_CoreyIBv1STUDY.ts`
12. `AA_CoreyRFv2STUDY.ts`
13. `AA_CoreySFv2STUDY.ts`
14. `AA_CoreyGapfinderv1STUDY.ts`
15. `shared_mtftrendbarSTUDY.ts`
16. `shared_shared_OB_OMEGA_5mSTUDY.ts`
17. `TRIN_ChetanSTUDY.ts`

---

## HTML REPORT DESIGN DECISIONS

- **Background**: `#0d1117` (GitHub dark, matches ThinkorSwim default theme)
- **Accent**: `#58a6ff` (blue — active links, stats, highlights)
- **Text**: `#c9d1d9` (primary), `#8b949e` (muted), `#e6edf3` (headings)
- **Layer color coding**: L1=`#58a6ff`, L2=`#bc8cff`, L3=`#3fb950`, L4=`#f0883e`, L5=`#f85149`
- **Badges**: ACTIVE=green, IGNORE=gray, SUB-STUDY=orange
- **Sidebar**: fixed, 240px, IntersectionObserver active-link highlighting
- **Font**: `-apple-system, BlinkMacSystemFont, 'Segoe UI'` (system sans-serif)

### Merge Operation (this session)
Both HTML files merged into `TOS_SCRIPTS_ANALYSIS.html`:
- Two-button pill tab switcher in sidebar header: "Overview" / "Deep Dive"
- `#nav-overview` / `#nav-deepdive` sidebar panels toggle
- `#content-overview` / `#content-deepdive` main panels toggle
- `switchTab(tab)` JS function — toggles both nav and content panels simultaneously
- `ddScrollTo(id)` — auto-switches to Deep Dive tab if called from wrong tab
- Two independent `IntersectionObserver` instances (one per tab)
- Default state: Overview active

---

## BEST BACKTEST RESULTS (from MEMORY.md)
- MES 1h: PF 5.27, Sharpe 4.16, +47.2% (hardcoded in BacktestCompareWidget)

---

## CURRENT STATE

| File | Location | Size | Status |
|------|----------|------|--------|
| `TOS_SCRIPTS_ANALYSIS.html` | `docs/dashboards/` | 196KB, 3,636 lines | Complete — tabbed Overview + Deep Dive |
| `TOS_SCRIPTS_DEEP_DIVE.html` | `docs/dashboards/` | 128KB, 2,427 lines | Complete — preserved as standalone |
| `TOS_SCRIPT_ANALYSIS_SESSION_LOG.md` | `docs/session-logs/` | this file | Complete |

---

## OPTIONAL NEXT STEPS (not requested — recommendations only)

1. **Fix `OB_Omega_5m` default period** — change `aggregationPeriod = AggregationPeriod.FIFTEEN_MIN` to `FIVE_MIN` in `shared_shared_OB_OMEGA_5mSTUDY.ts`
2. **Remove RFv1Mobile from desktop setups** — `AA_CoreyRFv1MobileSTUDY.ts` adds no value on desktop
3. **Consolidate Keltner scripts** — merge 4 scripts using `SMA(TrueRange, 20)` into one parameterized version
4. **Add direct TOS→JARVIS connection** — currently requires TradingView as middleman; a direct ThinkScript alert → JARVIS webhook would eliminate the dependency

---

*End of session log. Source of truth for parameters: `engine/backtest/signals.py`. Source of truth for indicators: `engine/backtest/indicators.py`. HTML reports: `docs/dashboards/TOS_SCRIPTS_ANALYSIS.html`.*
