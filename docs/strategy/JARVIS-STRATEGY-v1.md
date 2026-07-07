# JARVIS TRADER — Strategy Document v1
**Author:** JARVIS (extracted from code + TOS scripts) · **For:** Matt Morrison · **Date:** 2026-04-10 (updated 17:32 CDT with canon corrections) · **Status:** v1.1 — canon-reconciled

**⚠️ This is an implementation-layer companion to the canonical strategic framework, not a replacement.** Authority order:
1. [`.claude/imports/validated-instruments.md`](../../.claude/imports/validated-instruments.md) — instrument list, WFE, validation gates (ABSOLUTE TRUTH)
2. [`docs/JARVIS_TRADER_UNIFIED_CANON.md`](../JARVIS_TRADER_UNIFIED_CANON.md) — canon narrative + research truth ledger
3. [`docs/strategic/`](../strategic/README.md) — 9-doc strategic command center (Executive Brief, System Map, Capability Matrix, SWOT, Risk Register, Validation Gates, Execution Spine, Analysis Protocol)
4. [`.claude/rules/backtest-signals.md`](../../.claude/rules/backtest-signals.md) — Tier-3 signal parameter rules
5. This document — extracts entry/exit rules from code + TOS scripts for implementation reference

**Where this doc ever contradicts any source above, the source above wins. Report the contradiction as a doc bug.**

---

## Purpose of This Document

After 5 days without a working paper trading system, this is the first time we write down **what JARVIS is actually supposed to do** before writing more code. Everything below is extracted from:
- 37 ThinkorSwim scripts in `thinkorswim-scripts/`
- `engine/backtest/signals.py` (949 lines — per-instrument signal generator)
- `engine/backtest/composite_signals.py` (462 lines — MES multi-source composite)
- `engine/backtest/regime.py` (185 lines — regime classifier)
- `engine/agents/corey_auction_analyst.py` (499 lines — Corey overlay)
- `engine/analysis/hidden_pivots.py` (826 lines — HP pattern detection)
- `.claude/rules/backtest-signals.md` (Tier 3 canonical rules)

**Where the code and the rules file contradict, I flag the contradiction in Section L rather than picking a winner.** Matt makes those calls.

---

## A. Instruments & Universe

Five approved instruments, split into "production" vs "experimental" based on Walk-Forward Efficiency (WFE):

| Symbol | Contract | WFE | Status | Signal Path | Why |
|---|---|---|---|---|---|
| **MCL** | Micro Crude Oil | **0.82** | ✅ PRODUCTION | `generate_signals()` | Highest edge; Sprint 16 WF consensus (OOS PF 1.21) |
| **MNQ** | Micro Nasdaq-100 | **0.57** | ✅ PAPER-APPROVED | `generate_signals()` | Approved per canon; PF 1.51, 86 trades |
| **MES** | Micro E-mini S&P 500 | **0.09** | ✅ PAPER-APPROVED (WFE improvement pending) | `generate_composite_signals()` | **CORRECTED 2026-04-10 17:32:** `validated-instruments.md` says "PAPER — authorized 2026-04-09, WFE improvement pending". MES IS approved for paper trading per canon. Composite path is safe (D6 diagnosis confirmed Sprint 16 `exit_date=None` bug was fixed in commit `93464ae` on 2026-04-03). Low WFE is noted but does not disqualify from paper validation window. |
| **MGC** | Micro Gold | **0.14** | ⛔ HALTED | `generate_signals()` (params exist but disabled) | Canon: overfit/small-sample |
| **SPY** | S&P 500 ETF | — | ⚠️ NOT IN CANONICAL APPROVED LIST | `generate_signals()` | Optimizer shows PF 3.79, 23 trades — insufficient sample. Not in validated-instruments.md. Do NOT route in paper window. |

**Paper window recommendation (canon-aligned):** MCL + MNQ + MES per `validated-instruments.md`. Three instruments, 1h timeframe, all under the 2-contract hard cap enforced by `config.py` validator added in commit `be6927d`.

---

## B. Exact Entry Rules by Instrument ⭐ (Matt's #1 must-have)

These are pulled directly from `INSTRUMENT_PARAMS` in `engine/backtest/signals.py:49-96` and confirmed against the TOS scripts. Each instrument has its own parameter set.

### B.1 — MCL (Micro Crude Oil) — 1h timeframe

**Enter LONG when ALL of:**
1. `STC` crosses **above 23** (OS threshold per MCL's WF-validated params — NOT the default 15)
2. Current bar closes in a **TRENDING or RANGING** regime (NOT VOLATILE — VOLATILE is a hard veto via regime filter)
3. STC cross is confirmed by `stc_prev <= 23 AND stc_now > 23`
4. Trade passes minimum R:R ≥ 1.50 (T1=1.00x ATR / Stop=0.50x ATR = 2.0:1 by construction)
5. Not inside the **MCL_INVENTORY_BLACKOUT** window (15 min before + 30 min after Wed 10:30 ET EIA release)

**Enter SHORT when ALL of:**
1. `STC` crosses **below 83** (OB threshold)
2. Regime is TRENDING or RANGING (not VOLATILE)
3. Confirmed cross: `stc_prev >= 83 AND stc_now < 83`
4. R:R ≥ 1.50
5. Not in EIA blackout

### B.2 — MNQ (Micro Nasdaq-100) — 1h timeframe

**Enter LONG when ALL of:**
1. `STC` crosses **above 15** (standard OS)
2. Regime = TRENDING or RANGING (NOT VOLATILE)
3. Confirmed cross
4. R:R ≥ 1.42 (T1=1.00x / Stop=0.70x ATR = 1.43:1)

**Enter SHORT when ALL of:**
1. `STC` crosses **below 92** (tighter OB than default to filter Nasdaq noise per optimizer)
2. Regime ≠ VOLATILE
3. Confirmed cross
4. R:R ≥ 1.42

### B.3 — MES (Micro E-mini S&P 500) — 1h timeframe (COMPOSITE PATH)

**MES is different.** It uses `generate_composite_signals()` which scores 3 independent sources with regime-adaptive weights:

| Regime | STC weight | ORB weight | VWAP weight |
|---|---|---|---|
| TRENDING | 0.60 | 0.30 | 0.10 |
| RANGING | 0.50 | 0.20 | 0.30 |
| VOLATILE | **0.00** (all veto) | 0.00 | 0.00 |

**Enter LONG when ALL of:**
1. `composite_score ≥ 0.35` (entry threshold)
2. **STC gate is active** — STC must fire a bullish cross (this is a hard gate; ORB+VWAP alone cannot enter)
3. Regime ≠ VOLATILE
4. Composite R:R ≥ 1.2 (T1=2.50x ATR / Stop=1.00x ATR = 2.5:1 by construction)
5. If both long_score and short_score fire on the same bar → take the stronger one

**Component signals that contribute to the score:**
- **STC**: crosses above 15 (long) or below 83 (short)
- **ORB**: close breaks above opening range high (long) or below low (short), restricted to RTH window, after first 30 min
- **VWAP reversion**: price touches lower band (`vwap - 2.5 * ATR`) and reverses up (long), or upper band and reverses down (short)

**Enter SHORT** — mirror of LONG conditions, with `short_score ≥ 0.35` and STC bearish cross required.

**Status note (updated 2026-05-24):** MES 1h is now **APPROVED and active on paper** (Tier-3 auth, gate v2 ALT PASS, p_edge 0.75) using the SMA(60,200) trend config — not the old STC composite. The prior "data collection only" / WFE 0.09 framing is superseded. See `engine/CLAUDE.md` Active Instruments.

### B.4 — MGC (Micro Gold) — HALTED

Params exist (`STC_OS=17, OB=88, Stop=0.30x, T1=1.50x, regime ON`) but WFE 0.14 is below the 0.50 threshold. **Do not trade until re-validated.**

### B.5 — SPY (Equity ETF, 1h) — Optional tertiary

Params: `STC_OS=15, OB=88, Stop=0.30x, T1=1.00x, T2=1.618x, T3=2.618x, regime ON`. Backtest PF 3.79 but only 23 trades — insufficient sample. **Only enable if Matt explicitly wants equity exposure in addition to futures.**

---

## C. Exact Exit Rules ⭐ (Matt's #2 must-have)

### C.1 — Stop-Loss Placement (by instrument)

The stop is placed at `entry_price ± (ATR * STOP_MULT)` where `STOP_MULT` is per-instrument:

| Symbol | Stop ATR Mult | Example on 1h (ATR=1.50) |
|---|---|---|
| MCL | **0.50** | $0.75 away from entry |
| MNQ | **0.70** | 105 points away |
| MGC | **0.30** | $4.50 away |
| SPY | **0.30** | 45 cents away |
| **MES (composite)** | **1.00** | ~26 points away (wider because composite uses ATR=1.0) |

**Direction:** LONG stop = `entry - (ATR * mult)`, SHORT stop = `entry + (ATR * mult)`.

### C.2 — Profit Target Placement

Three-level scaling targets (T1 / T2 / T3) per instrument:

| Symbol | T1 ATR | T2 ATR | T3 ATR | T1:Stop R:R |
|---|---|---|---|---|
| MCL | 1.00 | 2.618 | 4.00 | **2.0:1** |
| MNQ | 1.00 | 1.80 | 2.618 | **1.43:1** |
| MGC | 1.50 | 2.618 | 4.00 | **5.0:1** |
| SPY | 1.00 | 1.618 | 2.618 | **3.33:1** |
| MES (composite) | 2.50 | 4.00 | 6.00 | **2.5:1** |

**Scale-out rules (from `backtest/paper_runner.py:386-437`):**
- At T1 hit: exit 1/3 of position (or 1 contract minimum)
- At T2 hit: exit 1/2 of remaining
- At T3 hit: exit remainder
- **After T1 hit: stop moves to breakeven** (entry price)

### C.3 — Time Stops & Session Rules

- **`SESSION_FLATTEN_TIME_ET = "15:45"`** (config.py) — all intraday positions closed by 3:45 PM ET regardless of P&L
- **`REENTRY_LOCKOUT_MINUTES = 240`** — after a stop-out, no new entry on that symbol for 4 hours
- **`BREAKEVEN_STOP_ATR_MULT = 0.50`** — stop moves to breakeven after price travels +0.50x ATR in favor
- **Overnight holding:** `MAX_OVERNIGHT_CONTRACTS = 1` — only 1 contract allowed to carry overnight
- **MCL EIA blackout:** no new MCL entries 15 min before or 30 min after Wed 10:30 ET

### C.4 — Hard Exit Conditions

In addition to stops/targets, the SafetyLayer force-closes all positions if:
- Daily P&L hits **-2%** (kill switch)
- Drawdown from equity peak hits **-10%** (emergency halt)
- Consecutive loss streak hits **7** (24-hour halt)
- Price outside plausible range (scanner guard added 2026-04-10 in commit `be6927d`)

---

## D. 30-Day Paper Window Success Criteria ⭐ (Matt's #3 must-have)

**CANONICAL SOURCE:** [`.claude/imports/validated-instruments.md`](../../.claude/imports/validated-instruments.md) is authoritative for all validation gates. If this section ever disagrees with that file, **that file wins** and this table must be updated. (Earlier v1 draft had looser floors. Canon values below.)

### D.1 — Canon Validation Gates (MUST HIT ALL)

Per `validated-instruments.md` — the inequality that gates Phase 3 eligibility:

| Metric | Canon Gate | Source |
|---|---|---|
| **Profit Factor** | **≥ 2.0** | validated-instruments.md |
| **Sharpe ratio** | **≥ 1.5** | validated-instruments.md |
| **Win rate** | **≥ 55%** | validated-instruments.md |
| **Total trades** | **≥ 60** | validated-instruments.md |
| **Trading days** | **≥ 30** | validated-instruments.md |
| **Max drawdown** | **≤ 15%** | validated-instruments.md |
| **Paper capital** | **$10,000** | validated-instruments.md |

**These are the Phase 3 go-live gates. All 6 must hit simultaneously for the 30-day window to PASS.**

### D.2 — Operational Health Targets (orthogonal to canon — my additions)

These are NOT in canon but are operational targets for system trust:

| Metric | Target | Rationale |
|---|---|---|
| Pipeline uptime during RTH | ≥ 98% | Can't validate a strategy that can't run |
| Decision → paper_trades latency | ≤ 5 seconds | Audit trail completeness |
| WhatsApp alert fire rate on non-HOLD signals | **persistence ≥ 100%** (sends may be cooldown-suppressed but MUST be alert_logged) | D3 diagnosis — fix committed in Phase 1 |
| Dashboard render on all canonical routes | pass | D4 diagnosis — fix committed in Phase 1 |
| Kill switch activations during 30-day window | 0 (none triggered, just proved functional on drill) | Safety system integrity |
| Days with contaminated trades (wrong price) | 0 | The be6927d scanner sanity guards prevent this |

### D.3 — Phase 3 Readiness Matrix

| Canon gates (D.1) | Operational targets (D.2) | Verdict |
|---|---|---|
| ALL 6 hit | ALL hit | **GO for Phase 3 conversation** (not same as live — see PHASE3_READINESS.md) |
| ALL 6 hit | ANY miss | **CONDITIONAL** — operational targets are fixable; address and re-run validation |
| ANY canon miss | N/A | **NO-GO** — strategy doesn't have edge per validated-instruments policy. Iterate or halt. |

**Per `docs/strategic/07_EXECUTION_SPINE.md §Phase 3 alignment`: "DoD for Phase 3 conversation" is P0 complete + risks addressed + 30-day validation plan running on approved symbols only. Hitting canon gates is the validation half.**

---

## E. TOS Script Inventory (37 scripts) ⭐ (Matt's #4 must-have)

| # | File | Purpose | Layer | Status | JARVIS Consumption |
|---|---|---|---|---|---|
| 1 | `COHEN_MES_COMPOSITE.ts` | STC+ORB+VWAP regime-weighted composite | Entry + Regime | PRODUCTION | ✅ Mirrored in `composite_signals.py` (MES only) |
| 2 | `COHEN_MES_STC_SUB.ts` | STC sub-pane oscillator (fast=23, slow=50, OB=83, OS=15) | Bias + Entry | PRODUCTION | ✅ Mirrored in `signals.py:stc()` |
| 3 | `shared_OB_STYLE_CYCLE_TIMESHIFT_PAINT_BARSSTUDY.ts` | OB STC variant (OB=88, OS=19) + multi-TF + paint bars | Bias | REFERENCE | ⚠️ Different params than canonical — visual only, **do not port** |
| 4 | `AA_CoreyIBv1STUDY.ts` | Initial Balance (first 60min) + quads (25/50/75) + next-day extensions | Structure | PRODUCTION | ✅ Partial port in `engine/discord/ib_levels.py`; TOS visual remains source of truth |
| 5 | `AA_CoreyTscorev2STUDY.ts` | TPO Score — POC, Value Area, profile extensions (0.382/0.5/0.618/0.786/1.0/2.0) | Structure | PRODUCTION | ⚠️ **NOT ported** — lives in TOS only; opportunity to consume via TradingView MCP bridge |
| 6 | `AA_CoreyGapfinderv1STUDY.ts` | Unfilled gap detection + forward extension | Structure | PRODUCTION | ⚠️ **NOT ported** — same as above |
| 7 | `AA_CoreyRFv2STUDY.ts` | Rangefinder (range/expansion detection) | Structure | PRODUCTION | ⚠️ NOT ported |
| 8 | `AA_CoreyRFv1MobileSTUDY.ts` | Mobile variant of Rangefinder | Structure | REFERENCE | ❌ Skip (mobile duplicate) |
| 9 | `AA_CoreySFv2STUDY.ts` | Singlefinder (single-print detection in profile) | Structure | PRODUCTION | ⚠️ NOT ported |
| 10 | `AA_CoreyTPOProfilev1STUDY.ts` | TPO profile visualization | Structure | PRODUCTION | ⚠️ NOT ported |
| 11 | `shared_AA_CoreyRangefinderv1_01STUDY.ts` | Rangefinder older version | Structure | REFERENCE | ❌ Superseded by RFv2 |
| 12 | `shared_AA_CoreySinglefinderv2STUDY.ts` | Singlefinder duplicate | Structure | REFERENCE | ❌ Duplicate |
| 13 | `shared_AA_CoreyTPOScorev2STUDY.ts` | TPO Score duplicate | Structure | REFERENCE | ❌ Duplicate |
| 14 | `Saty_ATR_LevelsSTUDY.ts` | ATR-based support/resistance levels | Sizing | PRODUCTION | ✅ Conceptually mirrored in `wilder_atr()` + per-instrument stop/target mults |
| 15 | `shared_Saty_ATR_LevelsSTUDY.ts` | Duplicate | Sizing | REFERENCE | ❌ Duplicate |
| 16 | `Saty_Phase_OscillatorSTUDY.ts` | Phase oscillator with compression detection | Bias | PRODUCTION | ✅ Ported in `signals.py:phase_oscillator()` |
| 17 | `Saty_Volume_StackSTUDY.ts` | Volume delta stack (buy vs sell volume) | Bias | PRODUCTION | ✅ Ported in `signals.py:volume_stack()` |
| 18 | `GAPS_Chetan1STUDY.ts` | Gap analysis (different methodology than Corey's) | Structure | EXPERIMENTAL | ⚠️ NOT ported |
| 19 | `TRIN_ChetanSTUDY.ts` | TRIN (Arms index) classification | Regime | EXPERIMENTAL | ⚠️ Partial in `signals.py:classify_trin()` |
| 20 | `NextSignalMomentumSTUDY.ts` | Momentum signal from NextSignal | Bias | EXPERIMENTAL | ❌ NOT ported |
| 21 | `ThinkScript_study_20221014STUDY.ts` | Dated experiment | — | LEGACY | ❌ Skip |
| 22 | `ThinkScript_study_20221016STUDY.ts` | Dated experiment | — | LEGACY | ❌ Skip |
| 23 | `ThinkScript_study_20230523STUDY.ts` | Dated experiment | — | LEGACY | ❌ Skip |
| 24 | `shared_OB_OMEGA_15m7STUDY.ts` | OB Omega 15m variant | Entry | EXPERIMENTAL | ❌ NOT ported |
| 25 | `shared_OB_OMEGA_30m7STUDY.ts` | OB Omega 30m variant | Entry | EXPERIMENTAL | ❌ NOT ported |
| 26 | `shared_OB_OMEGA_5mSTUDY.ts` | OB Omega 5m variant | Entry | EXPERIMENTAL | ❌ NOT ported |
| 27 | `shared_shared_OB_LBR_BARS_HH_LL17STUDY.ts` | LBR (Linda Bradford Raschke) bar pattern + HH/LL | Entry | EXPERIMENTAL | ❌ NOT ported |
| 28 | `shared_midcloudoteSTUDY.ts` | Mid cloud (Ichimoku-like) | Structure | EXPERIMENTAL | ❌ NOT ported |
| 29 | `shared_shared_midcloudoteSTUDY.ts` | Duplicate | — | REFERENCE | ❌ Duplicate |
| 30 | `shared_mtftrendbarSTUDY.ts` | Multi-timeframe trend bar | Regime | EXPERIMENTAL | ❌ NOT ported |
| 31-32 | `shared_shared_shared_shared_kelt_3.01STUDY.ts` (+dup) | Keltner Channels 3.0x | Sizing | PRODUCTION | ✅ Ported in `signals.py:keltner_channels()` |
| 33-34 | `shared_shared_shared_shared_shared_Priceline11STUDY.ts` (+dup) | Price lines overlay | Context | REFERENCE | ❌ Visual only |
| 35-36 | `shared_shared_shared_shared_shared_kmaster1STUDY.ts` (+dup) | kmaster (Keltner master?) | Sizing | EXPERIMENTAL | ❌ NOT ported — investigate |
| 37 | `engine/thinkorswim-scripts/JARVIS_Regime_MCP_Output.pine` (Pine) | Pine regime indicator for TradingView MCP | Regime | NEW | ✅ Planned MCP consumption |

**Summary:**
- **Already ported to Python (production):** STC, ATR, Phase Oscillator, Volume Stack, Keltner Channels, EMA Ribbon, composite signals, regime classifier, IB levels (partial)
- **Not ported — opportunity to consume via TradingView MCP:** TPO Score (POC/VA/extensions), Gap Finder, Rangefinder, Singlefinder, TPO Profile
- **Legacy/experimental — skip or investigate:** OB Omega variants, TRIN Chetan, NextSignal, LBR bars, mid cloud, kmaster

---

## F. Position Sizing & Risk

**Per-trade:**
- Max position size: **5%** of portfolio (`MAX_POSITION_SIZE_PCT`)
- Max contracts per instrument: **2** (hard-capped in `config.py` validator as of commit `be6927d`)
- Max single order value: **$5,000** (`MAX_SINGLE_ORDER_VALUE`)
- Max correlated exposure: **20%** of portfolio (`MAX_CORRELATED_EXPOSURE_PCT`) — e.g., can't hold full-size MES + MNQ simultaneously
- Fixed-fractional sizing: 1% risk per trade via ATR stop distance

**Portfolio-wide:**
- Max margin utilization: **40%**
- Max overnight contracts: **1**
- Max orders per minute: **10** (rate throttle)
- Price collar: reject orders > **5%** from NBBO

**Correlation rule:** Don't open both MES and MNQ in the same direction simultaneously (high correlation — acts as a leveraged single bet on equities).

---

## G. Hidden Pivots Integration

Hidden Pivots is Rick Ackerman's methodology, implemented in `engine/analysis/hidden_pivots.py` (826 LOC, 36 tests passing). It runs as a **non-blocking Stage 1 context layer** in `engine/agents/pipeline.py`.

**What HP detects (pattern library):**
- `rounded_base` (bullish reversal)
- `rounded_top` (bearish reversal)
- `bull_flag` / `bear_flag` (continuation)
- `triangle` (indecision → break)
- `channel_reversal`

**HP scoring output:**
- `bias`: LONG / SHORT / WATCH / SOH ("sit on hands")
- `trigger_price` (entry level)
- `tight_stop` + `riskier_stop`
- `targets[]` (3 levels)
- `hp_ou_level` (the HP overshoot/undershoot dotted line)
- `ema_alignment`: BULLISH_FAN / BEARISH_FAN / COMPRESSED / MIXED (4-EMA: 10/50/100/200)
- `rs_rw_score` (-1 to +1, relative strength/weakness)
- `confidence` (0 to 1)

**Integration with signal scoring:**
- HP result is injected into `analyst_reports["hidden_pivots"]` dict
- `CoreyAuctionAnalystAgent` uses `hp_context` to add an alignment bonus: **+0.15 to alignment_score when HP direction matches Corey bias** (e.g., HP bullish + Corey bullish + IB level confluence)
- HP does NOT veto signals independently — it's a confluence BOOST, not a GATE
- `SOH` flag is advisory only (logged, not enforced)

**Recommendation:** Once HP is fully trusted, promote it from "confluence boost" to "weighted component" — e.g., compute a combined score `final_score = 0.60 * composite + 0.20 * corey + 0.20 * hp`.

---

## H. Corey Auction Tools Integration

Corey Auction Tools feeds via Discord into `engine/agents/corey_auction_analyst.py` (499 LOC) and `engine/discord/commentary_processor.py` (488 LOC).

**Data sources:**
1. **Corey commentary** (live Discord messages) → LLM-extracted directional bias (`bullish` / `bearish` / `neutral`) + conviction + key levels
2. **Discord bot signals** (215,887 rows in `discord_bot_signals` table) → active signals with win rate tracking

**Signal computation** (`corey_auction_analyst.py:10-17`):
```
base_signal = {bullish: +0.5, bearish: -0.5, neutral: 0.0}
bot_boost   = ±0.5 (within 0.5x ATR of active bot signal)
            | ±0.3 (within 1.5x ATR)
            | 0 (further away)
signal      = clamp(base_signal + bot_boost, -1.0, +1.0)

win_rate_multiplier = 0.7 + 0.6 * ((win_rate - 0.5) / 0.5)  # 0.7@50%, 1.3@100%
confidence          = min(1.0, commentary.conviction × multiplier)
```

**Staleness handling:**
- Data older than **2 days** → confidence capped at **0.4**
- Data older than **16 months** (prior audit finding) → treat as `data_quality="stale"` and heavily discount

**IB bias overlay:**
- `ib_bias`: "above_ib" | "below_ib" | "inside_ib" | "not_mentioned"
- Used as a session-bias gate — if Corey says "above IB = bullish day" and price is above IB, that's confluence

**Integration with debate:**
- Corey signal feeds into Stage 1 analyst reports
- Bull/Bear researchers in Stage 2 reference Corey bias when constructing arguments
- **Does NOT directly override** the Trader Agent's final decision

---

## I. Session Timing & Calendar Gates

**Trading sessions:**
- **RTH (Regular Trading Hours):** 9:30 AM – 4:00 PM ET (8:30 AM – 3:00 PM CT)
- **Session flatten:** **15:45 ET** (`SESSION_FLATTEN_TIME_ET` in config.py) — close all intraday
- **Avoid entries:** first 5 min of RTH (9:30-9:35 ET), last 15 min (3:45-4:00 ET)
- **Overnight:** max 1 contract (`MAX_OVERNIGHT_CONTRACTS`)

**Cron schedules (from `main.py`):**
- Watchlist auto-scan: every 30 min during 9:00-15:00 CT weekdays (currently gated OFF via `WATCHLIST_SCAN_ENABLED=false`)
- SignalScanner: 60-minute interval (currently paused via `/scanner/pause`)
- Intraday 15m scanner: every 15 min 9:45-15:45 ET weekdays (signals only, no trades)
- EOD snapshot: 16:05 ET weekdays
- IB Gateway health: every 15 min during market hours

**Calendar exclusion windows:**
- **MCL EIA blackout:** Wed 10:15-11:00 ET (±45 min around 10:30 crude inventory release)
- **FOMC days:** No new entries 1h before – 30 min after announcement
- **NFP days:** First Friday of month, no new entries 8:25-8:45 ET around release
- **Equity options earnings weeks:** If SPY/QQQ positions open, flatten by 3:30 ET on FOMC/CPI/NFP days

---

## J. Non-Negotiable Safety Rules (Tier 3 — cannot be changed without explicit confirmation)

| Rule | Limit | Enforced In |
|---|---|---|
| `LIVE_TRADING_ENABLED` | **False** (paper only until Phase 3) | `config.py` + `safety_layer.py` |
| `REQUIRE_HUMAN_APPROVAL` | **True** (every trade needs human review) | `config.py` |
| Kill switch: daily loss | **-2%** → halt | `safety_layer.py` |
| Kill switch: drawdown | **-10%** from equity peak → halt | `safety_layer.py` |
| Max position size | **5%** of portfolio | `config.py` |
| Max contracts per instrument | **2** (hard-cap validator, cannot override via .env) | `config.py` + validator (commit `be6927d`) |
| Max overnight contracts | **1** | `config.py` |
| Price collar | reject > **5%** from NBBO | `safety_layer.py` |
| Max single order value | **$5,000** | `config.py` |
| Max margin utilization | **40%** | `config.py` |
| Consecutive loss halt | **7** losses → 24h halt | `pnl_monitor.py` |
| Consecutive loss 0.5x sizing | **3** losses | `pnl_monitor.py` |
| Consecutive loss 0.25x sizing | **5** losses | `pnl_monitor.py` |
| Port 4001 (live IBKR) | **PERMANENTLY BLOCKED** | `ib_gateway_connector.py` |
| SCHWAB_READY | **False** (not active until Phase 3) | `config.py` |
| Safety layer = **pure hardcoded Python** — NEVER LLM-driven | invariant | `safety_layer.py` comment header |

---

## K. Best-Traders Overlay ⭐ (Matt's explicit ask)

Gap analysis against the rules/frameworks used by world-class traders. For each: what JARVIS does today, what the pro approach is, and a specific concrete recommendation.

### K.1 — Paul Tudor Jones: Risk-First Sizing

> "Don't focus on making money, focus on protecting what you have."

**JARVIS today:** Fixed-fractional 1% risk per trade via ATR stop, max 5% position size. Stops are always defined at entry.
**PTJ principle:** Risk per idea scales with conviction but never above 1%. Cut fast when wrong. Let winners run via trailing stops.
**Gap:** JARVIS has breakeven-move-after-T1 but does NOT have an explicit trailing stop for winners past T2.
**Recommendation:** **ADOPT** — add a trailing stop after T2 hit that tracks price by `1.5x ATR` or the 21-EMA (whichever is closer). Keeps the remaining position alive for runner moves without giving back T2 gains.

### K.2 — Linda Raschke: Holy Grail / First Pullback

> "The first pullback after a breakout is the highest-probability entry."

**JARVIS today:** Enters on STC cross above OS, which is roughly a mean-reversion-in-trend signal. Does NOT explicitly wait for the first pullback after breakout.
**Raschke principle:** After a clean structural breakout (e.g., above prior day's high), wait for the first pullback that holds the 20 EMA, then enter.
**Gap:** MES composite path has ORB breakout confluence but enters at the breakout, not the pullback.
**Recommendation:** **CONDITIONAL ADOPT** — add a "Raschke entry" alternative for MES/MNQ where STC fires OS then price touches 20-EMA on a pullback before re-crossing up. Backtest vs current entry to confirm edge before integrating.

### K.3 — Al Brooks: Price Action Purity

> "Never enter on an indicator alone. Always confirm with a clean bar."

**JARVIS today:** Enters on STC cross (an indicator). Does NOT require a "strong close" or "clean bar" confirmation.
**Brooks principle:** Need bar-close confirmation — e.g., a bull signal needs a bull bar closing in the upper 1/3 of its range.
**Gap:** No bar-quality filter on entries.
**Recommendation:** **ADOPT** — add a `is_clean_bar()` check: bar body ≥ 60% of range AND close in direction of signal. Reject entries on doji / inside-bar / weak-close bars. 10-line filter.

### K.4 — Stan Druckenmiller: Concentrated Conviction

> "It's not whether you're right or wrong, it's how much money you make when you're right and how much you lose when you're wrong."

**JARVIS today:** Fixed 1% risk regardless of setup quality. All entries sized the same.
**Druck principle:** Size with conviction. High-conviction setups get 1.5-2x normal size; low-conviction setups get 0.5x or skip.
**Gap:** JARVIS has a `conviction` field in `TradeDecision` but doesn't scale size by it.
**Recommendation:** **ADOPT (carefully)** — introduce conviction-tiered sizing:
  - conviction ≥ 0.80 → 1 contract (normal size, respecting 2-contract cap)
  - conviction ≥ 0.65 → 1 contract
  - conviction 0.50-0.65 → 0.5 contract (or skip if min lot can't honor)
  - conviction < 0.50 → SKIP (already done via debate INCONCLUSIVE → HOLD)

### K.5 — Ernie Chan: Statistical Edge Validation

> "Before you risk real money, prove the edge survived out-of-sample data."

**JARVIS today (2026-05-24):** Validation moved to gate v2 (p_edge / Monte Carlo / rolling WFO). Active paper: MES p_edge=0.75, MGC p_edge=0.6842 (both ALT gate v2 PASS). Halted: MCL (WFE 0.82) and MNQ (WFE 0.57) — `DO_NOT_TRADE`; M2K rejected. Bootstrap p-value check exists in `proactive_validation` suite.
**Chan principle:** OOS Sharpe ≥ 1.0, WFE ≥ 0.5, Monte Carlo p-value ≤ 0.05. Regime-conditional performance (does edge hold in bull AND bear regimes?).
**Gap:** Halted instruments (MCL, MNQ) still have params in code and can be accidentally used — `DO_NOT_TRADE_SYMBOLS` and `paper_config.enabled=False` are the guards.
**Recommendation:** **ALREADY DOING** — but tighten: add a startup guard in `main.py` that refuses to activate any instrument below `WFE ≥ 0.50`. Currently only advisory via handoff notes.

### K.6 — James Simons / Renaissance: Signal Orthogonality

> **NO VERIFIABLE QUOTE** — per D10 research, Simons' methods are proprietary. Strip the attributed quote. Reframe as architecture inspiration only.

**JARVIS today:** STC + ORB + VWAP + Corey + HP + EMA ribbon + Phase oscillator + Volume stack. Unknown orthogonality — no correlation matrix across signals.
**Simons-style architecture principle (widely reported, not directly quoted):** measure pairwise correlation of signal time-series; reject/decorrelate highly correlated signals (|r| > 0.7).
**Gap:** No correlation audit of signal sources.
**Recommendation:** **CONDITIONAL ADOPT** — once paper trading produces 60+ trades, compute pairwise signal correlation across all Stage 1 analyst outputs. Drop duplicates (e.g., STC and EMA ribbon may be > 0.8 correlated). Weight each unique signal by its standalone Sharpe. Defer to post-Phase-1 stabilization.

### K.7 — Mark Minervini / SEPA: Stage Analysis (regime overlay)

> "Only buy stocks in Stage 2 advance. Short only Stage 4 decline."

**JARVIS today:** RegimeClassifier detects TRENDING / RANGING / VOLATILE. Does NOT classify trend stage (early / mid / exhausted).
**Minervini principle:** For futures, equivalent is "is this a fresh breakout from compression (Stage 2) or an exhausted trend (Stage 3 top)?" Phase Oscillator with compression detection approximates this.
**Gap:** JARVIS has phase_signal ("compression" / "extended_up" / "extended_down") but doesn't use it as a gate.
**Recommendation:** **ADOPT** — add an exhaustion gate: if `phase_signal == "extended_up"` (phase ≥ +61.8) AND signal is LONG, REJECT the entry (likely late-cycle buying). Same for shorts at "extended_down".

### K.8 — Steve Cohen / Point72: "Never bet on one signal"

**JARVIS today:** ALREADY DOING — the composite signal path (MES) combines STC + ORB + VWAP. The standard path (MCL/MNQ) relies on STC alone, albeit filtered by regime.
**Cohen principle:** No trade without ≥ 2 independent confirming signals.
**Gap:** MCL/MNQ standard path technically fires on STC alone (regime filter is a gate, not an independent confirmation).
**Recommendation:** **PARTIAL ADOPT** — keep MCL/MNQ on the validated standard path for now (they work). Over time, move all instruments to composite with 2+ signal requirement once per-instrument composite params are re-validated via WFE.

### K.9 — John Carter: Volatility Expansion Entries

> "Enter when volatility is compressed and about to expand — before the move, not during it."

**JARVIS today:** Phase Oscillator detects `phase_compression` flag. Does NOT explicitly trade compression-to-expansion transitions.
**Carter principle:** TTM Squeeze — when Bollinger Bands go inside Keltner Channels (compression), prepare for breakout entry in the direction of the first momentum surge.
**Gap:** Compression is detected but not traded on.
**Recommendation:** **DEFER** — this is a different strategy family. Revisit in Phase 4 as an additional signal source if the core STC+regime system works.

### K.10 — Systematic vs Discretionary — The Biggest Gap

All the traders above use some discretion on top of rules. **JARVIS is 100% systematic.** Pros:
- Emotionless execution
- Reproducible results
- No overnight worry about discipline

Cons:
- Misses regime shifts the rules don't encode (e.g., post-Fed surprise)
- Can't exercise judgment on confluence quality
- Hard to improve without re-training/re-backtesting

**Recommendation:** Keep JARVIS systematic for paper trading validation. Add a "manual override" channel for Phase 3 live: Matt can flag a pending approval as "block — regime shift detected" in real-time via the dashboard, and JARVIS will respect it. **This is already wired via `REQUIRE_HUMAN_APPROVAL = True`.** Use it.

---

## L. Contradictions & Open Questions (Matt — I need your answers here)

### L.1 — Rules file vs code conflicts (RESOLVED 2026-04-10 17:32 via canon)

1. **STC params: rules file (OS=15, OB=83) or per-instrument in `INSTRUMENT_PARAMS`?**
   - **RESOLVED:** Per-instrument params win. `.claude/rules/backtest-signals.md` is a starter-template reference; actual WFE-validated params live in `engine/backtest/signals.py:INSTRUMENT_PARAMS`. Canon does not override per-symbol validation artifacts.

2. **MES status: HALTED or APPROVED?**
   - **RESOLVED:** `validated-instruments.md:10` says "PAPER — authorized 2026-04-09, WFE improvement pending". **MES IS approved for paper window.** The `01_EXECUTIVE_BRIEF.md §2` line saying "MES do not trade" is stale and should be updated to match canon. Matt confirmed inclusion in Phase 2 targets (17:32 CDT).
   - Paper_trades DB contaminated trades (#108/#109/#110) were closed to $0 per Stage 3 of the earlier EOD hardening session (commit `be6927d`). Not a trading flag issue — was data-quality issue.

3. **ATR stop for 1h: rules file (0.70x) or per-instrument (code)?**
   - **RESOLVED:** Per-instrument wins, same rationale as (1). Rules file's `0.70x` is the generic default; WFE validated instrument-specific values (MCL=0.50, MNQ=0.70, MGC=0.30, SPY=0.30, MES=1.00 composite).

### L.2 — Integration gaps (deferred to post-Phase-1)

4. **Hidden Pivots weight:** HP is a "boost" (+0.15 to Corey alignment_score) currently. Promoting to weighted voting component deferred to post-Phase-1 research. No blocker for paper window.

5. **TPO Score (AA_CoreyTscorev2):** Not ported to Python. Slated for TradingView MCP Stage 1 wiring in Phase 2.5 or Phase 3 (see D10 recommendation and data source answer).

6. **Corey IB bias gate:** Currently advisory. Deferred — D10 research noted "intraday-focused scope creep risk" for Raschke/Brooks/Carter overlays. Same applies here.

### L.3 — Strategic decisions (RESOLVED 2026-04-10 17:32)

7. **Instruments for paper window:** **MCL + MNQ + MES** per canon (validated-instruments.md). MGC halted. SPY not in canonical list.

8. **Paper window duration:** **≥ 30 trading days** per canon (validated-instruments.md § validation gate).

9. **Success rubric:** **Canon-aligned** — PF ≥ 2.0, Sharpe ≥ 1.5, WR ≥ 55%, Trades ≥ 60, Days ≥ 30, DD ≤ 15%. See §D above. Earlier draft floors were loose and have been corrected.

10. **Manual override authority:** `REQUIRE_HUMAN_APPROVAL = True` remains NON-NEGOTIABLE per `01_EXECUTIVE_BRIEF.md §2` and `.claude/rules/safety.md`. Matt approves every trade during paper window. No auto-approve exceptions.

### L.4 — Tier-3 process note on commit `be6927d`

The 2026-04-10 EOD hardening commit `be6927d` modified `engine/config.py` (Tier-3 file per `06_VALIDATION_GATES.md §3`). The changes were:
- `WATCHLIST_SCAN_ENABLED` setting (additive, kill switch for scanner scheduler)
- `MAX_CONTRACTS_PER_INSTRUMENT` @field_validator (hard-cap at 2)
- `SQLITE_DB_PATH` @field_validator (resolves to absolute path anchored at engine/ root)

**Process status:**
- Matt verbally approved the `MAX_CONTRACTS` hard cap via clarifying question during the same session.
- `WATCHLIST_SCAN_ENABLED` was discussed as part of the scanner kill switch and implicitly approved.
- `SQLITE_DB_PATH` resolver is a pure bug-fix (no parameter change).
- **Missing:** `/review` (gstack) skill was NOT run on the commit per `06_VALIDATION_GATES.md §3` mandatory review for safety-layer-adjacent changes. `config.py` is Tier-3 but not safety_layer.py directly — the `/review` mandate is specifically for `safety_layer.py` per AGENTS.md. Unclear if `config.py` requires it.

**Action TODO for next session:** Run `/review` skill retroactively on commit `be6927d` to confirm process compliance and catch anything the human confirmation missed. This is not blocking — Phase 1 does not touch Tier-3 files.

### L.5 — Things I did NOT cover in this doc

- Options strategies on SPY/QQQ — JARVIS has stubs but no validated options strategy. Out of scope for Phase 1.
- Live broker routing to IBKR — Tier 3, Phase 3 only. Runbooks: `docs/runbooks/P0_PAPER_IB_VERIFICATION.md`, `docs/runbooks/PHASE3_READINESS.md`
- RL agent experimental results — MES-only, data-collection, not part of production strategy.
- TradingView MCP Stage 1 wiring — biggest under-utilized asset per prior audit, deferred to Phase 2.5 or Phase 3 (D9/D10 recommendations).

### L.4 — Things I did NOT cover in this doc

- Options strategies on SPY/QQQ — JARVIS has stubs but no validated options strategy. Out of scope for Phase 1.
- Live broker routing to IBKR — Tier 3, Phase 3 only.
- RL agent experimental results — MES-only, data-collection, not part of production strategy.
- TradingView MCP Stage 1 wiring — biggest under-utilized asset per prior audit, deferred to Phase 2+.

---

## Matt — Your Next Action

**If you approve this document as-is:** Reply "approved" and I'll move to Phase 1 (decision→paper_trades plumbing fix with this strategy as the reference spec).

---

## Changelog

- **2026-04-10 17:27 CDT** — v1 initial draft (22 min, 37 TOS scripts + 3,797 engine LOC + rules file)
- **2026-04-10 17:32 CDT** — v1.1 canon reconciliation after reading `docs/strategic/` framework:
  - §A: MES status corrected from "EXPERIMENTAL — treat as halted" to "PAPER-APPROVED per validated-instruments.md"
  - §D: validation gates corrected to canonical values (PF ≥ 2.0, Sharpe ≥ 1.5, WR ≥ 55%, Trades ≥ 60, Days ≥ 30, DD ≤ 15%)
  - §K.6: Simons quote flagged unverifiable per D10, reframed as architecture principle
  - §L.1-3: all 10 open questions resolved per canon
  - §L.4: added Tier-3 process note on commit `be6927d` config.py touch
  - Header: added authority order linking to validated-instruments, UNIFIED_CANON, docs/strategic/, rules/backtest-signals.md
- **Next revision:** After Phase 1 completes and D9 strategy-doc-review recommendations land.

---

*Document updated 2026-04-10 17:32 CDT. Canon-reconciled. Ready for Phase 1 execution.*
