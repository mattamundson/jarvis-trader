# JARVIS TRADER — ThinkorSwim Integration Guide

**Version**: 1.0
**Generated**: 2026-03-29
**Purpose**: Map every TOS script to the JARVIS 5-layer signal framework. Get visual/audio TOS alerts that mirror JARVIS trade signals.

---

## SECTION 1: Script Inventory by Layer

The 34 .ts files contain **21 unique scripts** (13 are nested `shared_` duplicates created by TOS during export/sharing). The table below maps each unique script to its role in the JARVIS framework.

---

### Layer 1 — Regime Map
*What regime is the market in? (TRENDING_BULL, TRENDING_BEAR, COMPRESSION, RANGE_BOUND, EXHAUSTED)*

| Script File | What It Shows | JARVIS Regime Signal |
|---|---|---|
| `Saty_ATR_LevelsSTUDY.ts` | **EMA Ribbon (8/21/34)** on price chart. Green label = bullish, red = bearish, orange = mixed. Also shows ATR range consumed % vs full ATR. | `ema_trend` → TRENDING_BULL / TRENDING_BEAR. ATR % label directly matches `atr_consumed_pct` (>90% = EXHAUSTED) |
| `Saty_Phase_OscillatorSTUDY.ts` | Phase oscillator from -100 to +100. Magenta = compression. Green/red = directional phase. Fibonacci zone lines at ±23.6, ±61.8, ±100 | `phase_val` and `phase_compression`. Compression (magenta) = JARVIS COMPRESSION regime |
| `shared_mtftrendbarSTUDY.ts` | CCI-based trend trail stop line (green = long, red = short). Multi-timeframe — defaults to 5m but configurable. Up/down arrows on CCI zero-cross | Supplementary regime confirmation via CCI(50). Arrows = directional flip |

**EMA Ribbon Rule** (hardcoded in `Saty_ATR_LevelsSTUDY.ts`):
- `fast_ema=8`, `pivot_ema=21`, `slow_ema=34`
- `bullish = price >= ema8 >= ema21 >= ema34`
- `bearish = price <= ema8 <= ema21 <= ema34`
- This is the exact same logic as `ema_ribbon()` in `engine/backtest/indicators.py`

---

### Layer 2 — Structure Map
*WHERE is price relative to value? (BUYER_CONTROL, SELLER_CONTROL, NEUTRAL_STRUCTURE)*

| Script File | What It Shows | JARVIS Structure Signal |
|---|---|---|
| `AA_CoreyTPOProfilev1STUDY.ts` | TPO time profile with **POC** (white), **VAH/VAL** (cyan), profile high/low. Also plots VA balance midpoint and Fibonacci extensions from POC | POC ≈ VPOC. VAH = va_high. VAL = va_low. Price above VAH + POC = BUYER_CONTROL |
| `AA_CoreyTscorev2STUDY.ts` | TPO score that quantifies price vs POC/VAH/VAL as a numeric score. Outputs labels: "Buyers in Control above X", "Price above/below Value", TPO Score positive/negative/neutral | Direct score readout of JARVIS `layer2_structure()`. Positive score = BUYER_CONTROL |
| `AA_CoreyIBv1STUDY.ts` | **Initial Balance** (first 60-min RTH range). IB High (red), IB Low (green), quadrant lines (25/50/75%), extensions up/down (50%, 100%, 3x). Extends forward to next session. EMA 8/13 cross embedded | `ib_high` / `ib_low`. IB High breakout = JARVIS ENTRY_NOW trigger. `above_ib_high` flag in `layer4_entry()` |
| `AA_CoreyRFv2STUDY.ts` | **Rangefinder v2** — dynamic volume profile that resets on each new expansion range. Shows POC/VAH/VAL of current range + Fibonacci extensions. Control zone (38.2–61.8% of range from POC) highlighted | Fills in as VP context between IB resets. Range High/Low extension lines = price imbalance targets |
| `AA_CoreySFv2STUDY.ts` | **Singlefinder v2** — identifies "single prints" (price areas visited only once, leaving gaps in the TPO profile). Bullish singles (pink) below price, bearish singles (orange) above price. Fail dots added | Gap-fill targets. Unfilled singles act as magnets. Complements gap-fill bias in Layer 2 |
| `AA_CoreyGapfinderv1STUDY.ts` | Marks open-to-close gaps. Gap Down zones (red), Gap Up zones (green). Lines extend right until gap is filled | Supplementary Layer 2 context. Unfilled gap above = resistance to respect before initiating longs |

---

### Layer 3 — Bias
*What is the directional lean? (STRONG_BULL, LEAN_BULL, NEUTRAL, LEAN_BEAR, STRONG_BEAR)*

| Script File | What It Shows | JARVIS Bias Signal |
|---|---|---|
| `NextSignalMomentumSTUDY.ts` | **KAMA** (Kaufman Adaptive Moving Average, period=10) plotted on price. Blue = price above KAMA (long bias). Red = price below KAMA (short bias). Also plots 7-bar and 20-bar linear regression lines | `kama_signal` = long/short. Matches `kama()` in indicators.py exactly |
| `Saty_Volume_StackSTUDY.ts` | **Volume Stack** — buy/sell volume separated by candle OHLC ratio. Winner stacked on top. Label shows buy% and sell% each bar | `buy_pct`. >60% = buyer_dominant (bull point), <40% = seller_dominant (bear point) |
| `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` | **STC (Schaff Trend Cycle)** — oscillator 0-100. Green = rising, red = falling. Crossover arrows at overbought/oversold. Multi-timeframe via `TimeShift` input. Paints price bars | `stc_val`, `stc_cross_up`, `stc_cross_down`. The crossover arrows ARE the JARVIS `stc_cross_up` / `stc_cross_down` entry signals |

**Note**: `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` also embeds supplementary level plots (`StyleBuy=15`, `StyleSell=85`, `Midline=50`, `BULLTRIGGER=82`, `Beartrigger=20`) that shadow JARVIS thresholds.

---

### Layer 4 — Entry Timing
*Is this bar an entry? (ENTRY_NOW, WAIT_FOR_PULLBACK, NO_TRADE, FADE_EXTREME)*

| Script File | What It Shows | JARVIS Entry Signal |
|---|---|---|
| `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` | STC crossover arrows: **RegularBuy** = green arrow up when STC crosses above oversold. **RegularSell** = red arrow down when STC crosses below overbought | `stc_cross_up` → ENTRY_NOW (long). `stc_cross_down` → ENTRY_NOW (short). The TOS arrows ARE the entry signals |
| `AA_CoreyIBv1STUDY.ts` | IB High breakout: when price closes above IB High line with cloud confirmation | `above_ib_high` fresh breakout → ENTRY_NOW (unconditional, per `layer4_entry()`) |
| `shared_shared_shared_shared_kelt_3.01STUDY.ts` | **Keltner Channel** — single-factor version. Default `iFactor=3.0`, `iLength=20`, SMA type. Multi-timeframe via `iAggregationPeriod` input. Plots Avg, Upper_Band, Lower_Band | Keltner breakout at 3.0x band = extreme level. Channel basis = JARVIS `kelt_basis` |
| `shared_shared_OB_OMEGA_5mSTUDY.ts` | **OB Omega** — dual Keltner (1.5x and 2.0x factors). Plots as horizontal level lines with labels ("1hr Top", "Daily Bottom"). Cloud shading between bands. Embedded MACD primer cloud | Outer/inner Keltner bands. Outer band (2.0x) breach = JARVIS outer Keltner signal. Inner (1.5x) = inner band |
| `shared_shared_OB_OMEGA_15m7STUDY.ts` | OB Omega scaled for 15-min aggregation | Same as above, different default timeframe |
| `shared_shared_OB_OMEGA_30m7STUDY.ts` | OB Omega scaled for 30-min aggregation | Same as above, different default timeframe |
| `AA_CoreyRFv2STUDY.ts` | Range expansion arrows (up=green, down=red) trigger on new range expansions | Breakout confirmation. Arrow up + bull bias = ENTRY_NOW candidate |

---

### Layer 5 — Position Sizing (ATR-Based Stops & Targets)

| Script File | What It Shows | JARVIS Sizing Signal |
|---|---|---|
| `Saty_ATR_LevelsSTUDY.ts` | **All ATR Fibonacci levels** from prior close. 0.236×, 0.382×, 0.5×, 0.618×, 0.786×, 1.0×, (extensions: 1.236×–3.0×). Cyan trigger line = +0.236 ATR (calls), orange = -0.236 ATR (puts) | `stop_level` = 0.70 ATR. `target_1` = 1.50 ATR. `target_2` = 2.618 ATR. `target_3` = 4.0 ATR. All visible on chart simultaneously |
| `shared_Saty_ATR_LevelsSTUDY.ts` | Duplicate of above for TOS sharing import | Same as above |

**Key**: The 0.70 ATR stop level falls between the 0.618 and 0.786 Fibonacci lines on the Saty ATR Levels chart. The 1.50 ATR T1 is between the 1.382 and 1.618 lines. The 2.618 ATR T2 is the golden ratio extension line exactly.

---

### Supporting/Supplementary Scripts

| Script File | Purpose | Use Case |
|---|---|---|
| `GAPS_Chetan1STUDY.ts` | Alternative gap-finder (Chetan version) | Use alongside Corey gap finder for double confirmation |
| `TRIN_ChetanSTUDY.ts` | TRIN (Arms Index) for market internals | Macro sentiment. High TRIN (>2.0) = extreme selling, signals potential reversal |
| `ThinkScript_study_20221014STUDY.ts` | Custom utility script (Oct 2022) | Review contents if additional context needed |
| `ThinkScript_study_20221016STUDY.ts` | Custom utility script (Oct 2022) | Review contents if additional context needed |
| `ThinkScript_study_20230523STUDY.ts` | Custom utility script (May 2023) | Review contents if additional context needed |
| `AA_CoreyRFv1MobileSTUDY.ts` | Rangefinder v1 mobile variant | Legacy — use RFv2 instead |

---

## SECTION 2: Critical Settings — Match JARVIS Engine Parameters

These are the exact parameter values used by the JARVIS engine (`engine/backtest/signals.py` and `engine/backtest/indicators.py`). Set them identically in TOS to see the same signals.

---

### STC (Schaff Trend Cycle) — `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts`

| Parameter | TOS Input Name | JARVIS Value | Notes |
|---|---|---|---|
| Fast EMA length | `fastLength` | **23** | Set in TOS study settings |
| Slow EMA length | `slowLength` | **50** | Set in TOS study settings |
| %K period | `KPeriod` | **10** | Set in TOS study settings |
| %D smoothing | `DPeriod` | **3** | Set in TOS study settings |
| Oversold (1h chart) | `over_sold` | **15** | Change from TOS default of 19 |
| Oversold (daily chart) | `over_sold` | **23** | Different value for daily timeframe |
| Overbought | `over_bought` | **83** | Change from TOS default of 88 |
| TimeShift (1h trading) | `TimeShift` | **1h** | Match chart timeframe |
| TimeShift (daily trading) | `TimeShift` | **Daily** | Match chart timeframe |
| Paint bars | `paintBars` | **yes** | Recommended for visual clarity |

**Optimization note**: The default TOS values (OS=19, OB=88) were replaced by grid search over 162 combinations on SPY 2024–2026. The 1h optimal (OS=15, OB=83) scored 496; daily optimal (OS=23, OB=83) scored 493.

---

### ATR Levels — `Saty_ATR_LevelsSTUDY.ts`

| Parameter | TOS Input Name | JARVIS Value | Notes |
|---|---|---|---|
| ATR period | `atr_length` | **14** | Wilder's smoothing, period=14 |
| Trading type | `trading_type` | **Day** (1h charts) | Controls aggregation period for ATR |
| Fast EMA | `fast_ema` | **8** | Must match JARVIS ribbon |
| Pivot EMA | `pivot_ema` | **21** | Must match JARVIS ribbon |
| Slow EMA | `slow_ema` | **34** | Must match JARVIS ribbon |
| Show extensions | `show_extensions` | **yes** | Needed to see 1.5x–3.0x levels |
| Show all Fibonacci | `show_all_fibonacci_levels` | **yes** | Shows all intermediate levels |
| Trigger percentage | `trigger_percentage` | **0.236** | Trigger/call-put level at 0.236 ATR |

**JARVIS stop & target levels on the ATR chart**:
- Stop loss: **0.70 ATR** → between the 0.618 and 0.786 lines
- T1 target: **1.50 ATR** (1h) → the `upper_1500` / `lower_1500` lines
- T1 target: **2.00 ATR** (daily) → the `upper_2000` / `lower_2000` lines (white)
- T2 target: **2.618 ATR** → the `upper_2618` / `lower_2618` lines (golden ratio extension)
- T3 target: **4.00 ATR** → beyond the chart at 3x; manually calculate or extend

---

### Keltner Channels — `shared_shared_OB_OMEGA_5mSTUDY.ts`

| Parameter | TOS Input Name | JARVIS Value | Notes |
|---|---|---|---|
| Inner factor | `factor` | **1.5** | Inner channel |
| Outer factor | `factor2` | **2.0** | Outer channel |
| SMA length | `length` | **20** | Matches `keltner_channels(sma_len=20)` |
| Aggregation period | `period` | Match chart TF | Use HOUR for 1h charts |

For the 3.0x band (used in JARVIS for extreme extension), use `shared_shared_shared_shared_kelt_3.01STUDY.ts` with `iFactor=3.0`.

**JARVIS Keltner signal interpretation**:
- Price between basis and 1.5x upper = normal bull trend
- Price touches 1.5x upper = moderate extension
- Price touches 2.0x upper = significant extension, consider partial profit
- Price touches 3.0x upper = extreme extension (`FADE_EXTREME` regime condition)
- Mirror logic applies for short side (lower bands)

---

### EMA Ribbon — `Saty_ATR_LevelsSTUDY.ts` (embedded)

| Parameter | Value |
|---|---|
| Fast EMA | **8** |
| Pivot EMA | **21** |
| Slow EMA | **34** |
| Bullish condition | price >= ema8 >= ema21 >= ema34 |
| Bearish condition | price <= ema8 <= ema21 <= ema34 |

The ribbon is **not a separate script** — it is baked into `Saty_ATR_LevelsSTUDY.ts` as the trend label logic. The three EMA values are not plotted as lines by default (the script uses them for the label color only). To see the ribbon as lines, add three separate EMA plots in TOS or enable them via the `show_info` label.

---

### Phase Oscillator — `Saty_Phase_OscillatorSTUDY.ts`

| Parameter | TOS Variable | JARVIS Value |
|---|---|---|
| EMA length | `ExpAverage(close, 21)` | **21** (hardcoded) |
| ATR for bands | `ta.atr(14)` | **14** (hardcoded) |
| BB length | `STDev(close, 21)` | **21** (hardcoded) |
| BB std dev | `2.0 * STDev(...)` | **2.0** (hardcoded) |
| Phase formula | `(close - EMA) / (3 * ATR) * 100` | Exact match |

**JARVIS Phase thresholds**:
- `phase >= 61.8` = extended_up → potential EXHAUSTED regime
- `phase <= -61.8` = extended_down → potential EXHAUSTED regime
- `phase > 23.6` = bullish
- `phase < -23.6` = bearish
- `is_compression` (magenta) = COMPRESSION regime

---

### KAMA — `NextSignalMomentumSTUDY.ts`

| Parameter | TOS Input | JARVIS Value |
|---|---|---|
| Mode | `mode` | **KAMA** (not AMA) |
| Period | direction/volatility window | **10** (hardcoded as `close[10]` and `Sum(..., 10)`) |
| Fast SC | ScaledSF fast bound | **0.4** (= 2/(2+1) from indicators.py `fast_period=2`) |
| Slow SC | SlowSF | **0.2222** (= 2/(30+1) from indicators.py `slow_period=30`) |

**Signal**: Label at bottom of chart. "Long" label (blue) = price above KAMA. "Short" label (red) = price below KAMA. Bar colors match (blue = bull, red = bear).

---

## SECTION 3: Step-by-Step TOS Import

### Import a Study from a .ts File

1. Open ThinkorSwim
2. Go to **Charts** tab
3. Click **Studies** (beaker icon) in the upper right of the chart
4. Select **Edit Studies**
5. In the Studies window, click the icon that looks like a wrench or a code bracket (`</>`) — "thinkScript Editor"
6. In the editor window, click **Open** (folder icon)
7. Navigate to your `thinkorswim-scripts/` directory
8. Select the `.ts` file to import
9. Click **Save As** in the editor — give it a name (e.g., "Saty ATR Levels")
10. Close the editor
11. In the Edit Studies window, find your newly saved study in the "All Studies" list
12. Double-click or click the "+" button to add it to the chart
13. Configure parameters in the study settings dialog
14. Click **Apply**, then **OK**

### Import Order (Recommended)

Import scripts in this order to avoid dependency confusion:

**Sub-studies first** (these are called by wrappers):
1. `shared_shared_shared_shared_kelt_3.01STUDY.ts` — Keltner core
2. `shared_shared_shared_shared_shared_kmaster1STUDY.ts` — KMaster support
3. `shared_shared_shared_shared_shared_Priceline11STUDY.ts` — Price line support

**Main studies next**:
4. `Saty_ATR_LevelsSTUDY.ts` — ATR levels + EMA ribbon
5. `Saty_Phase_OscillatorSTUDY.ts` — Phase oscillator (lower panel)
6. `Saty_Volume_StackSTUDY.ts` — Volume stack (lower panel)
7. `NextSignalMomentumSTUDY.ts` — KAMA on price
8. `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` — STC (lower panel)
9. `AA_CoreyTPOProfilev1STUDY.ts` — TPO profile (on price)
10. `AA_CoreyTscorev2STUDY.ts` — TPO score (lower panel)
11. `AA_CoreyIBv1STUDY.ts` — Initial Balance (on price)
12. `AA_CoreyRFv2STUDY.ts` — Rangefinder v2 (on price)
13. `AA_CoreySFv2STUDY.ts` — Singlefinder v2 (on price)
14. `AA_CoreyGapfinderv1STUDY.ts` — Gap finder (on price)
15. `shared_mtftrendbarSTUDY.ts` — MTF trend bar (on price)
16. `shared_shared_OB_OMEGA_5mSTUDY.ts` — OB Omega Keltner (on price)
17. `TRIN_ChetanSTUDY.ts` — TRIN (separate chart/panel)

### Save as a Chart Layout

After importing all studies, save the chart setup:
1. Right-click the chart → **Save Chart Setup As**
2. Name it "JARVIS 5-Layer Setup"
3. This saves the study configuration for quick reload

---

## SECTION 4: Signal Alignment Table

This table maps every JARVIS engine signal to its TOS visual/audio equivalent and the exact alert condition to create.

### How to Create a TOS Alert
For each row in the table below:
1. Right-click the chart → **Add Alert for Study Plot**
2. OR go to **MarketWatch** → **Alerts** → **Create Alert**
3. Select Study condition, set threshold, choose sound (Bell, Ding, Ring, etc.)
4. Enable **Send email** or **Push notification** for critical alerts

---

### Layer 1 — Regime Alerts

| JARVIS Signal | Condition | TOS Study | TOS Alert Condition |
|---|---|---|---|
| `COMPRESSION` regime | Phase oscillator turns magenta | `Saty_Phase_OscillatorSTUDY` | Alert when `is_compressed = 1` crosses above 0 (study plot "is_compressed" value changes to 1) |
| `TRENDING_BULL` starts | EMA8 > EMA21 > EMA34 AND price above all | `Saty_ATR_LevelsSTUDY` | No direct alert plot. Monitor the label color turning GREEN |
| `TRENDING_BEAR` starts | EMA8 < EMA21 < EMA34 AND price below all | `Saty_ATR_LevelsSTUDY` | Monitor the label color turning RED |
| `EXHAUSTED` regime | Range consumed > 90% of ATR | `Saty_ATR_LevelsSTUDY` | ATR % label turns RED (built-in: `tr_percent_of_atr >= 90` → red label) |
| Phase extended up | Phase >= 61.8 | `Saty_Phase_OscillatorSTUDY` | Alert when `phase_oscillator` crosses above 61.8 (distribution_zone line) |
| Phase extended down | Phase <= -61.8 | `Saty_Phase_OscillatorSTUDY` | Alert when `phase_oscillator` crosses below -61.8 (accumulation_zone line) |

---

### Layer 2 — Structure Alerts

| JARVIS Signal | Condition | TOS Study | TOS Alert Condition |
|---|---|---|---|
| `BUYER_CONTROL` | Close > VAH AND close > IB High | `AA_CoreyTscorev2STUDY` | TPO Score label shows "Buyers in Control" AND `AA_CoreyIBv1` price above IB High line |
| `SELLER_CONTROL` | Close < VAL AND close < IB Low | `AA_CoreyTscorev2STUDY` | TPO Score label shows "Sellers in Control" AND price below IB Low |
| IB High breakout | Close crosses above IB High this bar | `AA_CoreyIBv1STUDY` | Alert on price crossing above `OpenRangeHigh` / `IBHighext` plot. Set alert: `close crosses above IB_High_value` |
| IB Low breakdown | Close crosses below IB Low this bar | `AA_CoreyIBv1STUDY` | Alert on price crossing below `OpenRangeLow` / `IBLowext` plot |
| Price above VAH | Close > VAH | `AA_CoreyTPOProfilev1STUDY` | Alert when `close` crosses above `VAHigh` plot |
| Gap fill in progress | Price enters gap zone | `AA_CoreyGapfinderv1STUDY` | Alert when `close` crosses into gap zone (GUS or GDS plot levels) |

---

### Layer 3 — Bias Alerts

| JARVIS Signal | Condition | TOS Study | TOS Alert Condition |
|---|---|---|---|
| `kama_signal = long` | Close crosses above KAMA | `NextSignalMomentumSTUDY` | Alert when `close` crosses above `MAA` plot. Sound: Ding |
| `kama_signal = short` | Close crosses below KAMA | `NextSignalMomentumSTUDY` | Alert when `close` crosses below `MAA` plot. Sound: Ding |
| `buyer_dominant` (>60%) | Buy volume > sell volume substantially | `Saty_Volume_StackSTUDY` | No direct threshold alert in TOS. Visually monitor for green dominance bars |
| `seller_dominant` (<40%) | Sell volume dominant | `Saty_Volume_StackSTUDY` | Visually monitor for red dominance bars |
| `stc_signal = rising` | STC trending up | `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY` | Monitor STC line color (green = rising) |
| `stc_signal = falling` | STC trending down | `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY` | Monitor STC line color (red = falling) |

---

### Layer 4 — Entry Alerts (Most Critical)

| JARVIS Signal | Condition | TOS Study | TOS Alert Condition |
|---|---|---|---|
| `ENTRY_NOW` (STC cross long) | STC crosses above oversold (15 on 1h, 23 on daily) | `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY` | Alert when `RegularBuy` plot is not NaN (the green up arrow appears). Sound: **Bell** |
| `ENTRY_NOW` (STC cross short) | STC crosses below overbought (83) | `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY` | Alert when `RegularSell` plot is not NaN (the red down arrow appears). Sound: **Bell** |
| `ENTRY_NOW` (IB breakout long) | Close crosses above IB High fresh this bar | `AA_CoreyIBv1STUDY` | Alert when `close` crosses above `IBHighext`. Sound: **Ring** |
| `ENTRY_NOW` (IB breakdown short) | Close crosses below IB Low fresh this bar | `AA_CoreyIBv1STUDY` | Alert when `close` crosses below `IBLowext`. Sound: **Ring** |
| `FADE_EXTREME` | Phase > 61.8 AND ATR consumed > 90% | Combined: `Saty_Phase_OscillatorSTUDY` + `Saty_ATR_LevelsSTUDY` | Phase crosses above 61.8 AND ATR label is red simultaneously |
| Range expansion long | New range expansion up arrow | `AA_CoreyRFv2STUDY` | Alert on `ExpandArrowUp` plot. Used as additional ENTRY_NOW confirmation |
| Keltner inner breach | Price touches 1.5x upper band | `shared_shared_OB_OMEGA_5mSTUDY` | Alert when `close` crosses above `Upper_Band1` plot. Sound: Ding |
| Keltner outer breach | Price touches 2.0x upper band | `shared_shared_OB_OMEGA_5mSTUDY` | Alert when `close` crosses above `Upper_Band2` plot. Sound: Bell |

---

### Layer 5 — Stop & Target Levels

| JARVIS Level | ATR Multiple | TOS Visual | Action |
|---|---|---|---|
| Stop loss | **0.70 ATR** | Between `lower_0618` (orange) and `lower_0786` (gray) on Saty ATR chart | Set hard stop at this price at entry |
| T1 target (1h) | **1.50 ATR** | `upper_1500` line on Saty ATR chart | First profit target — exit 50% of position |
| T1 target (daily) | **2.00 ATR** | `upper_2000` line (white) on Saty ATR chart | First profit target for daily trades |
| T2 target | **2.618 ATR** | `upper_2618` line (light gray extension) | Second target — exit 30% of remaining |
| T3 target (runner) | **4.00 ATR** | Not shown by default — calculate manually | Runner target — exit final 20% |

**Alert setup for targets**: Create price alerts (not study alerts) at calculated levels after entry:
1. Note current ATR from the Saty ATR label (`ATR ($X.XX)`)
2. Calculate: T1 = entry_price + (1.50 × ATR) for longs
3. Right-click chart at that price level → Add Alert

---

## SECTION 5: Setup Checklist

Follow this exact order when setting up the full 5-layer JARVIS display on a TOS chart.

### Pre-Work

- [ ] Download all 34 .ts files from `thinkorswim-scripts/` to a local folder
- [ ] Choose your primary trading timeframe (1h for intraday, daily for swing)
- [ ] Set chart to correct symbol (SPY, MES=F, MNQ=F, etc.)

---

### Step 1: Price Chart Studies (Upper Panel)

Add these studies to the main price panel in this order:

- [ ] **`Saty_ATR_LevelsSTUDY.ts`** — Import and add to chart
  - Set `trading_type` = Day (for 1h charts) or Multiday (for daily charts)
  - Verify `fast_ema=8`, `pivot_ema=21`, `slow_ema=34`
  - Set `show_extensions=yes`
  - Confirm ATR level lines are visible on chart

- [ ] **`NextSignalMomentumSTUDY.ts`** — Import and add to chart
  - Mode = KAMA
  - Verify blue/red color on price bars

- [ ] **`AA_CoreyTPOProfilev1STUDY.ts`** — Import and add to chart
  - `timePerProfile` = day
  - `showPointOfControl` = yes
  - `showValueArea` = yes
  - `valueAreaPercent` = 70
  - Confirm POC (white line) and VAH/VAL (cyan lines) visible

- [ ] **`AA_CoreyIBv1STUDY.ts`** — Import and add to chart
  - `OpenRangeMinutes` = 60 (first hour = IB)
  - `MarketOpenTime` = 0930
  - `ShowQuads` = yes
  - `ShowExtensions` = yes
  - `ShowLabels` = yes
  - Confirm red IB High and green IB Low lines visible after 10:30 AM ET

- [ ] **`AA_CoreyRFv2STUDY.ts`** — Import and add to chart
  - `showExtensions` = yes
  - `showRfClouds` = yes
  - `showControlZone` = yes
  - `showArrows` = yes

- [ ] **`AA_CoreySFv2STUDY.ts`** — Import and add to chart
  - `ShowExtensions` = yes
  - `ShowArrows` = yes

- [ ] **`AA_CoreyGapfinderv1STUDY.ts`** — Import and add to chart
  - Default settings are fine

- [ ] **`shared_mtftrendbarSTUDY.ts`** — Import and add to chart
  - Set `timeframe` = HOUR (for 1h-based regime confirmation)

- [ ] **`shared_shared_OB_OMEGA_5mSTUDY.ts`** — Import and add to chart
  - Set `period` = AggregationPeriod.HOUR for 1h trading
  - Verify `factor=1.5`, `factor2=2.0`
  - `ShowCloud` = yes
  - `ShowLabel` = yes

---

### Step 2: Lower Panel Studies

Add these to a new lower panel:

- [ ] **`Saty_Phase_OscillatorSTUDY.ts`** — Add to lower panel
  - No user inputs to change (all hardcoded)
  - Confirm green/red oscillator with magenta compression coloring

- [ ] **`Saty_Volume_StackSTUDY.ts`** — Add to lower panel (can share with Phase panel)
  - No inputs needed

- [ ] **`shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts`** — Add to lower panel
  - Set `TimeShift` = 1h (for 1h trading) or Daily (for daily trading)
  - **1h settings**: `over_sold=15`, `over_bought=83`
  - **Daily settings**: `over_sold=23`, `over_bought=83`
  - `fastLength=23`, `slowLength=50`, `KPeriod=10`, `DPeriod=3`
  - `paintBars=yes`
  - Confirm green up-arrows (buy signals) and red down-arrows (sell signals)

- [ ] **`AA_CoreyTscorev2STUDY.ts`** — Add to lower panel
  - `showLabels` = yes
  - `showLabels1` = yes
  - `showLabels2` = yes
  - Confirm TPO Score label visible ("Positive"/"Negative"/"Neutral")

---

### Step 3: Configure Alerts (Priority Order)

Set up alerts in this priority order — most actionable first:

1. [ ] **STC CrossUp** (RegularBuy arrow) → Sound: Bell, Email notification ON
2. [ ] **STC CrossDown** (RegularSell arrow) → Sound: Bell, Email notification ON
3. [ ] **IB High Breakout** (close crosses above IBHighext) → Sound: Ring
4. [ ] **IB Low Breakdown** (close crosses below IBLowext) → Sound: Ring
5. [ ] **Phase Compression** (is_compressed changes to 1) → Sound: Ding
6. [ ] **KAMA Cross** (close crosses KAMA line) → Sound: Ding
7. [ ] **Phase Extended** (phase crosses ±61.8) → Sound: Ding
8. [ ] **Keltner 2x Breach** (close crosses 2x band) → Sound: Ding

---

### Step 4: Verification

Before trading, verify each layer is working:

- [ ] Load a chart with known historical ENTRY_NOW signals from the JARVIS backtest
  - File: `engine/backtest/results/` — check dates/times where `entry_signal = ENTRY_NOW`
  - Confirm TOS STC arrows appear on those same bars
- [ ] Confirm ATR levels are calculating from prior close (not current close)
  - `Saty_ATR_LevelsSTUDY.ts` parameter `use_current_close = no` (default)
- [ ] Confirm IB resets at 9:30 AM ET each day
- [ ] Confirm Phase Oscillator shows compression in known low-volatility periods
- [ ] Test one alert fires correctly on a historical bar by adjusting alert threshold

---

### Step 5: Save and Maintain

- [ ] Save chart template as "JARVIS 5-Layer 1H" and "JARVIS 5-Layer Daily"
- [ ] When JARVIS engine optimal parameters update (new backtest run), update:
  - STC `over_sold` and `over_bought` values in TOS
  - ATR Levels `trading_type` if timeframe changes
- [ ] JARVIS PRD parameter source: `engine/backtest/signals.py` lines 48–57 (STC params) and lines 413–414 (stop/target ATR multiples)

---

## Quick Reference: Duplicate Files to Ignore

These are TOS-generated nested copies. Import and use only the root-level originals listed above. The duplicates exist because TOS embeds sub-studies inside exported files.

| Duplicate File | Original to Use |
|---|---|
| `shared_AA_CoreyRangefinderv1_01STUDY.ts` | Use `AA_CoreyRFv2STUDY.ts` |
| `shared_AA_CoreySinglefinderv2STUDY.ts` | Use `AA_CoreySFv2STUDY.ts` |
| `shared_AA_CoreyTPOScorev2STUDY.ts` | Use `AA_CoreyTscorev2STUDY.ts` |
| `shared_midcloudoteSTUDY.ts` | Sub-study — do not add directly |
| `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` | This IS the main STC study — USE this one |
| `shared_Saty_ATR_LevelsSTUDY.ts` | Use `Saty_ATR_LevelsSTUDY.ts` |
| `shared_shared_midcloudoteSTUDY.ts` | Sub-study — do not add directly |
| `shared_shared_OB_LBR_BARS_HH_LL17STUDY.ts` | Sub-study — do not add directly |
| `shared_shared_OB_OMEGA_5mSTUDY.ts` | USE THIS — main Keltner Omega (5m default) |
| `shared_shared_OB_OMEGA_15m7STUDY.ts` | Use for 15m charts |
| `shared_shared_OB_OMEGA_30m7STUDY.ts` | Use for 30m charts |
| `shared_shared_shared_shared_kelt_3.01STUDY.ts` | USE THIS — 3x Keltner |
| `shared_shared_shared_shared_shared_kmaster1STUDY.ts` | Sub-study dependency |
| `shared_shared_shared_shared_shared_Priceline11STUDY.ts` | Sub-study dependency |
| `shared_shared_shared_shared_shared_shared_kmaster1STUDY.ts` | Deeper nested — ignore |
| `shared_shared_shared_shared_shared_shared_Priceline11STUDY.ts` | Deeper nested — ignore |

---

*End of Integration Guide. Source of truth for parameters: `engine/backtest/signals.py`. Source of truth for indicators: `engine/backtest/indicators.py`.*

---

## SECTION 6: Per-Script Documentation Index

Each unique script now has a full-spec `.md` in `docs/`. The `registry.yaml` at the root of this folder is the machine-readable index; both engines expose it via HTTP.

### Registry Endpoints

- **jarvis-trader**: `GET http://localhost:8010/thinkscript/registry` + `/thinkscript/registry/{id}`
- **master-jarvis**: `GET http://localhost:8009/trade/thinkscript/registry` + `/trade/thinkscript/registry/{id}`

### Documentation Index

| ID | File | Layer | Status | Doc |
|---|---|---|---|---|
| saty_atr_levels | Saty_ATR_LevelsSTUDY.ts | 1 Regime | Ported | [saty_atr_levels.md](docs/saty_atr_levels.md) |
| saty_phase_oscillator | Saty_Phase_OscillatorSTUDY.ts | 1 Regime | Ported | [saty_phase_oscillator.md](docs/saty_phase_oscillator.md) |
| mtf_trendbar | shared_mtftrendbarSTUDY.ts | 1 Regime | Ported | [mtf_trendbar.md](docs/mtf_trendbar.md) |
| corey_tpo_profile_v1 | AA_CoreyTPOProfilev1STUDY.ts | 2 Structure | Orphan | [corey_tpo_profile_v1.md](docs/corey_tpo_profile_v1.md) |
| corey_tscore_v2 | AA_CoreyTscorev2STUDY.ts | 2 Structure | Orphan | [corey_tscore_v2.md](docs/corey_tscore_v2.md) |
| corey_ib_v1 | AA_CoreyIBv1STUDY.ts | 2 Structure | Orphan | [corey_ib_v1.md](docs/corey_ib_v1.md) |
| corey_rangefinder_v2 | AA_CoreyRFv2STUDY.ts | 2 Structure | Orphan | [corey_rangefinder_v2.md](docs/corey_rangefinder_v2.md) |
| corey_singlefinder_v2 | AA_CoreySFv2STUDY.ts | 2 Structure | Orphan | [corey_singlefinder_v2.md](docs/corey_singlefinder_v2.md) |
| corey_gapfinder_v1 | AA_CoreyGapfinderv1STUDY.ts | 2 Structure | Orphan | [corey_gapfinder_v1.md](docs/corey_gapfinder_v1.md) |
| kama_next_signal_momentum | NextSignalMomentumSTUDY.ts | 3 Bias | Ported | [kama_next_signal_momentum.md](docs/kama_next_signal_momentum.md) |
| saty_volume_stack | Saty_Volume_StackSTUDY.ts | 3 Bias | Ported | [saty_volume_stack.md](docs/saty_volume_stack.md) |
| stc_ob_style_cycle | shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts | 4 Entry | Ported | [stc_ob_style_cycle.md](docs/stc_ob_style_cycle.md) |
| ob_omega_keltner_5m | shared_shared_OB_OMEGA_5mSTUDY.ts | 4 Entry | Ported | [ob_omega_keltner_5m.md](docs/ob_omega_keltner_5m.md) |
| ob_omega_keltner_15m | shared_shared_OB_OMEGA_15m7STUDY.ts | 4 Entry | Ported | [ob_omega_keltner_15m.md](docs/ob_omega_keltner_15m.md) |
| ob_omega_keltner_30m | shared_shared_OB_OMEGA_30m7STUDY.ts | 4 Entry | Ported | [ob_omega_keltner_30m.md](docs/ob_omega_keltner_30m.md) |
| keltner_3x | shared_shared_shared_shared_kelt_3.01STUDY.ts | 4 Entry | Ported | [keltner_3x.md](docs/keltner_3x.md) |
| cohen_mes_composite | COHEN_MES_COMPOSITE.ts | 5 Sizing | Ported | [COHEN_MES_README.md](COHEN_MES_README.md) |
| cohen_mes_stc_sub | COHEN_MES_STC_SUB.ts | 5 Sizing | Ported | [COHEN_MES_COMPOSITE_INSTALL.md](COHEN_MES_COMPOSITE_INSTALL.md) |
| gaps_chetan | GAPS_Chetan1STUDY.ts | 0 Supporting | Orphan | [gaps_chetan.md](docs/gaps_chetan.md) |
| trin_chetan | TRIN_ChetanSTUDY.ts | 0 Supporting | Ported | [trin_chetan.md](docs/trin_chetan.md) |
| corey_rangefinder_v1_mobile | AA_CoreyRFv1MobileSTUDY.ts | 2 Structure | Deprecated | [corey_rangefinder_v1_mobile.md](docs/corey_rangefinder_v1_mobile.md) |
| legacy_utilities | ThinkScript_study_20221014/16, 20230523 | 0 Supporting | Reference-only | [thinkscript_legacy_studies.md](docs/thinkscript_legacy_studies.md) |
