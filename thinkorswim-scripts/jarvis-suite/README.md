# JARVIS ThinkScript Suite

Self-contained ThinkorSwim studies that MIRROR the JARVIS engine's canonical
parameters so TOS charts visually match engine signals.

**Engine is canonical; TOS is visual reference + manual-execution alerts.**
If a chart and the engine ever disagree, the engine is right -- check
`engine/backtest/signals.py` and `engine/backtest/indicators.py` first.

## Install

1. ThinkorSwim -> **Studies -> Edit Studies -> Create** (or **Import** if you
   saved the `.ts` file locally).
2. Paste the contents of the `.ts` file.
3. Name the study exactly as the filename (e.g. `JARVIS_STC_Signals`) -> OK.
4. Repeat per file. `JARVIS_Scan_STC_Regime` is pasted into
   **Scan > Stock Hacker > Add study filter > Custom > thinkScript Editor**
   instead of Edit Studies.

## Which study goes on which chart

| Chart | Studies |
|---|---|
| **MES 1h (primary)** | JARVIS_STC_Signals (upper) + JARVIS_MissionControl_Lower (lower) + JARVIS_RiskSizer (upper labels) |
| MES 1h/5m (mean-rev watch) | JARVIS_VWAP_Bands (upper) -- **EXPERIMENTAL, OOS pending** |
| MGC 1h | JARVIS_STC_Signals with OS=17 OB=88 stop=0.30 T1=1.50 + MissionControl |
| MNQ 1h (DO_NOT_TRADE -- watch only) | JARVIS_STC_Signals with OS=15 OB=92 |
| MCL 1h (DO_NOT_TRADE -- watch only) | JARVIS_STC_Signals with OS=23 OB=83 stop=0.50 |
| Any chart, always-on | JARVIS_MissionControl_Lower -- the single pane to keep under every chart |
| Daily | JARVIS_RegimeFilter (lower) for the 5-layer regime read |

Note: MCL, MNQ (and M2K) are in the engine's `DO_NOT_TRADE_SYMBOLS` blocklist.
Charts for them are watch-only; the engine will emit NO_TRADE regardless of
what the study shows.

## Alert setup (the two Alert() studies)

`JARVIS_STC_Signals` and (optionally) a saved chart with
`JARVIS_MissionControl_Lower` are the alerting surfaces. `Alert()` only fires
in **studies** (never strategies), and only while the chart is open, OR via a
study alert:

1. **MarketWatch -> Alerts -> Study Alert** (or right-click chart -> Create Alert).
2. Condition: `JARVIS_STC_Signals` -> plot `LongSignal` (crosses above OS) or
   `ShortSignal` (crosses below OB). Aggregation: **1h** to match the engine.
3. The in-study `Alert()` calls are closed-bar confirmed (evaluated on the
   prior completed bar), so they fire at the open of the bar AFTER the signal
   bar -- matching the engine's signal-on-close / enter-next-bar semantics.
4. Sound: Ding = LONG, Bell = SHORT/exit.

## Canonical-source table

| Study | Canonical source | Key params (verified from code 2026-07-06) |
|---|---|---|
| JARVIS_STC_Signals | `engine/backtest/indicators.py::stc`, `engine/backtest/signals.py` | MACD 23/50, K=10, EMA-span-3 smoothing; OS=15 OB=83 default (1h; daily OS=23); MNQ 15/92, MCL 23/83, MGC 17/88, SPY 15/88; ATR(14) Wilder; stop 0.70 / T1 1.00 / T2 1.80 / T3 2.618 defaults; MCL stop 0.50, MGC stop 0.30 T1 1.50, SPY stop 0.30 |
| JARVIS_RegimeFilter | `engine/backtest/signals.py::layer1_regime/layer3_bias` (approximation) | 200 EMA slope, 50>200 EMA, ATR(14) vs 30-bar avg, swing structure N=10, volume > 20-bar avg; >=4/5 = trending |
| JARVIS_VWAP_Bands | `engine/backtest/vwap_paper_track.py::CHAMPION`, `engine/backtest/vwap_signals.py` | **EXPERIMENTAL - OOS validation pending (loop vwap-sharpe)**. band 2.5xATR(14), stop 0.75xATR, no reversal-bar filter, regime filter ON, T1=VWAP, T2=opposite band, session anchor 09:30 ET, no entries 15:00+ ET. Backtest prior: PF 4.07 / Sharpe 0.40 / WR 0.40 (250 OOS trades) |
| JARVIS_RiskSizer | `engine/config.py` (MAX_CONTRACTS_PER_INSTRUMENT=2), `signals.py` multipliers | 1% risk default on $25k, hard cap 2 contracts, stop 0.70xATR, R:R = T1/stop; no-entry 9:30-9:35 + 3:45-4:00 ET (= 8:30-8:35 + 2:45-3:00 CT) |
| JARVIS_MissionControl_Lower | indicators.py::stc + signals.py + regime approximation | STC + OS/OB + regime histogram (x20 scale) + state label |
| JARVIS_Scan_STC_Regime | same as above | STC crossed above OS within 2 bars AND bull aligned-count >= 4 |

## Relationship to existing scripts

- `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` (community OS=19/OB=88)
  and `COHEN_MES_STC_SUB.ts` (older port, ad-hoc smoothing) both implement STC.
  This suite supersedes them for JARVIS signal-mirroring: it reproduces the
  engine's exact construction (EMA-span-3 = alpha 0.5 smoothing, range==0 -> 50
  stochastic fallback) and canonical thresholds. Keep the old ones for
  reference; put the JARVIS_* versions on live charts.

## Repaint / correctness notes

- All signals use closed-bar values; only the developing rightmost bar can
  change intrabar. In-study alerts are evaluated on the prior completed bar.
- thinkScript `SecondsFromTime`/`SecondsTillTime` are EASTERN time. Amo is CT:
  the ET literals in the scripts are already correct -- do not shift them.
- TOS `Lowest`/`Highest` use available bars during the warmup window while the
  engine's pandas rolling returns NaN -- expect divergence only on the first
  ~50 bars of a chart.
