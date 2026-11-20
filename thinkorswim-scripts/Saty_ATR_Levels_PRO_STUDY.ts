# Saty_ATR_Levels_PRO
# Hardened read-only volatility/context map derived from Saty_ATR_Levels.
# JARVIS port target: causal ATR displacement, trigger state, chase risk, and context labels.
# This study intentionally uses neutral trigger language instead of standalone calls/puts entries.

input trading_type = {"Scalp", default "Day", "Multiday", "Swing", "Position", "Long-term"};
input display_mode = {default "Clean", "Full", "TriggerOnly", "ExtensionsOnly"};
input trend_timeframe = {default "Chart", "TradingPeriod"};
input use_current_close = no;
input show_info = yes;
input show_debug_labels = no;
input atr_length = 14;
input trigger_percentage = 0.236;
input fast_ema = 8;
input pivot_ema = 21;
input slow_ema = 34;
input show_vwap_state = yes;
input show_chase_warning = yes;
input chase_range_pct_atr = 90.0;
input chase_displacement_atr = 0.786;

# Trading period selection

def trading_period;
switch (trading_type) {
case "Scalp":
    trading_period = AggregationPeriod.FOUR_HOURS;
case "Day":
    trading_period = AggregationPeriod.DAY;
case "Multiday":
    trading_period = AggregationPeriod.WEEK;
case "Swing":
    trading_period = AggregationPeriod.MONTH;
case "Position":
    trading_period = AggregationPeriod.QUARTER;
case "Long-term":
    trading_period = AggregationPeriod.YEAR;
}

# Stable ATR anchor. Default uses completed higher-timeframe close/ATR to avoid intraday anchor drift.

def anchor_index = if use_current_close then 0 else 1;
def previous_close = close(period = trading_period)[anchor_index];
def atr_raw = WildersAverage(TrueRange(high(period = trading_period), close(period = trading_period), low(period = trading_period)), atr_length)[anchor_index];
def atr = Round(atr_raw, 2);
def period_high = Highest(high(period = trading_period), 1);
def period_low = Lowest(low(period = trading_period), 1);
def tr = period_high - period_low;
def range_pct_atr = if atr > 0 then Round((tr / atr) * 100, 1) else 0;
def atr_displacement = if atr > 0 then Round((close - previous_close) / atr, 3) else 0;
def gap_atr = if atr > 0 then Round((open(period = trading_period) - previous_close) / atr, 3) else 0;

# Core levels. Clean mode intentionally suppresses most minor fib lines.

def lower_trigger = previous_close - (trigger_percentage * atr);
def upper_trigger = previous_close + (trigger_percentage * atr);
def lower_0382 = previous_close - (atr * 0.382);
def upper_0382 = previous_close + (atr * 0.382);
def lower_0500 = previous_close - (atr * 0.5);
def upper_0500 = previous_close + (atr * 0.5);
def lower_0618 = previous_close - (atr * 0.618);
def upper_0618 = previous_close + (atr * 0.618);
def lower_0786 = previous_close - (atr * 0.786);
def upper_0786 = previous_close + (atr * 0.786);
def lower_1000 = previous_close - atr;
def upper_1000 = previous_close + atr;
def lower_1236 = previous_close - (atr * 1.236);
def upper_1236 = previous_close + (atr * 1.236);
def lower_1382 = previous_close - (atr * 1.382);
def upper_1382 = previous_close + (atr * 1.382);
def lower_1500 = previous_close - (atr * 1.5);
def upper_1500 = previous_close + (atr * 1.5);
def lower_1618 = previous_close - (atr * 1.618);
def upper_1618 = previous_close + (atr * 1.618);
def lower_2000 = previous_close - (atr * 2.0);
def upper_2000 = previous_close + (atr * 2.0);
def lower_3000 = previous_close - (atr * 3.0);
def upper_3000 = previous_close + (atr * 3.0);

# Display-mode booleans.

def mode_clean = display_mode == display_mode."Clean";
def mode_full = display_mode == display_mode."Full";
def mode_trigger = display_mode == display_mode."TriggerOnly";
def mode_ext = display_mode == display_mode."ExtensionsOnly";
def show_clean_core = mode_clean or mode_full;
def show_minor = mode_full;
def show_extensions = mode_full or mode_ext;

# Trend ribbon can use chart timeframe or selected trading_period; explicit to avoid silent aggregation mismatch.

def trend_price = if trend_timeframe == trend_timeframe."TradingPeriod" then close(period = trading_period) else close;
def fast_ema_value = MovAvgExponential(trend_price, fast_ema);
def pivot_ema_value = MovAvgExponential(trend_price, pivot_ema);
def slow_ema_value = MovAvgExponential(trend_price, slow_ema);
def bullish = trend_price >= fast_ema_value and fast_ema_value >= pivot_ema_value and pivot_ema_value >= slow_ema_value;
def bearish = trend_price <= fast_ema_value and fast_ema_value <= pivot_ema_value and pivot_ema_value <= slow_ema_value;

# Context states.

def upside_trigger = close > upper_trigger;
def downside_trigger = close < lower_trigger;
def above_vwap = close > VWAP();
def below_vwap = close < VWAP();
def chase_risk = range_pct_atr >= chase_range_pct_atr and AbsValue(atr_displacement) >= chase_displacement_atr;
def full_atr_extension = AbsValue(atr_displacement) >= 1.0;
def range_expansion = AbsValue(atr_displacement) >= 0.618;
def inside_trigger_band = !upside_trigger and !downside_trigger;

# Plots

plot close_level = previous_close;
close_level.SetDefaultColor(Color.WHITE);
close_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot lower_trigger_level = if !mode_ext then lower_trigger else Double.NaN;
lower_trigger_level.SetDefaultColor(Color.ORANGE);
lower_trigger_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot upper_trigger_level = if !mode_ext then upper_trigger else Double.NaN;
upper_trigger_level.SetDefaultColor(Color.CYAN);
upper_trigger_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot lower_0382_level = if show_minor then lower_0382 else Double.NaN;
lower_0382_level.SetDefaultColor(Color.GRAY);
lower_0382_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot upper_0382_level = if show_minor then upper_0382 else Double.NaN;
upper_0382_level.SetDefaultColor(Color.GRAY);
upper_0382_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot lower_0500_level = if show_minor then lower_0500 else Double.NaN;
lower_0500_level.SetDefaultColor(Color.GRAY);
lower_0500_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot upper_0500_level = if show_minor then upper_0500 else Double.NaN;
upper_0500_level.SetDefaultColor(Color.GRAY);
upper_0500_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot lower_0618_level = if show_clean_core then lower_0618 else Double.NaN;
lower_0618_level.SetDefaultColor(Color.LIGHT_GRAY);
lower_0618_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot upper_0618_level = if show_clean_core then upper_0618 else Double.NaN;
upper_0618_level.SetDefaultColor(Color.LIGHT_GRAY);
upper_0618_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot lower_0786_level = if show_minor then lower_0786 else Double.NaN;
lower_0786_level.SetDefaultColor(Color.GRAY);
lower_0786_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot upper_0786_level = if show_minor then upper_0786 else Double.NaN;
upper_0786_level.SetDefaultColor(Color.GRAY);
upper_0786_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot lower_1000_level = if show_clean_core or mode_ext then lower_1000 else Double.NaN;
lower_1000_level.SetDefaultColor(Color.WHITE);
lower_1000_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot upper_1000_level = if show_clean_core or mode_ext then upper_1000 else Double.NaN;
upper_1000_level.SetDefaultColor(Color.WHITE);
upper_1000_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot lower_1236_level = if show_minor then lower_1236 else Double.NaN;
lower_1236_level.SetDefaultColor(Color.GRAY);
lower_1236_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot upper_1236_level = if show_minor then upper_1236 else Double.NaN;
upper_1236_level.SetDefaultColor(Color.GRAY);
upper_1236_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot lower_1382_level = if show_minor then lower_1382 else Double.NaN;
lower_1382_level.SetDefaultColor(Color.GRAY);
lower_1382_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot upper_1382_level = if show_minor then upper_1382 else Double.NaN;
upper_1382_level.SetDefaultColor(Color.GRAY);
upper_1382_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot lower_1500_level = if show_minor then lower_1500 else Double.NaN;
lower_1500_level.SetDefaultColor(Color.GRAY);
lower_1500_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot upper_1500_level = if show_minor then upper_1500 else Double.NaN;
upper_1500_level.SetDefaultColor(Color.GRAY);
upper_1500_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot lower_1618_level = if show_extensions then lower_1618 else Double.NaN;
lower_1618_level.SetDefaultColor(Color.LIGHT_GRAY);
lower_1618_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot upper_1618_level = if show_extensions then upper_1618 else Double.NaN;
upper_1618_level.SetDefaultColor(Color.LIGHT_GRAY);
upper_1618_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot lower_2000_level = if show_extensions then lower_2000 else Double.NaN;
lower_2000_level.SetDefaultColor(Color.WHITE);
lower_2000_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot upper_2000_level = if show_extensions then upper_2000 else Double.NaN;
upper_2000_level.SetDefaultColor(Color.WHITE);
upper_2000_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot lower_3000_level = if show_extensions then lower_3000 else Double.NaN;
lower_3000_level.SetDefaultColor(Color.DARK_GRAY);
lower_3000_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

plot upper_3000_level = if show_extensions then upper_3000 else Double.NaN;
upper_3000_level.SetDefaultColor(Color.DARK_GRAY);
upper_3000_level.SetPaintingStrategy(PaintingStrategy.HORIZONTAL);

# Labels use neutral decision-support wording.

AddLabel(show_info, "Saty ATR Pro | " + trading_type + " | " + atr_displacement + " ATR | Range " + range_pct_atr + "% ATR | Gap " + gap_atr + " ATR", if chase_risk then Color.RED else if upside_trigger then Color.GREEN else if downside_trigger then Color.RED else Color.GRAY);
AddLabel(show_info, if bullish then "Trend: Bullish" else if bearish then "Trend: Bearish" else "Trend: Mixed", if bullish then Color.GREEN else if bearish then Color.RED else Color.ORANGE);
AddLabel(show_info and show_vwap_state, if above_vwap then "VWAP: Above" else if below_vwap then "VWAP: Below" else "VWAP: At", if above_vwap then Color.GREEN else if below_vwap then Color.RED else Color.GRAY);
AddLabel(show_info, if upside_trigger then "Upside trigger > " + Round(upper_trigger, 2) + " | +1 ATR " + Round(upper_1000, 2) else if downside_trigger then "Downside trigger < " + Round(lower_trigger, 2) + " | -1 ATR " + Round(lower_1000, 2) else "Inside trigger band", if upside_trigger then Color.GREEN else if downside_trigger then Color.RED else Color.GRAY);
AddLabel(show_info and show_chase_warning and chase_risk, "CHASE RISK: " + range_pct_atr + "% ATR used, displacement " + atr_displacement + " ATR", Color.RED);
AddLabel(show_debug_labels, "DEBUG pc=" + previous_close + " atr=" + atr + " upTrig=" + upper_trigger + " dnTrig=" + lower_trigger + " up1=" + upper_1000 + " dn1=" + lower_1000, Color.YELLOW);
