# JARVIS_RegimeFilter -- lower study + chart labels
# ------------------------------------------------------------------------------
# Canonical source : engine/backtest/signals.py::layer1_regime / layer3_bias
#                    (5-layer Tony Stark framework). The engine's exact regime
#                    uses phase oscillator + ATR-consumed + EMA ribbon + TRIN;
#                    this study is the documented chart-side APPROXIMATION:
#                      L1  200 EMA slope sign (trend direction)
#                      L2  50 EMA > 200 EMA   (trend confirmation)
#                      L3  ATR(14) vs its 30-bar average, in trend direction
#                      L4  price structure: higher lows / lower highs over N bars
#                      L5  volume > 20-bar average, in bar direction
# Output           : aligned-count 0-5 per side. Background green when >=4 bull,
#                    red when >=4 bear, gray otherwise.
# Date             : 2026-07-06
# Engine is canonical; TOS is visual reference only.
#
# Repaint note: all layers use same-bar values that are final at bar close;
# only the developing rightmost bar can change intrabar.
# ------------------------------------------------------------------------------

declare lower;

input ema_fast_len = 50;
input ema_slow_len = 200;
input atr_length = 14;
input atr_avg_length = 30;    # "30-day" average on a daily chart; 30 bars intraday
input structure_lookback = 10;
input volume_avg_length = 20;
input align_threshold = 4;    # >=4 of 5 aligned = trending regime
input show_labels = yes;

# --- Layer computations --------------------------------------------------------
def ema50 = ExpAverage(close, ema_fast_len);
def ema200 = ExpAverage(close, ema_slow_len);
def atrVal = WildersAverage(TrueRange(high, close, low), atr_length);
def atrAvg = Average(atrVal, atr_avg_length);
def volAvg = Average(volume, volume_avg_length);

# L1 -- 200 EMA slope sign
def bull1 = ema200 > ema200[1];
def bear1 = ema200 < ema200[1];

# L2 -- 50 over/under 200
def bull2 = ema50 > ema200;
def bear2 = ema50 < ema200;

# L3 -- volatility expansion in the direction of trend
# (ATR above its 30-bar average while price is on the trend side of the 50 EMA)
def volExpansion = atrVal > atrAvg;
def bull3 = volExpansion and close > ema50;
def bear3 = volExpansion and close < ema50;

# L4 -- price structure via recent swing highs/lows
# higher lows: the lowest low of the last N bars sits above the lowest low of
# the N bars before that. Lower highs mirrored for bears.
def swingLow = Lowest(low, structure_lookback);
def swingHigh = Highest(high, structure_lookback);
def bull4 = swingLow > GetValue(swingLow, structure_lookback);
def bear4 = swingHigh < GetValue(swingHigh, structure_lookback);

# L5 -- volume confirmation on the signal bar, in bar direction
def volAbove = volume > volAvg;
def bull5 = volAbove and close >= close[1];
def bear5 = volAbove and close < close[1];

# --- Aligned counts --------------------------------------------------------------
def bullCount = (if bull1 then 1 else 0) + (if bull2 then 1 else 0)
              + (if bull3 then 1 else 0) + (if bull4 then 1 else 0)
              + (if bull5 then 1 else 0);
def bearCount = (if bear1 then 1 else 0) + (if bear2 then 1 else 0)
              + (if bear3 then 1 else 0) + (if bear4 then 1 else 0)
              + (if bear5 then 1 else 0);

def isBullRegime = bullCount >= align_threshold;
def isBearRegime = bearCount >= align_threshold;

# --- Plots -----------------------------------------------------------------------
plot AlignedCount = if isBullRegime then bullCount
                    else if isBearRegime then -bearCount
                    else Max(bullCount, bearCount) * (if bullCount >= bearCount then 1 else -1);
AlignedCount.SetPaintingStrategy(PaintingStrategy.HISTOGRAM);
AlignedCount.AssignValueColor(
    if isBullRegime then Color.GREEN
    else if isBearRegime then Color.RED
    else Color.GRAY);
AlignedCount.SetLineWeight(3);

plot ThresholdUp = align_threshold;
ThresholdUp.SetDefaultColor(Color.DARK_GREEN);
ThresholdUp.SetStyle(Curve.SHORT_DASH);
ThresholdUp.HideBubble();

plot ThresholdDown = -align_threshold;
ThresholdDown.SetDefaultColor(Color.DARK_RED);
ThresholdDown.SetStyle(Curve.SHORT_DASH);
ThresholdDown.HideBubble();

plot ZeroLine = 0;
ZeroLine.SetDefaultColor(Color.DARK_GRAY);
ZeroLine.HideBubble();

# --- Background ------------------------------------------------------------------
AssignBackgroundColor(
    if isBullRegime then CreateColor(0, 40, 0)
    else if isBearRegime then CreateColor(50, 0, 0)
    else CreateColor(30, 30, 30));

# --- Labels ----------------------------------------------------------------------
AddLabel(show_labels,
    "REGIME: " +
    (if isBullRegime then "TRENDING_BULL " + bullCount + "/5"
     else if isBearRegime then "TRENDING_BEAR " + bearCount + "/5"
     else "MIXED bull " + bullCount + "/5 bear " + bearCount + "/5"),
    if isBullRegime then Color.GREEN
    else if isBearRegime then Color.RED
    else Color.GRAY);

AddLabel(show_labels,
    "L1 slope " + (if bull1 then "+" else if bear1 then "-" else "0") +
    " | L2 50v200 " + (if bull2 then "+" else if bear2 then "-" else "0") +
    " | L3 vol-x " + (if bull3 then "+" else if bear3 then "-" else "0") +
    " | L4 struct " + (if bull4 then "+" else if bear4 then "-" else "0") +
    " | L5 volume " + (if bull5 then "+" else if bear5 then "-" else "0"),
    Color.LIGHT_GRAY);
