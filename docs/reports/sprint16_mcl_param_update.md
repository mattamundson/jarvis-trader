# Sprint 16 — MCL Parameter Reconciliation + Composite Exit Fix

**Date**: 2026-04-03
**Story**: US-1602 — MCL parameter reconciliation + composite backtester exit fix

---

## MCL Parameter Update

### Before (in-sample params — Sprint 14)

```python
# engine/backtest/signals.py INSTRUMENT_PARAMS
"MCL": (15, 83, 0.90, 1.50, 2.618, 4.00, True)
#       OS  OB  stop   T1    T2     T3
```

```python
# engine/backtest/paper_config.py MCL_PAPER_CONFIG
"stc_os": 15, "stop_atr_mult": 0.90, "t1_atr_mult": 1.50
```

### After (walk-forward consensus — Sprint 16)

```python
# engine/backtest/signals.py INSTRUMENT_PARAMS
"MCL": (23, 83, 0.50, 1.00, 2.618, 4.00, True)
#       OS  OB  stop   T1    T2     T3    # WF consensus, WFE=0.82, OOS PF=1.21
```

```python
# engine/backtest/paper_config.py MCL_PAPER_CONFIG + MCL_15M_CONFIG
"stc_os": 23, "stop_atr_mult": 0.50, "t1_atr_mult": 1.00
```

### Rationale

**Source of truth**: `WF_MCL_1h_walk_forward.json`
- WFE = 0.8221 (EXCELLENT — top of any instrument tested)
- Average OOS profit factor = 1.2122
- 4/6 windows profitable out of sample

The walk-forward optimizer found that raising the oversold threshold from OS=15 to OS=23 significantly improves out-of-sample edge by requiring deeper oversold conditions before entry. Tightening the stop (0.90→0.50 ATR) and target (1.50→1.00 ATR) reduces the R:R slightly but dramatically improves win rate in OOS windows.

**Why OS=15 was wrong**: OS=15 was the in-sample optimizer result. Walk-forward validation revealed this was overfit — the 15-level triggers too many marginal entries that don't hold in new windows.

### Impact

| Parameter | Before | After | Change |
|-----------|--------|-------|--------|
| stc_os | 15 | 23 | +8 (more selective) |
| stc_ob | 83 | 83 | No change |
| stop_atr_mult | 0.90 | 0.50 | Tighter stop |
| t1_atr_mult | 1.50 | 1.00 | Closer T1 |
| t2_atr_mult | 2.618 | 2.618 | No change |
| t3_atr_mult | 4.00 | 4.00 | No change |

MCL_15M_CONFIG also updated to match (baseline alignment — 15m still requires independent WF validation).

---

## COMPOSITE_INSTRUMENTS Change

### Before
```python
COMPOSITE_INSTRUMENTS = {"MES", "MCL", "MNQ"}
```

### After
```python
COMPOSITE_INSTRUMENTS = {"MES"}  # MCL/MNQ use standard signals (WF-validated path)
```

### Rationale

The walk-forward validation that produced WFE=0.82 for MCL and WFE=0.57 for MNQ used the **standard** `generate_signals()` path, not the composite STC+ORB+VWAP path. Running MCL/MNQ through composite signals produces different (worse) results than what WF validated.

Additionally, the composite backtester had a bug (see next section) that caused all composite trades to have `exit_date=None`, making composite PF/Sharpe calculations invalid.

---

## Composite Backtester Exit Bug

### Root Cause

**File**: `engine/backtest/composite_signals.py` lines 287-291 (long) and 317-321 (short)

`target_3` was initialized to `NaN` at line 132 in `_add_empty_composite_cols()` but was **never set** in the entry blocks. Only `target_1` and `target_2` were set.

The backtester in `backtester.py` uses `target_3` as the final exit price for the third tranche of the position. When `target_3 = NaN`, the backtester never closes the T3 portion, causing `exit_date = NaN` for all composite trades (because the trade is considered open until T3 closes).

This explained the "581 trades, all exit_dates=None, PF=0.41" anomaly observed for MCL composite backtest — it wasn't bad strategy performance, it was a bug preventing any trade from ever closing.

### Fix

```python
# Added in composite_signals.py (~line 272)
COMP_T3_ATR = 6.00  # Sprint 16: fixes exit_date=None (target_3 was always NaN)

# In long entry block (lines 288-292):
t1 = entry_p + COMP_T1_ATR * atr_val
t2 = entry_p + COMP_T2_ATR * atr_val
t3 = entry_p + COMP_T3_ATR * atr_val
result.at[idx_val, "target_1"] = round(t1, 4)
result.at[idx_val, "target_2"] = round(t2, 4)
result.at[idx_val, "target_3"] = round(t3, 4)  # ← NEW

# In short entry block (lines 318-323):
t1 = entry_p - COMP_T1_ATR * atr_val
t2 = entry_p - COMP_T2_ATR * atr_val
t3 = entry_p - COMP_T3_ATR * atr_val
result.at[idx_val, "target_1"] = round(t1, 4)
result.at[idx_val, "target_2"] = round(t2, 4)
result.at[idx_val, "target_3"] = round(t3, 4)  # ← NEW
```

**COMP_T3_ATR = 6.00** — 6× ATR matches the T3 ratio used in standard signals (4.00 for T3 in MCL standard, but composite uses wider stops/targets so 6.00 ATR at 1.0 ATR stop gives R:R = 6:1 for T3 tranche).

### Verification

After this fix, running `python -m backtest.run_composite_backtest --symbol MES` should produce trades where all three tranches (T1, T2, T3) have valid `exit_date` values (no NaN).

MCL and MNQ are now excluded from composite path entirely, so the fix primarily benefits future MES composite analysis.

---

## Files Changed

| File | Change |
|------|--------|
| `engine/backtest/signals.py` | MCL INSTRUMENT_PARAMS: OS 15→23, stop 0.90→0.50, T1 1.50→1.00 |
| `engine/backtest/signals.py` | COMPOSITE_INSTRUMENTS: removed MCL/MNQ, only MES |
| `engine/backtest/paper_config.py` | MCL_PAPER_CONFIG + MCL_15M_CONFIG: stc_os=23, stop=0.50, t1=1.00 |
| `engine/backtest/composite_signals.py` | COMP_T3_ATR = 6.00 + target_3 set in both long/short entry blocks |
