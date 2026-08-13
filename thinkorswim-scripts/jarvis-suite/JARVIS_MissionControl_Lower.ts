# JARVIS_MissionControl_Lower -- composite lower study (the one pane to keep)
# ------------------------------------------------------------------------------
# Canonical source : engine/backtest/indicators.py::stc (MACD 23/50, K=10,
#                    EMA span-3 double stochastic smoothing) and
#                    engine/backtest/signals.py (OS=15 OB=83 defaults, cross
#                    logic). Regime block is the documented 5-layer chart-side
#                    approximation (same layers as JARVIS_RegimeFilter.ts).
# Shows            : STC value + OS/OB lines, regime aligned-count histogram
#                    (scaled x20 to share the 0-100 STC axis), and a state
#                    label: LONG SETUP / SHORT SETUP / NO ENTRY (regime) /
#                    NEUTRAL.
# State logic      : LONG SETUP  = STC crossed above OS this bar AND >=4/5
#                                  layers bull-aligned
#                    SHORT SETUP = STC crossed below OB this bar AND >=4/5
#                                  layers bear-aligned
#                    NO ENTRY (regime) = STC cross fired but regime not aligned
#                    NEUTRAL     = no cross this bar
# Date             : 2026-07-06
# Engine is canonical; TOS is visual reference only.
#
# Repaint note: values are final at bar close; the developing rightmost bar
# can change intrabar. Cross conditions compare the current value against the
# prior CLOSED bar (stc[1]) -- no lookahead is used anywhere.
# ------------------------------------------------------------------------------

declare lower;

# --- STC inputs (canonical) ------------------------------------------------------
input fast_length = 23;
input slow_length = 50;
input k_period = 10;
input d_span = 3;
input stc_oversold = 15;      # MNQ 15 | MCL 23 | MGC 17 | SPY 15
input stc_overbought = 83;    # MNQ 92 | MCL 83 | MGC 88 | SPY 88

# --- Regime inputs (approximation layers) ----------------------------------------
input ema_fast_len = 50;
input ema_slow_len = 200;
input atr_length = 14;
input atr_avg_length = 30;
input structure_lookback = 10;
input volume_avg_length = 20;
input align_threshold = 4;
input show_labels = yes;

# === STC (exact mirror of indicators.py::stc) =====================================
def macdLine = ExpAverage(close, fast_length) - ExpAverage(close, slow_length);

def lo1 = Lowest(macdLine, k_period);
def hi1 = Highest(macdLine, k_period);
def rng1 = hi1 - lo1;
def k1 = if rng1 != 0 then (macdLine - lo1) / rng1 * 100 else 50;

def d1 = ExpAverage(k1, d_span);

def lo2 = Lowest(d1, k_period);
def hi2 = Highest(d1, k_period);
def rng2 = hi2 - lo2;
def k2 = if rng2 != 0 then (d1 - lo2) / rng2 * 100 else 50;

def stcVal = Max(0, Min(100, ExpAverage(k2, d_span)));

def crossUp = stcVal > stc_oversold and stcVal[1] <= stc_oversold;
def crossDown = stcVal < stc_overbought and stcVal[1] >= stc_overbought;

# === Regime aligned-count (same 5 layers as JARVIS_RegimeFilter.ts) ===============
def ema50 = ExpAverage(close, ema_fast_len);
def ema200 = ExpAverage(close, ema_slow_len);
def atrVal = WildersAverage(TrueRange(high, close, low), atr_length);
def atrAvg = Average(atrVal, atr_avg_length);
def volAvg = Average(volume, volume_avg_length);

def bull1 = ema200 > ema200[1];
def bear1 = ema200 < ema200[1];
def bull2 = ema50 > ema200;
def bear2 = ema50 < ema200;
def volExpansion = atrVal > atrAvg;
def bull3 = volExpansion and close > ema50;
def bear3 = volExpansion and close < ema50;
def swingLow = Lowest(low, structure_lookback);
def swingHigh = Highest(high, structure_lookback);
def bull4 = swingLow > GetValue(swingLow, structure_lookback);
def bear4 = swingHigh < GetValue(swingHigh, structure_lookback);
def volAbove = volume > volAvg;
def bull5 = volAbove and close >= close[1];
def bear5 = volAbove and close < close[1];

def bullCount = (if bull1 then 1 else 0) + (if bull2 then 1 else 0)
              + (if bull3 then 1 else 0) + (if bull4 then 1 else 0)
              + (if bull5 then 1 else 0);
def bearCount = (if bear1 then 1 else 0) + (if bear2 then 1 else 0)
              + (if bear3 then 1 else 0) + (if bear4 then 1 else 0)
              + (if bear5 then 1 else 0);

def isBullRegime = bullCount >= align_threshold;
def isBearRegime = bearCount >= align_threshold;

# === Combined state ================================================================
# 2 = LONG SETUP, -2 = SHORT SETUP, 1/-1 = cross without regime, 0 = NEUTRAL
def state = if crossUp and isBullRegime then 2
            else if crossDown and isBearRegime then -2
            else if crossUp then 1
            else if crossDown then -1
            else 0;

# === Plots =========================================================================
plot STC = stcVal;
STC.SetLineWeight(2);
STC.AssignValueColor(
    if stcVal >= stcVal[1] then Color.GREEN else Color.RED);

plot OSLine = stc_oversold;
OSLine.SetDefaultColor(Color.DARK_GREEN);
OSLine.SetStyle(Curve.LONG_DASH);
OSLine.HideBubble();

plot OBLine = stc_overbought;
OBLine.SetDefaultColor(Color.DARK_RED);
OBLine.SetStyle(Curve.LONG_DASH);
OBLine.HideBubble();

# Regime histogram scaled x20 so 0-5 shares the 0-100 STC axis (5/5 = 100)
plot RegimeHist = (if isBullRegime or (!isBearRegime and bullCount >= bearCount)
                   then bullCount else bearCount) * 20;
RegimeHist.SetPaintingStrategy(PaintingStrategy.HISTOGRAM);
RegimeHist.AssignValueColor(
    if isBullRegime then Color.DARK_GREEN
    else if isBearRegime then Color.DARK_RED
    else Color.DARK_GRAY);
RegimeHist.SetLineWeight(1);

# Signal arrows on the STC line
plot LongDot = if state == 2 then stcVal else Double.NaN;
LongDot.SetPaintingStrategy(PaintingStrategy.ARROW_UP);
LongDot.SetDefaultColor(Color.GREEN);
LongDot.SetLineWeight(3);

plot ShortDot = if state == -2 then stcVal else Double.NaN;
ShortDot.SetPaintingStrategy(PaintingStrategy.ARROW_DOWN);
ShortDot.SetDefaultColor(Color.RED);
ShortDot.SetLineWeight(3);

plot BlockedDot = if state == 1 or state == -1 then stcVal else Double.NaN;
BlockedDot.SetPaintingStrategy(PaintingStrategy.POINTS);
BlockedDot.SetDefaultColor(Color.ORANGE);
BlockedDot.SetLineWeight(3);

# === Labels ========================================================================
AddLabel(show_labels,
    if state == 2 then "LONG SETUP"
    else if state == -2 then "SHORT SETUP"
    else if state == 1 or state == -1 then "NO ENTRY (regime)"
    else "NEUTRAL",
    if state == 2 then Color.GREEN
    else if state == -2 then Color.RED
    else if state != 0 then Color.ORANGE
    else Color.GRAY);

AddLabel(show_labels, "STC " + Round(stcVal, 1),
    if stcVal < stc_oversold then Color.GREEN
    else if stcVal > stc_overbought then Color.RED
    else Color.GRAY);

AddLabel(show_labels,
    "REGIME " +
    (if isBullRegime then "BULL " + bullCount + "/5"
     else if isBearRegime then "BEAR " + bearCount + "/5"
     else "MIXED " + Max(bullCount, bearCount) + "/5"),
    if isBullRegime then Color.GREEN
    else if isBearRegime then Color.RED
    else Color.GRAY);
