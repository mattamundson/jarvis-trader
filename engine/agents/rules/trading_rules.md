# JARVIS TRADER — Trading Rules
## The 5-Layer "Tony Stark" Framework
All 5 layers must align for a valid trade signal.

---

## LAYER 1: REGIME FILTER (Go/No-Go Gate)

Evaluate market conditions BEFORE looking at any setup.

### Regime Classifications

| Regime | Conditions | Action |
|--------|-----------|--------|
| TRENDING_BULL | TRIN < 1.0 + Phase > 0 + ATR consumed < 70% + EMA ribbon all up | Trade longs freely |
| TRENDING_BEAR | TRIN > 1.5 + Phase < 0 + ATR consumed < 70% + EMA ribbon all down | Trade shorts freely |
| RANGE_BOUND | TRIN 0.8-1.2 + Phase between -23.6 and +23.6 + price inside VA | Mean reversion only |
| COMPRESSION | Phase Bollinger inside ATR bands + ATR consumed < 50% | Wait for breakout direction |
| EXHAUSTED | ATR consumed > 90% OR price at 2x ATR extension | No new trades (fade only with 0.5% risk) |

### TRIN Thresholds (Chetan TRIN script)
- **Capitulation (BUY zone)**: TRIN close > 2.0 AND TRIN low > 1.0 AND VIX > 30 → cyan bars
- **Blow-off TOP (SELL zone)**: TRIN close < 0.6 AND TRIN high < 1.0 AND VVIX < 120 → magenta bars
- Normal range: TRIN 0.6-2.0 = no extreme signal

### ATR Range Consumed (Saty ATR Levels script)
- ATR period: 14 (Wilder's smoothing)
- Range consumed = abs(current_price - prior_close) / ATR × 100
- **< 70%** = green (room to run, trade with trend)
- **70-90%** = orange (caution, reduce size)
- **> 90%** = red (exhausted, wait or fade only)

### Phase Oscillator (Saty Phase script)
- Formula: (close - EMA(21)) / (3 × ATR(14)) × 100
- **Compression**: Bollinger Bands (21, 2SD) contracting INSIDE ATR bands → BREAKOUT IMMINENT
- **+100**: Extreme extension up (distribution zone, fade)
- **+61.8**: Distribution (start scaling out longs)
- **+23.6**: Neutral up
- **-23.6**: Neutral down
- **-61.8**: Accumulation (start scaling into longs)
- **-100**: Extreme extension down (fade shorts)

### EMA Ribbon (Saty ATR script)
- EMA 8, EMA 21, EMA 34 (standard EMA, not Wilder's)
- **Bullish**: EMA 8 > EMA 21 > EMA 34 (all stacked up)
- **Bearish**: EMA 8 < EMA 21 < EMA 34 (all stacked down)
- **Neutral**: Mixed order

---

## LAYER 2: STRUCTURE MAP (Establish Key Levels)

Build the price map BEFORE entering any trade.

### Initial Balance (Corey IB script)
- **Definition**: First 60 minutes of RTH (9:30-10:30 AM CT)
- **IB High / IB Low** = day's primary reference range
- **Quad levels** (support/resistance within range):
  - Q25 = IB Low + 0.25 × IB Range
  - Q50 = IB Low + 0.50 × IB Range (midpoint)
  - Q75 = IB Low + 0.75 × IB Range
- **Extensions** (targets if IB breaks):
  - Up: +50% of IB range above IB High (first target)
  - Up: +100% of IB range above IB High (second target)
  - Up: +300% of IB range above IB High (major extension)
  - Down: mirror of above
- **Day bias**: Price above IB High = bullish. Below IB Low = bearish.

### TPO/Volume Profile (Corey TPO + Virgin Profile scripts)
- **Value Area**: 70% of volume/time (standard)
- **POC (Point of Control)**: Price with most volume/TPO = FAIR VALUE
- **VAH (Value Area High)**: Upper boundary of 70% value area
- **VAL (Value Area Low)**: Lower boundary of 70% value area
- **Price location**:
  - Above VAH = buyer control (bullish)
  - Inside VA = balanced/rotating
  - Below VAL = seller control (bearish)
- **Virgin VPOC**: POC levels that have NEVER been revisited = HIGH-PRIORITY MAGNETS
  - Track up to 10 virgin VPOCs above and below current price
  - Price is attracted to nearest VPOC (gravity effect)

### ATR Fibonacci Levels (Saty ATR script)
- **Base**: Prior day's close
- **Trigger zones** (0.236 × ATR from close):
  - Call trigger: prior_close + 0.236 × ATR(14)
  - Put trigger: prior_close - 0.236 × ATR(14)
- **Full target levels** (both up and down from prior close):
  - 0.236 × ATR (trigger/entry)
  - 0.382 × ATR (Target 1)
  - 0.500 × ATR (Target 2 / midpoint)
  - 0.618 × ATR (Target 3 / golden ratio)
  - 0.786 × ATR (Target 4)
  - 1.000 × ATR (Full daily range)
  - 1.236 × ATR (Extension 1)
  - 1.500 × ATR (Extension 2)
  - 2.000 × ATR (Extension 3 / double range)
  - 3.000 × ATR (Extreme extension)

### Floor Pivot Points
- PP = (Prior High + Prior Low + Prior Close) / 3
- R1 = 2 × PP - Prior Low
- R2 = PP + (Prior High - Prior Low)
- R3 = 2 × PP + (Prior High - 2 × Prior Low)
- S1 = 2 × PP - Prior High
- S2 = PP - (Prior High - Prior Low)
- S3 = 2 × PP - (2 × Prior High - Prior Low)

### Multi-TF Keltner Channels (Omega 5m/15m/30m + KMaster 4H)
- **Basis**: SMA(20) of close
- **ATR**: SMA of True Range(20)
- **Inner bands** (±1.5 × ATR): Normal extension, pullback entry zone
- **Outer bands** (±2.0 × ATR): Extended price, caution zone
- **Extreme bands** (±3.0 × ATR): Extreme fade zone
- **MACD closed door** (12/26/9): When MACD aligns with a band, that side is "closed" (price unlikely to breach)
- **Timeframes**: 5-min, 15-min, 30-min, 4-hour — stacked for confluence

### Confluence Rules
- **STRONG S/R**: 2+ of the following at same price: VPOC, VAH/VAL, IB High/Low, ATR Fib, Pivot, Keltner band
- **WEAK S/R**: Only 1 of the above
- Always note nearest VPOC above and below as primary magnets

---

## LAYER 3: DIRECTIONAL BIAS

Determine the most likely direction BEFORE timing entry.

### TPO Score System (Corey TScore script)
5-component composite (-5 to +5):
1. VAH position vs POC: above=+1, below=-1
2. VAL position vs POC: below=-1, above=+1
3. POC position in profile: upper half=+1, lower half=-1
4. VA Balance direction: up=+1, down=-1
5. Imbalance: bull=+1, bear=-1

Score interpretation:
- **+3 to +5**: STRONG_BULL
- **+1 to +2**: LEAN_BULL
- **0**: NEUTRAL
- **-1 to -2**: LEAN_BEAR
- **-3 to -5**: STRONG_BEAR

### KAMA Direction (NextSignalMomentum script)
- KAMA period: 10
- **Long signal**: close > KAMA
- **Short signal**: close < KAMA
- **Confirmation**: LinReg(7) and LinReg(20) both positive slope (longs) or negative (shorts)

### Volume Stack (Saty Volume script)
- Buy volume proxy: volume × (close - low) / (high - low)
- Sell volume proxy: volume × (high - close) / (high - low)
- **Bullish confirmation**: buyers > 60% of total volume
- **Bearish confirmation**: sellers > 60% of total volume
- **Balanced**: 40-60% split → no edge

### Bias Classification
- **STRONG_BULL**: TPO score ≥ +3 AND KAMA long AND volume buyers > 60%
- **LEAN_BULL**: 2 of above conditions + EMA ribbon bullish
- **NEUTRAL**: Mixed signals, price inside VA, STC in 20-80 zone
- **LEAN_BEAR**: 2 bearish conditions + EMA ribbon bearish
- **STRONG_BEAR**: TPO score ≤ -3 AND KAMA short AND volume sellers > 60%

---

## LAYER 4: ENTRY TIMING

Identify precise entry after regime + structure + bias all confirmed.

### STC (Schaff Trend Cycle) — Primary Timing Tool
- Parameters: fast=23, slow=50, K_period=10, D_period=3
- Formula: MACD → Stochastic of MACD → EMA smooth → Stochastic again → EMA smooth
- **Buy trigger**: STC crosses UP through 23 (oversold → rising) — grid-optimized from TOS default 19
- **Sell trigger**: STC crosses DOWN through 83 (overbought → falling) — grid-optimized from TOS default 88
- **Bull momentum zone**: STC 20-80 (rising = trend continuation)
- **Bear momentum zone**: STC 80-20 (falling = trend continuation)

### Range Finder Signals (Corey RFv2 script)
- **Outside bar detection**: high > prior high AND low < prior low
- **Green up-arrow**: Outside bar with bullish 3-bar average + low excess → continuation up
- **Red down-arrow**: Outside bar with bearish 3-bar average + high excess → continuation down
- **Yellow arrow**: Caution — mixed signals
- **Bear/Bull Imbalance label**: Profile imbalance determines extension direction

### Keltner Channel Entries
- **Inner band (1.5x) touch**: Pullback entry on trend confirmation
- **Outer band (2.0x) touch**: More aggressive entry, wider stop
- **Extreme band (3.0x) touch**: COUNTER-TREND FADE only (small size, tight stop)
- **MACD closed door**: If MACD suggests band is "closed", fade that side

### Gap Fill Entries (Corey GapFinder script)
- Unfilled gap above = resistance, fade toward it from below
- Unfilled gap below = support, fade toward it from above
- Gap fill = high-probability target; enter on approach with confirmation

### Single Print Entries (Corey SingleFinder script)
- Unfilled bull single = support level (buy on test)
- Unfilled bear single = resistance level (sell on test)
- Filled single = confirms direction (enter in direction of fill)

### Entry Signal Classification
| Signal | Conditions |
|--------|-----------|
| ENTRY_NOW | STC crosses 19/88 + RFv2 arrow + Layer 1-3 all aligned |
| WAIT_FOR_PULLBACK | Bias confirmed, STC in middle zone (20-80), wait for retracement to POC/Keltner |
| FADE_EXTREME | Regime=EXHAUSTED, ATR>90%, Phase>+61.8 or <-61.8, counter-trend small size |
| NO_TRADE | Regime=EXHAUSTED without fade setup, or bias=NEUTRAL, or conflicting signals |

---

## LAYER 5: POSITION SIZING & RISK MANAGEMENT

### Stop Loss Rules
- **Long stop**: Below the LOWER of: IB Low OR nearest Keltner inner band
- **Short stop**: Above the HIGHER of: IB High OR nearest Keltner inner band
- **Maximum stop distance**: 1 × ATR from entry (hard cap)
- **Minimum stop distance**: 0.25 × ATR (avoid stops too tight)

### Profit Target Rules
- **Target 1** (50% exit): Entry + 0.382 × ATR (long) or Entry - 0.382 × ATR (short)
- **Target 2** (30% exit): Entry + 0.618 × ATR
- **Target 3** (20% exit): Entry + 1.0 × ATR
- Move stop to breakeven after Target 1 is hit

### Position Sizing
- **Risk per trade**: 1% of account equity
- **Contracts**: floor((account × 0.01) / (stop_distance × contract_multiplier))
- **Minimum**: 1 contract
- **Maximum**: Capped by available capital

### Contract Multipliers
| Symbol | Multiplier |
|--------|-----------|
| MES (Micro S&P) | $5 per point |
| MNQ (Micro Nasdaq) | $2 per point |
| MGC (Micro Gold) | $10 per oz |
| M2K (Micro Russell) | $5 per point |
| MYM (Micro Dow) | $0.50 per point |

### Kill Switch Rules (HARDCODED — LLM cannot override)
- **Daily loss limit**: Stop ALL trading if day's P&L < -2% of starting account value
- **Drawdown limit**: Stop ALL trading if drawdown from high-water mark > 5%
- **Intraday**: Kill switch resets at midnight CT (new trading day)
- **Regime shift**: If mid-trade regime becomes EXHAUSTED, exit at market or next Target 1

---

## THE SYNTHESIS RULE

```
VALID TRADE =
  Layer 1 (Regime) ≠ EXHAUSTED
  AND Layer 2 (Structure) shows clear S/R with ≥2 confluence factors
  AND Layer 3 (Bias) ≠ NEUTRAL
  AND Layer 4 (Timing) = ENTRY_NOW
  AND Layer 5 (Risk) R:R ≥ 1.5:1

ANY "no" from any layer = NO TRADE
```

---

## PRIORITY ORDER FOR DAILY PREPARATION

1. Check overnight ATR levels (prior close ± ATR Fibs) — these are the day's targets
2. Note IB range from 9:30-10:30 AM
3. Mark prior day's VPOC and any Virgin VPOCs near current price
4. Identify Keltner bands for the day on all 4 timeframes
5. Check breadth (TRIN, VIX) for regime classification
6. Watch Phase Oscillator for compression signals
7. Wait for STC entry trigger that aligns with all 5 layers
