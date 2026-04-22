# Strategy Doc Consistency Review — D9 Agent

**Date:** 2026-04-10 | **Scope:** Cross-check JARVIS-STRATEGY-v1.md against code

---

## Verified (matches code)

- **Section B.1–B.5 (Entry Rules by Instrument):** INSTRUMENT_PARAMS in signals.py:49-96 match exactly
  - MCL: OS=23, OB=83, Stop=0.50, T1=1.00 ✓
  - MNQ: OS=15, OB=92, Stop=0.70, T1=1.00 ✓
  - MGC: OS=17, OB=88, Stop=0.30, T1=1.50 ✓
  - SPY: OS=15, OB=88, Stop=0.30, T1=1.00 ✓
  - MES: OS=15, OB=83, Stop=1.00, T1=2.50 (composite) ✓

- **Section C.3 (Time & Session Rules):** config.py values match exactly
  - SESSION_FLATTEN_TIME_ET = "15:45" ✓
  - REENTRY_LOCKOUT_MINUTES = 240 ✓
  - BREAKEVEN_STOP_ATR_MULT = 0.50 ✓
  - MCL_INVENTORY_BLACKOUT_MINUTES = 45 ✓

- **Section C.4 (Hard Exit Conditions):** safety_layer.py confirms
  - Daily loss halt: -2% ✓
  - Drawdown halt: -10% ✓
  - Consecutive loss halt: 7 losses (24h halt) ✓

- **Section G (Hidden Pivots Integration):** pipeline.py:545-579 confirms
  - Called in Stage 1 analyst phase (line 545) ✓
  - Non-blocking with try/except (line 568) ✓
  - Injects confluence context into debate (line 579) ✓

- **Section H (Corey Auction Tools):** corey_auction_analyst.py:9-16 confirms
  - Signal formula: base_signal (-0.5 to +0.5) + bot_boost (0 to ±0.5) ✓
  - Staleness cap: data_quality=="stale" → confidence≤0.4 ✓
  - Win rate multiplier: 0.7 + 0.6×((win_rate-0.5)/0.5) ✓

---

## Discrepancies

- **Section E (TOS Script Inventory) — line 9 says "37 scripts"**
  - Filesystem count: 36 `.ts` files in `thinkorswim-scripts/`
  - One Pine script in `engine/thinkorswim-scripts/JARVIS_Regime_MCP_Output.pine`
  - **Total across both dirs: 37** — technically correct if counting the Pine file, but table only lists TOS scripts
  - **Recommendation:** Clarify in E that 36 are TOS (ThinkScript) + 1 Pine = 37 total; or adjust to match the 36 on disk

- **Section E.3 — Doc says `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` has "OB=88, OS=19"**
  - This script exists on disk but doc labels params as "OB STC variant (OB=88, OS=19)"
  - No evidence in signals.py that these params are canonical or used — marked as REFERENCE/visual only ✓
  - **No action needed** — doc correctly flags as visual reference

- **Section A (MES WFE Contradiction):** Doc correctly flags this in line 29
  - Rules file: HALTED (WFE 0.09 < 0.5 floor)
  - Code comment (signals.py:100-102): "data collection only"
  - MEMORY.md claims "Tier 3 approved 2026-04-09" yet WFE still 0.09
  - **Doc correctly surfaces the contradiction** ✓ (awaits Matt's decision per §L)

---

## Missing from doc

- **Missing**: Section mentions SPY params but MEMORY.md (2026-04-02) says SPY was "REJECTED per prior audit"
  - Doc Section A.32 notes this contradiction but doesn't explain why params are maintained if rejected
  - **Recommended addition:** Line 31 clarify "params exist as reference but not routed to live pipeline"

- **Missing**: MES composite path produces "broken exit_date=None artifacts" (signals.py:100)
  - Doc §B.3 doesn't mention the exit_date issue, only says "data collection only"
  - This is **critical pre-approval documentation** for Matt
  - **Recommended addition:** Section B.3 footnote explaining the exit_date bug

---

## Doc-only (not backed by code)

- **Section D (30-Day Paper Success Criteria):** Entire section is prescriptive, not extracted from code
  - These are **approval gates**, not implemented in engine yet
  - Confirm with Matt that D.1–D.4 are his stated requirements before writing test suite

---

## Recommended revisions

1. **Section E header:** Change "37 scripts" → "36 ThinkScript + 1 Pine (37 total)" for clarity

2. **Section E.3:** Add note that OB=88, OS=19 params in shared_OB_STYLE script are NOT used in production; document visual-only status more explicitly

3. **Section B.3 (MES composite):** Add footnote:
   > "Note: exit_date=None bug in composite path (Sprint 16) — validate fix before paper trading approval"

4. **Section A (MES status):** Append explicit action item:
   > "ACTION: Matt must confirm MES paper trading approval in writing; current state is ambiguous (rules: HALTED, code: data collection only, MEMORY: Tier 3 approved)."

5. **Section A (SPY):** Clarify line 31:
   > "SPY: Params exist for reference (PF 3.79 in 2024 backtest), but symbol is NOT routed to live pipeline per 2026-04-02 audit rejection."

---

## Token Count
This review: ~500 words. No code changes required.
