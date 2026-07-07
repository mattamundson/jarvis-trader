# JARVIS_STC_Signals -- upper-chart study
# ------------------------------------------------------------------------------
# Canonical source : engine/backtest/indicators.py::stc  (MACD 23/50 base,
#                    double stochastic K=10, EMA span-3 smoothing = alpha 0.5)
#                    engine/backtest/signals.py (thresholds, cross logic,
#                    ATR stop/target multipliers)
# Canonical params : STC fast=23 slow=50 K=10 D(span)=3
#                    Default OS=15 OB=83 (1h optimal; daily OS=23, OB=83)
#                    Per-instrument: MNQ OS=15 OB=92 | MCL OS=23 OB=83
#                                    MGC OS=17 OB=88 | SPY OS=15 OB=88
#                    ATR(14) Wilder. Defaults: stop=0.70 T1=1.00 T2=1.80 T3=2.618
#                    Per-instrument stops/T1: MNQ 0.70/1.00 | MCL 0.50/1.00
#                                             MGC 0.30/1.50 | SPY 0.30/1.00
# Cross logic      : LONG  = stc > OS and stc[1] <= OS   (cross above oversold)
#                    SHORT = stc < OB and stc[1] >= OB   (cross below overbought)
# Date             : 2026-07-06
# Engine is canonical; TOS is visual reference only.
#
# Supersedes for JARVIS use: shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts
# (OS=19/OB=88 community defaults) and COHEN_MES_STC_SUB.ts (older port).
# This version mirrors the engine construction exactly, including the
# range==0 -> 50 stochastic fallback the engine uses.
#
# Repaint note: arrows on CLOSED bars never repaint. On the developing
# (rightmost) bar the STC value moves until the bar closes, so a live arrow
# can appear/disappear intrabar. Alerts below are evaluated on the PRIOR
# (closed) bar, so they fire once at the open of the following bar --
# matching the engine's signal-on-close / enter-next-bar semantics.
# ------------------------------------------------------------------------------

declare upper;

input fast_length = 23;       # MACD fast EMA (canonical 23)
input slow_length = 50;       # MACD slow EMA (canonical 50)
input k_period = 10;          # stochastic lookback (canonical 10)
input d_span = 3;             # EMA smoothing span (canonical 3 -> alpha 0.5)
input stc_oversold = 15;      # canonical default (MNQ 15, MCL 23, MGC 17, SPY 15)
input stc_overbought = 83;    # canonical default (MNQ 92, MCL 83, MGC 88, SPY 88)
input atr_length = 14;        # Wilder ATR (canonical 14)
input stop_atr_mult = 0.70;   # canonical default (MCL 0.50, MGC 0.30, SPY 0.30)
input t1_atr_mult = 1.00;     # canonical default (MGC 1.50)
input show_stop_target = yes;
input show_labels = yes;

# --- STC construction (exact mirror of indicators.py::stc) --------------------
def macdLine = ExpAverage(close, fast_length) - ExpAverage(close, slow_length);

# first stochastic of MACD; engine returns 50 when the range is zero
def lo1 = Lowest(macdLine, k_period);
def hi1 = Highest(macdLine, k_period);
def rng1 = hi1 - lo1;
def k1 = if rng1 != 0 then (macdLine - lo1) / rng1 * 100 else 50;

# EMA span-3 (alpha = 2/(3+1) = 0.5) -- identical to pandas ewm(span=3)
def d1 = ExpAverage(k1, d_span);

# second stochastic of the smoothed line
def lo2 = Lowest(d1, k_period);
def hi2 = Highest(d1, k_period);
def rng2 = hi2 - lo2;
def k2 = if rng2 != 0 then (d1 - lo2) / rng2 * 100 else 50;

def stcRaw = ExpAverage(k2, d_span);
def stcVal = Max(0, Min(100, stcRaw));

# --- Cross detection (exact mirror of signals.py) ------------------------------
def crossUp = stcVal > stc_oversold and stcVal[1] <= stc_oversold;
def crossDown = stcVal < stc_overbought and stcVal[1] >= stc_overbought;

# --- Arrows on price ------------------------------------------------------------
plot LongSignal = if crossUp then low else Double.NaN;
LongSignal.SetPaintingStrategy(PaintingStrategy.ARROW_UP);
LongSignal.SetDefaultColor(Color.GREEN);
LongSignal.SetLineWeight(3);

plot ShortSignal = if crossDown then high else Double.NaN;
ShortSignal.SetPaintingStrategy(PaintingStrategy.ARROW_DOWN);
ShortSignal.SetDefaultColor(Color.RED);
ShortSignal.SetLineWeight(3);

# --- ATR(14) Wilder -------------------------------------------------------------
def atrVal = WildersAverage(TrueRange(high, close, low), atr_length);

# --- Stop / T1 lines from the most recent signal bar ----------------------------
# Engine computes stop/targets from the signal bar close (signals.py L961-964):
#   long : stop = close - stop_mult*ATR ; T1 = close + t1_mult*ATR
#   short: stop = close + stop_mult*ATR ; T1 = close - t1_mult*ATR
rec lastDir = CompoundValue(1,
    if crossUp then 1 else if crossDown then -1 else lastDir[1], 0);
rec sigClose = CompoundValue(1,
    if crossUp or crossDown then close else sigClose[1], Double.NaN);
rec sigAtr = CompoundValue(1,
    if crossUp or crossDown then atrVal else sigAtr[1], Double.NaN);

def haveSig = show_stop_target and lastDir != 0 and !IsNaN(sigClose);

plot StopLine = if haveSig then
    (if lastDir == 1 then sigClose - stop_atr_mult * sigAtr
     else sigClose + stop_atr_mult * sigAtr)
    else Double.NaN;
StopLine.SetDefaultColor(Color.RED);
StopLine.SetStyle(Curve.SHORT_DASH);
StopLine.SetLineWeight(1);

plot T1Line = if haveSig then
    (if lastDir == 1 then sigClose + t1_atr_mult * sigAtr
     else sigClose - t1_atr_mult * sigAtr)
    else Double.NaN;
T1Line.SetDefaultColor(Color.GREEN);
T1Line.SetStyle(Curve.SHORT_DASH);
T1Line.SetLineWeight(1);

plot EntryLine = if haveSig then sigClose else Double.NaN;
EntryLine.SetDefaultColor(Color.GRAY);
EntryLine.SetStyle(Curve.POINTS);
EntryLine.SetLineWeight(1);

# --- Labels ----------------------------------------------------------------------
AddLabel(show_labels, "STC " + Round(stcVal, 1) +
    (if stcVal < stc_oversold then " OVERSOLD"
     else if stcVal > stc_overbought then " OVERBOUGHT"
     else ""),
    if stcVal < stc_oversold then Color.GREEN
    else if stcVal > stc_overbought then Color.RED
    else Color.GRAY);

AddLabel(show_labels and haveSig,
    (if lastDir == 1 then "LAST: LONG " else "LAST: SHORT ") +
    "entry " + Round(sigClose, 2) +
    " stop " + Round(if lastDir == 1 then sigClose - stop_atr_mult * sigAtr
                     else sigClose + stop_atr_mult * sigAtr, 2) +
    " T1 " + Round(if lastDir == 1 then sigClose + t1_atr_mult * sigAtr
                   else sigClose - t1_atr_mult * sigAtr, 2),
    if lastDir == 1 then Color.GREEN else Color.RED);

# --- Alerts (closed-bar confirmed: evaluated on the prior completed bar) --------
Alert(crossUp[1], "JARVIS STC LONG: crossed above oversold (confirmed)",
    Alert.BAR, Sound.Ding);
Alert(crossDown[1], "JARVIS STC SHORT/EXIT: crossed below overbought (confirmed)",
    Alert.BAR, Sound.Bell);
