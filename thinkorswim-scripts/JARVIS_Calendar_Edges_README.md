# JARVIS_Calendar_Edges — install & usage

ThinkScript study that shades the two durable, gate-v2-validated **calendar edges**
from the JARVIS discovery campaign on a ThinkorSwim **daily (1D)** chart.

## Install
1. ThinkorSwim → **Studies → Edit Studies → Create**
2. Paste the contents of `JARVIS_Calendar_Edges.ts`
3. Name it `JARVIS_Calendar_Edges` → **Apply / OK**
4. Apply to a **1D** chart (SPY, GLD, QQQ, IWM, DIA, or the futures proxy).

## What it shows
| Window | Rule (canonical) | Paint |
|---|---|---|
| **Pre-holiday** ⭐ | trading day before a market-holiday closure | gold background + orange triangle |
| **Turn-of-month** | last 1 trading day + first 3 of next month | blue background + cyan triangle |
| Both | overlap | green background |

A live label reads: `Calendar edge TODAY: <state> | TOM day rank=N`. These are
**long-bias** close-to-close seasonal windows — not intraday signals.

## Inputs
- `ShowPreHoliday`, `ShowTurnOfMonth` — toggle each edge
- `ShowLiveHolidayEves` — flag TODAY via the hardcoded 2026–27 holiday-eve dates
  (needed because the gap method can't see the next session on the rightmost bar)
- `PaintBackground`, `ShowLabel`

## Caveats
- The hardcoded holiday-eve list (in the .ts) covers **2026–2027** — refresh annually.
- Pre-holiday history shading + "last trading day of month" reference the next bar,
  so they resolve one bar back; the "first 3 days of month" half is live-correct.

## Validation provenance
- Rules: `engine/backtest/daily_calendar_discovery.py` (`mask_pre_holiday`,
  `mask_turn_of_month` n_end=1/n_start=3) on the `feat/free-daily-export` track.
- Pre-holiday: SPY n=302 PF-CI 2.55 Sharpe 1.32 DD 7.8% **PASS gate-v2 ALT**;
  GLD n=201 PF-CI 2.43 Sharpe 2.77 DD 6.1% **PASS gate-v2 ALT**; robust SPY/QQQ/IWM/GLD/DIA.
- TOM: SPY 1993–2026 Sharpe 1.07 gross / 0.79 net@2bps, positive every 5-yr era.
- Forward-shadow: `Jarvis-PreHolidayPaperTrack` (observe-only); first edge day ~2026-07-02.
