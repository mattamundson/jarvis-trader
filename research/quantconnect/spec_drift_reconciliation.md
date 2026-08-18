# Spec Drift Reconciliation — TOS Scripts vs Engine (B5)

Status:  DECIDED (documented reconciliation; engine code untouched)
Date:    2026-08-18
Author:  dev (B5 reconciliation task t_a5663239)
Sources: `research/quantconnect/tos_scripts_analysis.md` (§3 discrepancy table),
         TOS originals in `C:\Users\mattm\master-jarvis\thinkorswim-scripts`,
         engine `engine/backtest/indicators.py` + `engine/backtest/signals.py` +
         `engine/backtest/backtester.py`
Scope:   **Composite signal family only** (SPY/STC and the legacy MNQ/MCL/MGC
         composite path — Layer 2/3 indicators). The approved MES SMA trend
         path (`TREND_INSTRUMENTS`, `trend_signals.generate_sma_trend_signals`)
         uses none of these indicators and is **unaffected** by every decision
         below.

Decision per discrepancy: `FIX` = align engine to the TOS spec (TOS is the
spec source); `ACCEPT` = engine behavior is authoritative, divergence is
intentional and documented. Every `FIX` requires a composite-family funnel
re-run (`validation_architecture.md`) before that family is re-validated.

---

## Summary table

| # | Indicator | TOS spec | Engine today | Severity | Decision |
|---|---|---|---|---|---|
| 1 | KAMA smoothing constants | `SlowSF=0.2222`, fast bound `0.4` (NextSignalMomentum:20-21) | `fast_sc=2/(2+1)=0.6667`, `slow_sc=2/(30+1)=0.0645` (indicators.py:45-46) | HIGH | **FIX** |
| 2 | Phase oscillator 3-EMA smoothing | `ExpAverage(raw_phase, 3)` (Saty_Phase:12) | raw `(close−ema)/(3·ATR)·100`, no EMA3 (indicators.py:125) | MEDIUM | **FIX** |
| 3 | Phase compression logic | stateful `compression_tracker` (Saty_Phase:50-59) | raw `bb_width < 2·ATR` (indicators.py:139) | LOW-MEDIUM | **ACCEPT** (approximation; fix spec reserved) |
| 4 | EMA ribbon price leg | `bullish = price >= ema8 >= ema21 >= ema34` (Saty_ATR:52-53) | `ema8 > ema21 > ema34` only (signals.py:311-318) | LOW | **FIX** |
| 5 | ATR stop anchoring | prior close + prior ATR on **Day** aggregation (Saty_ATR:56-57) | 1h-bar ATR(14), entry-bar anchor (signals.py:913, backtester.py:785) | MEDIUM | **ACCEPT** (engine authoritative) |
| 6 | STC thresholds | chart defaults OS=19 / OB=88 (STC study:13-14) | per-symbol optimized (SPY 15/88, MES path 15/83; signals.py:50-89) | expected | **ACCEPT** |
| 7 | Volume stack div-by-zero | NaN when high==low (Saty_Volume:12-13) | 50/50 fill (indicators.py:156-159) | improvement | **ACCEPT** |
| 8 | Keltner channels | SMA(20) basis + SMA-of-TR × factor | identical (indicators.py:171-174) | — | ✅ match, no action |
| 9 | CCI | `(h+l+c − SMA50)/(LinDev(...,14))/0.015` | identical formula | — | ✅ match, no action |

---

## 1. KAMA smoothing constants — **FIX** (HIGH)

**TOS spec** — `NextSignalMomentumSTUDY.ts`:
- ER window: `direction = AbsValue(close − close[10])`; `volatility = Sum(AbsValue(close − close[1]), 10)`; `ER = direction / volatility` (lines 11-13). Matches engine exactly.
- Smoothing: `SlowSF = 0.2222`; `ScaledSF = ER * (0.4 − SlowSF) + SlowSF`; `AMA = AMA[1] + Sqr(ScaledSF) * (close − AMA[1])` (lines 20-22). **The SC bounds 0.4 / 0.2222 are hardcoded constants** — they do not derive from any period.
- Signal: label/bar color on `close > AMA` (lines 60-62). Matches engine `close > kama_val`.

**Engine** — `kama()` (indicators.py:38-68) derives the SC bounds from periods:
`fast_sc = 2/(2+1) = 0.6667`, `slow_sc = 2/(30+1) = 0.0645` (lines 45-46); called as
`kama(close, period=10)` (signals.py:211) → effective 0.6667 / 0.0645.

**Delta**: smoothing constants differ on both ends (fast 0.6667 vs 0.4; slow
0.0645 vs 0.2222). The TOS KAMA is *much* smoother (lower fast bound, higher
slow bound → narrower SC range and a higher floor), so `kama_signal`
long/short crossings on the chart and in the backtest diverge materially. ER
window, SC squaring, and the close-vs-KAMA comparison all already match.

**Guide error to correct** — `INTEGRATION_GUIDE.md` (KAMA section, lines
204-205) claims `0.4 = 2/(2+1)` and `0.2222 = 2/(30+1)`. Both are
arithmetically wrong (2/(2+1)=0.6667, 2/(30+1)=0.0645). The engine ported the
guide's wrong derivation instead of the script's hardcoded constants.

**Decision: FIX.** Add explicit `fast_sc` / `slow_sc` parameters to `kama()`
with TOS defaults (`fast_sc=0.4`, `slow_sc=0.2222`); keep `period=10` as the
ER window and the existing `(er*(fast_sc−slow_sc)+slow_sc)**2` recursion.
Call site `signals.py:211` needs no change (defaults apply). Optionally retain
the standard-Kaufman derivation behind a named mode for reference, but the
composite path must use the TOS constants.
**Validation gate:** composite-family funnel re-run before re-validation.

## 2. Phase oscillator 3-EMA smoothing — **FIX** (MEDIUM)

**TOS spec** — `Saty_Phase_OscillatorSTUDY.ts:12`:
`oscillator_signal = Round(ExpAverage(((close − pivot) / (3.0 * ATR())) * 100, 3), 2)`
— the raw phase is smoothed by a 3-period EMA. `pivot = ExpAverage(close, 21)`,
`ATR()` = Wilder ATR(14). Zones: ±23.6 / ±61.8 / ±100 (lines 25-37).

**Engine** — `phase_oscillator()` (indicators.py:107-141): raw
`(close − ema21)/(3·ATR14)·100` clipped to ±100 (line 125), no EMA3.
Thresholds in `_phase_signal` (signals.py:257-271) are ±23.6/±61.8 — identical
to the TOS zone lines. EMA window (21), ATR length (14), BB (21, 2.0) all match.

**Delta**: without the EMA3 smoothing the oscillator crosses the ±23.6/±61.8
thresholds earlier/later than the chart. MEDIUM — affects phase classification
timing, not the formula family. (Engine's ±100 clip is cosmetic; classification
thresholds are ±61.8/±23.6 so clipping never changes a signal.)

**Decision: FIX.** Apply `phase.ewm(span=3, adjust=False).mean()` to the raw
phase before clipping/classification. Keep thresholds at the TOS zone values.
**Validation gate:** composite-family funnel re-run before re-validation.

## 3. Phase compression logic — **ACCEPT** (documented approximation)

**TOS spec** — `Saty_Phase_OscillatorSTUDY.ts:50-59`: a stateful
`compression_tracker` with hysteresis: `compression` = gap between the BB band
and the ATR band *on the active side* (`bband_up − compression_threshold_up`
when above pivot, mirror below); `expansion = compression[1] <= compression[0]`;
`compression_tracker = 1` when the BB band is inside the ATR band, with the
expansion latch resetting it. Per-side comparison: `2·STDev(close,21)` vs
`2·ATR(14)` → compressed when `STDev <= ATR`.

**Engine** — `indicators.py:139`: `is_compression = bb_width < atr_band_width`
where `bb_width = bb_upper − bb_lower = 4·STDev` and `atr_band_width = 2·ATR`
→ compressed when `2·STDev < ATR`. Stricter than TOS and without hysteresis.

**Delta**: LOW-MEDIUM. Engine flags compression less often (needs 2·STDev <
ATR vs STDev ≤ ATR) and has no latch. This only feeds the regime label
(COMPRESSION / EXHAUSTED gating), never an entry directly.

**Decision: ACCEPT as a documented approximation** for the current state of the
composite family (no active composite instruments). Reserve the exact port
(per-side comparison + `compression_tracker` latch) for the composite
re-validation cycle rather than churning the regime output now. Rationale: the
engine's stricter condition errs toward *fewer* compression flags, which is the
conservative direction for regime filtering, and the composite family is
dormant. If the family is re-activated, port the state machine exactly and
re-run the funnel.

## 4. EMA ribbon price leg — **FIX** (LOW)

**TOS spec** — `Saty_ATR_LevelsSTUDY.ts:52-53`:
`bullish = price >= fast_ema and fast_ema >= pivot_ema and pivot_ema >= slow_ema`
(and the mirror `bearish`). Price-vs-EMA8 is the first leg.

**Engine** — `signals.py:311-318` `_ema_trend`: only the EMA ordering
(`ema_8 > ema_21 > ema_34`), the price leg is omitted. `ema_ribbon()`
(indicators.py:277-286) itself is a faithful 8/21/34 port.

**Delta**: LOW. Ribbon can call `bullish` while price is below EMA8 — a late
trend read versus the chart.

**Decision: FIX.** Add the price leg to `_ema_trend`: bullish requires
`row["close"] >= row["ema_8"] > row["ema_21"] > row["ema_34"]`; bearish the
mirror (`row["close"] <= row["ema_8"] < ...`). Trivial, contained change.
**Validation gate:** composite-family funnel re-run before re-validation.

## 5. ATR stop anchoring — **ACCEPT** (engine authoritative)

**TOS spec** — `Saty_ATR_LevelsSTUDY.ts:56-57`: levels are anchored to
`previous_close = close(period = trading_type)[1]` and
`atr = WildersAverage(TrueRange(...), 14)[1]` on the **Day** aggregation
(default `trading_type = "Day"`) — i.e. *prior-day close* and *prior-day ATR*.
The chart's "0.70 ATR" stop line is 0.70 × **daily** ATR below yesterday's close.

**Engine** — `signals.py:913`:
`df["stop_level"] = np.where(is_long, close − stop_atr * atr, close + stop_atr * atr)`
where `atr` is Wilder ATR(14) on the **1h bar** (signals.py:208). The backtester
reads the entry bar's `stop_level` and re-anchors at the actual (next-bar)
entry by ATR multiple (backtester.py:785-799). `stop_atr = 0.70` by default
(SPY 0.30, MCL 0.50, MGC 0.30; INSTRUMENT_PARAMS signals.py:50-89).

**Delta**: MEDIUM. The "0.70 ATR stop" is a *different number* on the TOS
chart (daily ATR, prior-day anchor) vs the engine/QC backtest (1h ATR,
entry-bar anchor). Chart-vs-backtest divergence is inherent and should be
expected, not "fixed" by chasing the chart.

**Decision: ACCEPT.** The engine's 1h-ATR entry-bar anchoring is the backtest
spec:
- The stop multipliers (0.70 default, 0.30 SPY, …) were grid-searched against
  **1h ATR** (162-combo grid, SPY 2024-06-01 → 2026-03-27; see
  signals.py:219-228). Re-anchoring to daily ATR would invalidate every
  optimized parameter set and every validated result for the composite family.
- The QC layer (Project E) ports `trend_signals` exactly as production trades
  it; the TOS chart is a visual aid, not the backtest spec.
- Rule going forward: **never read TOS Saty ATR levels as backtest stop
  levels.** If the composite family is re-validated, re-optimize the stop
  multiplier under an *explicitly chosen* anchoring rather than silently
  re-anchoring the existing params.

## 6. STC thresholds — **ACCEPT**

**TOS spec** — `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts:13-14`:
chart defaults `over_bought = 88`, `over_sold = 19`.

**Engine** — per-symbol optimized params in `INSTRUMENT_PARAMS`
(signals.py:50-89): SPY 15/88, MES path 15/83, MNQ 15/92, MCL 23/83, MGC 17/88;
module defaults STC_OS=15 / STC_OB=83 (signals.py:195-196).

**Decision: ACCEPT.** Engine values are the optimized, research-validated
parameters; TOS defaults are chart visuals. The INTEGRATION_GUIDE's generic
"1h optimal 15/83" is a different instrument set — keep the per-symbol engine
values authoritative. Already flagged as "expected" in tos_scripts_analysis.md
§3 #6; no action.

## 7. Volume stack div-by-zero — **ACCEPT** (improvement)

TOS yields NaN when `high == low`; the engine fills 50/50
(indicators.py:156-159). Strictly better for downstream signals; no action.

## 8-9. Keltner / CCI — **MATCH**

Formula-verified identical (indicators.py:171-174 and :340 per
tos_scripts_analysis.md §3 #8-9). No action.

---

## Follow-up required

1. **Implement fixes #1, #2, #4** (small, contained, zero production risk —
   composite family is dormant: `COMPOSITE_INSTRUMENTS = set()`, MCL/MNQ in
   `DO_NOT_TRADE_SYMBOLS`). Tracked as kanban child task of B5.
2. **Re-run the composite-family funnel** (`validation_architecture.md`)
   after the fixes, before any composite re-validation. #3 (compression state
   machine) is explicitly deferred to that cycle.
3. **Correct INTEGRATION_GUIDE.md** KAMA section (lines 204-205): the
   `0.4 = 2/(2+1)` / `0.2222 = 2/(30+1)` claims are arithmetically wrong; the
   script hardcodes 0.4/0.2222.
4. **Never mix chart ATR levels into backtest stop semantics** (see #5).

## Affected / unaffected

- **Affected:** composite family only — SPY/STC and legacy composite
  MNQ/MCL/MGC Layer 2/3 signals (`kama_signal`, `phase_val`/`phase_signal`,
  `ema_trend`). None of these is a live production path today.
- **Unaffected:** approved MES SMA trend path (SMA 50/200 + 2.0×ATR trail),
  Project E QC layer, gate-v2 verdicts, all validated MES results.
