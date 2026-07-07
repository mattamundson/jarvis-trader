# COHEN-MES Composite Strategy — Price Overlay
# STC + ORB + VWAP with Regime-Adaptive Weighting
# JARVIS TRADER — 2026-04-02
#
# Mirrors: engine/backtest/composite_signals.py
# Regime weights (from composite_signals.py):
#   TRENDING  -> STC=0.60, ORB=0.30, VWAP=0.10
#   RANGING   -> STC=0.50, ORB=0.20, VWAP=0.30
#   VOLATILE  -> ALL=0.00 (no entries)
# Entry threshold: composite_score >= 0.35
#
# Usage: Add to /MES chart, 1-hour timeframe. Works on any MES/ES chart.
#        Pair with COHEN_MES_STC_SUB lower study for full signal suite.

declare upper;

# ── User Inputs ──────────────────────────────────────────────────────────────
input atr_length = 14;
input band_mult = 2.5;           # VWAP band ATR multiplier (match composite_signals.py)
input orb_minutes = 30;          # Opening Range period (first 30 min)
input show_vwap = yes;
input show_orb = yes;
input show_regime_label = yes;
input show_signal_arrows = yes;
input show_ema_ribbon = no;      # 8/21/34 EMA ribbon (optional visual)
input entry_threshold = 0.35;    # Composite score threshold (match engine default)

# ── Core Calculations ────────────────────────────────────────────────────────
def price = close;
def atr14 = WildersAverage(TrueRange(high, close, low), atr_length);

# ── VWAP + ATR Bands ────────────────────────────────────────────────────────
def vwapLine = vwap();
def upperBand = vwapLine + band_mult * atr14;
def lowerBand = vwapLine - band_mult * atr14;

plot VWAP_Line = if show_vwap then vwapLine else Double.NaN;
VWAP_Line.SetDefaultColor(Color.CYAN);
VWAP_Line.SetLineWeight(2);
VWAP_Line.HideBubble();

plot VWAP_Upper = if show_vwap then upperBand else Double.NaN;
VWAP_Upper.SetDefaultColor(Color.RED);
VWAP_Upper.SetStyle(Curve.LONG_DASH);
VWAP_Upper.SetLineWeight(1);
VWAP_Upper.HideBubble();

plot VWAP_Lower = if show_vwap then lowerBand else Double.NaN;
VWAP_Lower.SetDefaultColor(Color.GREEN);
VWAP_Lower.SetStyle(Curve.LONG_DASH);
VWAP_Lower.SetLineWeight(1);
VWAP_Lower.HideBubble();

# ── Opening Range Breakout ───────────────────────────────────────────────────
# Capture the first N minutes of RTH (9:30 ET) as the opening range
def rthStart = 0930;
def rthEnd = rthStart + orb_minutes;
def isORBPeriod = SecondsFromTime(rthStart) >= 0 and SecondsFromTime(rthEnd) < 0;
def isFirstBar = SecondsFromTime(rthStart) >= 0 and SecondsFromTime(rthStart)[1] < 0;
def isAfterORB = SecondsFromTime(rthEnd) >= 0 and SecondsFromTime(1600) < 0;

# Track ORB high/low during the opening range, then freeze after
rec orbHigh = if isFirstBar then high
              else if isORBPeriod then Max(orbHigh[1], high)
              else if isAfterORB then orbHigh[1]
              else Double.NaN;
rec orbLow = if isFirstBar then low
             else if isORBPeriod then Min(orbLow[1], low)
             else if isAfterORB then orbLow[1]
             else Double.NaN;

plot ORB_High = if show_orb and isAfterORB then orbHigh else Double.NaN;
ORB_High.SetDefaultColor(Color.ORANGE);
ORB_High.SetLineWeight(2);
ORB_High.SetStyle(Curve.MEDIUM_DASH);
ORB_High.HideBubble();

plot ORB_Low = if show_orb and isAfterORB then orbLow else Double.NaN;
ORB_Low.SetDefaultColor(Color.ORANGE);
ORB_Low.SetLineWeight(2);
ORB_Low.SetStyle(Curve.MEDIUM_DASH);
ORB_Low.HideBubble();

# ── EMA Ribbon (8/21/34 Pivot Ribbon) ───────────────────────────────────────
# Matches the regime detection in composite_signals.py
def emaFast = ExpAverage(price, 8);
def emaMid = ExpAverage(price, 21);
def emaSlow = ExpAverage(price, 34);

plot EMA_8 = if show_ema_ribbon then emaFast else Double.NaN;
EMA_8.SetDefaultColor(CreateColor(0, 200, 100));
EMA_8.SetLineWeight(1);
EMA_8.HideBubble();
EMA_8.HideTitle();

plot EMA_21 = if show_ema_ribbon then emaMid else Double.NaN;
EMA_21.SetDefaultColor(CreateColor(100, 150, 255));
EMA_21.SetLineWeight(1);
EMA_21.HideBubble();
EMA_21.HideTitle();

plot EMA_34 = if show_ema_ribbon then emaSlow else Double.NaN;
EMA_34.SetDefaultColor(CreateColor(200, 100, 50));
EMA_34.SetLineWeight(1);
EMA_34.HideBubble();
EMA_34.HideTitle();

# ── Regime Detection ────────────────────────────────────────────────────────
# Simplified version of engine/backtest/regime.py RegimeClassifier
# Trend: EMA stack alignment (8 > 21 > 34 = bull; reverse = bear)
# Volatile: normalized ATR > 2% of price
# Ranging: neither trending nor volatile

def trendScore = if emaFast > emaMid and emaMid > emaSlow then 1
                 else if emaFast < emaMid and emaMid < emaSlow then -1
                 else 0;
def normATR = atr14 / price * 100;
def isVolatile = normATR > 2.0;
def isTrending = AbsValue(trendScore) == 1 and !isVolatile;
def isRanging = !isTrending and !isVolatile;

# Regime label (upper left)
AddLabel(show_regime_label,
    if isVolatile then "VOLATILE — NO ENTRIES"
    else if isTrending and trendScore > 0 then "TRENDING BULL"
    else if isTrending and trendScore < 0 then "TRENDING BEAR"
    else "RANGING",
    if isVolatile then Color.RED
    else if isTrending and trendScore > 0 then Color.GREEN
    else if isTrending and trendScore < 0 then Color.MAGENTA
    else Color.YELLOW
);

# ATR info label
AddLabel(show_regime_label,
    "ATR: " + Round(atr14, 2) + " (" + Round(normATR, 1) + "%)",
    if normATR > 2.0 then Color.RED else if normATR > 1.5 then Color.ORANGE else Color.GRAY
);

# ── STC Proxy (MACD crossover) ──────────────────────────────────────────────
# True STC is computed in the sub-pane study (COHEN_MES_STC_SUB)
# Here we use MACD(12,26,9) crossover as a fast STC entry proxy
def macdVal = MACD(12, 26, 9).Value;
def macdSig = MACD(12, 26, 9).Avg;
def stcLongProxy = macdVal crosses above macdSig;
def stcShortProxy = macdVal crosses below macdSig;

# ── VWAP Reversion Signals ──────────────────────────────────────────────────
# Long: price touches/crosses below lower band then recovers (mean reversion)
# Short: price touches/crosses above upper band then falls back
# Active primarily in RANGING regime (weight=0.30)
def vwapLongEntry = price <= lowerBand and price > price[1];
def vwapShortEntry = price >= upperBand and price < price[1];

# ── ORB Breakout Signals ────────────────────────────────────────────────────
# Long: close breaks above ORB high in a bullish trend
# Short: close breaks below ORB low in a bearish trend
# Active primarily in TRENDING regime (weight=0.30)
def orbLongEntry = isAfterORB and price > orbHigh and trendScore > 0;
def orbShortEntry = isAfterORB and price < orbLow and trendScore < 0;

# ── Composite Scoring (regime-adaptive) ──────────────────────────────────────
# Mirrors REGIME_WEIGHTS from composite_signals.py:
#   TRENDING:  STC=0.60, ORB=0.30, VWAP=0.10
#   RANGING:   STC=0.50, ORB=0.20, VWAP=0.30
#   VOLATILE:  ALL=0.00

def wSTC = if isVolatile then 0.00 else if isTrending then 0.60 else 0.50;
def wORB = if isVolatile then 0.00 else if isTrending then 0.30 else 0.20;
def wVWAP = if isVolatile then 0.00 else if isTrending then 0.10 else 0.30;

def longScore = wSTC * (if stcLongProxy then 1 else 0)
              + wORB * (if orbLongEntry then 1 else 0)
              + wVWAP * (if vwapLongEntry then 1 else 0);

def shortScore = wSTC * (if stcShortProxy then 1 else 0)
               + wORB * (if orbShortEntry then 1 else 0)
               + wVWAP * (if vwapShortEntry then 1 else 0);

# Composite entry: score >= threshold AND not volatile
def compositeLong = longScore >= entry_threshold and !isVolatile;
def compositeShort = shortScore >= entry_threshold and !isVolatile;

# Conflict resolution: if both fire, take the stronger
def longEntry = if compositeLong and compositeShort then longScore > shortScore else compositeLong;
def shortEntry = if compositeLong and compositeShort then shortScore >= longScore else compositeShort;

# ── Entry Arrows ─────────────────────────────────────────────────────────────
plot LongArrow = if show_signal_arrows and longEntry then low - atr14 * 0.4 else Double.NaN;
LongArrow.SetPaintingStrategy(PaintingStrategy.ARROW_UP);
LongArrow.SetDefaultColor(Color.GREEN);
LongArrow.SetLineWeight(3);
LongArrow.HideBubble();

plot ShortArrow = if show_signal_arrows and shortEntry then high + atr14 * 0.4 else Double.NaN;
ShortArrow.SetPaintingStrategy(PaintingStrategy.ARROW_DOWN);
ShortArrow.SetDefaultColor(Color.RED);
ShortArrow.SetLineWeight(3);
ShortArrow.HideBubble();

# ── Volatile Block Markers ───────────────────────────────────────────────────
# Show small X when a signal WOULD have fired but was blocked by volatile regime
def volatileBlock = isVolatile and (stcLongProxy or stcShortProxy or vwapLongEntry or vwapShortEntry);
plot VolatileBlockDot = if show_signal_arrows and volatileBlock then price else Double.NaN;
VolatileBlockDot.SetPaintingStrategy(PaintingStrategy.TRIANGLES);
VolatileBlockDot.SetDefaultColor(Color.DARK_GRAY);
VolatileBlockDot.SetLineWeight(2);
VolatileBlockDot.HideBubble();

# ── Signal Source Labels (on entry bars) ─────────────────────────────────────
AddChartBubble(longEntry and stcLongProxy, low - atr14 * 0.7, "STC", Color.LIGHT_GREEN, no);
AddChartBubble(longEntry and orbLongEntry, low - atr14 * 1.0, "ORB", Color.ORANGE, no);
AddChartBubble(longEntry and vwapLongEntry, low - atr14 * 1.3, "VWAP", Color.CYAN, no);

AddChartBubble(shortEntry and stcShortProxy, high + atr14 * 0.7, "STC", Color.LIGHT_RED, yes);
AddChartBubble(shortEntry and orbShortEntry, high + atr14 * 1.0, "ORB", Color.ORANGE, yes);
AddChartBubble(shortEntry and vwapShortEntry, high + atr14 * 1.3, "VWAP", Color.CYAN, yes);

# ── Composite Score Label ────────────────────────────────────────────────────
def compositeScore = longScore - shortScore;
AddLabel(show_regime_label,
    "Score: " + Round(compositeScore, 2),
    if compositeScore > 0.35 then Color.GREEN
    else if compositeScore < -0.35 then Color.RED
    else Color.GRAY
);

# ── VWAP Cloud Fill ──────────────────────────────────────────────────────────
AddCloud(if show_vwap then VWAP_Upper else Double.NaN, VWAP_Line, Color.DARK_RED, Color.DARK_RED);
AddCloud(if show_vwap then VWAP_Line else Double.NaN, VWAP_Lower, Color.DARK_GREEN, Color.DARK_GREEN);

# ── ORB Range Cloud Fill ─────────────────────────────────────────────────────
AddCloud(if show_orb and isAfterORB then ORB_High else Double.NaN,
         if show_orb and isAfterORB then ORB_Low else Double.NaN,
         CreateColor(80, 60, 0), CreateColor(80, 60, 0));
