# JARVIS TRADER — Paper Trading Approval

**Date:** 2026-03-30
**Version:** v2.7
**Status:** 2 instruments APPROVED, 1 HALTED, 2 NOT CLEARED

> **SUPERSEDED (2026-05-24).** This is the historical v2.7 approval record. The
> Tier-3 instrument flip on 2026-05-24 changed the active set: **MES 1h**
> (p_edge 0.75) and **MGC 1h** (p_edge 0.6842) are now the approved active-paper
> symbols under gate v2 (ALT path); **MCL 1h** and **MNQ 1h** are **HALTED**
> (`DO_NOT_TRADE`), and **M2K** was rejected. For current status see
> `engine/CLAUDE.md` (Active Instruments) and
> `.claude/imports/validated-instruments.md`. The sections below are retained
> only as the dated record of the original MCL/MNQ approval rationale.

---

## Approved Instruments

### MCL 1h (Micro Crude Oil)
- **WFE:** 0.82 (EXCELLENT — threshold 0.50)
- **Walk-Forward Windows:** 6/6 analyzed (2024-06-01 to 2026-03-27)
- **Config:** Static params (adaptive regime REJECTED — WFE drops to -0.31)
- **Params:** STC_OS=15, STC_OB=83, Stop=0.90 ATR, T1=1.50 ATR
- **Risk:** 0.25% per trade, kill at -3% monthly
- **Notes:** Highest WFE of all instruments. Oil's mean-reverting behavior suits STC well.

### MNQ 1h (Micro Nasdaq)
- **WFE:** 0.57 (GOOD — threshold 0.50)
- **Walk-Forward Windows:** 6/6 analyzed (2024-04-26 to 2026-03-27)
- **Config:** Adaptive regime ONLY (volume filter REJECTED, MTF filter REJECTED)
- **Filter Verdicts:**
  - Adaptive regime: 0.24→0.57 (+0.33 improvement) ✅
  - \+ Volume filter: 0.57→-0.23 (-0.80 degradation) ❌
  - \+ MTF filter: 0.57→0.17 (-0.40 degradation) ❌
- **Params:** STC_OS=15, STC_OB=92, Stop=0.70 ATR, T1=1.00 ATR, regime=adaptive
- **Risk:** 0.25% per trade, kill at -3% monthly
- **Notes:** Adaptive regime improves generalization. Adding filters over-constrains the model.

---

## Halted Instruments

### MGC 1d (Micro Gold)
- **WFE:** 0.14 (OVERFIT — threshold 0.30)
- **Status:** HALTED — do not paper trade
- **History:** Prior WFE=0.88 was small-sample bias (3 windows, 2025 gold bull run only)
- **Re-evaluation:** Requires 24+ months of new data before reconsideration

---

## Not Cleared

### MES 1h (Micro S&P 500)
- **WFE:** 0.09 — deeply overfit
- **Action:** Signal redesign required

### SPY 1h (S&P 500 ETF)
- **WFE:** Not confirmed post-bugfix
- **Action:** Re-run walk-forward for final determination

---

## Risk Management Rules

1. **Per-trade risk:** 0.25% of total capital
2. **Daily loss limit:** -2% triggers pause until next session
3. **Monthly kill switch:** -3% triggers automatic halt and review
4. **Consecutive losses:** 3 in a row triggers manual review
5. **Position limit:** 1 contract per instrument (MCL, MNQ independent)
6. **No live trading** until paper trading shows edge consistency for 60+ days

---

## Re-Evaluation Schedule

- **Rolling WFE check:** Every 4 weeks, recalculate WFE with new data added
- **Quarterly review:** Full parameter re-optimization if WFE drops below 0.40
- **Annual review:** Full strategy assessment
