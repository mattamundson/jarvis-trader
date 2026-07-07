# JARVIS_Scan_STC_Regime -- scan-ready condition (TOS Study Filter)
# ------------------------------------------------------------------------------
# Canonical source : engine/backtest/indicators.py::stc + signals.py cross
#                    logic (OS=15 default). Regime = 5-layer chart-side
#                    approximation (same layers as JARVIS_RegimeFilter.ts).
# Condition        : STC crossed above oversold within the last 2 bars
#                    AND regime aligned-count >= 4 bull.
# Usage            : Scan > Stock Hacker > Add study filter > Custom >
#                    thinkScript Editor > paste this file. The single `scan`
#                    plot is the pass/fail condition.
# Date             : 2026-07-06
# Engine is canonical; TOS is visual reference only.
#
# Scans evaluate on closed bars of the scan aggregation -- no repaint concern.
# Keep the scan aggregation at 1h to match the engine's primary timeframe.
# ------------------------------------------------------------------------------

input fast_length = 23;
input slow_length = 50;
input k_period = 10;
input d_span = 3;
input stc_oversold = 15;      # MNQ 15 | MCL 23 | MGC 17 | SPY 15
input ema_fast_len = 50;
input ema_slow_len = 200;
input atr_length = 14;
input atr_avg_length = 30;
input structure_lookback = 10;
input volume_avg_length = 20;
input align_threshold = 4;

# --- STC (exact mirror of indicators.py::stc) -------------------------------------
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
def crossUpWithin2 = crossUp or crossUp[1];

# --- Regime bull aligned-count (same 5 layers as JARVIS_RegimeFilter.ts) ----------
def ema50 = ExpAverage(close, ema_fast_len);
def ema200 = ExpAverage(close, ema_slow_len);
def atrVal = WildersAverage(TrueRange(high, close, low), atr_length);
def atrAvg = Average(atrVal, atr_avg_length);
def volAvg = Average(volume, volume_avg_length);

def bull1 = ema200 > ema200[1];
def bull2 = ema50 > ema200;
def bull3 = atrVal > atrAvg and close > ema50;
def swingLow = Lowest(low, structure_lookback);
def bull4 = swingLow > GetValue(swingLow, structure_lookback);
def bull5 = volume > volAvg and close >= close[1];

def bullCount = (if bull1 then 1 else 0) + (if bull2 then 1 else 0)
              + (if bull3 then 1 else 0) + (if bull4 then 1 else 0)
              + (if bull5 then 1 else 0);

# --- Scan condition ----------------------------------------------------------------
plot scan = crossUpWithin2 and bullCount >= align_threshold;
