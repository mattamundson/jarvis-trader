# JARVIS TRADER — Formal trading rules & strategy thesis

**Version:** 1.0  
**Date:** 2026-04-03  
**Canonical code:** [`engine/backtest/signals.py`](../../engine/backtest/signals.py), [`engine/backtest/composite_signals.py`](../../engine/backtest/composite_signals.py), [`engine/config.py`](../../engine/config.py)  
**Math reference:** [EQUATIONS.md](./EQUATIONS.md) — LaTeX-style formulas aligned to those modules.  
**Next review:** After 30-day paper milestone or any change to `INSTRUMENT_PARAMS` / safety limits.

---

## Table of contents

1. [Entry and exit rules](#1-entry-and-exit-rules)  
2. [Position sizing](#2-position-sizing)  
3. [Regime filters and layer flow](#3-regime-filters-and-layer-flow)  
4. [MCL vs MNQ](#4-mcl-vs-mnq)  
5. [Time-of-day and session policy](#5-time-of-day-and-session-policy)  
6. [Edge thesis and falsifiers](#6-edge-thesis-and-falsifiers)  
7. [Cross-check vs project docs](#7-cross-check-vs-claudemd--project-docs)

---

## 1. Entry and exit rules

### 1.1 Two signal paths (must not be conflated)

| Path | Symbols | Entry function | Role |
|------|---------|----------------|------|
| **Standard 5-layer** | All symbols not in composite set, and STC base math | `generate_signals()` in `signals.py` | Layer1–4 + per-symbol `INSTRUMENT_PARAMS` for STC OS/OB and ATR multiples |
| **Composite (Cohen-style)** | `MES`, `MCL`, `MNQ` only (`COMPOSITE_INSTRUMENTS`) | `generate_composite_signals()` in `composite_signals.py` | STC (**gated**) + ORB + VWAP, regime-weighted; **different** stops/targets than pure STC |

Routing: `generate_instrument_signals(df, symbol, **kwargs)` calls composite for MES/MCL/MNQ, else `generate_signals()`.

### 1.2 Standard path — every condition that yields `ENTRY_NOW`

All paths require **non-NEUTRAL bias** from `layer3_bias` except where noted. **Regime** is first adjusted by `regime_filter` (see §3).

**A. Exhausted regime**

- If `layer1_regime` is `EXHAUSTED` and `atr_consumed_pct > 90` and phase extended (`phase_val > 61.8` or `< -61.8`): signal `FADE_EXTREME` (not `ENTRY_NOW`).
- Otherwise in `EXHAUSTED`: `NO_TRADE`.

**B. Structure-aligned trend (buy side)**

- `structure_position == BUYER_CONTROL` (above VAH **and** above IB high)
- `bias` in `STRONG_BULL`, `LEAN_BULL`
- `regime == TRENDING_BULL`  
→ `ENTRY_NOW`

**C. Structure-aligned trend (sell side)**

- `structure_position == SELLER_CONTROL` (below VAL **and** below IB low)
- `bias` in `STRONG_BEAR`, `LEAN_BEAR`
- `regime == TRENDING_BEAR`  
→ `ENTRY_NOW`

**D. IB high breakout**

- `above_ib_high` true this bar, `prev_above_ib_high` false (first close above prior bar’s IB high proxy)
- `bias` in `STRONG_BULL`, `LEAN_BULL`  
→ `ENTRY_NOW`

**E. IB low breakdown**

- `below_ib_low` true, `structure_position == SELLER_CONTROL`, bearish bias  
→ `ENTRY_NOW`

**F. STC crossover (classic)**

- Long: `bias` in `STRONG_BULL`, `LEAN_BULL` **and** `stc_cross_up` (cross above oversold threshold).
- Short: `bias` in `STRONG_BEAR`, `LEAN_BEAR` **and** `stc_cross_down` (cross below overbought threshold).  
→ `ENTRY_NOW`

**Other labels (not immediate entries):** `WAIT_FOR_PULLBACK` (STC mid-zone 20–80), `NO_TRADE`, plus post-filters that **replace** `ENTRY_NOW`: `LOW_VOLUME_BLOCK`, `MTF_BLOCKED`, `NEWS_BLACKOUT`.

### 1.3 Composite path — `ENTRY_NOW` conditions

- **Volatile** `regime_type` (from `RegimeClassifier`): no entries; conflicting raw signals become `COMPOSITE_VOLATILE_BLOCK`.
- **STC gate:** `stc_cross_up` / `stc_cross_down` must be true for long/short respectively (ORB/VWAP only add score; they cannot enter alone).
- **Score:** `long_score` or `short_score` ≥ `entry_threshold` (default **0.35**), using regime weights: TRENDING STC 0.60 / ORB 0.30 / VWAP 0.10; RANGING STC 0.50 / ORB 0.20 / VWAP 0.30.
- **R:R filter:** `composite_rr` must be ≥ **`MIN_RR = 1.2`** (entries below that are forced to `NO_TRADE`).
- Composite sets **its own** stop/target ATR multiples: `COMP_STOP_ATR = 1.00`, `COMP_T1_ATR = 2.50`, `COMP_T2_ATR = 4.00` (not the same as `INSTRUMENT_PARAMS`).

### 1.4 Exit mechanics (stops, targets, EOD)

**Standard + composite (column semantics)**

- **Stop:** `stop_level` — long: `close - stop_atr * ATR`; short: `close + stop_atr * ATR` (composite uses fixed 1.0 ATR for its branch as above).
- **Targets:** `target_1`, `target_2`, `target_3` from `t1_atr`, `t2_atr`, `t3_atr` × ATR (composite fills T1/T2; T3 may carry through from STC base where applicable).

**Backtest engine** ([`engine/backtest/backtester.py`](../../engine/backtest/backtester.py)): processes stop/target hits bar-by-bar and **EOD close** at day boundary (`_check_eod_close`).

**Paper runner** ([`engine/backtest/paper_runner.py`](../../engine/backtest/paper_runner.py)): stop checked first; targets **scale out** (≈1/3 at T1, 1/2 of remainder at T2, rest at T3); **breakeven** stop after T1 hit.

**LLM pipeline** ([`engine/agents/pipeline.py`](../../engine/agents/pipeline.py)): does **not** recompute `signals.py` rows; `trade_decision` comes from agents (e.g. Technical analyst may expose `stop_price`, `limit_price`, `target_*`). Quantitative alignment is **best-effort**—operators should treat **`signals.py` + backtest** as canonical for rule formalization, and pipeline output as an overlay that must stay within [`engine/risk/safety_layer.py`](../../engine/risk/safety_layer.py) + `TradingConfig`.

### 1.5 Rules table (template + approved micros)

| Item | MNQ (standard via router) | MCL (standard via router) | Notes |
|------|---------------------------|---------------------------|--------|
| **Routing** | Composite if `generate_instrument_signals` | Composite if `generate_instrument_signals` | Both in `COMPOSITE_INSTRUMENTS` → composite path for **backtests** that call `generate_instrument_signals` |
| **STC OS / OB** | 15 / 92 | 15 / 83 | From `INSTRUMENT_PARAMS` when `symbol` passed into underlying `generate_signals` inside composite |
| **Stop (× ATR)** | 0.70 | 0.90 | Per-symbol; **not** universal 0.70 |
| **T1 / T2 / T3** | 1.00 / 1.80 / 2.618 | 1.50 / 2.618 / 4.00 | Long: below/above close per long/short rules |
| **Regime filter flag** | True (block EXHAUSTED/COMPRESSION as entries) | True | Overridden inside composite STC leg with `regime_filter=False` then composite applies its own VOLATILE block |
| **Invalidation** | NEUTRAL bias; EXHAUSTED (except fade); optional volume/MTF/news flags | Same | Composite adds score + R:R + STC gate |

*If your run uses **only** `generate_signals(symbol="MNQ")` without composite, use the MNQ row as pure 5-layer STC with composite-specific ORB/VWAP **off**.*

---

## 2. Position sizing

### 2.1 Layer 5 (`compute_position_size`)

**Inputs:** `bias`, `regime` (from **layer1** labels: `TRENDING_BULL`, `TRENDING_BEAR`, `RANGE_BOUND`, etc.), `structure_position` (`BUYER_CONTROL`, `SELLER_CONTROL`, `NEUTRAL_STRUCTURE`, …), `base_risk_pct`.

**Multipliers** (applied to `base_risk_pct`):

| Condition | Multiplier |
|-----------|------------|
| Strong bias + trending + directional structure | `SIZING_FULL` 1.00 |
| Strong bias + trending (any structure) | `SIZING_HIGH` 0.80 |
| Lean bias **or** not trending | `SIZING_HALF` 0.50 |
| Else | `SIZING_MIN` 0.25 |

**Used in:** [`paper_runner`](../../engine/backtest/paper_runner.py) / [`paper_tracker`](../../engine/backtest/paper_tracker.py) for **quantitative** paper paths—not automatically in LLM `final_quantity`.

### 2.2 Hard caps (`TradingConfig` + safety)

From [`engine/config.py`](../../engine/config.py): `MAX_POSITION_SIZE_PCT` (5%), `MAX_CONTRACTS_PER_INSTRUMENT` (2 micros), `MAX_SINGLE_ORDER_VALUE` ($5k), `MAX_MARGIN_UTILIZATION` (40%), `MAX_CORRELATED_EXPOSURE_PCT` (20%), consecutive-loss scaling thresholds (`CONSECUTIVE_LOSS_*`), `PRICE_COLLAR_PCT`, `MAX_ORDERS_PER_MINUTE`. **Enforcement** is in the hardcoded safety layer—not LLM.

### 2.3 Pipeline `final_quantity`

[`_resolve_final_action`](../../engine/agents/pipeline.py) takes quantity from **fund manager** (`contracts` / `quantity`) when risk approved; else from **trade decision**; default **0** on hold. So live/paper **LLM path** sizing is **agent-driven**, then clamped by safety. This is **mixed**: quantitative stack has Layer 5; pipeline has discretionary/structured agent output.

### 2.4 Gaps (documentation-only recommendations)

- **Single source of truth:** Either document that operators must align fund-manager contract count with `compute_position_size` output from the same bar, or add a future integration ticket to pass signal-row sizing into the pipeline.
- **Per-symbol max:** `MAX_CONTRACTS_PER_INSTRUMENT` is global—no MCL vs MNQ split in config today.

---

## 3. Regime filters and layer flow

### 3.1 Layer 1 (`layer1_regime`)

**Outputs:** `EXHAUSTED`, `COMPRESSION`, `TRENDING_BULL`, `TRENDING_BEAR`, `RANGE_BOUND`.

**Logic (simplified):** `atr_consumed_pct > 90` → `EXHAUSTED`; compression phase + low consumption → `COMPRESSION`; bullish/bearish EMA trend + phase + consumption bands → trending; else `RANGE_BOUND`.

**`regime_filter` in `generate_signals`:** When **True**, `EXHAUSTED` / `COMPRESSION` are **not** downgraded—`layer4_entry` still sees them (entries largely blocked in EXHAUSTED except fade). When **False**, those two are rewritten to `RANGE_BOUND` before `layer4_entry` (optimizer / composite STC leg behavior).

### 3.2 Layers 2–4 (operator view)

- **Layer 2** `layer2_structure`: auction proxy—VPOC/VAH/VAL/IB high-low from OHLCV; position `BUYER_CONTROL` / `SELLER_CONTROL` / `NEUTRAL_STRUCTURE`.
- **Layer 3** `layer3_bias`: votes across KAMA, STC signal, volume skew, EMA ribbon → `STRONG_*`, `LEAN_*`, `NEUTRAL`.
- **Layer 4** `layer4_entry`: combines regime + bias + structure + STC crosses per §1.2.

### 3.3 Optional gates in `generate_signals`

| Flag | Effect |
|------|--------|
| `adaptive_regime` | Per-bar STC OS/OB via `RegimeClassifier`; recomputes crosses |
| `volume_filter` | Low volume vs MA → `LOW_VOLUME_BLOCK` |
| `mtf_df` | MTF alignment → else `MTF_BLOCKED` |
| `news_blackout` | Economic calendar window → `NEWS_BLACKOUT` |

**Production/paper defaults:** Typical **hourly backtest and paper_runner** paths use symbol-specific params; **not all** flags are enabled globally—confirm each entrypoint (e.g. `main.py` intraday job passes explicit flags). LLM pipeline **does not** automatically apply these flags to agent reasoning.

### 3.4 Flow (onboarding)

```mermaid
flowchart TD
  bars[OHLCV_bars] --> indicators[compute_all_indicators]
  indicators --> L1[layer1_regime]
  indicators --> L2[layer2_structure]
  indicators --> L3[layer3_bias]
  L1 --> rf[regime_filter_optional]
  rf --> L4[layer4_entry]
  L2 --> L4
  L3 --> L4
  L4 --> post[volume_MTF_news_optional]
  post --> levels[stop_target_ATR_levels]
```

**Composite parallel flow:** `generate_composite_signals` → STC (`generate_signals` with `adaptive_regime=True`, `regime_filter=False`) + ORB + VWAP → weighted score → STC gate → R:R filter → VOLATILE block.

---

## 4. MCL vs MNQ

### 4.1 `INSTRUMENT_PARAMS` (from code)

| Symbol | STC_OS | STC_OB | Stop ATR | T1 | T2 | T3 | Regime filter |
|--------|--------|--------|-----------|----|----|-----|----------------|
| **MNQ** | 15 | 92 | 0.70 | 1.00 | 1.80 | 2.618 | True |
| **MCL** | 15 | 83 | 0.90 | 1.50 | 2.618 | 4.00 | True |

### 4.2 Economics narrative

- **MNQ:** Higher beta / noise; **wider STC OB (92)** and **tighter stop (0.70 ATR)** and **tighter T1 (1.00)** reflect Nasdaq microstructure and optimizer notes in-code (noise filtering).
- **MCL:** **Wider stop (0.90)** and **wider T1 (1.50)** match crude’s swing characteristics and documented R:R intent in comments.

**Intentional split:** Yes—parameters are **per-symbol research tuples**, not one-size-fits-all.

### 4.3 Validation / approval status (from root `CLAUDE.md`)

- **MCL 1h WFE 0.82 — APPROVED** (paper active).  
- **MNQ 1h WFE 0.57 — APPROVED** (paper active).  
- **MES** — strategy doc parameters exist but **DO NOT TRADE** per project status (overfit / gate failure).  
Align operator discipline with `CLAUDE.md` **Validated Instruments** table before enabling symbols in production configs.

### 4.4 Decision items

- Keep **split params** (recommended) vs converge templates only if new joint walk-forward justifies it.  
- Any change to `INSTRUMENT_PARAMS` requires backtest + WFE re-gate and safety review if sizing/limits touched.

---

## 5. Time-of-day and session policy

### 5.1 Scanner ([`signal_scanner.py`](../../engine/scanner/signal_scanner.py))

- **Futures week:** Sunday **5:00 PM CT** through Friday **4:00 PM CT** (loop uses approximate CT offset from UTC).
- **Saturday:** no scan.
- **RTH no-new-entry windows (ET, approximate offset UTC-5 in code):** no entries **9:30–9:35 ET**; no entries **3:45–4:00 PM ET** (last 15 minutes).

### 5.2 Signal layer vs scanner

- **`signals.py`** does **not** embed the same RTH first/last 15-minute windows; those apply when the **scanner** invokes the pipeline.
- **Manual** `POST /pipeline/run` or other callers can still run **without** those windows—**operational gap** to manage via SOP or future shared gate.

### 5.3 Session policy (proposal)

- **NY session** prioritized for micro equity index and crude liquidity; **Asia/London** left to discretionary pause unless data shows edge (document outcomes in paper journal).  
- **Config hook:** `SESSION_FLATTEN_TIME_ET` in `TradingConfig` (3:45 PM ET) aligns with flatten/risk culture—ensure scanner, paper, and live policies stay consistent over time.

---

## 6. Edge thesis and falsifiers

### 6.1 Thesis (one paragraph)

The stack combines **multi-factor confluence** (trend/phase/volume/structure/STC) to trade **directional continuation and controlled reversals** in liquid micro futures, with **explicit risk geometry** (ATR-scaled stops and targets) and **regime gating** to avoid trading exhaustion/compression blindly. **Composite** symbols add **independent confirmation** (ORB + VWAP) so entries are not driven by a single indicator. Edge is **statistical**: positive expectancy emerges from the interaction of selective entries, bounded loss per trade, and scaling rules—not from single-bar prediction.

### 6.2 Measurable checks

Project validation gates (from `CLAUDE.md`): e.g. **PF ≥ 2.0**, **Sharpe ≥ 1.5**, **WR ≥ 55%**, **≥ 60 trades**, **≥ 30 days**, **DD ≤ 15%** (paper validation targets—treat as north-star for formal sign-off).  
Per-symbol **WFE** and **halt list** (e.g. MES, MGC) are **hard gates** before promoting symbols.

### 6.3 What would falsify the thesis

- **Persistent WFE collapse** on approved symbols while in-sample stays strong (overfit).  
- **Live/paper divergence** beyond slippage/fees after controlled sample size.  
- **Risk-adjusted metrics** failing validation gates with no regime explanation.  
- **Kill switch / daily loss / drawdown** trips from strategy behavior rather than operational bugs (indicates edge not scaled to risk).

**References (no code changes here):** [`engine/risk/safety_layer.py`](../../engine/risk/safety_layer.py), `TradingConfig` kill/drawdown fields.

---

## 7. Cross-check vs CLAUDE.md / project docs

| Claim (typical summary) | This document / code | Verdict |
|-------------------------|----------------------|---------|
| STC OS=15, OB=83, ATR stop 0.70× | Defaults in `signals.py` module text use 15/83/0.70 for **generic** copy; **MNQ OB=92**, **MCL stop=0.90** in `INSTRUMENT_PARAMS` | **Nuance:** headline is **simplified**; approved micros use **table in §4.1** |
| 5-layer regime filter | Layers 1–4 explicit; Layer 5 is **sizing** not regime | **Agree** with framework naming; clarify Layer 5 = sizing |
| MES / validation | Params exist for MES in `INSTRUMENT_PARAMS` but **DO NOT TRADE** in CLAUDE | **Agree** — status overrides raw params |

---

*End of document.*
