# JARVIS_Calendar_Edges
# ------------------------------------------------------------------------------
# Shades the two durable, gate-v2-validated CALENDAR edges from the JARVIS
# discovery campaign so you can see (and act on) the long-bias windows on a
# ThinkorSwim DAILY chart. These are long-on-selected-days, close-to-close
# seasonal effects -- NOT intraday signals. Use on a 1D chart.
#
#   1) PRE-HOLIDAY  (the standout): the trading day immediately BEFORE a market
#      holiday closure. SPY n=302 PF-CI 2.55 Sharpe 1.32 DD 7.8% (PASS gate-v2 ALT);
#      GLD n=201 PF-CI 2.43 Sharpe 2.77 DD 6.1% (PASS gate-v2 ALT). Robust across
#      SPY/QQQ/IWM/GLD/DIA, stationary H1/H2.
#
#   2) TURN-OF-MONTH (TOM): last 1 trading day of the month + first 3 of the next
#      (n_end=1, n_start=3). SPY 1993-2026 Sharpe 1.07 gross / 0.79 net@2bps,
#      positive every 5-yr era incl. 2008 & 2020, stationary.
#
# Canonical source rules: jt-free-daily/engine/backtest/daily_calendar_discovery.py
#   mask_turn_of_month(n_end=1, n_start=3); mask_pre_holiday (gap-to-next-session).
#
# CAVEAT: pre-holiday history shading and "last trading day of month" reference
# the NEXT bar (GetTime()[-1] / GetMonth()[-1]). On the rightmost (today) bar the
# next bar does not exist yet, so those two conditions cannot light up intraday on
# the current session from price data alone. For live "is today a pre-holiday"
# certainty, the hardcoded holiday-eve list below (ShowLiveHolidayEves) flags the
# current bar. The "first 3 trading days of month" part of TOM is fully live-correct.
# ------------------------------------------------------------------------------

input ShowPreHoliday      = yes;
input ShowTurnOfMonth     = yes;
input ShowLiveHolidayEves = yes;   # hardcoded eve dates so TODAY can flag pre-holiday live
input PaintBackground     = yes;
input ShowLabel           = yes;

# ── TURN-OF-MONTH ────────────────────────────────────────────────────────────
# rank_start: 1-based trading-day index within the calendar month (live-correct).
def newMonth = GetMonth() != GetMonth()[1] or GetYear() != GetYear()[1];
rec dayRankStart = if newMonth then 1 else dayRankStart[1] + 1;

# last trading day of month: next bar rolls to a new month (references future bar).
def nextIsNewMonth = GetMonth()[-1] != GetMonth() or GetYear()[-1] != GetYear();
def isLastTradingDay = !IsNaN(GetTime()[-1]) and nextIsNewMonth;

def inTOM = ShowTurnOfMonth and (dayRankStart <= 3 or isLastTradingDay);

# ── PRE-HOLIDAY (gap method — faithful to the backtest, history) ──────────────
# A session is pre-holiday when the calendar gap to the NEXT session is abnormal.
# gap==1 is a normal weekday-to-next; gap==3 is ONLY a normal Fri->Mon weekend
# (a Monday holiday makes Friday's gap 4, a midweek holiday makes the prior gap 2).
def msPerDay = 86400000;
def tNext = GetTime()[-1];
def gapDays = RoundDown((tNext - GetTime()) / msPerDay, 0);
def preHolidayGap = ShowPreHoliday and !IsNaN(tNext) and gapDays != 1 and gapDays != 3;

# ── PRE-HOLIDAY (hardcoded eves — makes TODAY actionable live) ────────────────
# US equity market holiday EVES (the long day) for 2026-2027. Update annually.
# Format YYYYMMDD. Covers: New Year's, MLK, Presidents', Good Friday(-eve),
# Memorial, Juneteenth, Independence, Labor, Thanksgiving, Christmas.
def d = GetYYYYMMDD();
def eve2026 =
    d == 20260116 or # eve of MLK (Mon 1/19)
    d == 20260213 or # eve of Presidents' (Mon 2/16)
    d == 20260402 or # eve of Good Friday (4/3)
    d == 20260522 or # eve of Memorial (Mon 5/25)
    d == 20260618 or # eve of Juneteenth (Fri 6/19)
    d == 20260702 or # eve of Independence (observed Fri 7/3)
    d == 20260904 or # eve of Labor (Mon 9/7)
    d == 20261125 or # eve of Thanksgiving (Thu 11/26)
    d == 20261224 or # eve of Christmas (Fri 12/25)
    d == 20261231;   # eve of New Year's 2027
def eve2027 =
    d == 20270115 or # eve of MLK (Mon 1/18)
    d == 20270212 or # eve of Presidents' (Mon 2/15)
    d == 20270325 or # eve of Good Friday (3/26)
    d == 20270528 or # eve of Memorial (Mon 5/31)
    d == 20270618 or # eve of Juneteenth (observed)
    d == 20270702 or # eve of Independence (observed Mon 7/5 -> eve Fri 7/2)
    d == 20270903 or # eve of Labor (Mon 9/6)
    d == 20271124 or # eve of Thanksgiving (Thu 11/25)
    d == 20271223 or # eve of Christmas (Fri 12/24)
    d == 20271231;   # eve of New Year's 2028
def preHolidayList = ShowLiveHolidayEves and (eve2026 or eve2027);

def inPreHoliday = preHolidayGap or preHolidayList;

# ── PAINT ────────────────────────────────────────────────────────────────────
# Priority: pre-holiday (gold) over TOM (blue); both -> green.
AssignBackgroundColor(
    if !PaintBackground then Color.CURRENT
    else if inPreHoliday and inTOM then Color.DARK_GREEN
    else if inPreHoliday then Color.DARK_ORANGE
    else if inTOM then CreateColor(20, 40, 90)
    else Color.CURRENT
);

# Up-triangle under bars on any edge day (long-bias marker).
plot EdgeDay = if (inPreHoliday or inTOM) then low - (TickSize() * 6) else Double.NaN;
EdgeDay.SetPaintingStrategy(PaintingStrategy.TRIANGLES);
EdgeDay.AssignValueColor(if inPreHoliday then Color.ORANGE else Color.CYAN);
EdgeDay.SetLineWeight(3);

# ── LIVE STATUS LABEL ────────────────────────────────────────────────────────
AddLabel(ShowLabel,
    "Calendar edge TODAY: " +
    (if inPreHoliday and inTOM then "PRE-HOLIDAY + TOM (long bias)"
     else if inPreHoliday then "PRE-HOLIDAY (long bias)"
     else if inTOM then "TURN-OF-MONTH (long bias)"
     else "none") +
    "  |  TOM day rank=" + dayRankStart,
    if inPreHoliday then Color.ORANGE else if inTOM then Color.CYAN else Color.GRAY
);
