# COHEN-MES STC Oscillator — Sub-Pane Study
# Schaff Trend Cycle with regime-aware coloring
# JARVIS TRADER — 2026-04-02
#
# The STC combines MACD with double Stochastic smoothing to produce
# a fast-cycling oscillator (0-100) that leads MACD by several bars.
#
# Signal interpretation:
#   - Cross above 15 from below = bullish momentum igniting
#   - Cross below 83 from above = bearish momentum igniting
#   - Between 30-70 = neutral zone, no strong signal
#   - Color: GREEN below 30 (oversold), RED above 70 (overbought), YELLOW between
#
# Pair with COHEN_MES_COMPOSITE upper study for full signal suite.

declare lower;

# ── User Inputs ──────────────────────────────────────────────────────────────
input fast_length = 23;      # MACD fast period
input slow_length = 50;      # MACD slow period
input stc_length = 10;       # Stochastic smoothing period
input smooth_factor = 3.0;   # Exponential smoothing factor
input ob_level = 83;         # Overbought threshold
input os_level = 15;         # Oversold threshold
input show_labels = yes;
input show_histogram = yes;

# ── MACD Difference ─────────────────────────────────────────────────────────
def macdDiff = ExpAverage(close, fast_length) - ExpAverage(close, slow_length);

# ── First Stochastic Pass (on MACD diff) ────────────────────────────────────
def lowestMacd = Lowest(macdDiff, stc_length);
def highestMacd = Highest(macdDiff, stc_length);
def macdRange = highestMacd - lowestMacd;
def fastK1 = if macdRange > 0 then ((macdDiff - lowestMacd) / macdRange) * 100 else 50;

# Exponential smoothing of first stochastic
rec smoothK1 = CompoundValue(1, smoothK1[1] + (1.0 / smooth_factor) * (fastK1 - smoothK1[1]), fastK1);

# ── Second Stochastic Pass (on smoothed K1) ─────────────────────────────────
def lowestK1 = Lowest(smoothK1, stc_length);
def highestK1 = Highest(smoothK1, stc_length);
def k1Range = highestK1 - lowestK1;
def fastK2 = if k1Range > 0 then ((smoothK1 - lowestK1) / k1Range) * 100 else 50;

# Exponential smoothing of second stochastic = final STC
rec stcLine = CompoundValue(1, stcLine[1] + (1.0 / smooth_factor) * (fastK2 - stcLine[1]), fastK2);

# Clamp to 0-100 range
def stcClamped = Max(0, Min(100, stcLine));

# ── STC Plot ─────────────────────────────────────────────────────────────────
plot STC = stcClamped;
STC.SetLineWeight(2);
STC.AssignValueColor(
    if stcClamped <= 30 then Color.GREEN
    else if stcClamped >= 70 then Color.RED
    else Color.YELLOW
);

# ── Signal Line (EMA of STC for crossover detection) ────────────────────────
def stcSignal = ExpAverage(stcClamped, 5);
plot Signal = stcSignal;
Signal.SetDefaultColor(Color.GRAY);
Signal.SetLineWeight(1);
Signal.SetStyle(Curve.SHORT_DASH);

# ── OB/OS Reference Lines ───────────────────────────────────────────────────
plot OB_Line = ob_level;
OB_Line.SetDefaultColor(Color.RED);
OB_Line.SetStyle(Curve.LONG_DASH);
OB_Line.SetLineWeight(1);
OB_Line.HideBubble();
OB_Line.HideTitle();

plot OS_Line = os_level;
OS_Line.SetDefaultColor(Color.GREEN);
OS_Line.SetStyle(Curve.LONG_DASH);
OS_Line.SetLineWeight(1);
OS_Line.HideBubble();
OS_Line.HideTitle();

plot MidLine = 50;
MidLine.SetDefaultColor(Color.DARK_GRAY);
MidLine.SetStyle(Curve.SHORT_DASH);
MidLine.SetLineWeight(1);
MidLine.HideBubble();
MidLine.HideTitle();

# ── Zone Fills ───────────────────────────────────────────────────────────────
AddCloud(OB_Line, 100, Color.DARK_RED, Color.DARK_RED);
AddCloud(0, OS_Line, Color.DARK_GREEN, Color.DARK_GREEN);

# ── Histogram (optional — momentum intensity) ───────────────────────────────
def histValue = stcClamped - 50;
plot Histogram = if show_histogram then histValue else Double.NaN;
Histogram.SetPaintingStrategy(PaintingStrategy.HISTOGRAM);
Histogram.AssignValueColor(
    if histValue > 0 and histValue > histValue[1] then Color.GREEN
    else if histValue > 0 and histValue <= histValue[1] then Color.DARK_GREEN
    else if histValue < 0 and histValue < histValue[1] then Color.RED
    else Color.DARK_RED
);
Histogram.SetLineWeight(2);
Histogram.HideBubble();

# ── Cross Signals ────────────────────────────────────────────────────────────
# Bullish: STC crosses above OS level from below
def bullCross = stcClamped crosses above os_level;
# Bearish: STC crosses below OB level from above
def bearCross = stcClamped crosses below ob_level;

plot BullSignal = if bullCross then stcClamped else Double.NaN;
BullSignal.SetPaintingStrategy(PaintingStrategy.ARROW_UP);
BullSignal.SetDefaultColor(Color.GREEN);
BullSignal.SetLineWeight(3);
BullSignal.HideBubble();

plot BearSignal = if bearCross then stcClamped else Double.NaN;
BearSignal.SetPaintingStrategy(PaintingStrategy.ARROW_DOWN);
BearSignal.SetDefaultColor(Color.RED);
BearSignal.SetLineWeight(3);
BearSignal.HideBubble();

# ── Labels ───────────────────────────────────────────────────────────────────
AddLabel(show_labels,
    "STC: " + Round(stcClamped, 1),
    if stcClamped <= 30 then Color.GREEN
    else if stcClamped >= 70 then Color.RED
    else Color.YELLOW
);

AddLabel(show_labels,
    if stcClamped <= os_level then "OVERSOLD"
    else if stcClamped >= ob_level then "OVERBOUGHT"
    else if stcClamped > 50 then "BULLISH"
    else "BEARISH",
    if stcClamped <= os_level then Color.GREEN
    else if stcClamped >= ob_level then Color.RED
    else if stcClamped > 50 then Color.DARK_GREEN
    else Color.DARK_RED
);

# ── Divergence Detection (price vs STC) ─────────────────────────────────────
# Bullish divergence: price makes lower low but STC makes higher low
def priceLow = Lowest(low, 5);
def stcLow = Lowest(stcClamped, 5);
def bullDiv = priceLow < priceLow[5] and stcLow > stcLow[5] and stcClamped <= 30;
def bearDiv = Highest(high, 5) > Highest(high[5], 5) and Highest(stcClamped, 5) < Highest(stcClamped[5], 5) and stcClamped >= 70;

AddLabel(show_labels and bullDiv, "BULL DIV", Color.LIGHT_GREEN);
AddLabel(show_labels and bearDiv, "BEAR DIV", Color.LIGHT_RED);
