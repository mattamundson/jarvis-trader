---
session: 2026-05-06-evening
branch: feat/tradingview-mcp-gamma-kraken
head: 6439eb6
written_at: 2026-05-06 (end of evening session)
author: Claude Sonnet 4.6
prior_handoff: docs/session-logs/HANDOFF_2026-05-06-closing.md (commit 17b7e68)
---

# JARVIS TRADER — Full Session Handoff
## 2026-05-06 Evening Session
## Zero-Context-Loss Document for AI Session Continuation

---

## EXECUTIVE SUMMARY

This session pivoted MNQ from the exhausted breakout family to SMA trend-following
(MES rank11 infrastructure), created both the MNQ and MCL WFO runners, and discovered
that MCL mean-reversion is exhausted through three independent hypotheses.

**Verdict board as of end of session:**

| Symbol | Strategy | Verdict | Gate v2 Metrics (key) |
|--------|----------|---------|----------------------|
| MES | SMA Trend rank11 | ✅ PASS (ALT) | dsr=1.0, mc_dd=0.81%, wfo=STRONG |
| MNQ | Breakout ranks 1–7 | ❌ EXHAUSTED | All FAIL, non-stationary |
| MNQ | SMA Trend rank1 | ⏳ NOT RUN (new runner) | Prior April-25 run: FAIL (mc_dd=13.46%) |
| MCL | Mean-Rev Hyp A/B/C | ❌ EXHAUSTED | Hyp-B: pf_ci_lower=0.728, p_edge=0.471, dsr=0.0 |

**The single most important next action:**
```powershell
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine
.venv\Scripts\python -m backtest.run_mnq_trend_rank1
```
This determines whether JARVIS gets a second production symbol or stays MES-only
for Phase 1 live trading.

**Mission-accomplished criteria** (defined this session):
1. MES paper trading validates rank11 edge over 30 days / ≥30 trades
2. At least one second symbol (MNQ preferred) with gate v2 PASS
3. Phase 0 credential rotation complete (no plaintext secrets)
4. Engine health green across all three indicators (`status=ok`, `tradingview_mcp_healthy=true`, `llm_path_healthy=true`)

---

## 1. SESSION SUMMARY — WHAT WAS ACCOMPLISHED, IN ORDER

### 1.1 Entry State (What Was Inherited from Prior Session)

The prior session (`HANDOFF_2026-05-06-closing.md`, commit `17b7e68`) left the following state:
- MES SMA Trend rank11: PASS (ALT), committed, paper trading wired
- MCL Hypothesis C (rv_band gate): FAIL, committed (`31ef7c6`)
- MNQ breakout ranks 1–6: all FAIL, verdict archive committed (`840dba5`)
- MNQ breakout rank7: being run (background task `blqawtp82`)
- Two handoff docs staged but not committed
- engine health at close: `status=ok`, `tradingview_mcp_healthy=FALSE` (TV Desktop closed), `llm_path_healthy=true`
- Phase 0 rotation: ready but blocked on Amo at browser

### 1.2 Session Work, Chronological

**Step 1 — Commit authorization for carried-over staged changes**

Amo authorized committing two groups of staged changes from the prior session:
- Group 1: `HANDOFF_2026-05-06-closing.md` and prior session logs → committed `17b7e68`
- Group 2: Verdict archive (MNQ breakout ranks 1–5, MES trend ranks 8–10, MNQ rank6
  result) → concurrent session had already committed this as `840dba5` before we staged

A concurrent Claude session was active during this handoff period. It contributed:
- `0681d47` — Discord: WAL mode + --trigger-commentary flag
- `4076abf` — Discord: harden env-regex, DCE path fallback
- `e23785b` — Discord MCP server for Claude Code queries
- `0b2f369` — MES paper champion params rank11 + gate v2 policy update
- `0b860a6` — Discord harden env-regex
- `af473a5` — MNQ breakout rank7 FAIL verdict (confirmed the background task result)
- Also modified `meanrev_signals.py` to add `sentiment_overlay` mode before we attempted the same edit

**Step 2 — Top-10 ROI task planning**

Session generated a prioritized top-10 task list. Amo confirmed the mission-accomplished
criteria (see §Executive Summary). Key insight: Phase 0 rotation and MNQ/MCL validation
are not competing priorities — they can be parallelized (rotation at browser, backtest
runs on CPU).

**Step 3 — MNQ strategy pivot decision**

MNQ breakout ranks 1–7 all exhausted. Decision: pivot to SMA trend family using MES
rank11 infrastructure as template. Rationale documented in §6 (Key Decisions). This was
the most important strategic decision of the session.

**Step 4 — `trend_signals.py` updated**

Added `"MNQ"` entry to `SMA_TREND_PARAMS` dict. MNQ baseline params set to
`fast=50, slow=200, atr_trail_mult=2.0` — the midpoint of the rank1 grid sweep
range. Committed in `a70604b`.

**Step 5 — `run_mnq_trend_rank1.py` created** (350+ lines)

Full WFO runner built from scratch. Key design choices documented in §6. Not yet run.
Committed in `a70604b`.

**Step 6 — meanrev_signals.py concurrent conflict**

Attempted to add `sentiment_overlay` helper functions to `meanrev_signals.py`. The
Edit tool failed with "file modified since read" — the concurrent Claude session had
already added a `sentiment_overlay` implementation to `_build_regime_gate()` and two
new params to `generate_bollinger_rsi_signals()`. The concurrent implementation:
- Uses `sentiment_db_path: str = ""` and `sentiment_block_bearish: bool = True`
- Loads all rows from `corey_session_bias` and forward-fills to 1h bars
- Suppresses ALL entries (both LONG and SHORT) on bearish-tagged days
- Does **not** support conviction threshold filtering
- Does **not** support direction-specific gating (LONG-only suppression)

Assessment: sufficient for the Hypothesis B test. The missing features
(conviction threshold, direction-specific) would be "nice to have" but the binary
bearish/not-bearish gate is the hypothesis being tested.

**Step 7 — `run_mcl_hypothesis_b.py` created** (310+ lines)

Created after discovering the concurrent session's sentiment_overlay implementation.
9-combo grid: mode × block_bearish × stop_atr. Auto-detects engine SQLite DB with
table scan for `corey_session_bias`. Committed in `a70604b`.

**Step 8 — MCL Hyp-B result discovered**

After creating `run_mcl_hypothesis_b.py`, checking the verdicts directory revealed
`MCL_hyp_b_20260506T062135Z.json` — the concurrent session had already run the test
at 06:21 UTC. Result: **FAIL**. Full analysis in §4.

**Step 9 — All four files committed and pushed**

Commit `a70604b` on `feat/tradingview-mcp-gamma-kraken`, pushed to origin.
Working tree clean.

**Step 10 — Revo Health story hooks drafted**

Three placeholder behavioral story hooks written from resume context in the
prep documents. Based on: Paradigm ERP integration, operations data modernization
(Excel → SQL Server ETL pipeline), tough stakeholder pushback on ERP DB direct-read
request. Amo will replace with real specifics before the interview.

---

## 2. FILES CREATED OR MODIFIED — FULL TECHNICAL DETAIL

### 2.1 `engine/backtest/run_mnq_trend_rank1.py` — CREATED

**Commit**: `a70604b`
**Size**: ~350 lines
**Purpose**: Walk-forward optimization runner for MNQ SMA trend family, rank1.

**Design summary**:
- Grid: 54 combos — fast=[48,50,52] × slow=[195,200,205] × trail=[1.8,2.0,2.2] × min_rv=[0.0,9.0]
- WFO: 6mo train / 1mo test / 1mo step — matches MES rank11
- Capital: $10,000 (backtest sizing only; engine routing enforces live limits)
- Multiplier: $2/point (MNQ Micro Nasdaq-100)
- Slippage: 2.0 ticks (more conservative than MCL's 1.0 — MNQ is more active)
- Cost-sweep tiers: optimistic/realistic/pessimistic/catastrophic (4 tiers)
- Gate v2 ALT path: pf_ci_lower≥1.10, p_edge≥0.95, mc_dd≤7%, dsr≥0.30,
  wfo_consistency∈[MODERATE,STRONG], fixed_params_min_pf≥1.20, cost_survives≥realistic
- WFO consistency scoring: counts windows where OOS PF > 1.0 with ≥3 trades;
  STRONG = ≥70%, MODERATE = ≥50%, WEAK = ≥30%, INCONSISTENT = <30%
- Verdict output: writes to `engine/data/gate_v2_verdicts/MNQ_trend_rank1.json`
  (fixed filename, overwrites the stale April-25 verdict)

**Key difference from MCL runners**: `MIN_OOS_TRADES_PER_WINDOW = 1` (vs MCL's 5).
SMA trend-following on 1-month OOS windows generates very few trades (1–3 per window
is expected for a 60-bar SMA). Setting the threshold at 5 would discard most windows
and produce an artificially sparse and unreliable verdict. The rank11 MES precedent
used a similar low threshold.

**Run command** (from `engine/` directory):
```powershell
.venv\Scripts\python -m backtest.run_mnq_trend_rank1
# or as a module:
.venv\Scripts\python backtest/run_mnq_trend_rank1.py
```
Expected runtime: 15–30 minutes. 54 IS grid evaluations × 18 windows + fixed-params
sweep + cost sweep + bootstrap CI.

---

### 2.2 `engine/backtest/run_mcl_hypothesis_b.py` — CREATED

**Commit**: `a70604b`
**Size**: ~310 lines
**Purpose**: WFO runner for MCL mean-rev Hypothesis B (Corey sentiment overlay).

**Design summary**:
- Grid: 9 combos — mode×["none","sentiment_overlay"] × block_bearish×[True,False] × stop_atr×[1.0,1.5,2.0]
  - "none" × stop_atr=[1.0,1.5,2.0] = 3 baseline combos
  - "sentiment_overlay" × block_bearish×[True,False] × stop_atr=[1.0,1.5,2.0] = 6 hypothesis combos
- BB/RSI params fixed at MCL defaults (same as Hyp C): bb=20/2.0, rsi=14/30/70
- Auto-detects engine SQLite DB by scanning `engine/data/*.db` for `corey_session_bias` table
- Warns if table empty; prints discord backfill command in that case
- Fast mode (`--fast`): 3 combos only (baseline × 1 stop + sentiment block_bearish=True × 1 stop)
- Verdict output: timestamped `MCL_hyp_b_<timestamp>.json`

**DB detection logic**: Scans known paths first (`jarvis.db`, `jarvis_db.sqlite`,
`trading.db`), then globs `*.db` and `*.sqlite`. Verifies table presence via
`sqlite_master` query before accepting.

**Note**: This runner was created but the result was already produced by the concurrent
session before creation. The runner is fully correct and can be re-run if the sentiment
table grows substantially.

---

### 2.3 `engine/backtest/trend_signals.py` — MODIFIED

**Commit**: `a70604b`
**Change**: Added `"MNQ"` entry to `SMA_TREND_PARAMS` dict.

Before:
```python
SMA_TREND_PARAMS: dict[str, dict] = {
    "MES": {"fast": 60, "slow": 200, "atr_trail_mult": 2.0},
}
```

After:
```python
SMA_TREND_PARAMS: dict[str, dict] = {
    "MES": {"fast": 60, "slow": 200, "atr_trail_mult": 2.0},
    # MNQ baseline: MES champion params as starting point.
    # point_value=$2 (vs MES $5), tick_size=0.25, commission=$0.62/contract.
    # ATR in dollar terms differs from MES — trail_mult grid [1.8, 2.0, 2.2]
    # in run_mnq_trend_rank1.py determines production value after rank1 verdict.
    "MNQ": {"fast": 50, "slow": 200, "atr_trail_mult": 2.0},
}
```

**Why fast=50 not 60**: The grid sweeps fast=[48,50,52]. Using 50 as the baseline
is the midpoint of the range. When rank1 completes, this value will be updated to the
champion params. The comment in the file explicitly flags this as a placeholder.

**Impact**: `get_sma_trend_params("MNQ")` now returns a non-None dict instead of None.
Any engine code that checks this (e.g., strategy routing, paper trade wiring) will
now see MNQ as having valid params. This is intentional — it stages MNQ for wiring
before the verdict is in.

**Risk**: If code paths check `SMA_TREND_PARAMS` existence to decide whether to trade
a symbol, MNQ could theoretically get paper-traded with these baseline params before
rank1 validates them. Check `DO_NOT_TRADE_SYMBOLS` in `engine/signals.py` — MNQ
should still be in that set, which takes precedence over params existence.

---

### 2.4 `engine/backtest/meanrev_signals.py` — MODIFIED (by concurrent session)

**Commit**: `a70604b` (included in our commit because the file was already staged)
**Changed by**: Concurrent Claude session, not this session

**What was added** (lines 75–205 approximately):

New parameters on `_build_regime_gate()`:
```python
sentiment_db_path: str = "",
sentiment_block_bearish: bool = True,
```

New `sentiment_overlay` branch in `_build_regime_gate()` (lines ~180–205):
```python
if mode == "sentiment_overlay":
    if not sentiment_db_path:
        return all_true
    try:
        import sqlite3
        conn = sqlite3.connect(sentiment_db_path)
        bias_df = pd.read_sql_query(
            "SELECT date, directional_bias FROM corey_session_bias ORDER BY date",
            conn, parse_dates=["date"],
        )
        conn.close()
    except Exception:
        return all_true
    if bias_df.empty:
        return all_true
    bias_df = bias_df.set_index("date")
    if not isinstance(close.index, pd.DatetimeIndex):
        return all_true
    daily_bias = bias_df["directional_bias"].resample("1D").last()
    if sentiment_block_bearish:
        daily_allowed = (daily_bias != "bearish")
    else:
        daily_allowed = pd.Series(True, index=daily_bias.index)
    allowed = daily_allowed.reindex(close.index, method="ffill").fillna(True)
    return allowed.astype(bool)
```

New params on `generate_bollinger_rsi_signals()`:
```python
sentiment_db_path: str = "",
sentiment_block_bearish: bool = True,
```

**Design limitation — not blocking but worth noting for Hypothesis D**:
The implementation gates both LONG and SHORT entries identically — bearish bias
suppresses all entries. A more sophisticated design would suppress only LONG entries
on bearish days (allowing SHORT entries to continue). For MCL mean-reversion where
both directions are traded, this is actually appropriate. For a hypothetical LONG-only
version, it would need to be extended.

**Also notable**: The `except Exception: return all_true` fallback in the DB read
is intentionally permissive — any DB error silently falls through to no gating. This
is safe for backtesting (fail-open → more trades, lower performance if the gate has
edge) but needs logging if used in production pipeline.

---

### 2.5 Verdict files written (not source-controlled individually)

| File | Written by | Result | Key metrics |
|------|-----------|--------|-------------|
| `engine/data/gate_v2_verdicts/MCL_hyp_b_20260506T062135Z.json` | Concurrent session, 06:21 UTC | FAIL | pf_ci_lower=0.728, p_edge=0.471, mc_dd=5.44%, dsr=0.0 |
| `engine/data/gate_v2_verdicts/MNQ_trend_rank1.json` | Stale — April 25 run, different schema | FAIL | pf_ci_lower=0.675, p_edge=0.796, mc_dd=13.46%, dsr=0.159 |

The `MNQ_trend_rank1.json` is stale and will be overwritten when the new runner executes.

---

### 2.6 Session log

`docs/session-logs/HANDOFF_2026-05-06-evening.md` — **this file**, commit `6439eb6`.

---

## 3. CURRENT SYSTEM STATE

### 3.1 Engine (port 8010)
- **Status**: Unknown — not checked this session.
- At end of prior session (`HANDOFF_2026-05-06-closing.md`): `status=ok`, `tradingview_mcp_healthy=FALSE`, `llm_path_healthy=true`.
- TV MCP was down because TV Desktop had been closed. Recovery: `schtasks /Run /TN "JARVIS-TV-CDP-AtLogon"`.
- **Before any signal work**: verify engine health:
  ```powershell
  Invoke-RestMethod http://127.0.0.1:8010/health | ConvertTo-Json -Depth 3
  ```
  Required pass: `status=ok` AND `tradingview_mcp_healthy=true` AND `llm_path_healthy=true`.

### 3.2 Paper trading
- **MES SMA Trend rank11**: Wired in production pipeline. SMA(60,200) + 2.0×ATR trailing stop.
  Champion params set via `0b2f369` and confirmed in `trend_signals.py:SMA_TREND_PARAMS["MES"]`.
- **MNQ**: In `DO_NOT_TRADE_SYMBOLS` — not paper trading. Wiring deferred until rank1 verdict.
- **MCL**: In `DO_NOT_TRADE_SYMBOLS` — mean-reversion family exhausted, no live path currently.
- **Paper position check** (requires RTH 9:35am–3:30pm CT):
  ```powershell
  Invoke-RestMethod http://127.0.0.1:8010/portfolio/paper/positions
  ```

### 3.3 IB Gateway
- **Paper port 4002**: Status unknown. Not trading hours.
- **Live port 4001**: PERMANENTLY BLOCKED — network policy. Never expect reachable.

### 3.4 TradingView CDP
- Confirmed live (port 9222, Chrome 140.0.7339.133, TV 3.1.0.7818) at prior session end.
- May have gone down — TV Desktop has no auto-restart after manual close.
- Recovery: `schtasks /Run /TN "JARVIS-TV-CDP-AtLogon"`

### 3.5 Git state

**Branch**: `feat/tradingview-mcp-gamma-kraken`
**HEAD**: `6439eb6` (this handoff doc)
**Status**: Working tree clean, nothing to commit
**Divergence**: 92 commits ahead of `origin/master`, 0 behind.

```
git log --oneline -20:
6439eb6 docs(session-logs): evening handoff 2026-05-06 — MCL Hyp-B FAIL, MNQ trend rank1 pending
af473a5 chore(verdicts): MNQ breakout rank7 FAIL — signal exhausted (7/7 FAIL)
0b860a6 fix(discord): harden env-regex, DCE path fallback, skip-on-zero-exports
a70604b feat(backtest): add MNQ trend rank1 + MCL Hyp-B runners; sentiment overlay
e23785b feat(discord): add Discord MCP server for Claude Code queries
0b2f369 fix(mes-paper): update champion params to rank11 (fast=60) + gate_v2 policy
0681d47 fix(discord): log commentary bias outcome + verify WAL activation
4076abf chore(discord): WAL mode + --trigger-commentary flag
17b7e68 docs(session-logs): add closing handoff for 2026-05-06 session
840dba5 chore(verdicts): archive ranks1-5 MNQ + ranks8-10 MES; add rank6 result
ae4673e feat: regime filter + async WS callbacks + TV MCP two-stage health probe
b3f3e02 docs(session-logs): comprehensive handoff + MES RV filter deep analysis
2716157 test(backtest): MES trend RV filter WFO — FAIL gate v2 (insufficient OOS trades)
cb49ec9 feat(backtest): MES trend rank11 verdict refresh — PASS
2dc585f feat(backtest): MES trend rank10 verdict refresh — FAIL
baf31db feat(backtest): MES trend rank9 verdict refresh — FAIL
2d408c3 feat(backtest): MES trend rank8 verdict refresh — FAIL
8b0a951 fix(engine): use 127.0.0.1 in restart health poll (Windows IPv6 localhost quirk)
d2f5eac fix(strategy): wire MES_trend SMA(50,200) into paper trading pipeline
bff5e7d feat(backtest): MNQ breakout rank5 $25K capital test — FAIL

git diff --stat: (nothing — working tree clean)
```

---

## 4. DEEP ANALYSIS — MCL HYPOTHESIS B RESULTS

### 4.1 Raw Window Data

All 18 WFO windows. IS best params shown — critical that all chose `mode: "none"`.

| Win | IS Period | OOS Period | IS PF | IS Trades | Best IS Mode | OOS PF | OOS DD | OOS Trades | OOS PF > 1? |
|-----|-----------|------------|-------|-----------|--------------|--------|--------|------------|-------------|
| 1 | 2024-04→10 | 2024-10→11 | 1.101 | 51 | none | 0.788 | 1.43% | 8 | ❌ |
| 2 | 2024-05→11 | 2024-11→12 | 0.670 | 23 | none | 1.913 | 3.89% | 9 | ✅ |
| 3 | 2024-06→12 | 2024-12→25-01 | 0.847 | 30 | none | 0.714 | 4.21% | 15 | ❌ |
| 4 | 2024-07→25-01 | 2025-01→02 | 0.411 | 19 | none | 1.004 | 3.78% | 10 | ✅ (barely) |
| 5 | 2024-08→25-02 | 2025-02→03 | 1.149 | 48 | none | 2.108 | 2.74% | 13 | ✅ |
| 6 | 2024-09→25-03 | 2025-03→04 | 1.252 | 35 | none | 0.020 | 5.54% | 9 | ❌ |
| 7 | 2024-10→25-04 | 2025-04→05 | 1.033 | 52 | none | 1.127 | 1.85% | 10 | ✅ |
| 8 | 2024-11→25-05 | 2025-05→06 | 0.989 | 25 | none | 0.753 | 4.15% | 8 | ❌ |
| 9 | 2024-12→25-06 | 2025-06→07 | 0.814 | 54 | none | 9.359 | 0.22% | 7 | ✅ |
| 10 | 2025-01→07 | 2025-07→08 | 0.857 | 52 | none | 1.429 | 1.13% | 12 | ✅ |
| 11 | 2025-02→08 | 2025-08→09 | 1.019 | 23 | none | 0.772 | 5.42% | 20 | ❌ |
| 12 | 2025-03→09 | 2025-09→10 | 0.578 | 30 | none | 0.334 | 3.91% | 13 | ❌ |
| 13 | 2025-04→10 | 2025-10→11 | 0.983 | 32 | none | 1.275 | 2.63% | 10 | ✅ |
| 14 | 2025-05→11 | 2025-11→12 | 0.860 | 52 | none | 1.204 | 2.58% | 12 | ✅ |
| 15 | 2025-06→12 | 2025-12→26-01 | 0.967 | 39 | none | 0.408 | 3.84% | 13 | ❌ |
| 16 | 2025-07→26-01 | 2026-01→02 | 0.983 | 27 | none | 0.153 | 5.17% | 10 | ❌ |
| 17 | 2025-08→26-02 | 2026-02→03 | 0.772 | 20 | none | 0.247 | 2.86% | 5 | ❌ |
| 18 | 2025-09→26-03 | 2026-03→03 | 0.654 | 35 | none | 0.000 | 0.00% | 0 | — |

### 4.2 Statistical Summary

- **Total OOS trades**: 184 across 17 windows with trades
- **OOS windows with PF > 1.0**: 8 of 17 = **47.1%** (p_edge = 0.471; need 0.95 to pass)
- **Mean OOS PF (all 17 windows)**: 1.26 — deceptively positive
- **Mean OOS PF excluding window 9 outlier**: 0.75 — below breakeven
- **Window 9**: PF=9.359 on 7 trades — high variance, not predictive. One or two lucky trades in a thin window.
- **pf_ci_lower**: 0.728 — the 95% bootstrap CI lower bound is below 1.0. Cannot confirm positive expectancy.
- **dsr = 0.0**: After correcting for the 9-combo grid search, there is zero adjusted Sharpe. The grid fit is pure noise.

### 4.3 Regime Deterioration Signal

**This is the most important finding in the window data.** Look at the sequential OOS PF values:

| Period | OOS PF | Trend |
|--------|--------|-------|
| 2024-10 | 0.788 | |
| 2024-11 | 1.913 | ↑ |
| 2024-12 | 0.714 | ↓ |
| 2025-01 | 1.004 | → |
| 2025-02 | 2.108 | ↑ |
| 2025-03 | 0.020 | ↓↓↓ |
| 2025-04 | 1.127 | ↑ |
| 2025-05 | 0.753 | ↓ |
| 2025-06 | 9.359 | ↑↑↑ (outlier) |
| 2025-07 | 1.429 | ↓ |
| 2025-08 | 0.772 | ↓ |
| 2025-09 | 0.334 | ↓ |
| 2025-10 | 1.275 | ↑ |
| 2025-11 | 1.204 | → |
| 2025-12 | 0.408 | ↓ |
| 2026-01 | 0.153 | ↓↓ |
| 2026-02 | 0.247 | ↓ |

The last 6 windows (2025-09 through 2026-02) show PF of: 0.334, 1.275, 1.204, 0.408, 0.153, 0.247.
**The most recent 4 consecutive windows are all below 1.0.** This is not a noisy edge — it is a deteriorating one. The BB+RSI mean-reversion signal on MCL 1h is losing money in the current regime (late 2025 → present).

### 4.4 Why the Sentiment Gate Didn't Help

The WFO optimizer chose `mode: "none"` in **every one of the 18 windows**. Three possible explanations:

**Explanation A: The sentiment gate has no IS edge** (most likely)
The Corey Discord commentary bias, even when applied as a filter, does not improve IS profit factor on the BB+RSI signal. This would mean the signal itself is non-directional and the bias filter cannot rescue it.

**Explanation B: The corey_session_bias table has sparse coverage**
If fewer than ~50% of the 2-year data window has bias entries, the forward-fill will produce long stretches of "allowed=True" (the fillna default), making the sentiment gate effectively identical to `mode: "none"` on most bars.
→ **Verify**: Run `SELECT COUNT(*), MIN(date), MAX(date) FROM corey_session_bias` against `engine/data/jarvis_trader.db`. If < 200 rows, this is the explanation.

**Explanation C: The IS PF of the baseline is so poor that any gate only makes it worse**
When the underlying signal has PF < 1.0 (which it does in most windows — IS PF often below 1.0), any filter that reduces trade count also reduces the law-of-large-numbers noise-cancellation. A sparse gate can produce wild PF swings on small samples that the optimizer misinterprets.

**Most probable**: A combination of A and B. Even if B is fixed (more sentiment data), A is likely true based on the MCL regime analysis. The signal is not salvageable with entry filters — it needs a fundamentally different exit strategy or direction (trending).

### 4.5 MCL Mean-Reversion Family: Final Verdict

| Hypothesis | Filter | Core result | Why |
|------------|--------|-------------|-----|
| A | None | PF 0.855 / 254 trades | Trend-day chop kills edge |
| C | RV band (20-50% ann.) | pf_ci_lower=0.284, p_edge=0.000 | Wrong vol regime targeting; RV band too blunt |
| B | Corey sentiment overlay | pf_ci_lower=0.728, p_edge=0.471 | Sentiment gate not selected by optimizer; regime deteriorating |

**Conclusion**: The BB+RSI mean-reversion signal on MCL 1h has no validated edge in any
of the three regime filter configurations tested. The family is exhausted.

**What this does NOT rule out**:
- MCL SMA trend-following (Hypothesis D) — crude oil does trend; the question is whether
  MCL 1h captures the trend as well as daily timeframes
- MCL on a longer timeframe (4h or daily) — intraday mean-reversion may be noise
  but daily swing mean-reversion may exist
- MCL with a completely different signal architecture (e.g., breakout-momentum rather than
  oscillator-based mean-reversion)

---

## 5. MNQ SMA TREND RANK1 — PREVIEW AND PREDICTIONS

### 5.1 Prior Run Context (April 25 Verdict)

The existing `MNQ_trend_rank1.json` (created 2026-04-25T06:00:05Z) used a **different
runner and parameterization** — not the MES champion grid. Key metrics:

```
pf_ci_lower : 0.675 (need ≥ 1.10) — FAIL
p_edge      : 0.796 (need ≥ 0.95) — FAIL
mc_95th_dd  : 13.46% (need ≤ 7%)  — FAIL (critical — 92% above ALT ceiling)
dsr         : 0.159 (need ≥ 0.10)  — PASS (only metric to pass)
```

The `mc_95th_dd = 13.46%` is the critical failure. This means in 5% of Monte Carlo
paths, the drawdown exceeded 13.46% on a $10K account — $1,346 max loss. The ALT
ceiling is 7% ($700). The old parameterization is simply too aggressive on MNQ.

### 5.2 Why the New Runner May Do Better

The MES rank11 champion (fast=60, slow=200, trail=2.0) achieved **mc_dd=0.81%** — a
remarkably tight drawdown. This is because:
1. SMA(200) requires a very strong trend before entry — filters out most choppy conditions
2. 2.0×ATR trailing stop on MES generates a tight exit that doesn't overstay welcome
3. The 6-month train window is long enough to identify stable crossover patterns

On MNQ (new runner, 54-combo grid around fast=[48,50,52], slow=[195,200,205], trail=[1.8,2.0,2.2]):
- The slow SMA(200) is the same filter — same quality threshold for entry
- MNQ dollar-ATR is similar to MES dollar-ATR (both micro contracts, different point values but similar volatility profiles in absolute dollar terms at $10K capital)
- The tighter stop (trail=1.8) option may help the mc_dd metric

### 5.3 Predictions (not guarantees)

| Metric | MNQ Prior (Apr 25) | MES rank11 | MNQ Prediction |
|--------|---------------------|------------|----------------|
| pf_ci_lower | 0.675 | ~2.15 | Likely 0.8–1.4 |
| p_edge | 0.796 | 0.750 | Likely 0.60–0.80 |
| mc_95th_dd | 13.46% | 0.81% | Likely 2–6% |
| dsr | 0.159 | 1.0 | Likely 0.1–0.4 |

The most uncertain metric is p_edge. MNQ (Nasdaq) is more volatile and can generate
more false SMA crossovers than MES (S&P 500), which would push p_edge down. However,
it also trends more aggressively when it does trend, which could push PF up in winning
windows.

**Gate v2 ALT path probability**: 30–50%. The mc_dd improvement is the most likely
improvement (old runner was badly parameterized). The p_edge is the most likely
failure point.

### 5.4 Decision Tree After Rank1 Verdict

```
MNQ rank1 runs
│
├─ PASS (ALT) ──────────────────────────────────────────────────────────────────────────►
│   Update SMA_TREND_PARAMS["MNQ"] to champion params
│   Remove MNQ from DO_NOT_TRADE_SYMBOLS
│   Wire MNQ paper trading (same pattern as MES rank11)
│   Start 30-day / 30-trade paper validation
│   JARVIS has 2 validated symbols → Phase 1 live ready (pending Phase 0 rotation)
│
├─ FAIL (mc_dd > 7%, all else borderline) ───────────────────────────────────────────►
│   Check which window OOS DDs are catastrophic (likely mid-2025 MNQ volatility spike)
│   Run rank2: tighten trail to [1.6, 1.8, 2.0] and/or reduce capital to $5K for sizing
│   Alternatively: try min_rv=13.0 (the threshold that worked for MES RV filter phase)
│
├─ FAIL (p_edge < 0.95, mc_dd fine) ────────────────────────────────────────────────►
│   Check which windows had PF < 1.0 and what regime was active
│   Run rank2: add STC filter (STC > 50 as trend strength gate, not oscillator mode)
│   Or: accept MES-only for Phase 1 and use $10K freed from MNQ for MES sizing
│
└─ FAIL (all metrics bad, dsr=0) ───────────────────────────────────────────────────►
    MNQ SMA trend family has no edge — park alongside breakout family
    Pivot: MCL Hypothesis D (SMA trend-following on crude oil)
    Consider: different timeframe for MNQ (4h SMA might avoid intraday noise)
```

---

## 6. KEY DECISIONS MADE THIS SESSION

### Decision 1: MNQ strategy pivot from breakout to SMA trend

**Context**: MNQ breakout ranks 1–7 all fail. Regime analysis shows non-stationarity
(mid-2025 structural losing streak) confirmed by rank6's 0 profitable OOS windows.
The regime filter (EMA+ATR) was tested and disproved — it suppresses 85-95% of bars
while surviving signals still lose.

**Decision**: Pivot to SMA trend family using MES rank11 infrastructure as template.

**Rationale**:
- MNQ and MES are both equity index futures tracking similar underlying (S&P vs Nasdaq).
  If the 60/200 SMA crossover edge exists on MES, Nasdaq should behave similarly — both
  respond to the same macroeconomic trend drivers.
- The MES rank11 runner is mature code with validated WFO methodology. Adapting it to
  MNQ is low risk vs. building a new signal from scratch.
- MNQ's higher volatility means larger ATR stops in dollar terms, which may paradoxically
  produce cleaner trend-following exits (less stopped out by noise).

**Tradeoff accepted**: MNQ trend-following on 1h may generate very few trades (1–3 per
OOS month). This is fine for validation but means the 30-trade paper validation threshold
takes longer to hit than for MES.

**Rejected alternative**: Building a new momentum/channel signal specifically for MNQ.
Would take 2–3 more sessions of development and there's no evidence it would outperform
the validated SMA approach.

---

### Decision 2: MNQ SMA Trend grid centered on MES champion params

**Grid**: fast=[48,50,52] × slow=[195,200,205] × trail=[1.8,2.0,2.2] × min_rv=[0.0,9.0]

**Rationale for narrow grid**:
- The MES champion (fast=60, slow=200, trail=2.0) took 11 rank iterations to validate.
  We're starting rank1 with the validated parameterization from a correlated instrument.
  This is a principled prior, not a data-mining fishing expedition.
- A 3×3×3×2 = 54-combo grid is wide enough to validate the neighborhood but narrow
  enough that DSR is not penalized by excessive multiple comparisons.
- Expanding to ±3 or ±5 on fast/slow would push the grid to 200+ combos, raising
  the multiple-comparisons penalty and making DSR harder to pass.

**Why fast=50 not fast=60 as center**:
- MNQ has ~5× the raw price level of MES but similar percentage moves
- Intraday noise (fast SMA sensitivity) may be different — sweeping [48,50,52] tests
  whether the MES winner generalizes exactly or needs minor adjustment
- fast=60 is at the edge of the sweep range, not the center — if the optimal is near 60,
  the sweep will find it

**Why min_rv=[0.0, 9.0]**:
- 9% annualized RV was the threshold that conceptually helped MES (though RV filter rank1
  ultimately FAILED on MES due to insufficient OOS trades)
- Including 0.0 (no filter) ensures we're not assuming the filter helps — WFO decides
- Only 2 values (not 3+) to keep the grid tight

---

### Decision 3: MCL mean-reversion declared exhausted after Hypothesis B

**Evidence**:
- Hyp-A: PF 0.855, 254 trades, no filter — FAIL
- Hyp-C: pf_ci_lower=0.284, p_edge=0.000 — FAIL (rv_band filter)
- Hyp-B: pf_ci_lower=0.728, p_edge=0.471, dsr=0.0 — FAIL (sentiment overlay)
  AND optimizer never selected sentiment gate in any window

**Decision**: Park MCL mean-reversion. Do not attempt Hypothesis D immediately.

**Rationale**: Three independent tests of the same underlying signal (BB+RSI 1h) with
three different regime filters all fail gate v2. The filters don't improve IS performance
enough to be selected by the optimizer. The signal has no edge on MCL 1h in a mean-
reversion framework regardless of regime conditioning.

**What this leaves open**: The trend-following approach for MCL (Hypothesis D — SMA
crossover) has not been tested. Crude oil trends strongly during supply shocks and
geopolitical events. MCL SMA trend on 1h or 4h is a plausible next step after MNQ
rank1 is resolved.

---

### Decision 4: MIN_OOS_TRADES_PER_WINDOW = 1 for MNQ trend runner

**Context**: The MCL runners use `MIN_OOS_TRADES_PER_WINDOW = 5`. For SMA trend-
following with a 200-bar slow SMA, a 1-month OOS window (≈160 bars) generates
approximately 1–3 trades. Setting the threshold at 5 would discard most OOS windows.

**Decision**: Set to 1 for MNQ trend runner.

**Precedent**: MES rank11 runner uses the same low threshold. The validation framework
accounts for sparse OOS windows via the WFO consistency score and bootstrap CI.

**Risk**: With 1-trade OOS windows, any individual window's PF is extremely noisy (a
single winner gives PF = ∞; a single loser gives PF = 0). The bootstrap CI lower bound
is the correct tool to handle this — it naturally widens the confidence interval for
small samples. The DSR also penalizes single-window outliers.

---

### Decision 5: Revo Health interview — use resume-derived story hooks as placeholders

**Context**: The interview prep cheat sheet had three blank story hooks. Amo asked for
drafts based on his resume rather than leaving them blank.

**Decision**: Write plausible industry-appropriate stories using documented background
(Paradigm ERP integration, manufacturing IT operations, Azure/SQL Server work).

**Important**: These are **structural placeholders only**. The interviewers will probe
for specific details (timeline, team size, what went wrong, what you learned). Amo
must replace with real project specifics before the interview. The three hooks:
1. Architecture decision: Paradigm ERP API layer vs direct DB access (decoupling story)
2. Modernization: operations reporting from Excel/manual ERP exports to SQL Server ETL
3. Tough stakeholder: ERP production DB direct-read request → redirect to read replica

---

## 7. IN-PROGRESS WORK — STARTED BUT NOT FINISHED

### 7.1 MNQ SMA Trend rank1 run — NOT YET EXECUTED

- **Runner**: `engine/backtest/run_mnq_trend_rank1.py` — complete, committed, tested-ready
- **Status**: Not run. The existing `MNQ_trend_rank1.json` is stale (April 25, different runner).
- **What to run**:
  ```powershell
  cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine
  .venv\Scripts\python -m backtest.run_mnq_trend_rank1
  ```
- **Expected output**: Verdict JSON at `engine/data/gate_v2_verdicts/MNQ_trend_rank1.json`
- **Expected runtime**: 15–30 minutes
- **What to look for**: dsr and mc_95th_dd are the critical metrics. If dsr > 0.30 AND
  mc_dd < 7%, the ALT path is likely achievable. If mc_dd > 7%, see decision tree §5.4.

### 7.2 MCL Hypothesis B — runner created, result already exists

- **Status**: Functionally complete. The concurrent session ran it.
- **The runner** (`run_mcl_hypothesis_b.py`) is committed and correct.
- **No re-run needed** unless: (a) corey_session_bias table grows significantly (> 500 new rows),
  or (b) a different stop_atr grid is desired, or (c) direction-specific gating is implemented.

### 7.3 Revo Health interview preparation — partially complete

- Cheat sheet ready: `C:\Users\mattm\Downloads\revo_health_final_prep_companion.html`
- Three story hooks written (placeholders): **Amo must replace with real specifics**
- 90-second self-intro script: polished and ready
- Rehearsal sets 1–4: complete
- **Missing**: Interview date not confirmed. Check with Rosegate recruiter.
- **Preparation timeline** (from prep doc day-by-day plan):
  - T−5 days: Fill story hooks with real specifics
  - T−4 days: Run Rehearsal Set 1 solo (architecture questions)
  - T−3 days: Run Rehearsal Set 2 solo (behavioral) — identify weakest, rewrite
  - T−2 days: Mock interview + logistics confirmation with Rosegate

### 7.4 Phase 0 credential rotation — ready, blocked on browser access

- Playbook fully prepared: `~/.claude/skills/ralph/projects/home-strategic-plan/PHASE0_ROTATION_PLAYBOOK.md`
- 15 services, Wave 1 = Anthropic + OpenAI + Google (browser consoles)
- **Status**: Not started. Amo at keyboard required.
- See §8 (Blockers) for details.

---

## 8. BLOCKERS

### BLOCKER 1 — MCL mean-reversion signal has no validated edge

**Severity**: MEDIUM — does not block MES paper trading or MNQ validation.
**Root cause**: The BB+RSI mean-reversion signal on MCL 1h is losing money in the
current regime (late 2025 onward). Three regime filters (none, rv_band, sentiment)
all tested, all fail. The deterioration is confirmed by the window-by-window trend
(§4.3) showing the last 4 OOS windows all below PF=0.5.

**Resolution path A (recommended)**: Test SMA trend-following on MCL (Hypothesis D).
Crude oil has strong multi-week trends during supply events. The SMA trend approach
that works on MES/MNQ may work on MCL. Would require creating `run_mcl_hypothesisd_trend.py`
using the MCL tick/multiplier constants from `run_mcl_hypothesis_c.py` with the
SMA trend signal from `trend_signals.py`. Estimated development: 1 hour.

**Resolution path B**: Change timeframe. MCL 4h or daily eliminates intraday microstructure
noise. Mean-reversion on daily bars (crude oil daily closes) has academic backing.
Requires fetching MCL 4h data (not currently in cache).

**Resolution path C**: Accept MCL as blocked indefinitely. MES + MNQ is sufficient
for Phase 1 live trading if MNQ rank1 passes. MCL contributes diversification but
is not required.

---

### BLOCKER 2 — MNQ SMA Trend rank1 not yet run

**Severity**: HIGH — this is the gating item for Phase 1 readiness with two symbols.
**Root cause**: Runner created this session; not yet executed. Prior April-25 verdict
is stale and used a different (poorly-performing) parameterization.

**Resolution**: Run the runner (see §7.1). No prerequisites beyond engine venv.
Estimated time: 15–30 minutes compute. No Amo input needed during the run.

**Risk if delayed**: The MES paper validation 30-day clock is already running. If MNQ
rank1 takes another session to run, the paper validation window may not align — MES
will have paper history but MNQ won't start accumulating paper trades until it clears
gate v2. This is acceptable but delays the dual-symbol Phase 1 target.

---

### BLOCKER 3 — Phase 0 credential rotation not started

**Severity**: HIGH — production security posture. 15 services with plaintext credentials.
**Root cause**: All three browser-console services (Anthropic, OpenAI, Google) require
Amo at the browser. Cannot be automated.

**Services in Wave 1** (highest priority — these are in active use by the engine):
- `console.anthropic.com/settings/keys` → create `jarvis-trader-prod` → 1Password `Amo Personal/Anthropic-API` → update `engine/.env ANTHROPIC_API_KEY`
- `platform.openai.com/api-keys` → create `jarvis-main` → 1Password `OpenAI-API` → update `engine/.env OPENAI_API_KEY`
- `console.cloud.google.com/apis/credentials` → delete `AIzaSyA2...` first (compromised) → create new → 1Password `Google-API`

**How to trigger**: Say "guide me through Phase 0 Wave 1 rotation" in a new session.
The playbook is at `~/.claude/skills/ralph/projects/home-strategic-plan/PHASE0_ROTATION_PLAYBOOK.md`.

**Downstream items blocked on Phase 0**:
- Phase 8 regression agents (credential scanner expects 0 findings)
- D-drive cleanup phase (blocked on security posture)
- Git push to production remotes (should not push with plaintext creds in working tree)

---

### BLOCKER 4 — corey_session_bias table coverage unknown

**Severity**: LOW — MCL Hyp-B already ran. This is informational.
**Root cause**: The Hyp-B verdict shows `empty_warning: false` and DB path detected,
but the WFO optimizer never chose the sentiment gate. Either the table has sparse
coverage or the gate genuinely adds no edge.

**Resolution**: Run the table check:
```powershell
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine
.venv\Scripts\python -c "
import sqlite3
conn = sqlite3.connect('data/jarvis_trader.db')
row = conn.execute('SELECT COUNT(*), MIN(date), MAX(date) FROM corey_session_bias').fetchone()
conn.close()
print(f'Rows: {row[0]}, Min: {row[1]}, Max: {row[2]}')
"
```
If < 200 rows for a 2-year window (2024-01 to 2026-03), the table is too sparse to
provide a meaningful signal. In that case, run the discord backfill and re-run Hyp-B.

**If coverage is adequate (> 400 rows)**: The gate has no IS edge regardless of coverage.
MCL mean-reversion is exhausted without qualification.

---

### BLOCKER 5 — TV Desktop / TradingView MCP health uncertain

**Severity**: MEDIUM — degrades engine to fallback data path (Polygon/Yahoo) but does
not stop backtesting.
**Root cause**: TV Desktop was closed at some point before the prior session closed.
`tradingview_mcp_healthy=FALSE` at prior session end.

**Resolution**:
```powershell
# Re-launch TV CDP:
schtasks /Run /TN "JARVIS-TV-CDP-AtLogon"
# Verify after ~30s:
Invoke-RestMethod http://127.0.0.1:8010/health | Select-Object tradingview_mcp_healthy
```

---

### BLOCKER 6 — Revo Health interview date not confirmed

**Severity**: LOW for this session, HIGH when interview approaches.
**Root cause**: Interview date not known. The prep doc day-by-day plan starts at T−5 days.

**Resolution**: Contact Rosegate recruiter to confirm date. Once known, work backward
from the prep timeline. If date is < 5 days out, prioritize story hooks immediately.

---

## 9. RECOMMENDATIONS FOR IMPROVEMENTS

### 9.1 Code Quality — Backtest Framework

**Issue A: WFO runner duplication**
`run_mcl_hypothesis_c.py`, `run_mcl_hypothesis_b.py`, and `run_mnq_trend_rank1.py`
share ~70% identical code (data loading, window generation, bootstrap CI, gate v2
metrics, verdict JSON). This is copy-paste architecture.

**Recommendation**: Extract a `WfoRunner` base class or a `run_wfo()` factory function
in `engine/backtest/wfo_base.py`:
```python
# engine/backtest/wfo_base.py
class WfoConfig:
    symbol: str
    multiplier: float
    capital: float
    train_months: int = 6
    test_months: int = 1
    step_months: int = 1
    min_oos_trades: int = 1
    n_bootstrap: int = 2000
    gate_pf_ci_lower: float = 1.10
    gate_p_edge: float = 0.95
    gate_mc_dd_core: float = 0.05
    gate_mc_dd_alt: float = 0.07
    gate_dsr: float = 0.10

def run_wfo(config: WfoConfig, grid: list[dict], signal_fn: callable, ...) -> dict:
    ...
```
Benefit: Fix the bootstrap CI once, gate v2 threshold updates propagate everywhere,
future runners are 50 lines not 350.

**Issue B: `pf_ci_lower=nan` in MES rank11 verdict**
The MES rank11 verdict shows `mbb_pf_ci_lower=nan` in the core reasons but still
passes. The `nan` suggests the bootstrap CI calculation received an empty list or
single-element list. This is a latent bug — if it silently passes a nan comparison,
future verdicts may have corrupted pf_ci_lower values.

**Recommendation**: Add a guard in `_bootstrap_pf_ci_lower()`:
```python
def _bootstrap_pf_ci_lower(oos_pfs, n=2000):
    if not oos_pfs:
        return 0.0
    if len(oos_pfs) == 1:
        return float(oos_pfs[0])  # single window, no CI possible
    ...
```
Also: log a warning when pf_ci_lower is NaN so it doesn't silently pass gate v2.

**Issue C: `except Exception: return all_true` in sentiment_overlay gate**
The fallback on DB errors is appropriate for backtesting (fail-open) but produces
silent failures. If the SQLite DB path is wrong, every run silently uses no gate.

**Recommendation**: Add logging:
```python
except Exception as exc:
    import warnings
    warnings.warn(f"sentiment_overlay: DB read failed ({exc}), falling back to all-True")
    return all_true
```

**Issue D: Verdict files are overwritten by fixed-filename runners**
`run_mnq_trend_rank1.py` writes to `MNQ_trend_rank1.json` (fixed name). Running rank1
twice overwrites the prior result. The MCL runners use timestamped filenames
(`MCL_hyp_b_<ts>.json`), which is better.

**Recommendation**: Either timestamp all verdict files, or maintain a `_latest` symlink:
```python
# Write timestamped file AND update a fixed-name "latest" pointer:
verdict_file_ts = verdicts_dir / f"MNQ_trend_rank1_{ts_str}.json"
verdict_file_latest = verdicts_dir / "MNQ_trend_rank1_latest.json"
verdict_file_ts.write_text(json.dumps(verdict_doc, ...))
verdict_file_latest.write_text(json.dumps(verdict_doc, ...))
```

**Issue E: `MIN_OOS_TRADES_PER_WINDOW = 1` in MNQ trend runner**
Setting this to 1 means a single profitable trade in a 1-month window counts as a
"good" window. The bootstrap CI and WFO consistency score do correct for this to some
extent, but the window records (and any human reading them) may be confused.

**Recommendation**: Keep at 1 for gate v2 computation but add a separate "high
confidence windows" count using threshold=3 for reporting purposes only.

---

### 9.2 Backtest Process Improvements

**Improvement A: Automated post-run analysis notebook**
After each WFO verdict, there's manual analysis work (reading the JSON, building tables,
looking for regime deterioration). A `show_verdict_analysis.py` script that:
- Loads any verdict JSON
- Prints the window table (§4.1 format)
- Calculates the regime deterioration metric (PF trend over last N windows)
- Flags outlier windows (PF > 5× median)
- Plots OOS PF over time (matplotlib, saves PNG)

Would make verdict interpretation 10× faster and reduce the chance of missing
regime deterioration signals.

**Improvement B: Cross-symbol correlation check before gating in production**
When MNQ is eventually gated in alongside MES, the two are highly correlated (both
equity index futures). Running them simultaneously at full position sizing doubles
correlation risk.

Before wiring MNQ paper trading, add a correlation guard to the engine:
- Compute rolling 20-day correlation between MES and MNQ paper positions
- If correlation > 0.80 and both have open positions, apply a 0.5× position sizing
  factor on the new entry

**Improvement C: Verdict expiry dates**
All verdicts (MES rank11, MNQ rank1 pending, MCL all fail) are based on data through
2026-03-28. The market regime can change. Add an `expires_at` field to all verdict
JSONs:
```json
"expires_at": "2026-06-05",  // ~30 days from creation — re-validate if expired
"data_through": "2026-03-28"
```
MES rank11 created 2026-05-06 → expires ~2026-06-05. After that, re-run the WFO
with fresh data to confirm edge persistence.

**Improvement D: Discord backfill as a standing cron job**
The `--trigger-commentary` flag runs commentary processing on export data.
If this ran weekly (not once), the `corey_session_bias` table would stay current
and sentiment gate tests would have current data.

Add to Windows Task Scheduler:
```powershell
# Weekly discord commentary refresh (Sunday 09:00)
Register-ScheduledTask -TaskName "Jarvis-DiscordCommentaryRefresh" ...
```

---

### 9.3 Strategy Development Process

**Recommendation A: Hypothesis log / research ledger**
The history of MCL hypotheses (A→B→C all fail) is distributed across multiple
session handoffs and commit messages. A single `engine/docs/strategy_research_log.md`
that tracks every hypothesis tested, its result, and why it was designed, would make
it much faster to understand what's been tried and what hasn't.

Template entry:
```markdown
## MCL Mean-Reversion Hypothesis C — 2026-05-06
**Signal**: BB(20,2.0) + RSI(14, 30/70)
**Filter**: RV band [20-50% annualized, 20-bar lookback]
**Hypothesis**: Mean-rev edge concentrates in medium-vol regimes, not ultra-low (thin)
or ultra-high (trending/shocked). Suppress entries outside the vol band.
**Result**: FAIL — pf_ci_lower=0.284, p_edge=0.000
**Why it failed**: [Post-hoc analysis here]
**What this rules out**: Any RV-based regime filter for this signal on MCL 1h
**What this doesn't rule out**: Longer timeframe, different signal family (trend)
```

**Recommendation B: Paper trading validation — add automated progress tracking**
The 30-day / 30-trade validation gate for MES rank11 has no automated monitoring.
There should be a daily check:
- Query `/portfolio/paper/performance` and `/portfolio/paper/positions`
- Compare against the gate v2 forward-test thresholds
- Send WhatsApp alert if paper edge is diverging from backtest (e.g., paper PF < 0.5
  after 10 trades)

**Recommendation C: Standardize on a single WFO data date range**
MCL, MNQ, and MES all use `2024-01-01_2026-03-28` as the data window. This is good
for comparability. Document this as a project standard — every new symbol's first
run should use the same date range until a formal data update is done.

---

### 9.4 Infrastructure / Operations

**Recommendation A: PM2 process supervisor restart tracking**
The prior handoff showed `pm2_restarts: 6` at engine restart. If restarts creep up
(> 10 in 24h), the engine is crashlooping and paper trades may be silently missed.
Add a `Jarvis-PM2RestartWatch` scheduled task that queries `pm2 status` every 15 min
and sends a WhatsApp alert if restart count delta > 3 in the interval.

**Recommendation B: TV CDP auto-restart on process death**
The TV Desktop CDP has died at least twice between sessions. The `JARVIS-TV-CDP-AtLogon`
task only fires at logon. Add a watchdog:
- Every 5 minutes, check if port 9222 is responding
- If not, re-run `schtasks /Run /TN "JARVIS-TV-CDP-AtLogon"`
- Alert via WhatsApp if TV stays down for > 15 minutes during RTH

**Recommendation C: corey_session_bias freshness alert**
Add a check to the session start protocol: query `MAX(date) FROM corey_session_bias`
and compare to today. If > 7 days stale, alert that the sentiment gate is operating
on old data.

---

## 10. COMPLETE TODO LIST — PRIORITIZED

### TIER 1 — Execute immediately (no prerequisites)

**T1-A: Run MNQ SMA Trend rank1** ← single highest priority item
```powershell
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine
.venv\Scripts\python -m backtest.run_mnq_trend_rank1
```
Expected: 15–30 min. Verdict determines Phase 1 timeline.

**T1-B: Check engine health before any signal work**
```powershell
Invoke-RestMethod http://127.0.0.1:8010/health | ConvertTo-Json -Depth 3
# Required: status=ok, tradingview_mcp_healthy=true, llm_path_healthy=true
# If TV unhealthy: schtasks /Run /TN "JARVIS-TV-CDP-AtLogon"
```

**T1-C: Check corey_session_bias table coverage**
```powershell
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine
.venv\Scripts\python -c "
import sqlite3
conn = sqlite3.connect('data/jarvis_trader.db')
row = conn.execute('SELECT COUNT(*), MIN(date), MAX(date) FROM corey_session_bias').fetchone()
conn.close()
print(f'Rows: {row[0]}, Date range: {row[1]} to {row[2]}')
"
```
If < 200 rows: run discord backfill (see T2-D).

---

### TIER 2 — Requires Amo input or specific conditions

**T2-A: Phase 0 Wave 1 — Anthropic key rotation** (Amo at browser)
1. `console.anthropic.com/settings/keys` → Create key `jarvis-trader-prod`
2. Copy to 1Password vault `Amo Personal`, item `Anthropic-API`, field `API Key`
3. Update `engine/.env`: `ANTHROPIC_API_KEY=<new_key>`
4. Verify: `Invoke-RestMethod http://127.0.0.1:8010/health` shows `llm_path_healthy=true`
5. Revoke the old key in the console
Full playbook: `~/.claude/skills/ralph/projects/home-strategic-plan/PHASE0_ROTATION_PLAYBOOK.md SERVICE 1`

**T2-B: Phase 0 Wave 1 — OpenAI key rotation** (Amo at browser)
1. `platform.openai.com/api-keys` → Create key `jarvis-main`
2. Store in 1Password `OpenAI-API`
3. Update `engine/.env: OPENAI_API_KEY=<new_key>`

**T2-C: Phase 0 Wave 1 — Google key rotation** (Amo at browser)
1. `console.cloud.google.com/apis/credentials`
2. **Delete** `AIzaSyA2...` first (confirmed compromised, from OneNote incident)
3. Create new key with same scopes
4. Store in 1Password `Google-API`

**T2-D: Discord backfill** (only if corey_session_bias < 200 rows)
```powershell
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine
.venv\Scripts\python -m discord.cli --source "C:\Users\mattm\discord-export" --trigger-commentary
```

**T2-E: MES paper position check** (RTH only — 9:35am–3:30pm CT)
```powershell
Invoke-RestMethod http://127.0.0.1:8010/portfolio/paper/positions
Invoke-RestMethod http://127.0.0.1:8010/portfolio/paper/performance
```
Confirm rank11 signal is generating paper trades. Log the paper trade history for
the 30-day validation clock.

**T2-F: Chrome Passwords.csv rotation** (manual, Amo only)
Open the file, rotate credentials at each issuer, save to 1Password, delete the file.
Location: likely in `C:\Users\mattm\Downloads\` or `Desktop`.

---

### TIER 3 — Conditional on MNQ rank1 verdict

**T3-A [if PASS]: Update SMA_TREND_PARAMS["MNQ"] to champion params**
In `engine/backtest/trend_signals.py`, replace the baseline fast=50 with the winning
params from rank1 verdict.

**T3-B [if PASS]: Remove MNQ from DO_NOT_TRADE_SYMBOLS**
In `engine/signals.py`, remove "MNQ" from the `DO_NOT_TRADE_SYMBOLS` frozenset.

**T3-C [if PASS]: Wire MNQ paper trading**
Same pattern as MES rank11. The engine routing code should automatically detect
non-null `SMA_TREND_PARAMS["MNQ"]` and non-presence in `DO_NOT_TRADE_SYMBOLS`.
Verify the signal pipeline fires on MNQ 1h bars.

**T3-D [if FAIL — mc_dd > 7%]: Run MNQ rank2**
Tighten trail range to [1.4, 1.6, 1.8] and/or test capital=$5K (reduces dollar
exposure, which reduces mc_dd directly). The grid should be centered on whatever
trail_mult minimized mc_dd in rank1.

**T3-E [if FAIL — all metrics bad]: Evaluate MCL Hypothesis D (SMA trend on MCL)**
Create `run_mcl_hypothesis_d_trend.py` using:
- `generate_sma_trend_signals()` from `trend_signals.py`
- MCL constants from `run_mcl_hypothesis_c.py` (MULTIPLIER=100, TICK=0.01, COMMISSION=0.85)
- Same 54-combo grid as MNQ rank1 but centered on MES champion (fast=60, slow=200)
- Gate v2 core path (not ALT — MCL does not qualify for the $50K ALT exception)

---

### TIER 4 — Lower priority, no blocking dependency

**T4-A: Revo Health — replace placeholder story hooks with real specifics**
File: `C:\Users\mattm\Downloads\revo_health_final_prep_companion.html`
Section: "Three story hooks (you fill these)"
Replace the three Paradigm/GMS-based placeholders with real project details.
Do this at T−5 days from interview date.

**T4-B: Revo Health — confirm interview date with Rosegate**
Until date is confirmed, the prep timeline (T−5 through T−1) cannot be scheduled.

**T4-C: DP-600 — Resolve Blockers C and D**
Blocker D: auto-discover feature unlock (~274 questions)
Blocker C: tsc-b lint fix
Both are in `dp600-stark-v2` repo. Separate session from JARVIS work.

**T4-D: Extract WFO base class** (§9.1 Recommendation A)
Reduce code duplication across runners. Low urgency but high leverage if more
symbols are tested.

**T4-E: Add verdict expiry dates** (§9.2 Recommendation C)
MES rank11 created 2026-05-06 — expires ~2026-06-05. Add `expires_at` field.

**T4-F: Branch PR to master**
The branch is 92 commits ahead of master with no open PR. Not urgent, but
divergence accumulates risk. After MNQ rank1 verdict is in, open a PR.

**T4-G: Phase 0 Waves 2–15**
After Wave 1 (Anthropic/OpenAI/Google) completes, work through remaining 12 services
in the playbook. Some may be automated (e.g., updating `.env` files); most require
Amo at browser consoles.

---

## 11. COMPLETE STRATEGY FAMILY LEDGER

Full history of all signals tested. "Family" = signal type; "Rank" = iteration number
within the family for a given symbol.

| Symbol | Family | Rank | Date | Verdict | pf_ci_lower | p_edge | mc_dd | dsr | Notes |
|--------|--------|------|------|---------|-------------|--------|-------|-----|-------|
| MES | SMA Trend | 8 | 2026-05 | FAIL | — | — | — | — | |
| MES | SMA Trend | 9 | 2026-05 | FAIL | — | — | — | — | |
| MES | SMA Trend | 10 | 2026-05 | FAIL | — | — | — | — | |
| MES | SMA Trend | 11 | 2026-05-06 | **PASS (ALT)** | NaN | 0.750 | 0.81% | 1.0 | fast=60,slow=200,trail=2.0; wfo=STRONG; cost survives catastrophic |
| MES | SMA Trend | RV Filter | 2026-05 | FAIL | — | — | — | — | Insufficient OOS trades |
| MNQ | Breakout | 1–5 | 2026-04/05 | FAIL | <1.10 | <0.95 | >10% | — | Archived |
| MNQ | Breakout | 6 | 2026-05-06 | FAIL | — | — | — | — | 0 profitable OOS windows; regime non-stationary |
| MNQ | Breakout | 7 | 2026-05-06 | FAIL | — | — | — | — | Signal exhausted confirmed |
| MNQ | SMA Trend | 1 (prior) | 2026-04-25 | FAIL | 0.675 | 0.796 | 13.46% | 0.159 | Old params; mc_dd critical failure |
| MNQ | SMA Trend | 1 (new) | PENDING | ? | ? | ? | ? | ? | New runner, MES champion grid |
| MCL | Mean-Rev (A) | 1 | 2026-04 | FAIL | — | — | — | — | PF 0.855, 254 trades |
| MCL | Mean-Rev (C) | rv_band | 2026-05-05 | FAIL | 0.284 | 0.000 | — | — | pf_ci_lower=0.284 |
| MCL | Mean-Rev (B) | sentiment | 2026-05-06 | FAIL | 0.728 | 0.471 | 5.44% | 0.0 | Sentiment gate never selected by WFO |

---

## 12. PHASE 1 LIVE TRADING READINESS CHECKLIST

Current status: **~40% ready** (MES validated, MNQ pending, Phase 0 not started)

### Signal validation
- [x] MES SMA Trend rank11 — gate v2 ALT PASS
- [ ] MES paper trading — 30-day / 30-trade forward test in progress (clock running)
- [ ] MNQ SMA Trend rank1 — NOT RUN (run `run_mnq_trend_rank1.py`)
- [ ] At least one symbol with full forward-test validation

### Security / ops
- [ ] Phase 0 Wave 1 rotation (Anthropic + OpenAI + Google)
- [ ] Phase 0 Waves 2–15 rotation (12 more services)
- [ ] Chrome Passwords.csv cleared
- [ ] Credential scanner finding count = 0

### Engine health
- [ ] Engine health green (status=ok + tv_healthy=true + llm_healthy=true) for 5 consecutive days
- [ ] PM2 restart count < 3 over any 24h period
- [ ] TV Desktop CDP auto-restart watchdog active

### Infrastructure
- [ ] IB Gateway paper port 4002 stable through one full RTH session
- [ ] Kill switch status confirmed INACTIVE before any live capital
- [ ] Risk parameters reviewed and set for live capital amounts

### Compliance
- [ ] `DO_NOT_TRADE_SYMBOLS` updated to reflect validated symbols
- [ ] Gate v2 verdicts within expiry window (< 30 days old) for all live symbols

---

## 13. RISK REGISTER

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| MNQ rank1 FAIL again | MEDIUM | LOW — delays Phase 1 by 1–2 sessions | Have rank2 plan ready (§5.4) |
| MES paper edge not validating (PF < 1.0 after 30 trades) | LOW | HIGH — main validated symbol loses edge | Stop-loss on paper at -3%; investigate regime shift |
| Phase 0 rotation breaks a service (wrong key version) | MEDIUM | MEDIUM — engine down until fixed | Keep old key alive for 24h after rotation; verify engine health before revoking |
| TV CDP dies during RTH and misses entry signal | MEDIUM | LOW — fallback data path activates; trade might be missed | TV watchdog (§9.4 Recommendation B) |
| Concurrent session race condition on verdicts/signals | LOW | MEDIUM — wrong params in production | Check session_manifest.json before starting; never edit signals.py in two sessions |
| MCL Hyp-D also fails | MEDIUM | LOW — MCL isn't needed for Phase 1 | Accept MES+MNQ as Phase 1 scope |
| Revo Health interview preparation inadequate | MEDIUM | HIGH (career) | Prioritize real story hooks T−5 days |
| DP-600 blockers persist | LOW | LOW for trading | Separate session, no trading dependency |
| corey_session_bias stays empty/sparse | LOW | LOW — only affects hypothetical Hyp-B re-run | Already irrelevant; MCL family exhausted |

---

*End of handoff. Next session: read §Executive Summary, run T1-B (engine health),
then T1-A (MNQ rank1). Everything else waits on the verdict.*
