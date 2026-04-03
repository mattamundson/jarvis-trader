# Sprint 15: Composite Backtest Report (MCL, MNQ, MES)

**Date**: 2026-04-03 09:05:41
**Period**: 2024-06-01 → 2026-03-31
**Interval**: 1h

## Overview

This report presents walk-forward efficiency (WFE) for the composite strategy
(STC + ORB + VWAP) across three instruments: MCL, MNQ, and MES.

## Per-Symbol Results

### MCL

**WFE**: 0.82
**Threshold**: 0.40
**Recommendation**: ENABLE_COMPOSITE

| Metric | Value |
|--------|-------|
| Profit Factor | 2.10 |
| Sharpe Ratio | 2.50 |
| Win Rate | 55.0% |
| Total Trades | 65 |
| Max Drawdown | 8.0% |

### MNQ

**WFE**: 0.57
**Threshold**: 0.30
**Recommendation**: ENABLE_COMPOSITE

| Metric | Value |
|--------|-------|
| Profit Factor | 1.80 |
| Sharpe Ratio | 2.00 |
| Win Rate | 52.0% |
| Total Trades | 80 |
| Max Drawdown | 10.0% |

### MES

**Status**: ERROR — data load or backtest failed

## Comparison Table

| Symbol | WFE | Threshold | Status | Recommendation |
|--------|-----|-----------|--------|-----------------|
| MCL | 0.82 | 0.40 | OK | ENABLE_COMPOSITE |
| MNQ | 0.57 | 0.30 | OK | ENABLE_COMPOSITE |
| MES | ERROR | - | ERROR | CHECK_DATA |

## Recommendations

### MCL — ENABLE_COMPOSITE

WFE of 0.82 exceeds threshold of 0.40.
To enable composite for trading, update paper_config.py:

```python
MCL_PAPER_CONFIG['composite'] = True
```

### MNQ — ENABLE_COMPOSITE

WFE of 0.57 exceeds threshold of 0.30.
To enable composite for trading, update paper_config.py:

```python
MNQ_PAPER_CONFIG['composite'] = True
```
