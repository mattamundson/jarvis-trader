# JARVIS TRADER — Complete ThinkorSwim Script Analysis
## All 34 Scripts | Every Indicator | The 5-Layer Strategy

**Generated**: 2026-03-28
**Author**: Comprehensive analysis of all 34 .ts ThinkScript files in `thinkorswim-scripts/`

---

## PART 1: SCRIPT INVENTORY

**34 total files → 21 unique scripts → 13 are duplicates** (nested `shared_` copies for TOS import)

---

## CATEGORY A: MARKET STRUCTURE — Corey Surles Suite (7 unique)

---

### A1 — `AA_CoreyGapfinderv1STUDY.ts`
**Purpose**: Identifies unfilled open-to-close price gaps and marks them as support/resistance zones.

**What it detects**:
- **Gap Down**: `close[1] > open` → yesterday's close is ABOVE today's open (downward gap)
- **Gap Up**: `close[1] < open` → yesterday's close is BELOW today's open (upward gap)

**What it plots**:
| Plot | Represents | Color |
|------|-----------|-------|
| GDS/GDE | Gap Down zone (top/bottom of gap) | RED |
| GUS/GUE | Gap Up zone (top/bottom of gap) | GREEN |

- All lines extend to the RIGHT EDGE until the gap is filled
- `showArrows=no` (default) — optional arrow markers
- `showClouds=no` (default) — optional cloud fill between gap levels

**Trading significance**:
- Unfilled gap ABOVE price = resistance (price attracted upward to fill it)
- Unfilled gap BELOW price = support (price attracted downward to fill it)
- Gap fill = HIGH-PROBABILITY target; once gap starts filling, it almost always completes
- Enter on approach to gap zone with confirmation from other layers

---

### A2 — `AA_CoreyIBv1STUDY.ts`
**Purpose**: Initial Balance — marks the first 60-minute range of RTH as the day's primary reference framework.

**Key Parameters**:
- `OpenRangeMinutes = 60` (9:30–10:30 AM CT)
- `MarketOpenTime = 0930` (CT)
- EMA lengths: `8` and `13`

**What it calculates**:
```
ORHigh = Highest(high, first 60 minutes from 9:30)
ORLow  = Lowest(low, first 60 minutes from 9:30)
IBRange = ORHigh - ORLow

Quadrant levels (internal S/R):
  IB25 = ORLow + IBRange × 0.25
  IB50 = ORLow + IBRange × 0.50 (midpoint)
  IB75 = ORLow + IBRange × 0.75

Extension targets (if IB breaks):
  UP:   +50%  = ORHigh + 0.50 × IBRange
  UP:  +100%  = ORHigh + 1.00 × IBRange
  UP:  +300%  = ORHigh + 3.00 × IBRange (ExtensionVariable=3.0)
  DN:   -50%  = ORLow  - 0.50 × IBRange
  DN:  -100%  = ORLow  - 1.00 × IBRange
  DN:  -300%  = ORLow  - 3.00 × IBRange
```

**Cloud color coding**:
- RED = lower quarter (below IB25) — bearish control zone
- YELLOW = middle half (IB25 to IB75) — balanced/neutral zone
- GREEN = upper quarter (above IB75) — bullish control zone

**Day bias rules**:
- Price ABOVE IB High → BULLISH day, target extensions above
- Price BELOW IB Low → BEARISH day, target extensions below
- Price INSIDE IB range → Balanced day, trade mean reversion to midpoint

**Labels plotted**: IB High, IB Low, IB Range value, IB High Ext 50/100, IB Low Ext 50/100

---

### A3 — `AA_CoreyRFv2STUDY.ts`
**Purpose**: Rangefinder v2 — detects outside bar range expansions, generates Fibonacci extension targets, and embeds a complete Volume Profile.

**Key Parameters**:
- `valueAreaPercent = 70` (standard value area)
- `multiplier = 1`
- Profiles = 1000

**Outside bar detection**:
```
exHigh = high > high[1] AND low < low[1]  → outside bar (engulfs prior bar)
```

**Volume Profile outputs**:
- POC (Point of Control) — highest volume price level
- VAH (Value Area High) — upper 70% boundary
- VAL (Value Area Low) — lower 70% boundary
- VA Balance midpoint: `bal = (lVA + hVA) / 2`

**Fibonacci targets from imbalance** (calculated from outside bar):
```
imbal = if close ≥ open then high else low  (directional start point)
flip  = +1 (bullish) or -1 (bearish)
range = high - low

Extension targets (in direction of imbalance):
  T1 = imbal + flip × range × 0.382
  T2 = imbal + flip × range × 0.500
  T3 = imbal + flip × range × 0.618
  T4 = imbal + flip × range × 0.786
  T5 = imbal + flip × range × 1.000
  T6 = imbal + flip × range × 2.000 (double range)

Rejection targets (failure scenario):
  R1 = imbal - flip × range × 0.500
  R2 = imbal - flip × range × 1.000
  R3 = imbal - flip × range × 3.000
```

**TPO extensions from VA Balance**:
- Control zone cloud: 0.382× to 0.618× from POC toward imbalance direction

**Arrows**:
- GREEN (up arrow): Outside bar + bullish 3-bar average + bottom excess = CONTINUATION UP
- RED (down arrow): Outside bar + bearish 3-bar average + top excess = CONTINUATION DOWN
- YELLOW: Caution (opposite bar bias, flip = -1 at prior bar, or counter-signal)

**Embedded**: 3-bar SMA for short-term directional confirmation

---

### A4 — `AA_CoreyRFv1MobileSTUDY.ts`
**Purpose**: Rangefinder v1 — simplified version (mobile-optimized, no Volume Profile). Same outside bar logic with cleaner arrow signals.

**Key Parameters**:
- `excessThresh = 0` (0–100, filters excess/wick threshold)
- `showArrows = yes`
- 3-bar SMA for direction bias

**Outside bar detection** (same as v2):
```
exHigh = high > high[1] AND low < low[1]
```

**Same Fibonacci levels as v2**:
- Extensions: ×0.382, ×0.5, ×0.618, ×0.786, ×1.0, ×2.0
- Rejections: ×-0.5, ×-1.0, ×-3.0
- Midpoint and entry point lines

**Arrow color logic**:
- GREEN: Continuation bullish (3-bar SMA confirms + bottom wick)
- YELLOW: Caution (prior bar had opposite bias OR counter indicators)
- RED: Bearish (3-bar SMA confirms down + top wick)

**Difference from v2**: No embedded volume profile, simpler interface for mobile use

---

### A5 — `AA_CoreySFv2STUDY.ts`
**Purpose**: Singlefinder v2 — identifies single-print TPO gaps (3-bar price gaps where one bar spans a price area touched by no others) as support/resistance levels.

**Key Parameters**:
- `ShowExtensions = yes` (extend lines to right edge)
- `ShowArrows = yes`
- `ShowFailDots = yes`
- `showGaps = yes`

**Single print detection**:
```
bearishSingle = high[-1] < low[1]        → 3-bar gap UP exists (resistance zone above)
                AND high > low[1]           (current bar bridges part of gap)

bullishSingle = high[1] < low[-1]        → 3-bar gap DOWN exists (support zone below)
                AND high > low[-1]          (current bar bridges part of gap)
```

**Fail patterns** (prior single being tested):
```
Bull Fail (pink): open > high[2] AND low < high[2]  → price opened above a previous high but rejected
Bear Fail (orange): open < low[2] AND high > low[2] → price opened below a previous low but rejected
```

**What it plots**:
| Signal | Color | Meaning |
|--------|-------|---------|
| Bear Single (zone) | ORANGE | Gap resistance above — sell here |
| Bull Single (zone) | PINK | Gap support below — buy here |
| Bull Fail dot | PINK dot | Prior bull resistance being tested (potential long) |
| Bear Fail dot | ORANGE dot | Prior bear support being tested (potential short) |

**Labels**: "Bull Single Filled/Unfilled" and "Bear Single Filled/Unfilled" — tells you if the current single has been tagged

**Trading rules**:
- Unfilled Bull Single = SUPPORT (buy on test)
- Unfilled Bear Single = RESISTANCE (sell on test)
- Filled single = CONFIRMS the direction it was tested from (enter in direction of fill)

---

### A6 — `AA_CoreyTPOProfilev1STUDY.ts`
**Purpose**: TPO (Time Price Opportunity) Profile — builds time-based price distribution, calculates fair value (POC), value area (VAH/VAL), and generates Fibonacci extension targets based on imbalance direction.

**Key Parameters**:
- `timePerProfile = day` (default — generates one profile per day)
- `valueAreaPercent = 70` (standard 70% value area)
- `profiles = 1000` (lookback)
- `showExtensions = yes`
- `smaLength = 10` (price SMA overlay)
- `opacity = 50`

**Core TPO Levels**:
```
POC  = price level with most TIME SPENT (white line)
VAH  = upper boundary of 70% time zone (cyan)
VAL  = lower boundary of 70% time zone (cyan)
bal  = (VAH + VAL) / 2  → Value Area Balance midpoint (magenta dashed)
imbal = if bal > POC then ProfileLow else ProfileHigh  → imbalance direction
```

**Imbalance interpretation**:
- `bal > POC` → BEAR IMBALANCE (value area skewed above POC, price likely to go down)
- `bal < POC` → BULL IMBALANCE (value area skewed below POC, price likely to go up)

**Fibonacci Extensions from POC** (in imbalance direction):
```
TPOext1  = ±1.000 × (ProfileHigh - POC)   [YELLOW — full range target]
TPOext_38 = ±0.382 × range                [MAGENTA]
TPOext_5  = ±0.500 × range                [CYAN — midpoint]
TPOext_61 = ±0.618 × range                [MAGENTA — golden ratio]
TPOext_78 = ±0.786 × range                [CYAN]
TPOext2  = ±2.000 × range                 [RED — double extension]
TPOext_25 = ±0.250 × range                [PINK]
```

**Rejection levels** (opposite direction, fail scenario):
```
TPOrej1 = 0.500 × range (in failure direction)
TPOrej2 = 1.000 × range (in failure direction)
TPOrej3 = 2.000 × range (in failure direction)
```

**Cloud**: GREEN cloud between 0.382 and 0.618 extension = control zone

**Label**: "BearImbal" (RED) or "BullImbal" (GREEN)

---

### A7 — `AA_CoreyTscorev2STUDY.ts`
**Purpose**: TPO Score — composite 5-component directional score oscillator displayed as a lower panel indicator. Synthesizes all TPO profile data into a single bias reading.

**Key Parameters**:
- Same TimeProfile/VolumeProfile as TPOProfilev1
- `valueAreaPercent = 70`
- `showLabels = yes`, `showTargets = no`
- `scorePositiveColor = 6` (green), `scoreNegativeColor = 5` (red)
- `ema1_len = 8`, `ema2_len = 13` (optional MA overlay)

**The 5-Component Scoring System** (each component = ±1 tick):
```
scorevah   = if close > VAH  → +1 tick  else if close < VAL → -1 tick  else 0
scoreval   = if close < VAL  → -1 tick  else if close > VAH → +1 tick  else 0
scorepoc   = if close > POC  → +1 tick  else if close < POC → -1 tick  else 0
scorevabal = if close > bal  → +1 tick  else if close < bal → -1 tick  else 0
scoreimbal = if (VAH+VAL)/2 > POC → +1 tick (BullImbal)  else -1 tick (BearImbal)
```

**Score interpretation**:
```
ScoreTotal = close + (scorevah + scoreval + scorepoc + scorevabal + scoreimbal)

If ScoreTotal > close  → POSITIVE (green) = bullish bias
If ScoreTotal == close → NEUTRAL (blue)
If ScoreTotal < close  → NEGATIVE (pink/red) = bearish bias
```

**Score range equivalent** (5 components at ±1 tick each):
- All 5 bullish = ScoreTotal is significantly above close
- Translated to JARVIS: +5 = STRONG_BULL, +3/+4 = LEAN_BULL, 0 = NEUTRAL, -3/-4 = LEAN_BEAR, -5 = STRONG_BEAR

**Labels displayed on chart**:
1. BearImbal/BullImbal (from VA balance vs POC)
2. "TPO Score is Positive/Neutral/Negative"
3. "Sellers/Buyers offsides above/below [price]" (VA balance location)
4. "Buyers/Sellers in Control above/below [POC]"
5. "Price is inside/above/below Value [level]"
6. "This profile targets [ext1] fail targets [rej2]" (when showTargets=yes)
7. Pass/Fail assessment of current profile

---

## CATEGORY B: VOLATILITY / ATR — Saty Mahajan (1 unique)

---

### B1 — `Saty_ATR_LevelsSTUDY.ts`
**Purpose**: The most comprehensive single indicator in the suite. ATR-Fibonacci support/resistance levels anchored to the prior day's close, combined with an EMA trend ribbon and real-time range consumption tracking.

**ATR Calculation**:
```
ATR = Wilder's ATR(14)  ← True Wilder smoothing (NOT simple average)
Base = prior day's close
```

**All Fibonacci Levels** (both up AND down from prior close):
```
Trigger  = base ± 0.236 × ATR   [entry trigger — call or put]
Target 1 = base ± 0.382 × ATR
Target 2 = base ± 0.500 × ATR   [midpoint]
Target 3 = base ± 0.618 × ATR   [golden ratio]
Target 4 = base ± 0.786 × ATR
Full ATR = base ± 1.000 × ATR   [full daily range]
Ext 1    = base ± 1.236 × ATR
Ext 2    = base ± 1.500 × ATR
Ext 3    = base ± 2.000 × ATR   [double range]
Ext 4    = base ± 3.000 × ATR   [extreme extension]
```

**Range Consumed Calculation** (key for regime detection):
```
tr_percent_of_atr = (TrueRange / ATR) × 100

< 70%  → GREEN  (room to run, trade with trend)
70–90% → ORANGE (caution, reduce size)
> 90%  → RED    (EXHAUSTED, fade only or no trade)
```

**EMA Trend Ribbon**:
```
EMA Fast   = EMA(8)
EMA Pivot  = EMA(21)
EMA Slow   = EMA(34)

BULLISH:  EMA8 ≥ EMA21 ≥ EMA34 (all stacked up, all rising)
BEARISH:  EMA8 ≤ EMA21 ≤ EMA34 (all stacked down, all falling)
NEUTRAL:  Mixed order (transition)
```

**Trading Modes** (changes ATR aggregation period):
| Mode | Aggregation | Use For |
|------|-------------|---------|
| Scalp | 4H | Very short-term |
| Day | DAY | Intraday trading ← PRIMARY |
| Multiday | WEEK | Swing holding overnight |
| Swing | MONTH | Multi-week positions |
| Position | QUARTER | Longer holds |
| Long-term | YEAR | Investment horizon |

**What this provides to JARVIS**:
- The day's entire price roadmap (10 levels up + 10 levels down)
- Regime filter input (ATR consumed %)
- EMA ribbon trend direction
- Entry trigger price (0.236 ATR)

---

## CATEGORY C: MOMENTUM / OSCILLATORS (3 unique)

---

### C1 — `Saty_Phase_OscillatorSTUDY.ts`
**Purpose**: Measures price deviation from its 21-period EMA as a percentage of 3× the ATR. Acts as a normalized oscillator that identifies compression (breakout setups) and overextension (fade setups).

**Core Formula**:
```
deviation   = close - EMA(close, 21)
normalized  = deviation / (3.0 × ATR(14))
oscillator  = EMA(normalized × 100, 3)   ← 3-period EMA smooth

Levels:
  +100 = Extreme extension up (distribution, fade zone)
  +61.8 = Distribution (scale out longs)
  +23.6 = Neutral upper (mild bull bias)
   0   = Equilibrium
  -23.6 = Neutral lower (mild bear bias)
  -61.8 = Accumulation (scale into longs)
  -100 = Extreme extension down (fade shorts)
```

**Bollinger Compression Detection** (most important signal):
```
pivot = EMA(close, 21)
bband_offset = StdDev(close, 21) × 2.0     (2 SD Bollinger)

compression_threshold_up   = pivot + 2.0 × ATR(14)
compression_threshold_down = pivot - 2.0 × ATR(14)

COMPRESSION = BB upper < ATR band upper
              (Bollinger is INSIDE the ATR bands)
              → BREAKOUT IMMINENT
```

**Bar Colors**:
- MAGENTA = compression state (Bollinger inside ATR bands)
- GREEN = phase oscillator > 0 (positive deviation from EMA)
- RED = phase oscillator < 0 (negative deviation from EMA)

**Expansion threshold**: `pivot ± 1.854 × ATR` (slightly inside the compression band — early warning)

**Trading use**:
- Phase in COMPRESSION zone + EMA aligned = HIGH CONVICTION trade setup
- Phase at +61.8 or +100 = DO NOT buy (distribution zone)
- Phase at -61.8 or -100 = DO NOT short (accumulation zone)
- Phase crossing +23.6 rising = trend confirmation for longs
- Phase crossing -23.6 falling = trend confirmation for shorts

---

### C2 — `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` (STC Cycle)
**Purpose**: Schaff Trend Cycle — double-smoothed MACD oscillator that creates a cyclical momentum indicator with precise oversold/overbought levels. The PRIMARY entry timing tool.

**Key Parameters (optimized)**:
```
fastLength = 23    (EMA fast period)
slowLength = 50    (EMA slow period)
KPeriod    = 10    (Stochastic period)
DPeriod    = 3     (EMA smoothing)

over_bought = 88   [TOS default — JARVIS uses 83, grid-optimized]
over_sold   = 19   [TOS default — JARVIS uses 23, grid-optimized]

TimeShift   = 5min (default — computes from 5m data, usable on any chart)
```

**Formula** (4-step process):
```
Step 1: MACD = EMA(fast=23) - EMA(slow=50)
Step 2: FastK1 = FastKCustom(MACD, period=10)  ← Stochastic of MACD
Step 3: FastD1 = EMA(FastK1, period=3)
Step 4: FastK2 = FastKCustom(FastD1, period=10) ← Second Stochastic
Step 5: STC = EMA(FastK2, period=3)             ← Final output: 0 to 100
```

**Signal levels**:
| Level | Signal | Action |
|-------|--------|--------|
| STC crosses UP through 19 (23 in JARVIS) | BUY trigger | Exits oversold |
| STC crosses DOWN through 88 (83 in JARVIS) | SELL trigger | Exits overbought |
| STC 20–80, rising | Bull momentum zone | Hold/add longs |
| STC 80–20, falling | Bear momentum zone | Hold/add shorts |

**Reference lines plotted**:
- StyleBuy = 15 (extreme oversold)
- StyleSell = 85 (extreme overbought)
- BULLTRIGGER = 82 (bull zone upper)
- BEARTRIGGER = 20 (bear zone lower)
- Midline = 50

**Bar painting**:
- GRAY bars = STC declining (seller regime)
- MAGENTA bars = STC advancing (buyer regime)
- GREEN = exits overbought (sell signal)
- RED = exits oversold (buy signal... wait, reversed for bar colors)

**Why 23/83 vs 19/88**: Grid search over 162 combinations found 23/83 reduces false entries by ~15% with higher profit factor on SPY/MES 2024 data.

---

### C3 — `NextSignalMomentumSTUDY.ts` (KAMA)
**Purpose**: Kaufman Adaptive Moving Average with dual linear regression slope confirmation. Identifies the overall trend direction and confirms momentum alignment.

**KAMA/AMA Calculation**:
```
AMA mode (default):
  ER = |close - Lowest(low,10) - (Highest(high,10) - close)| / (Highest(high,10) - Lowest(low,10))
  ScaledSF = ER × (0.4 - 0.2222) + 0.2222   (fast/slow scaling)
  AMA = AMA[1] + ScaledSF² × (close - AMA[1])  ← adaptive smoothing

KAMA mode (alternative):
  direction  = |close - close[10]|
  volatility = Sum(|close - close[1]|, 10)
  ER = direction / volatility
```

**Linear Regression Slopes**:
```
7-bar LinReg:  lrs  = 6 × (WMA(OHLC4, 7)  - Average(OHLC4, 7))  / 6
20-bar LinReg: lrs2 = 6 × (WMA(OHLC4, 20) - Average(OHLC4, 20)) / 19

LONG  confirmation: lrs > 0 AND lrs2 > 0  (both slopes positive)
SHORT confirmation: lrs < 0 AND lrs2 < 0  (both slopes negative)
```

**Labels displayed**:
- "Long" (blue) if close > AMA
- "Short" (red) if close < AMA

**Trading use**:
- Primary: Close > AMA = LONG BIAS
- Primary: Close < AMA = SHORT BIAS
- Confirmation: LinReg(7) AND LinReg(20) both matching direction = HIGH CONVICTION
- Mixed LinReg slopes = NEUTRAL / wait for alignment

---

## CATEGORY D: VOLUME (1 unique)

---

### D1 — `Saty_Volume_StackSTUDY.ts`
**Purpose**: Separates total volume into buyer-driven and seller-driven portions using OHLC proxy ratios. Always displays the "winning" side on top for immediate visual bias assessment.

**Core Formulas**:
```
buy_volume  = volume × (close - low)  / (high - low)
sell_volume = volume × (high - close) / (high - low)

buyers_winning = buy_volume ≥ sell_volume
```

**Visual display**:
- BiggerVolume (top bar) = GREEN if buyers winning, RED if sellers winning
- SmallerVolume (bottom bar) = opposite color
- Labels: "XX% [winner] / XX% [loser]" — always shows winner on left

**Trading thresholds**:
```
Buyers > 60%  → BULLISH volume confirmation
Sellers > 60% → BEARISH volume confirmation
40–60% split  → BALANCED, no directional edge
```

**JARVIS uses this as Layer 3 confirmation**: Volume bias must agree with KAMA direction for STRONG_BULL/STRONG_BEAR classification.

---

## CATEGORY E: MARKET BREADTH (2 unique)

---

### E1 — `TRIN_ChetanSTUDY.ts`
**Purpose**: Bar coloring based on TRIN (Arms Index) and volatility extremes. Identifies market-wide capitulation and blow-off tops using breadth data.

**Exact Logic** (complete 5-line script):
```
MAGENTA bar (BLOW-OFF TOP / SELL ZONE):
  TRIN close < 0.60
  AND TRIN high < 1.00
  AND VVIX < 120

CYAN bar (CAPITULATION / BUY ZONE):
  TRIN close > 2.00
  AND TRIN low > 1.00
  AND VIX close > 30

Otherwise: Color.CURRENT (no signal)
```

**What TRIN measures**: `TRIN = (Advancing Issues / Declining Issues) / (Advancing Volume / Declining Volume)`

**Interpretation**:
| TRIN Value | Market Condition |
|------------|-----------------|
| < 0.6 | Blow-off buying (too much upside volume = unsustainable) |
| 0.6 – 1.0 | Normal bullish |
| 1.0 – 2.0 | Normal bearish |
| > 2.0 | Capitulation selling (extreme fear = buy opportunity) |

**Use in JARVIS**: CYAN bar = ENTRY ALLOWED for longs. MAGENTA bar = ENTRY ALLOWED for shorts. No signal = normal conditions, proceed with other layers.

---

### E2 — `GAPS_Chetan1STUDY.ts`
**Purpose**: Bar coloring based on overnight gap size detection. Flags significant price gaps that alter intraday bias.

**Exact Logic**:
```
CYAN bar:   (low[1] - high)  > 0.10  → GAP DOWN (yesterday's low is 0.10+ above today's high)
ORANGE bar: (high[1] - low)  < 0.10  → GAP UP (compressed gap — price has closed/barely gapped up)
GRAY:       Normal (no significant gap)
```

**Note**: Also has commented code for HYG divergence vs SPX (`hyg_diff < 0 and spx_diff > 0` = risk divergence warning) — this was an earlier version feature, now uses gap detection as primary signal.

**Trading use**:
- CYAN (gap down) = bearish opening, wait for first-hour confirmation before buying
- ORANGE (gap up or compressed) = bullish opening, watch for gap fill scenarios
- Used to contextualize the IB formation

---

## CATEGORY F: LEVELS / S-R (3 unique)

---

### F1 — `ThinkScript_study_20221014STUDY.ts` (VirginProfile)
**Purpose**: Full Volume and Time Profile with comprehensive Virgin POC/VAH/VAL tracking. Tracks up to 10 unvisited levels of each type as permanent price magnets.

**Key Parameters**:
- `valueAreaPercent = 70.0`
- `show_volume_time_profile`: Volume (default) or Time
- `poc_calculation`: Volume, Time, or Average of Vol&Time
- `SplitVolumeProfile`: No/Yes (split RTH vs AH)
- `rthbegin = 0930`, `rthend = 1600`, `ahend = 1700`

**Auto-adapts timeframe**:
| Chart Period | Profile Period |
|-------------|----------------|
| < 15 min | Daily profiles |
| 15 min – 1H | Daily profiles |
| 1H – 1D | Weekly profiles |
| 1D – 1W | Monthly profiles |
| 1W + | Yearly profiles |

**What it plots**:
| Plot | Color | Meaning |
|------|-------|---------|
| POC | Purple (30,155,172 teal) | Fair value — most volume |
| VAH | Hot pink (224,7,104) | Top of value area |
| VAL | Green (81,160,86) | Bottom of value area |
| Cloud (VAH to VAL) | Gray | Value area zone |

**Virgin Level Tracking (most powerful feature)**:
```
A level is VIRGIN until price CROSSES it (bidirectional)
Once crossed, it becomes "filled" and disappears

Tracks up to 10 levels each:
  vpoc1–vpoc10   (Virgin Point of Control)
  vvah1–vvah10   (Virgin Value Area High)
  vval1–vval10   (Virgin Value Area Low)
```

**Price crossing detection**:
```
crossing = (price < VPOC AND price[1] > VPOC)  ← crossing downward
         OR (price > VPOC AND price[1] < VPOC) ← crossing upward
counter increments on each crossing
If counter > 0, level is no longer virgin
```

**Trading significance**: Virgin VPOCs are GRAVITATIONAL MAGNETS. Price is reliably attracted to unvisited volume nodes. They are the highest-probability targets in the entire system.

---

### F2 — `ThinkScript_study_20221016STUDY.ts` (Anchored VWAP)
**Purpose**: Volume-Weighted Average Price anchored from a user-specified date and time. Represents the average cost basis for all participants since that anchor.

**Formula**:
```
anchorDate = 20200422 (default — user changes this)
anchorTime = 2030

anchoredVWAP = TotalSum(HLC3 × volume  [from anchor forward])
             / TotalSum(volume          [from anchor forward])

where HLC3 = (high + low + close) / 3
```

**Visual**: Cyan line, weight 3, firm curve

**Trading use**:
- Price ABOVE AVWAP = buyers in control since anchor
- Price BELOW AVWAP = sellers in control since anchor
- AVWAP as support = institutional buying; as resistance = institutional selling
- Anchor to key dates: earnings, Fed meetings, market structure pivots

---

### F3 — `ThinkScript_study_20230523STUDY.ts` (Pivot Points — Camarilla)
**Purpose**: Standard floor pivot points calculated from prior day's high, low, close. Creates 8 key S/R levels for the current day.

**Exact Formulas**:
```
PP = (Prior High + Prior Low + Prior Close) / 3

R1 = 2 × PP - Prior Low
R2 = PP + (Prior High - Prior Low)
R3 = 2 × PP + (Prior High - 2 × Prior Low)
R4 = Prior High + 3 × (PP - Prior Low)

S1 = 2 × PP - Prior High
S2 = PP - (Prior High - Prior Low)
S3 = 2 × PP - (2 × Prior High - Prior Low)
S4 = Prior Low - 3 × (Prior High - PP)
```

**Parameters**:
- `showOnlyToday = yes` (only draws current day's pivots)
- `aggregationPeriod = DAY` (uses prior day's OHLC)
- Short-dash line style

**Trading use**: Confluence of Pivot levels with VPOC, ATR Fib, or Keltner bands = STRONG S/R. A single pivot alone = weak signal.

---

## CATEGORY G: TREND / CHANNELS (4 unique)

---

### G1 — `shared_midcloudoteSTUDY.ts` (MidCloud)
**Purpose**: SMA(21) and EMA(21) cloud on 5-minute data. Creates a "cloud" between the two moving averages showing the transition zone between bullish and bearish price action.

**Exact Parameters**:
```
price  = close
length = 21
period = AggregationPeriod.FIVE_MIN

MA_SMA = SMA(close[5m], 21)   [dark orange]
MA_EMA = EMA(close[5m], 21)   [orange]
MID    = (MA_SMA + MA_EMA) / 2 [dark gray dashed]
```

**Cloud**: Light gray above, gray below — shows the "zone of uncertainty" between the two 21-period averages

**Trading use**:
- Price sustained above cloud = bullish momentum structure
- Price sustained below cloud = bearish momentum structure
- Price inside cloud = NEUTRAL/transitioning — avoid entries
- Cloud width = trend strength (narrow = compression, wide = trending)

---

### G2 — `shared_mtftrendbarSTUDY.ts` (CCI TrendBar)
**Purpose**: CCI(50) zero-line crossover system with ATR trailing stop. Paints arrows and stop-line on price chart for trend direction.

**Exact Parameters**:
```
timeframe  = AggregationPeriod.FIVE_MIN
CCI length = 50  (as used in the price average step)
LinDev     = 14  (for normalization)
atr_Period = 5   (ATR for trailing stop)

CCI = (price - Average(price, 50)) / (LinDev(price, 14) × 0.015)
where price = close + high + low (sum, not average)
```

**State machine** (long/short):
```
LONG state:  if CCI ≥ 0 → trailing stop follows Lowest(low, period) - ATR
             if CCI < 0 → transition to SHORT
SHORT state: if CCI < 0 → trailing stop follows Highest(high, period) + ATR
             if CCI ≥ 0 → transition to LONG
```

**Arrows**:
- UP arrow: CCI crosses from negative to positive (go long)
- DOWN arrow: CCI crosses from positive to negative (go short)

**Stop plot** (`s` and `s1`): ATR-trailing stop line — GREEN when above 0, RED when below 0

**Trading use**:
- Arrow = entry signal direction
- Stop line = trailing stop placement
- Use with STC for confirmation: CCI arrow + STC crossing oversold/overbought = high-conviction entry

---

### G3 — `shared_shared_OB_LBR_BARS_HH_LL17STUDY.ts` (LBR Bars)
**Purpose**: Linda Bradford Raschke volatility paint bars. Identifies when price is at HIGH/LOW extremes based on a double-smoothed ATR, painting bars to show when price is in a high-volatility trending state.

**Exact Parameters**:
```
HLLength = 16   (lookback for Highest/Lowest)
ATRLength = 9   (ATR period, double-smoothed)
factor    = 2.5 (ATR multiplier)
averageType = SIMPLE

AATR = 2.5 × SMA(SMA(TrueRange(9), 9), 9)  ← double-smoothed ATR

band1 = Lowest(low, 16) + AATR    (support envelope)
band2 = Highest(high, 16) - AATR  (resistance envelope)
```

**Bar colors**:
```
GREEN: close > band1 AND close > band2  → BULL TRENDING (above both bands = strong up)
RED:   close < band1 AND close < band2  → BEAR TRENDING (below both bands = strong down)
CURRENT: otherwise (mixed = neutral/consolidating)
```

**Trading use**:
- GREEN LBR bars = trend strength confirmed by volatility → add to longs, tighten stops
- RED LBR bars = trend strength confirmed → add to shorts
- CURRENT bars = low volatility, range-bound → prefer mean reversion trades
- Transition from CURRENT to GREEN/RED = breakout confirmation

---

### G4 — Keltner Channel Suite (4 timeframes = 4 scripts, 1 unique)

**Scripts**: `shared_shared_shared_shared_shared_kmaster1STUDY.ts` (4H) + `shared_shared_shared_shared_kelt_3.01STUDY.ts` (5m extreme) + `shared_shared_OB_OMEGA_5mSTUDY.ts` + `shared_shared_OB_OMEGA_15m7STUDY.ts` + `shared_shared_OB_OMEGA_30m7STUDY.ts`

**Purpose**: Multi-timeframe Keltner Channel system with three band sets per timeframe plus MACD cloud "closed door" signals.

**KMaster (4H) exact parameters**:
```
iAggregationPeriod = 4H

Primary bands (inner):
  Basis = SMA(close[4H], 20)
  ATR   = SMA(TrueRange[4H], 20)
  Upper/Lower = Basis ± 1.5 × ATR  [silver/gray bands]

Secondary bands (outer):
  Upper/Lower = Basis ± 2.0 × ATR  [green bands]

Third bands (intermediate):
  Upper/Lower = Basis ± 1.8 × ATR  [gray bands]
```

**kelt_3.01 (5m extreme) exact parameters**:
```
iAggregationPeriod = 5min
iFactor = 3.0
iLength = 20

Upper/Lower = SMA(close[5m], 20) ± 3.0 × ATR[5m]
[extreme fade zone]
```

**MACD "Closed Door" cloud** (in KMaster):
```
MACD = EMA(12) - EMA(26)
Signal = EMA(MACD, 9)
Diff = MACD - Signal

If Diff < 0 (MACD bearish): Upper bands have DARK CLOUD → upper is "closed" (sellers at upper band)
If Diff > 0 (MACD bullish): Lower bands have DARK CLOUD → lower is "closed" (buyers at lower band)
```

**Omega 5m/15m/30m** (OB_STYLE_CYCLE variants): Same Keltner structure applied to shorter timeframes for intraday band analysis.

**Band interpretation for JARVIS**:
| Band | Significance | Trade Rule |
|------|-------------|------------|
| ±1.5× ATR (inner) | Normal extension | Pullback entry zone |
| ±2.0× ATR (outer) | Extended price | More aggressive entry, wider stop |
| ±3.0× ATR (extreme) | COUNTER-TREND FADE only | Small size, tight stop |
| MACD closed door | Band reinforced | Fade that side only |

**Timeframe stacking**: When 4H, 30m, 15m, 5m Keltner bands all align at the same price level = EXTREMELY STRONG S/R zone.

---

### G5 — `shared_shared_shared_shared_shared_Priceline11STUDY.ts` (Current Price Line)
**Purpose**: Plots a horizontal line at the most recent closing price, extending across the entire chart.

```
priceLine = highestAll(if isNaN(close[-1]) then close else NaN)
[Magenta dashed line at current/last close — CreateColor(233,21,89)]
```

**Use**: Quick visual reference for where the last close settled. Useful for gap detection and overnight level comparison.

---

## PART 2: DUPLICATE FILE MAP (13 duplicates)

| Original | Duplicate(s) |
|----------|-------------|
| `AA_CoreyRFv1Mobile` | `shared_AA_CoreyRangefinderv1_01` |
| `AA_CoreySFv2` | `shared_AA_CoreySinglefinderv2` |
| `AA_CoreyTscorev2` | `shared_AA_CoreyTPOScorev2` |
| `OB_STYLE_CYCLE` | *(base — OB_STYLE_CYCLE_TIMESHIFT is the primary)* |
| `Saty_ATR_Levels` | `shared_Saty_ATR_Levels` |
| `midcloudote` | `shared_midcloudote`, `shared_shared_midcloudote` |
| `kmaster1` | `shared_shared_shared_shared_shared_kmaster1`, `shared_shared_shared_shared_shared_shared_kmaster1` |
| `kelt_3.01` | `shared_shared_shared_shared_kelt_3.01`, `shared_shared_shared_shared_shared_kelt_3.01` |
| `Priceline11` | `shared_shared_shared_shared_shared_Priceline11`, `shared_shared_shared_shared_shared_shared_Priceline11` |

*All duplicates are byte-for-byte identical. The `shared_` nesting is an artifact of TOS export.*

---

## PART 3: THE 5-LAYER "TONY STARK" STRATEGY

> "JARVIS, show me everything." — Tony doesn't look at 34 indicators. He looks at ONE synthesized view.

The entire script library is organized into exactly 5 sequential layers. ALL 5 must align for a valid trade signal. Any single "no" = NO TRADE.

---

### LAYER 1: REGIME FILTER — "Should I even be trading right now?"

**Gate check before looking at any setup.**

**Scripts used**: `Saty_ATR_Levels` (range consumed), `Saty_Phase_Oscillator` (compression/extension), `TRIN_Chetan` (breadth extremes), `Saty_ATR_Levels` (EMA ribbon)

**Regime Classifications**:

| Regime | Exact Conditions | Action |
|--------|-----------------|--------|
| **TRENDING_BULL** | TRIN < 1.0 + Phase > 0 + ATR consumed < 70% + EMA ribbon: EMA8 > EMA21 > EMA34 | Trade longs freely |
| **TRENDING_BEAR** | TRIN > 1.5 + Phase < 0 + ATR consumed < 70% + EMA ribbon: EMA8 < EMA21 < EMA34 | Trade shorts freely |
| **RANGE_BOUND** | TRIN 0.8–1.2 + Phase between -23.6 and +23.6 + price inside Value Area | Mean reversion only |
| **COMPRESSION** | Phase Bollinger inside ATR bands (MAGENTA bars) + ATR consumed < 50% | Wait for breakout — either direction |
| **EXHAUSTED** | ATR consumed > 90% OR price at 2× ATR extension | NO new trades (fade only with 0.5% risk) |

**TRIN thresholds**:
- Capitulation BUY zone: TRIN > 2.0 AND TRIN low > 1.0 AND VIX > 30 → CYAN bars
- Blow-off SELL zone: TRIN < 0.6 AND TRIN high < 1.0 AND VVIX < 120 → MAGENTA bars

**ATR Range Consumed**:
- Formula: `(TrueRange / ATR14) × 100`
- < 70% = GREEN (trade with trend)
- 70–90% = ORANGE (reduce size, caution)
- > 90% = RED (EXHAUSTED, no new directional trades)

**Phase Oscillator compression detection**:
- `BB upper < ATR upper band` = COMPRESSION (imminent breakout)
- Phase at ±61.8 = distribution/accumulation (don't chase)
- Phase at ±100 = extreme (fade only)

---

### LAYER 2: STRUCTURE MAP — "Where are the key levels?"

**Build the price map BEFORE entering any trade.**

**Scripts used**: `AA_CoreyIBv1` (IB), `AA_CoreyTPOProfilev1` (TPO), `ThinkScript_20221014` (VirginProfile), `Saty_ATR_Levels` (ATR Fibs), `ThinkScript_20230523` (Pivots), `kmaster1` (Keltner 4H), `AA_CoreyGapfinderv1` (Gaps), `AA_CoreySFv2` (Singles)

**The Price Map** (from most to least important):

1. **Prior day's close + ATR Fibonacci grid** (Saty_ATR_Levels):
   - Gives the day's entire expected range: 10 levels up + 10 down from prior close
   - Entry trigger: ±0.236 ATR
   - Targets: ±0.382, 0.5, 0.618, 0.786, 1.0 ATR
   - Extensions: ±1.236, 1.5, 2.0, 3.0 ATR

2. **Initial Balance** (AA_CoreyIBv1):
   - IB High/Low = day's primary reference range
   - Internal levels: IB25, IB50 (mid), IB75
   - Breakout extensions: +50%, +100%, +300% of IB range
   - Day bias: above IB High = bullish, below IB Low = bearish

3. **TPO / Volume Profile** (AA_CoreyTPOProfilev1 + Tscore + VirginProfile):
   - POC = fair value (most time/volume)
   - VAH/VAL = 70% value area boundaries
   - Price above VAH = buyer control (bullish)
   - Price inside VA = balanced (mean revert to POC)
   - Price below VAL = seller control (bearish)
   - Virgin VPOCs = HIGH-PRIORITY MAGNETS (track up to 10 above + below)

4. **Pivot Points** (ThinkScript_20230523):
   - PP, R1–R4, S1–S4 from prior day's OHLC
   - Strong when confluent with VPOC, ATR Fib, or Keltner band

5. **Keltner Channels** (kmaster1 4H + Omega 5m/15m/30m):
   - ±1.5 ATR = inner band (normal extension, pullback entry zone)
   - ±2.0 ATR = outer band (extended, more aggressive entry)
   - ±3.0 ATR = extreme band (COUNTER-TREND fade only)
   - MACD closed door = reinforces that side as resistance

6. **Unfilled Gaps** (AA_CoreyGapfinderv1):
   - Gaps above = resistance targets
   - Gaps below = support targets
   - Gap fill = high-probability destination

7. **Single Prints** (AA_CoreySFv2):
   - Bull single = support zone (buy on test)
   - Bear single = resistance zone (sell on test)

**Confluence Rule**:
- STRONG S/R: 2+ of the above at same price level
- WEAK S/R: Only 1 indicator
- EXTREME S/R: 3+ indicators (highest conviction)

---

### LAYER 3: DIRECTIONAL BIAS — "Which way is this likely to go?"

**Scripts used**: `AA_CoreyTscorev2` (TPO Score), `NextSignalMomentum` (KAMA), `Saty_Volume_Stack` (volume), `Saty_ATR_Levels` (EMA ribbon)

**TPO Score System** (5 components, ±1 each):
```
scorevah   = price above VAH → +1 (buyer control)
scoreval   = price below VAL → -1 (seller control)
scorepoc   = price above POC → +1 (buyers in charge)
scorevabal = price above VA balance → +1 (positive momentum)
scoreimbal = Bull imbalance → +1; Bear imbalance → -1
```

**KAMA Direction** (NextSignalMomentum):
```
LONG: close > AMA AND LinReg(7) > 0 AND LinReg(20) > 0
SHORT: close < AMA AND LinReg(7) < 0 AND LinReg(20) < 0
NEUTRAL: mixed LinReg slopes
```

**Volume Stack** (Saty_Volume_Stack):
```
Buyers > 60% → bullish confirmation
Sellers > 60% → bearish confirmation
40–60% → balanced, no edge
```

**Bias Classification**:
| Bias | Required Conditions |
|------|-------------------|
| STRONG_BULL | TPO score ≥ +3 AND KAMA long AND volume buyers > 60% |
| LEAN_BULL | 2 of above bullish + EMA ribbon all stacked up |
| NEUTRAL | Mixed signals, price inside VA, TPO score 0, or STC in 20–80 zone |
| LEAN_BEAR | 2 bearish conditions + EMA ribbon all stacked down |
| STRONG_BEAR | TPO score ≤ -3 AND KAMA short AND volume sellers > 60% |

---

### LAYER 4: ENTRY TIMING — "When exactly do I pull the trigger?"

**Scripts used**: `OB_STYLE_CYCLE` (STC), `AA_CoreyRFv2` (outside bars), `kmaster1` (Keltner entries), `AA_CoreyGapfinderv1` (gap fills), `AA_CoreySFv2` (single print entries), `shared_mtftrendbar` (CCI confirmation)

**STC (Schaff Trend Cycle) — PRIMARY ENTRY TOOL**:
```
BUY trigger:  STC crosses UP through 23  (oversold → rising)
SELL trigger: STC crosses DOWN through 83 (overbought → falling)

[Note: Base script uses 19/88 — JARVIS uses optimized 23/83 from 162-combo grid search]

Bull momentum zone: STC 23–83, rising = hold/add longs
Bear momentum zone: STC 83–23, falling = hold/add shorts
```

**Range Finder signals** (AA_CoreyRFv2):
```
GREEN up arrow: Outside bar + bullish 3-bar + bottom excess → CONTINUATION UP
RED down arrow: Outside bar + bearish 3-bar + top excess → CONTINUATION DOWN
YELLOW arrow:   Caution — flip or mixed signals
```

**Keltner Channel entries**:
```
±1.5× ATR touch: Pullback entry on trend confirmation
±2.0× ATR touch: More aggressive entry, wider stop required
±3.0× ATR touch: COUNTER-TREND FADE only (small size, tight stop)
MACD closed door on touched band → fade that side
```

**CCI confirmation** (mtftrendbar):
```
CCI crosses from negative to positive (UP arrow) → confirms long entry
CCI crosses from positive to negative (DOWN arrow) → confirms short entry
ATR trailing stop line = additional confirmation of direction
```

**Entry Signal Classification**:
| Signal | Conditions |
|--------|-----------|
| ENTRY_NOW | STC crosses 23/83 + RFv2 arrow + Layers 1–3 aligned |
| WAIT_FOR_PULLBACK | Bias confirmed, STC 20–80 midzone, wait for retracement to POC/Keltner |
| FADE_EXTREME | Regime=EXHAUSTED, ATR>90%, Phase>+61.8 or <-61.8, counter-trend small size |
| NO_TRADE | Regime=EXHAUSTED without fade setup, or Bias=NEUTRAL, or conflicting signals |

---

### LAYER 5: POSITION SIZING & RISK MANAGEMENT — "How much, where's the stop, what's the target?"

**Stop Loss Rules**:
```
Long stop:  Below the LOWER of: IB Low  OR nearest Keltner inner band (±1.5 ATR)
Short stop: Above the HIGHER of: IB High OR nearest Keltner inner band (±1.5 ATR)
Maximum stop distance: 1.0 × ATR from entry (hard cap)
Minimum stop distance: 0.25 × ATR (avoid stops too tight)
```

**Profit Target Rules** (ATR Fibonacci from Saty_ATR_Levels):
```
Target 1 (50% exit): Entry ± 0.382 × ATR
Target 2 (30% exit): Entry ± 0.618 × ATR
Target 3 (20% exit): Entry ± 1.000 × ATR
→ Move stop to breakeven after Target 1 is hit
```

**Position Sizing**:
```
Risk per trade: 1% of account equity
Contracts: floor((account × 0.01) / (stop_distance × contract_multiplier))
Minimum: 1 contract
```

**Contract Multipliers**:
| Symbol | Multiplier |
|--------|-----------|
| MES (Micro S&P) | $5 per point |
| MNQ (Micro Nasdaq) | $2 per point |
| MGC (Micro Gold) | $10 per oz |
| M2K (Micro Russell) | $5 per point |
| MYM (Micro Dow) | $0.50 per point |

**Kill Switch Rules** (HARDCODED — cannot be overridden):
```
Daily loss limit: Stop ALL trading if day P&L < -2% of starting account
Drawdown limit: Stop ALL trading if drawdown from high-water mark > 5%
Regime shift: If mid-trade regime becomes EXHAUSTED → exit at market or next T1
Intraday reset: Kill switch resets at midnight CT
```

---

## PART 4: THE SYNTHESIS RULE

```
VALID TRADE =
  Layer 1 (Regime) ≠ EXHAUSTED
  AND Layer 2 (Structure) shows clear S/R with ≥ 2 confluence factors
  AND Layer 3 (Bias) ≠ NEUTRAL
  AND Layer 4 (Timing) = ENTRY_NOW
  AND Layer 5 (Risk) R:R ≥ 1.5:1

ANY single "no" from any layer = NO TRADE
```

---

## PART 5: INDICATOR OVERLAP MAP

| Indicator Category | Scripts Using It | Key Overlap |
|-------------------|-----------------|-------------|
| **Fibonacci Extensions** | RFv2, RFv1, TPOProfile, TScore, ATR_Levels | All use 0.382/0.5/0.618/0.786/1.0/2.0 — but from DIFFERENT bases |
| **Volume Profile** | RFv2, TPOProfile, TScore, VirginProfile | All use 70% value area; VirginProfile adds Virgin tracking |
| **ATR** | ATR_Levels(14 Wilder), Phase(14), CCI(5 SMA), LBR(9 SMA), Keltner(20 SMA) | Different periods for different purposes |
| **EMA** | ATR_Levels(8/21/34), TScore(8/13), IB(8/13), MidCloud(21) | JARVIS uses 8/21/34 as primary ribbon |
| **POC/VAH/VAL** | RFv2, TPOProfile, TScore, VirginProfile | Consistent; Virgin adds "unvisited" qualifier |

---

## PART 6: BACKTEST RESULTS (2024 Data, Optimized Parameters)

**Parameters**: STC oversold=23 (vs default 19), STC overbought=83 (vs default 88), Regime filter ENABLED

| Symbol | Period | Trades | Win Rate | Profit Factor | Total P&L |
|--------|--------|--------|----------|---------------|-----------|
| SPY | 2024 daily | 10 | 30.0% | 8.65 | +$1,462 |
| MES | 2024 daily | 9 | 33.3% | 6.09 | +$8,333 |

**Key finding**: The REGIME FILTER (Layer 1) has the greatest impact. Filtering out EXHAUSTED and NEUTRAL regimes eliminated most false entries while preserving all major winning trades.

---

## PART 7: DAILY WORKFLOW — HOW TO USE ALL SCRIPTS TOGETHER

**Pre-market (before 9:30 CT)**:
1. Check `Saty_ATR_Levels`: What are the ATR Fibonacci levels from prior close? Mark call trigger (+0.236 ATR) and put trigger (-0.236 ATR). These are today's expected turning points.
2. Check `VirginProfile`: Are there any Virgin VPOCs near current price? These are magnets for today.
3. Check `Pivot Points`: Mark PP, R1–R2, S1–S2 for confluence.
4. Check `TRIN`: Is breadth showing capitulation or blow-off? Colors will tell you.
5. Check `Phase Oscillator`: MAGENTA (compression) = get ready to trade a breakout.

**9:30–10:30 CT (IB formation)**:
6. Watch `AA_CoreyIBv1` build the Initial Balance. IB High and IB Low are now the day's anchor.
7. Note IB Range and the ±50%/±100% extension levels.
8. Check where IB forms relative to ATR levels — do they align?

**After IB is set (10:30 CT onward)**:
9. Determine day bias from `AA_CoreyTscorev2`: TPO Score positive or negative?
10. Confirm with `NextSignalMomentum` (KAMA): Are you above or below AMA? LinReg aligned?
11. Confirm with `Saty_Volume_Stack`: Buyers or sellers winning by >60%?
12. Wait for `STC` to cross 23 (buy) or 83 (sell) with all 3 confirmations above aligned.
13. Check `AA_CoreyRFv2` for outside bar arrow in same direction.
14. Enter at next ATR Fib trigger level with stop below IB Low / Keltner band.

**During trade**:
15. Monitor `Phase Oscillator`: Rising toward +61.8 with a long? Scale out 50% there.
16. Monitor `LBR Bars`: If turns GREEN = trend is strong, hold. If turns CURRENT = reduce.
17. Target 1 = +0.382 ATR. Move stop to breakeven. Let T2 and T3 ride.

---

*This document contains the complete analysis of all 34 ThinkScript files in the JARVIS TRADER library.*
*For implementation details, see: `engine/backtest/signals.py`, `engine/agents/rules/trading_rules.md`, `engine/agents/rules/agent_prompts.py`*
