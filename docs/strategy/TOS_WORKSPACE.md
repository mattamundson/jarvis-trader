# TOS Workspace — JARVIS 5-Layer Layout

> ThinkOrSwim workspace configuration matching JARVIS's 5-layer regime framework.
> All scripts live in `thinkorswim-scripts/`. Import via Studies > Edit Studies > Import.

## Overview

The workspace has 5 tabs, each illuminating a different layer of the JARVIS signal pipeline.
Tab 1 is the primary trading tab. Tabs 2–4 provide context and confirmation.

```
Tab 1: JARVIS MAIN    — The actual signal (STC + composite overlay)
Tab 2: AUCTION        — IB levels, TPO Profile, gap structure (Corey tools)
Tab 3: REGIME LAYERS  — MTF trend confirmation, volatility, volume
Tab 4: MULTI-SYMBOL   — MES / MNQ / MCL / MES-4H grid (parallel signals)
Tab 5: COREY INTEL    — T-score, Single Finder, TPO Score (auction analytics)
```

---

## Tab 1 — JARVIS MAIN (Primary Signal)

**Purpose**: The signal tab. This is where trades are confirmed before entry.

| Pane | Study | Notes |
|------|-------|-------|
| Upper | `COHEN_MES_COMPOSITE.ts` | STC+ORB+VWAP composite overlay. Entry arrows when composite_score ≥ 0.35. Matches `composite_signals.py`. |
| Upper | `Saty_ATR_LevelsSTUDY.ts` | ATR stop and target levels painted on the chart. Set `trading_type = Day`. |
| Upper | `AA_CoreyIBv1STUDY.ts` | Initial Balance high/low + quad/extension lines. Shows IB structure on same chart. |
| Lower | `COHEN_MES_STC_SUB.ts` | STC oscillator (0–100). OS=15 (green zone), OB=83 (red zone). Entry signal fires when STC crosses above 15. |

**Setup**:
- Timeframe: **1h** (primary). Add 15m as secondary tab within this layout.
- Symbol: **/MES** (switch to /MNQ or /MCL as needed)
- Chart type: Candles

**Signal alignment check**: When COHEN_MES_COMPOSITE fires a LONG arrow AND COHEN_MES_STC_SUB shows STC crossing above 15, this matches a JARVIS engine LONG signal. They should agree — if they diverge, `signals.py` is canonical.

---

## Tab 2 — AUCTION STRUCTURE

**Purpose**: See the full auction context — where IB levels, TPO nodes, and gaps are. JARVIS's Layer 4 (price structure) and Layer 5 (volume confirmation) are visible here.

| Pane | Study | Notes |
|------|-------|-------|
| Upper | `AA_CoreyIBv1STUDY.ts` | IB H/L with quads, extensions (IBx1.5, IBx2.0). Primary auction structure. |
| Upper | `AA_CoreyTPOProfilev1STUDY.ts` | TPO Market Profile. POC, VAH, VAL visible. |
| Upper | `AA_CoreyGapfinderv1STUDY.ts` | Unfilled gap levels. Gaps act as magnets / targets. |
| Upper | `AA_CoreyRFv2STUDY.ts` + `shared_AA_CoreyRangefinderv1_01STUDY.ts` | Range Finder — prior day/week ranges. |
| Upper | `Saty_ATR_LevelsSTUDY.ts` | ATR levels for reference (stop/target from any level). |

**Setup**:
- Timeframe: **1h** (with 30m optional split)
- Symbol: **/MES** (ES structure is the same as MES)
- Note: `AA_CoreyIBv1STUDY` requires session start at 09:30 CT for correct IB calculation.

---

## Tab 3 — REGIME LAYERS (MTF Confirmation)

**Purpose**: Confirm the 5-layer regime filter. JARVIS only enters when 4/5 layers agree. This tab shows Layers 1–3 (trend, momentum, volatility).

| Pane | Study | Notes |
|------|-------|-------|
| Upper | `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` | STC on bars — paints bars green/red based on STC state across multiple timeframes. Set TimeShift to match desired HTF (e.g., 4h for 1h trading). |
| Upper | `shared_mtftrendbarSTUDY.ts` | MTF trend bar using 5min CCI + ATR state. Shows higher-timeframe trend alignment. |
| Upper | `NextSignalMomentumSTUDY.ts` | Momentum signal study. |
| Lower | `Saty_Phase_OscillatorSTUDY.ts` | Saty Phase Oscillator — momentum cycles. |
| Lower | `Saty_Volume_StackSTUDY.ts` | Volume stack — confirms breakouts (Layer 5). |

**Setup**:
- Use grid layout: Top = 4h, Middle = 1h, Bottom = 15m
- Symbol: **/MES**
- This tab answers: "Is the regime aligned for entry?"

**JARVIS Layer Mapping**:
| JARVIS Layer | TOS Equivalent |
|-------------|---------------|
| 1 — Trend direction | 200 EMA slope on upper chart |
| 2 — Short-term momentum | 50 EMA vs 200 EMA crossover |
| 3 — Volatility regime | Saty_ATR_Levels width vs average |
| 4 — Price structure | IB quads + TPO profile (Tab 2) |
| 5 — Volume confirmation | Saty_Volume_Stack |

---

## Tab 4 — MULTI-SYMBOL SCAN

**Purpose**: Monitor MCL, MNQ, MES, and a reference symbol side-by-side. Spot which instrument has the strongest signal.

| Grid Cell | Symbol | Studies |
|-----------|--------|---------|
| Top-left | **/MCL** | `COHEN_MES_COMPOSITE` + `COHEN_MES_STC_SUB` |
| Top-right | **/MNQ** | `COHEN_MES_COMPOSITE` + `COHEN_MES_STC_SUB` |
| Bottom-left | **/MES** | `COHEN_MES_COMPOSITE` + `COHEN_MES_STC_SUB` |
| Bottom-right | **/ES** | `COHEN_MES_COMPOSITE` only (ES for reference, full contract) |

**Setup**:
- All panes: 1h timeframe, candles
- Use TOS's grid layout (4-pane), link timeframes
- This tab answers: "Which instrument is in the best setup right now?"

---

## Tab 5 — COREY INTELLIGENCE

**Purpose**: Corey Auction Tools analytics — T-score, Single Finder, TPO scoring. These are the same data sources that feed JARVIS's Discord intelligence layer.

| Pane | Study | Notes |
|------|-------|-------|
| Upper | `AA_CoreyTscorev2STUDY.ts` | T-score — measures where price is relative to the value area. High T-score = price extended. |
| Upper | `shared_AA_CoreyTPOScorev2STUDY.ts` | TPO Score — quantifies TPO structure quality. |
| Upper | `AA_CoreySFv2STUDY.ts` | Single Finder — highlights single-print areas (unfinished auction). |
| Upper | `shared_AA_CoreySinglefinderv2STUDY.ts` | Shared Single Finder variant. |
| Lower | `TRIN_ChetanSTUDY.ts` | TRIN (Arms Index) — market breadth. Values > 2.0 = capitulation, < 0.5 = buying climax. |

**Setup**:
- Timeframe: 30m or 1h
- Symbol: **/ES** (ES has deeper TPO data than /MES)
- This tab answers: "What is the Corey auction structure saying right now?"

---

## Script Inventory

| Script | Category | Use In Tab |
|--------|----------|-----------|
| `COHEN_MES_COMPOSITE.ts` | Signal | 1, 4 |
| `COHEN_MES_STC_SUB.ts` | Signal | 1, 4 |
| `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` | Signal/MTF | 3 |
| `shared_shared_OB_OMEGA_5mSTUDY.ts` | Signal (5m) | 3 |
| `shared_shared_OB_OMEGA_15m7STUDY.ts` | Signal (15m) | 3 |
| `shared_shared_OB_OMEGA_30m7STUDY.ts` | Signal (30m) | 3 |
| `AA_CoreyIBv1STUDY.ts` | Auction/IB | 1, 2 |
| `AA_CoreyTPOProfilev1STUDY.ts` | Auction/TPO | 2 |
| `AA_CoreyGapfinderv1STUDY.ts` | Auction/Gaps | 2 |
| `AA_CoreyRFv2STUDY.ts` | Auction/Range | 2 |
| `shared_AA_CoreyRangefinderv1_01STUDY.ts` | Auction/Range | 2 |
| `AA_CoreyTscorev2STUDY.ts` | Corey Analytics | 5 |
| `AA_CoreySFv2STUDY.ts` | Corey Analytics | 5 |
| `shared_AA_CoreyTPOScorev2STUDY.ts` | Corey Analytics | 5 |
| `shared_AA_CoreySinglefinderv2STUDY.ts` | Corey Analytics | 5 |
| `AA_CoreyRFv1MobileSTUDY.ts` | Corey/Mobile | spare |
| `Saty_ATR_LevelsSTUDY.ts` | Levels/ATR | 1, 2 |
| `shared_Saty_ATR_LevelsSTUDY.ts` | Levels/ATR | 1 (shared version) |
| `Saty_Phase_OscillatorSTUDY.ts` | Momentum | 3 |
| `Saty_Volume_StackSTUDY.ts` | Volume | 3 |
| `shared_mtftrendbarSTUDY.ts` | MTF/Trend | 3 |
| `NextSignalMomentumSTUDY.ts` | Momentum | 3 |
| `TRIN_ChetanSTUDY.ts` | Breadth | 5 |
| `GAPS_Chetan1STUDY.ts` | Gaps | 2 |
| `shared_shared_OB_LBR_BARS_HH_LL17STUDY.ts` | Structure | 3 |
| `shared_midcloudoteSTUDY.ts` | OTE Zone | spare |
| `shared_shared_midcloudoteSTUDY.ts` | OTE Zone | spare |
| `shared_shared_shared_shared_kelt_3.01STUDY.ts` | Keltner | spare |
| `shared_shared_shared_shared_shared_kmaster1STUDY.ts` | Master | spare |
| `shared_shared_shared_shared_shared_Priceline11STUDY.ts` | Price Line | spare |
| `ThinkScript_study_20221014STUDY.ts` | Legacy | archive |
| `ThinkScript_study_20221016STUDY.ts` | Legacy | archive |
| `ThinkScript_study_20230523STUDY.ts` | Legacy | archive |

---

## JARVIS ↔ TOS Signal Alignment

The TOS workspace and JARVIS engine use the same STC parameters. If they diverge, `engine/backtest/signals.py` is the canonical source.

| Parameter | JARVIS `signals.py` | TOS `COHEN_MES_STC_SUB.ts` |
|-----------|--------------------|-----------------------------|
| Oversold threshold | OS = 15 | os_level = 15 ✓ |
| Overbought threshold | OB = 83 | ob_level = 83 ✓ |
| Fast length | 23 | fastLength = 23 ✓ |
| Slow length | 50 | slowLength = 50 ✓ |
| KPeriod | 10 | KPeriod = 10 ✓ |

**Note**: `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` uses different defaults (OS=19/OB=88) — this is an older variant used for MTF bar painting only, not primary signal generation. The canonical signal scripts (COHEN_MES_*) are fully aligned with `signals.py`.

---

## Import Instructions

1. In TOS: **Studies > Edit Studies > Import**
2. Navigate to `C:\Users\mattm\ThinkorSwim\jarvis-trader\thinkorswim-scripts\`
3. Import each `.ts` file
4. Studies appear under **My Studies** in the Studies list
5. Add to chart via the Studies dropdown

**Naming note**: Imported studies retain their filename as the study name. The `shared_` prefix is a TOS export artifact — the study name in TOS will still appear correctly.

---

*Last Updated: 2026-04-09*
*Scripts: 36 ThinkScript studies | Workspace: 5 tabs*
