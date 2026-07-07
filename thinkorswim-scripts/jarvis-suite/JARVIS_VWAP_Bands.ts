# JARVIS_VWAP_Bands -- upper-chart study                       *** EXPERIMENTAL ***
# ------------------------------------------------------------------------------
# STATUS           : EXPERIMENTAL - OOS validation pending (loop vwap-sharpe).
#                    The champion parameter set passed gate-v2 ALT (5/5) +
#                    PBO 0.198 on 250 OOS backtest trades (PF 4.07, per-trade
#                    Sharpe 0.40, WR 0.40) but the FORWARD paper-shadow record
#                    (engine/backtest/vwap_paper_track.py, observe-only) has not
#                    yet confirmed the edge post-inception. Do not trade this
#                    from the chart until the forward record grades PASS.
# Canonical source : engine/backtest/vwap_signals.py::generate_vwap_signals
#                    engine/backtest/vwap_paper_track.py::CHAMPION
# Canonical params : band_mult = 2.5 x ATR(14)   (entry bands)
#                    stop_mult = 0.75 x ATR(14)
#                    require_reversal_bar = False
#                    regime_filter = True (block entries in TRENDING regime)
#                    T1 = VWAP, T2 = opposite band
#                    Session VWAP anchored 09:30 ET, hlc3 typical price,
#                    zero-volume bars skipped; no new entries 15:00-16:00 ET.
# Date             : 2026-07-06
# Engine is canonical; TOS is visual reference only.
#
# NOTE on bands: the ENGINE entry bands are ATR-multiples (2.5 x ATR), not
# standard deviations. This study plots the canonical ATR entry bands AND
# optional +/-1 and +/-2 volume-weighted stdev bands for visual context only
# (the stdev bands are NOT part of the validated strategy).
#
# Time zone: thinkScript SecondsFromTime/SecondsTillTime evaluate in EASTERN
# time regardless of your local (CT) clock. 0930 ET = 8:30 CT, 1500 ET = 2:00 PM CT.
# ------------------------------------------------------------------------------

declare upper;

input band_atr_mult = 2.5;    # canonical champion (vwap_paper_track.py)
input stop_atr_mult = 0.75;   # canonical champion
input atr_length = 14;
input show_stdev_bands = yes; # visual reference only -- NOT the engine bands
input show_signals = yes;
input show_labels = yes;
input block_final_hour = yes; # engine blocks entries 15:00-16:00 ET

# --- Session anchor: 09:30 ET (engine resets at the 09:30 RTH bar) --------------
def sft = SecondsFromTime(0930);
def newSession = (sft >= 0 and sft[1] < 0) or (sft >= 0 and sft < sft[1]);

def tp = (high + low + close) / 3;
def vol = volume;

# engine skips zero-volume bars in the accumulation
rec cumPV = CompoundValue(1,
    if newSession then (if vol > 0 then tp * vol else 0)
    else cumPV[1] + (if vol > 0 then tp * vol else 0), tp * vol);
rec cumV = CompoundValue(1,
    if newSession then (if vol > 0 then vol else 0)
    else cumV[1] + (if vol > 0 then vol else 0), vol);
rec cumPV2 = CompoundValue(1,
    if newSession then (if vol > 0 then tp * tp * vol else 0)
    else cumPV2[1] + (if vol > 0 then tp * tp * vol else 0), tp * tp * vol);

def sessionVwap = if cumV > 0 then cumPV / cumV else tp;

plot VWAP = sessionVwap;
VWAP.SetDefaultColor(Color.CYAN);
VWAP.SetLineWeight(2);

# --- Canonical ATR entry bands (the validated strategy bands) -------------------
def atrVal = WildersAverage(TrueRange(high, close, low), atr_length);

plot UpperBand = sessionVwap + band_atr_mult * atrVal;
UpperBand.SetDefaultColor(Color.RED);
UpperBand.SetLineWeight(2);

plot LowerBand = sessionVwap - band_atr_mult * atrVal;
LowerBand.SetDefaultColor(Color.GREEN);
LowerBand.SetLineWeight(2);

# --- Optional stdev bands (visual context only) ---------------------------------
def vwVar = if cumV > 0 then Max(0, cumPV2 / cumV - sessionVwap * sessionVwap) else 0;
def vwSd = Sqrt(vwVar);

plot SD1Up = if show_stdev_bands then sessionVwap + vwSd else Double.NaN;
SD1Up.SetDefaultColor(Color.DARK_GRAY);
SD1Up.SetStyle(Curve.SHORT_DASH);
plot SD1Dn = if show_stdev_bands then sessionVwap - vwSd else Double.NaN;
SD1Dn.SetDefaultColor(Color.DARK_GRAY);
SD1Dn.SetStyle(Curve.SHORT_DASH);
plot SD2Up = if show_stdev_bands then sessionVwap + 2 * vwSd else Double.NaN;
SD2Up.SetDefaultColor(Color.GRAY);
SD2Up.SetStyle(Curve.LONG_DASH);
plot SD2Dn = if show_stdev_bands then sessionVwap - 2 * vwSd else Double.NaN;
SD2Dn.SetDefaultColor(Color.GRAY);
SD2Dn.SetStyle(Curve.LONG_DASH);

# --- Entry-window gate (engine: skip bars at/after 15:00 ET) ---------------------
def inFinalHour = SecondsFromTime(1500) >= 0 and SecondsTillTime(1600) > 0;
def entryWindowOK = !block_final_hour or !inFinalHour;

# --- Reversion signals (champion: require_reversal_bar = False) ------------------
# LONG : close below lower band (stretched >= 2.5 ATR under VWAP)
# SHORT: close above upper band
def longSetup = show_signals and entryWindowOK and close < LowerBand;
def shortSetup = show_signals and entryWindowOK and close > UpperBand;

plot LongMark = if longSetup then low else Double.NaN;
LongMark.SetPaintingStrategy(PaintingStrategy.ARROW_UP);
LongMark.SetDefaultColor(Color.GREEN);
LongMark.SetLineWeight(2);

plot ShortMark = if shortSetup then high else Double.NaN;
ShortMark.SetPaintingStrategy(PaintingStrategy.ARROW_DOWN);
ShortMark.SetDefaultColor(Color.RED);
ShortMark.SetLineWeight(2);

# --- Labels -----------------------------------------------------------------------
AddLabel(show_labels, "VWAP REVERSION: EXPERIMENTAL - OOS pending (vwap-sharpe)",
    Color.ORANGE);
AddLabel(show_labels,
    "VWAP " + Round(sessionVwap, 2) +
    " | band 2.5xATR = " + Round(band_atr_mult * atrVal, 2) +
    " | stop 0.75xATR = " + Round(stop_atr_mult * atrVal, 2),
    Color.CYAN);
AddLabel(show_labels and longSetup, "LONG SETUP (stretch below -2.5 ATR)", Color.GREEN);
AddLabel(show_labels and shortSetup, "SHORT SETUP (stretch above +2.5 ATR)", Color.RED);
