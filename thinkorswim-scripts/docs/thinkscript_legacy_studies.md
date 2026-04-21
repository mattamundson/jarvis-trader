# Legacy ThinkScript Utility Studies — Reference Archive

**Files**: 
- `ThinkScript_study_20221014STUDY.ts` (Oct 14, 2022)
- `ThinkScript_study_20221016STUDY.ts` (Oct 16, 2022)  
- `ThinkScript_study_20230523STUDY.ts` (May 23, 2023)

**Status**: Reference-only (archived utility scripts from 2022–2023)  
**Python counterpart**: None (not planned for porting)  
**Author**: Unknown (legacy handoff, no attribution in headers)

---

## Context

These three scripts predate the current JARVIS 5-layer framework and were retained as reference material during migration. None are integrated into active trading logic. Preserved for:
- Historical backtesting context (may have been used in prior strategy iterations)
- Educational reference (structure, input patterns, TOS best practices)
- Potential future experimental work (if research requires volume profile or pivot mechanics)

---

## Study 1: 2022-10-14 — Volume Profile / TPO Infrastructure (847 lines)

**Purpose**: Comprehensive **Volume Profile** and **Time Profile** generator with Virgin Point of Control (VPOC) and Virgin Value Area tracking.

**Core functionality**:
- Calculates POC, VAH, VAL using VolumeProfile() and TimeProfile() objects
- Tracks up to 10 **Virgin POCs** (prices never touched after initial POC formed) — stores first 10 historical levels
- Tracks up to 10 **Virgin Value Area High/Low** levels
- Auto-splits profiles RTH vs afterhours for equities; futures use session end time
- Adaptive period logic: <15min = daily profiles, 15min–1h = daily, 1h–1day = weekly, etc.
- Fibonacci zone markers (23.6, 61.8, 100%) on VAH/VAL/POC plots

**Historical use case**: Likely primary driver of `AA_CoreyTPOProfilev1STUDY.ts` (current study). This 2022 script is the foundation; Corey's version is simplified wrapper.

**Visual output**:
- POC line (magenta, 3pt weight)
- VAH line (pink, 3pt weight)
- VAL line (green, 3pt weight)
- Cloud fill between VAH/VAL (gray)
- Bubbles with label text on profile edges
- Stats labels (e.g., "Number of Virgin Point of Controls in Use: 7")

**Note**: Script is **feature-complete but complex** — 500+ lines of recursive VPOC/VVAH/VVAL handoff logic. Maintain as reference only; do not port unless profile research requires virgin-level granularity beyond current Corey implementation.

---

## Study 2: 2022-10-16 — Anchored VWAP (17 lines)

**Purpose**: Historical **Volume-Weighted Average Price** anchored to a custom date/time (intraday drift from economic data release, premarket gap, etc.).

**Core functionality**:
- Takes `anchorDate` (e.g., 20200422) and `anchorTime` (e.g., 2030 = 8:30 PM ET)
- Computes cumulative VWAP from anchor point forward: `sum((H+L+C)/3 × vol) / sum(vol)`
- Plots single cyan line on price chart
- 3pt line weight, Firm curve style

**Input parameters**:
- `anchorDate = 20200422` (YYYYMMDD format)
- `anchorTime = 2030` (military time)

**Condition logic**:
- Activates only after anchor date/time has passed (postAnchorDate flag)
- Handles 3 scenarios: (1) date > anchor, (2) same date but time passed, (3) same date but different session boundary

**Historical use case**: Likely used to track VWAP from Fed announcements or key premarket events during 2022. Can be applied to study mean-reversion from overnight gaps.

**Limitation**: No bands, no adaptive inputs, no alerts. Just a static reference line. **Not integrated into JARVIS** — use manual anchored VWAP on TOS chart instead (Studies > VWAP > set Time and Date inputs).

---

## Study 3: 2023-05-23 — Pivot Points Calculator (78 lines)

**Purpose**: Classic **Daily Pivot Points** (PP, R1–R4, S1–S4) calculated from prior day's OHLC.

**Formula** (standard Camarilla/Floor method):
```
Prior: PH=high[1], PL=low[1], PC=close[1]
PP = (PH + PL + PC) / 3
R1 = 2*PP - PL
R2 = PP + (PH - PL)
R3 = 2*PP + (PH - 2*PL)
R4 = PH + 3*(PP - PL)
S1 = 2*PP - PH
S2 = PP - (PH - PL)
S3 = 2*PP - (2*PH - PL)
S4 = PL - 3*(PH - PP)
```

**Core functionality**:
- Plots 8 horizontal lines: R4, R3, R2, R1, PP, S1, S2, S3
- Colors: R-levels = red (GetColor(5)), S-levels = green (GetColor(6)), PP = neutral (GetColor(0))
- Line styles: Dashed except PP (medium dash)
- Optional `showOnlyToday` input: hides all pivots if prior day's data is N/A (useful for first bar of session)

**Input parameters**:
- `aggregationPeriod = AggregationPeriod.DAY` (can be changed to weekly/monthly)
- `showOnlyToday = yes` (hide on day 1 of data)

**Visual output**:
- 8 labeled horizontal lines extending across chart
- Cyan = R-levels, green = S-levels

**Historical use case**: Pre-JARVIS mechanical pivot point system. Useful for **identifying key support/resistance levels** before opening. Often used in conjunction with Range Finder and Initial Balance.

**Note**: Pivots alone do NOT trigger trades in JARVIS (no regime/bias layer). Use as **structural context only** — confluence with Layer 2 (TPO/IB) signals.

---

## Recommended Action

**Archive** — do not integrate into active JARVIS framework unless explicitly re-reviewed. These scripts are preserved as:
1. **Historical reference** for strategy evolution (original pivots → IB → RF → current composite)
2. **Educational** for TOS syntax patterns (recursive loops, Fibonacci, profile handling)
3. **Fallback** if future research requires virgin-level or anchor-VWAP context

**If needed for backtest**: Manual import to TOS is possible; scripts are syntactically valid. However, prefer **current Corey versions** (TPO, IB, RF) which are optimized and tested with JARVIS engine.

---

## Summary Table

| File | Type | Lines | Purpose | Status |
|------|------|-------|---------|--------|
| 20221014 | Volume Profile | 847 | TPO/VPOC/VVAH archive | Superceded by `AA_CoreyTPOProfilev1` |
| 20221016 | Anchored VWAP | 17 | Historical mean-reversion anchor | Replaced by manual TOS chart VWAP |
| 20230523 | Pivot Points | 78 | Daily PP/R/S mechanical support | Replaced by IB + RF structure |
