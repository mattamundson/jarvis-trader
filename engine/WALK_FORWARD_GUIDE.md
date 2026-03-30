# Walk-Forward Validation System

## Overview

Walk-forward validation is the gold standard for backtesting validation. Unlike traditional backtesting (which can overfit by optimizing parameters on historical data), walk-forward validation:

1. **Trains** on a historical window (e.g., 6 months of data)
2. **Tests** on the subsequent out-of-sample period (e.g., 2 months)
3. **Rolls forward** through time, repeating for each window
4. **Compares** in-sample (IS) performance vs. out-of-sample (OOS) performance
5. **Detects overfitting** via Walk-Forward Efficiency (WFE)

### Key Metric: Walk-Forward Efficiency (WFE)

```
WFE = Average OOS Sharpe Ratio / Average IS Sharpe Ratio
```

**Interpretation:**
- **WFE > 0.70** — Excellent (minimal overfitting, strategy likely generalizes well)
- **WFE 0.50–0.70** — Good (acceptable degradation, usable strategy)
- **WFE 0.30–0.50** — Marginal (significant overfitting, use with caution)
- **WFE < 0.30** — Poor (severe overfitting, likely unusable)

## Components

### 1. **WalkForwardValidator Class**
**File:** `engine/backtest/walk_forward.py`

Core class that orchestrates the rolling validation:

```python
from backtest.walk_forward import WalkForwardValidator

validator = WalkForwardValidator(
    train_months=6,      # Training window size
    test_months=3,       # Test window size
    step_months=3,       # How far to roll forward each iteration
)

result = validator.run(
    df=data_frame,
    symbol="SPY",
    multiplier=1.0,
    capital=100_000.0,
    fast=True,           # Use fast param grid (default)
    adaptive_regime=False,
    volume_filter=False,
    mtf_filter=False,
)
```

**Window Generation:**
- **Train:** 6 months of data to optimize parameters
- **Test:** 2 months of data (out-of-sample) to validate
- **Step:** Roll forward 2 months and repeat
- **Non-overlapping test periods** ensure true out-of-sample validation

**Example:**
```
Window 1: Train Jun-Nov 2024 → Test Dec 2024-Jan 2025
Window 2: Train Aug 2024-Jan 2025 → Test Feb-Mar 2025
Window 3: Train Oct 2024-Mar 2025 → Test Apr-May 2025
```

### 2. **CLI Entry Point**
**File:** `engine/backtest/run_walk_forward.py`

Simple wrapper for command-line execution:

```bash
cd engine
python -m backtest.run_walk_forward \
    --symbol SPY \
    --interval 1h \
    --train-months 6 \
    --test-months 2 \
    --start 2024-06-01 \
    --end 2026-03-27
```

### 3. **FastAPI Endpoint**
**File:** `engine/main.py`

REST API endpoint for walk-forward validation:

```bash
curl -X POST http://localhost:8010/backtest/walk-forward \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "SPY",
    "interval": "1h",
    "start": "2024-06-01",
    "end": "2026-03-27",
    "train_months": 6,
    "test_months": 2,
    "adaptive_regime": false,
    "volume_filter": false
  }'
```

### 4. **Results Output**
**Path:** `engine/backtest/results/WF_{symbol}_{interval}[_filters].json`

Example structure:
```json
{
  "symbol": "SPY",
  "interval": "1h",
  "generated": "2026-03-29T15:30:00",
  "summary": {
    "avg_is_return": 0.0845,
    "avg_oos_return": 0.0512,
    "wfe": 0.606,
    "avg_oos_sharpe": 1.523,
    "avg_oos_profit_factor": 1.84,
    "windows_profitable": 4,
    "total_windows": 5
  },
  "windows": [
    {
      "window": 1,
      "train_period": "2024-06 to 2024-11",
      "test_period": "2024-12 to 2025-01",
      "best_params": {
        "stc_oversold": 15,
        "stc_overbought": 88,
        "atr_stop_mult": 0.70,
        "atr_target_mult": 1.00,
        "regime_filter": true
      },
      "is_result": {
        "total_trades": 42,
        "win_rate": 0.571,
        "profit_factor": 1.92,
        "sharpe_ratio": 1.45,
        "total_return_pct": 0.0862,
        "max_drawdown_pct": 0.0324
      },
      "oos_result": {
        "total_trades": 8,
        "win_rate": 0.500,
        "profit_factor": 1.65,
        "sharpe_ratio": 0.92,
        "total_return_pct": 0.0485,
        "max_drawdown_pct": 0.0412
      }
    },
    ...
  ]
}
```

## Usage Guide

### Option 1: CLI (Simplest)

```bash
cd engine
.venv\Scripts\activate
python -m backtest.run_walk_forward --symbol MES --interval 1h --adaptive-regime
```

**Common Flags:**
- `--full-grid` — Use full parameter grid (slower, more thorough)
- `--adaptive-regime` — Use regime-adaptive STC thresholds
- `--volume-filter` — Block entries on low volume bars
- `--mtf-filter` — Apply multi-timeframe confirmation filter

### Option 2: Python API

```python
from backtest.walk_forward import WalkForwardValidator
from backtest.data_loader import BacktestDataLoader

# Load data
loader = BacktestDataLoader()
df = loader.load("SPY", "2024-06-01", "2026-03-27", "1h")

# Run validation
validator = WalkForwardValidator(train_months=6, test_months=3, step_months=3)
result = validator.run(
    df,
    "SPY",
    multiplier=1.0,
    fast=True,
    adaptive_regime=False,
)

# Access results
print(f"WFE: {result['summary']['wfe']:.3f}")
for window in result['windows']:
    print(f"Window {window['window']}: OOS Sharpe={window['oos_result'].sharpe_ratio:.2f}")
```

### Option 3: REST API

```python
import requests

response = requests.post(
    "http://localhost:8010/backtest/walk-forward",
    json={
        "symbol": "SPY",
        "interval": "1h",
        "start": "2024-06-01",
        "end": "2026-03-27",
        "train_months": 6,
        "test_months": 2,
        "adaptive_regime": False,
    }
)

result = response.json()
print(f"WFE: {result['summary']['wfe']}")
print(f"Results saved to: {result['results_file']}")
```

## Parameter Configuration

### Grid Search Parameters

The optimizer searches across:

**Fast Grid (default, 162 combinations):**
```python
FAST_GRID = {
    "stc_oversold":    [15, 19, 23],          # STC oversold threshold
    "stc_overbought":  [83, 88, 92],          # STC overbought threshold
    "atr_stop_mult":   [0.3, 0.5, 0.7],       # Stop loss ATR multiple
    "atr_target_mult": [1.0, 1.5, 2.0],       # Take-profit ATR multiple
    "regime_filter":   [True, False],          # Use regime filtering
}
# 3 × 3 × 3 × 3 × 2 = 162 combinations
```

**Full Grid (optional, slower):**
```python
PARAM_GRID = {
    "stc_oversold":    [15, 17, 19, 21, 23],
    "stc_overbought":  [83, 85, 88, 90, 92],
    "atr_stop_mult":   [0.3, 0.4, 0.5, 0.6, 0.7],
    "atr_target_mult": [0.8, 1.0, 1.2, 1.5, 2.0],
    "regime_filter":   [True, False],
}
# 5 × 5 × 5 × 5 × 2 = 2,500 combinations
```

### Window Configuration

**Default (6 months train, 3 months test):**
```
Best for: Balanced detection of gradual regime shifts
Trade-off: More windows but larger window size
```

**Aggressive (6 months train, 2 months test):**
```
Best for: More frequent validation, detect rapid overfitting
Trade-off: Fewer trades per window, noisier results
```

**Conservative (12 months train, 3 months test):**
```
Best for: Larger sample size, reduce noise
Trade-off: Fewer windows, slower to detect issues
```

## Interpreting Results

### Walk-Forward Efficiency Analysis

**Case 1: WFE = 0.65 (Good)**
```
IS Sharpe: 1.50
OOS Sharpe: 0.98
WFE: 0.65 ✓ GOOD

Interpretation:
- Strategy generalizes well to unseen data
- ~35% performance degradation is acceptable
- Parameters are reasonably robust
```

**Case 2: WFE = 0.25 (Poor)**
```
IS Sharpe: 2.00
OOS Sharpe: 0.50
WFE: 0.25 ✗ OVERFIT

Interpretation:
- Severe overfitting detected
- Parameters are brittle and don't generalize
- Consider: simpler model, more features, wider param ranges
```

### Parameter Stability

Check if optimal parameters vary significantly across windows:

```
Window 1 Best: STC_OB=88, Stop=0.70, T1=1.00
Window 2 Best: STC_OB=85, Stop=0.50, T1=1.50
Window 3 Best: STC_OB=92, Stop=0.70, T1=1.00
         ↓
Stability: POOR (STC_OB varies, Stop varies)
Action: Parameters are unstable; use safeguards
```

### Degradation Profile

Look for patterns in performance decay:

```
Window 1 OOS Return: +8.5%
Window 2 OOS Return: +6.2%
Window 3 OOS Return: -1.3%
Window 4 OOS Return: +4.8%
         ↓
Profile: Erratic (not consistent degradation)
Action: Investigate what changed in Window 3
```

## Advanced Usage

### 1. Adaptive Regime Mode

Enable regime-adaptive STC thresholds:

```bash
python -m backtest.run_walk_forward \
    --symbol MCL \
    --interval 1h \
    --adaptive-regime
```

This adjusts STC thresholds dynamically based on market regime (trending vs. ranging).

### 2. Volume Filter

Exclude entries on below-average volume:

```bash
python -m backtest.run_walk_forward \
    --symbol MGC \
    --interval 1d \
    --volume-filter
```

### 3. Multi-Timeframe Confirmation

Apply 4-hour confirmation filter to block counter-trend entries:

```bash
python -m backtest.run_walk_forward \
    --symbol MES \
    --interval 1h \
    --mtf-filter
```

### 4. Combined Filters

```bash
python -m backtest.run_walk_forward \
    --symbol SPY \
    --interval 1h \
    --adaptive-regime \
    --volume-filter \
    --mtf-filter \
    --full-grid
```

## Troubleshooting

### Issue: "Not enough data to form any windows"
**Cause:** Date range too short
**Solution:** Increase date range (need > train_months + 2×test_months)

### Issue: "Optimisation returned no valid results"
**Cause:** Parameter set produces no valid trades
**Solution:** Widen parameter ranges (use PARAM_GRID instead of FAST_GRID)

### Issue: High variance between windows
**Cause:** Small number of trades per window
**Solution:** Increase window sizes (e.g., 12-month train windows)

### Issue: Results not saving
**Cause:** Missing permissions on results directory
**Solution:** `mkdir -p engine/backtest/results && chmod 755 engine/backtest/results`

## Integration with Paper Trading

Paper trading uses walk-forward-validated parameters:

```python
# From backtest/paper_config.py
MGC_PAPER_CONFIG = {
    "symbol": "MGC",
    "interval": "1d",
    "stc_oversold": 15,           # From WF validation
    "stc_overbought": 88,         # From WF validation
    "atr_stop_mult": 0.30,        # From WF validation
    "atr_target_mult": 1.50,      # From WF validation
}
```

## Performance Benchmarks

**Typical execution times:**

| Data | Grid | Windows | Est. Time |
|------|------|---------|-----------|
| SPY 1h, 6 months | Fast | 2 | ~2 mins |
| MES 1h, 12 months | Fast | 3 | ~5 mins |
| MCL 1h, 24 months | Full | 4 | ~20 mins |
| Gold 1d, 24 months | Fast | 4 | ~3 mins |

## Next Steps

1. **Test the System:**
   ```bash
   python engine/test_walk_forward_system.py
   ```

2. **Run Validation for Your Symbol:**
   ```bash
   python -m backtest.run_walk_forward --symbol MES --interval 1h
   ```

3. **Review Results:**
   - Check `engine/backtest/results/WF_MES_1h_walk_forward.json`
   - Verify WFE > 0.50 for production use
   - Check parameter stability

4. **Deploy to Paper Trading:**
   - Use optimal parameters in `backtest/paper_config.py`
   - Run paper trades with validated parameters
   - Monitor real-world performance

## References

- **Original Paper:** Pardo, R. "The Evaluation and Optimization of Trading Strategies" (2008)
- **Modern Take:** Vince, R. "Algorithmic Trading" (2014)
- **Industry Standard:** Walk-forward validation is required by most institutional traders

---

**Questions?** Check `engine/JARVIS_TRADER_ANALYSIS_AND_RECOMMENDATIONS.md` for system context.
