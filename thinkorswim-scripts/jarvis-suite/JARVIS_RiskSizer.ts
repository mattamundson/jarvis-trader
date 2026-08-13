# JARVIS_RiskSizer -- upper-chart labels + session-window shading
# ------------------------------------------------------------------------------
# Canonical source : engine/config.py (MAX_CONTRACTS_PER_INSTRUMENT = 2 live
#                    default; hard cap 20 authorized but 2 is the enforced
#                    live value) and engine/backtest/signals.py ATR multipliers
#                    (default stop 0.70 x ATR(14), T1 1.00 x ATR(14)).
# What it shows    : ATR(14) in points and dollars per contract, contract count
#                    for a fixed %-risk at the canonical ATR stop (hard-capped
#                    at MAX_CONTRACTS_PER_INSTRUMENT = 2), stop distance, and
#                    R:R at the canonical multipliers. Plus no-entry session
#                    shading 9:30-9:35 AM and 3:45-4:00 PM ET.
# Date             : 2026-07-06
# Engine is canonical; TOS is visual reference only.
#
# TIME ZONE -- READ THIS (Amo is Central Time):
#   thinkScript SecondsFromTime()/SecondsTillTime() are evaluated in EASTERN
#   time, NOT your local chart/clock time zone. The literals below are ET:
#     0930-0935 ET  ==  8:30-8:35 AM CT   (open no-entry zone)
#     1545-1600 ET  ==  2:45-3:00 PM CT   (close no-entry zone)
#   No code conversion is needed -- the ET literals are already correct.
#   Do NOT "fix" these to CT values; that would shift the zones by an hour.
#
# Point value: pointValue = TickValue()/TickSize() works on TOS futures data
# (MES $5/pt, MNQ $2/pt, MCL $100/pt, MGC $10/pt). If your symbol reports a
# bad tick value, set use_auto_point_value = no and enter it manually.
# ------------------------------------------------------------------------------

declare upper;

input account_size = 25000.0;   # dollars
input risk_percent = 1.0;       # percent of account risked per trade
input atr_length = 14;
input stop_atr_mult = 0.70;     # canonical default (MCL 0.50, MGC 0.30)
input t1_atr_mult = 1.00;       # canonical default (MGC 1.50)
input max_contracts = 2;        # MAX_CONTRACTS_PER_INSTRUMENT (engine/config.py)
input use_auto_point_value = yes;
input manual_point_value = 5.0; # MES 5.0 | MNQ 2.0 | MCL 100.0 | MGC 10.0
input shade_no_entry_zones = yes;
input show_labels = yes;

# --- ATR ---------------------------------------------------------------------
def atrVal = WildersAverage(TrueRange(high, close, low), atr_length);

# --- Dollars per point ---------------------------------------------------------
def autoPV = if TickSize() > 0 then TickValue() / TickSize() else manual_point_value;
def pointValue = if use_auto_point_value and !IsNaN(autoPV) and autoPV > 0
                 then autoPV else manual_point_value;

# --- Risk math ------------------------------------------------------------------
def stopPoints = stop_atr_mult * atrVal;                # stop distance, points
def riskPerContract = stopPoints * pointValue;          # dollars at the stop
def riskBudget = account_size * risk_percent / 100;     # dollars per trade
def rawContracts = if riskPerContract > 0
                   then Floor(riskBudget / riskPerContract) else 0;
def contracts = Min(max_contracts, Max(0, rawContracts));
def rr = if stop_atr_mult > 0 then t1_atr_mult / stop_atr_mult else 0;

# --- Labels ----------------------------------------------------------------------
AddLabel(show_labels,
    "ATR(14) " + Round(atrVal, 2) + " pts = $" + Round(atrVal * pointValue, 0) + "/ct",
    Color.CYAN);
AddLabel(show_labels,
    "Stop " + Round(stopPoints, 2) + " pts ($" + Round(riskPerContract, 0) + "/ct)",
    Color.ORANGE);
AddLabel(show_labels,
    "Size: " + contracts + " ct @ " + risk_percent + "% of $" + Round(account_size, 0) +
    (if rawContracts > max_contracts then " (CAPPED at " + max_contracts + ")" else ""),
    if contracts == 0 then Color.RED else Color.GREEN);
AddLabel(show_labels,
    "R:R at T1 = " + Round(rr, 2) + " (" + t1_atr_mult + "/" + stop_atr_mult + " ATR)",
    Color.LIGHT_GRAY);

# --- No-entry session windows (ET literals; see time zone note above) ------------
# Open window : 09:30:00 <= t < 09:35:00 ET
def inOpenZone = SecondsFromTime(0930) >= 0 and SecondsTillTime(0935) > 0;
# Close window: 15:45:00 <= t < 16:00:00 ET
def inCloseZone = SecondsFromTime(1545) >= 0 and SecondsTillTime(1600) > 0;
def noEntryZone = inOpenZone or inCloseZone;

AssignBackgroundColor(
    if shade_no_entry_zones and noEntryZone then CreateColor(60, 30, 0)
    else Color.CURRENT);

AddLabel(show_labels and noEntryZone,
    "NO-ENTRY WINDOW (" +
    (if inOpenZone then "open 9:30-9:35 ET / 8:30-8:35 CT"
     else "close 3:45-4:00 ET / 2:45-3:00 CT") + ")",
    Color.ORANGE);
