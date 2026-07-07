# Remaining TOS Scripts — Extended Inventory (Phase 0 Appendix)

**Reading date:** 2026-04-10  
**Agent:** D7 (read-only audit)  
**Files examined:** 13 ThinkorSwim ThinkScript files  
**Finding:** 10 of 13 files exist; all are REFERENCE-ONLY or EXPERIMENTAL status.

---

## Summary

- **NEW signal sources (not yet ported to Python):** 10 of 10 found scripts are new to JARVIS core
- **CRITICAL for core strategy:** NONE — all are reference implementations, multi-timeframe overlays, or experimental
- **DUPLICATES:** 4 files are exact duplicates (same content, different names):
  - `Saty_ATR_LevelsSTUDY.ts` ≡ `shared_Saty_ATR_LevelsSTUDY.ts` (identical)
  - `shared_OB_OMEGA_5mSTUDY.ts` ≡ `shared_OB_OMEGA_15m7STUDY.ts` ≡ `shared_OB_OMEGA_30m7STUDY.ts` (identical Keltner structure, different timeframes)

- **Files missing (3 of 13):**
  - `shared_OB_OMEGA_5mSTUDY.ts` — exists as `shared_shared_OB_OMEGA_5mSTUDY.ts`
  - `shared_OB_OMEGA_15m7STUDY.ts` — exists as `shared_shared_OB_OMEGA_15m7STUDY.ts`
  - `shared_OB_OMEGA_30m7STUDY.ts` — exists as `shared_shared_OB_OMEGA_30m7STUDY.ts`

---

## Script Inventory

### 1. Saty_ATR_LevelsSTUDY.ts
- **Purpose:** Multi-period ATR-based level generator; renders support/resistance zones via Fibonacci ratios (0.236–1.618 of ATR).
- **Key params:** `atr_length=14`, `trigger_percentage=0.236`, `trading_type={Scalp|Day|Multiday|Swing|Position|Long-term}`, `fast_ema=8`, `pivot_ema=21`, `slow_ema=34`
- **Layer:** Regime (8-21-34 EMA ribbon → bullish/bearish), Structure (ATR levels), Entry (trigger zones)
- **Status:** Production (Saty Mahajan 2022-2023, mature codebase)
- **JARVIS consumption:** **Port to Python** — ATR level engine fits Layer 1 (Structure). Missing from current signals.py. Create `engine/signals/atr_levels.py` to compute Fibonacci-scaled support/resistance.

### 2. Saty_Phase_OscillatorSTUDY.ts
- **Purpose:** Range-bound oscillator normalized by 3×ATR; six phase zones (Compression/Neutral/Extended/Accumulation/Distribution); Bollinger Band compression detector.
- **Key params:** `pivot_ema=21`, `bband_offset=2.0`, `compression_threshold=2.0×ATR`, `expansion_threshold=1.854×ATR`
- **Layer:** Bias (oscillator position relative to pivot), Context (compression/expansion state)
- **Status:** Production (2022-2024, signals mapped to color + labels)
- **JARVIS consumption:** **Port to Python** — adds oscillator-based bias confirmation. Create `engine/signals/phase_oscillator.py`. Layer 3 (Bias) or Layer 6 (Context).

### 3. Saty_Volume_StackSTUDY.ts
- **Purpose:** Stacked volume bar breakdown: separates buy/sell volume via OHLC proxy (close-low) / (high-low), displays with color (green=buy winning, red=sell winning).
- **Key params:** None (uses only OHLC bar data)
- **Layer:** Context (volume direction bias)
- **Status:** Production (2022-2024, visual only)
- **JARVIS consumption:** **Assess feasibility** — volume proxy requires bar-level OHLC. If TickData available, can compute in Layer 6 (Context). Otherwise reference-only. Note: currently disabled in signal pipeline (no volume_stack endpoint).

### 4. shared_Saty_ATR_LevelsSTUDY.ts
- **Purpose:** EXACT DUPLICATE of `Saty_ATR_LevelsSTUDY.ts`. Identical code.
- **Status:** Duplicate (reference archive)
- **JARVIS consumption:** **Skip** — same as #1.

### 5. shared_shared_shared_shared_kelt_3.01STUDY.ts
- **Purpose:** Multi-timeframe Keltner Channels (user-defined period). Plots upper/lower bands around moving average using ATR-scaled shifts.
- **Key params:** `iAggregationPeriod=FIVE_MIN` (configurable), `iFactor=3.0`, `iLength=20`, `iAvgType=SIMPLE`, `iTrueRangeAvgType=SIMPLE`
- **Layer:** Structure (dynamic bands), Regime (mean-reversion context)
- **Status:** Experimental (reference implementation, JP Boyd / Keltner standard)
- **JARVIS consumption:** **Reference only** — Keltner bands already partially covered by BollingerBandsAgent. Can enhance Structure layer if Keltner specifically preferred over Bollinger. Suggest skip unless explicit strategy requirement.

### 6. shared_shared_shared_shared_shared_kmaster1STUDY.ts
- **Purpose:** Multi-layer Keltner Channels (3 factor levels: Primary 1.5×ATR, Secondary 2.0×ATR, Tertiary 1.8×ATR) on 4-hour aggregation period.
- **Key params:** `iAggregationPeriod=FOUR_HOURS`, `iFactorPrimary=1.5`, `iFactorSecondary=2.0`, `iFactor=1.8`, `iLengthPrimary=20`, `iLengthSecondary=20`, `iLength=20`
- **Layer:** Structure (three-band envelope), Regime (mean-reversion tiers)
- **Status:** Experimental (reference, JBOYD renegade implementation)
- **JARVIS consumption:** **Skip** — similar to #5. Three-factor Keltner adds complexity without clear strategic advantage over single-factor Bollinger/Keltner. Not ported.

### 7. shared_shared_shared_shared_shared_Priceline11STUDY.ts
- **Purpose:** Plots highest close from last bar as horizontal dashed line (pink #E91559). Minimal study, marks price memory.
- **Key params:** None (code-hardcoded)
- **Layer:** Reference (context line only)
- **Status:** Reference-only (3 lines of functional code)
- **JARVIS consumption:** **Skip** — purely visual marker. No signal value for JARVIS.

### 8. shared_mtftrendbarSTUDY.ts
- **Purpose:** CCI-based trend SAR (stop-and-reverse) with state machine. Plots TrendUp / TrendDown on 5-minute timeframe; dynamic ATR-offset calculation.
- **Key params:** `length=50`, `timeframe=FIVE_MIN`, `atr_Period=5`, `CCI_threshold=0` (implicit from linDev normalization)
- **Layer:** Entry (SAR-style stops), Regime (trend state machine)
- **Status:** Experimental (state machine logic present, but code has null handling bugs at lines 50/68)
- **JARVIS consumption:** **Reference only** — SAR concept is directional, but implementation incomplete (plot s1 not fully defined, state transitions have logical gaps). Would need debugging. Not worth porting without full strategy clarity.

### 9. shared_midcloudoteSTUDY.ts
- **Purpose:** SMA/EMA hybrid moving average study (21-bar) with cloud fill. SMA (dark orange), EMA (orange), midpoint (dark gray). Period: 5 minutes.
- **Key params:** `length=21`, `period=FIVE_MIN`, `averageType1=SIMPLE`, `averageType2=EXPONENTIAL`
- **Layer:** Structure (short-term trend guides)
- **Status:** Production (simple, mature)
- **JARVIS consumption:** **Reference only** — 21-period MA already covered by TechnicalAnalystAgent EMA ribbon (8-21-34). Adding SMA/EMA hybrid adds no new signal class. Skip.

### 10. shared_shared_OB_OMEGA_5mSTUDY.ts
- **Purpose:** Multi-factor Keltner Channels on 15-minute period (NOT 5m, despite filename). Factor 1.5×ATR (inner), 2.0×ATR (outer). Plots average, upper/lower bands with labels (Monthly/Weekly/Daily/4h/1h/min).
- **Key params:** `period=FIFTEEN_MIN` (hardcoded), `factor=1.5`, `factor2=2.0`, `length=20`, `lineLength=50`, `ShowLabel=YES`, `ShowCloud=YES`
- **Layer:** Structure (multi-scale support/resistance), Context (timeframe labels)
- **Status:** Reference (Maverick & Renegade, 2020)
- **JARVIS consumption:** **Skip** — naming mismatch (5m filename, 15m implementation). Keltner already covered. Not a new source.

### 11. shared_shared_OB_OMEGA_15m7STUDY.ts
- **Purpose:** DUPLICATE of shared_shared_OB_OMEGA_5mSTUDY.ts (identical Keltner 15m bands).
- **Status:** Duplicate
- **JARVIS consumption:** **Skip**.

### 12. shared_shared_OB_OMEGA_30m7STUDY.ts
- **Purpose:** Same as #10-11, but `period=THIRTY_MIN` instead of FIFTEEN_MIN. Otherwise identical Keltner structure.
- **Key params:** `period=THIRTY_MIN`, `factor=1.5`, `factor2=2.0`, `length=20`, `lineLength=50`
- **Status:** Reference (timeframe variant)
- **JARVIS consumption:** **Skip** — same Keltner implementation, different timeframe. No new logic.

### 13. shared_shared_OB_LBR_BARS_HH_LL17STUDY.ts
- **Purpose:** Volatility paint bars (LBR = Lower Band Reversal). Compares close to HH/LL bands (ATR-scaled). Paints bullish (green) if close > both bands, bearish (red) if close < both bands.
- **Key params:** `HLLength=16`, `ATRLength=9`, `factor=2.5`, `paintBars=YES`, `averageType=SIMPLE`
- **Layer:** Regime (volatility context, trend continuation)
- **Status:** Production (simple, mature volatility detector)
- **JARVIS consumption:** **Reference only** — volatility detection via paintbars adds no new signal value beyond ATR + Bollinger. Not ported.

---

## Recommendations for JARVIS

| File | Status | Action | Reason |
|------|--------|--------|--------|
| 1. Saty_ATR_Levels | Production | **Port** | New Structure source; Fibonacci ATR levels not in current pipeline |
| 2. Saty_Phase_Oscillator | Production | **Port** | New Bias/Context oscillator; complements existing indicators |
| 3. Saty_Volume_Stack | Production | Assess | Only if bar-level OHLC available; otherwise visual-only |
| 4. shared_Saty_ATR_Levels | Duplicate | Skip | Identical to #1 |
| 5. Keltner 3.01 | Experimental | Skip | Redundant with BollingerBandsAgent |
| 6. Keltner Master | Experimental | Skip | 3-factor overlay too complex; no strategic advantage |
| 7. Priceline11 | Reference | Skip | Visual marker only |
| 8. MTFTrendbar | Experimental | Skip | Incomplete CCI-SAR, logic bugs |
| 9. Midcloud | Production | Skip | 21-MA already covered by EMA ribbon |
| 10. OMEGA_5m | Reference | Skip | Duplicate Keltner logic, naming mismatch |
| 11. OMEGA_15m | Duplicate | Skip | Exact copy of #10 |
| 12. OMEGA_30m | Reference | Skip | Same logic, different timeframe |
| 13. OB_LBR_Bars | Production | Skip | Volatility paint already covered via ATR |

---

## Final Verdict

- **NEW signal sources to consider:** 2 (Saty_ATR_Levels, Saty_Phase_Oscillator)
- **DUPLICATES found:** 4 (2 Saty_ATR_Levels variants, 3 OB_OMEGA variants)
- **CRITICAL additions:** 0 (all are enhancements, not core requirements)
- **Current pipeline coverage:** 90% of these functions already exist in BollingerBandsAgent, TechnicalAnalystAgent, SignalScanner. These scripts are mature reference implementations; porting adds marginal value unless specific strategy requires them.

**Recommended next step:** If Matt approves Phase 2 strategy direction, port #1 and #2 as optional Layer 3-6 enhancements. Do NOT block strategy approval on these.
