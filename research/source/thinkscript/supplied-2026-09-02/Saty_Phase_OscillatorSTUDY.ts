# Saty Phase Oscillator
# Copyright (C) 2022-2024
# A useful range-based signal to monitor various phases of the market.

declare lower;

input show_labels = yes;

# Saty Phase Oscillator Signal
def pivot = ExpAverage(close, 21);
def above_pivot = close >= pivot;
def oscillator_signal = Round(ExpAverage(((close - pivot) / (3.0 * ATR())) * 100, 3),2);
plot phase_oscillator = oscillator_signal;
phase_oscillator.SetLineWeight(2);

# Phases
plot extended_up_zone = 100.0;
extended_up_zone.AssignValueColor(Color.LIGHT_GRAY);
extended_up_zone.HideBubble();
extended_up_zone.HideTitle();
plot distribution_zone = 61.8;
distribution_zone.AssignValueColor(Color.GRAY);
distribution_zone.HideBubble();
distribution_zone.HideTitle();
plot neutral_up_zone = 23.6;
neutral_up_zone.AssignValueColor(Color.DARK_GRAY);
neutral_up_zone.HideBubble();
neutral_up_zone.HideTitle();
plot neutral_down_zone = -23.6;
neutral_down_zone.AssignValueColor(Color.DARK_GRAY);
neutral_down_zone.HideBubble();
neutral_down_zone.HideTitle();
plot accumulation_zone = -61.8;
accumulation_zone.AssignValueColor(Color.GRAY);
accumulation_zone.HideBubble();
accumulation_zone.HideTitle();
plot extended_down_zone = -100.0;
extended_down_zone.AssignValueColor(Color.LIGHT_GRAY);
extended_down_zone.HideBubble();
extended_down_zone.HideTitle();

# Bollinger Band Compression Signal
def bband_offset = 2.0 * STDev(close, 21);
def bband_up = pivot + bband_offset;
def bband_down = pivot - bband_offset;
def compression_threshold_up = pivot + (2.0 * ta.atr(14));
def compression_threshold_down = pivot - (2.0 * ta.atr(14));
def expansion_threshold_up = pivot + (1.854 * ta.atr(14));
def expansion_threshold_down = pivot - (1.854 * ta.atr(14));
def compression = if above_pivot then bband_up - compression_threshold_up else compression_threshold_down - bband_down;
def expansion_zone = if above_pivot then bband_up - expansion_threshold_up else expansion_threshold_down - bband_down;
def expansion = compression[1] <= compression[0];
def compression_tracker = if expansion and expansion_zone > 0 then 0 else if compression <= 0 then 1 else 0;
plot compression_level = If(IsNaN(close), Double.NaN, 0);
compression_level.AssignValueColor(if compression_tracker == 1 then Color.MAGENTA else Color.DARK_GRAY);
compression_level.HideBubble();
compression_level.HideTitle();
compression_level.SetLineWeight(2);
plot is_compressed = compression_tracker;
is_compressed.SetHiding(1);
is_compressed.HideBubble();
is_compressed.HideTitle();

# Compressing / Expanding / Expanded
AddLabel(show_labels == yes and compression_tracker == 1, "Compression ", Color.MAGENTA);

phase_oscillator.AssignValueColor(
    if compression_tracker == 1 then Color.MAGENTA
    else if phase_oscillator >= 0 then Color.GREEN
    else Color.RED
);
