# Walk-Forward Validation — Quick Reference

## One-Liners

### Run Walk-Forward for SPY (1-hour bars)
```bash
python -m backtest.run_walk_forward --symbol SPY --interval 1h
```

### Run for MES with Adaptive Regime
```bash
python -m backtest.run_walk_forward --symbol MES --interval 1h --adaptive-regime
```

### Run for MCL with Volume Filter
```bash
python -m backtest.run_walk_forward --symbol MCL --interval 1h --volume-filter
```

### Run for MGC (Gold) with All Filters
```bash
python -m backtest.run_walk_forward --symbol MGC --interval 1d --adaptive-regime --volume-filter --mtf-filter
```

### Use Full Parameter Grid (Slower, More Thorough)
```bash
python -m backtest.run_walk_forward --symbol SPY --interval 1h --full-grid
```

### Custom Window Sizes (3mo train, 1mo test)
```bash
python -m backtest.run_walk_forward --symbol SPY --interval 1h --train-months 3 --test-months 1 --step-months 1
```

### Custom Date Range
```bash
python -m backtest.run_walk_forward --symbol MES --interval 1h --start 2025-01-01 --end 2026-03-29
```

---

## Python API

### Minimal Example
```python
from backtest.walk_forward import WalkForwardValidator
from backtest.data_loader import BacktestDataLoader

loader = BacktestDataLoader()
df = loader.load("SPY", "2024-06-01", "2026-03-27", "1h")

validator = WalkForwardValidator()
result = validator.run(df, "SPY")

print(f"WFE: {result['summary']['wfe']:.3f}")
```

### Full Example with All Options
```python
from backtest.walk_forward import WalkForwardValidator, save_results
from backtest.data_loader import BacktestDataLoader

loader = BacktestDataLoader()
df = loader.load("MES", "2024-01-01", "2026-03-29", "1h")

validator = WalkForwardValidator(
    train_months=6,
    test_months=2,
    step_months=2,
)

multiplier = loader.get_multiplier("MES")
result = validator.run(
    df,
    "MES",
    multiplier=multiplier,
    capital=100_000.0,
    fast=False,                   # Use full grid
    adaptive_regime=True,
    volume_filter=True,
    mtf_filter=False,
)

# Save results
output_file = save_results(
    result, "MES", "1h",
    adaptive_regime=True,
    volume_filter=True,
)

# Access results
print(f"WFE: {result['summary']['wfe']:.3f}")
print(f"OOS Sharpe: {result['summary']['avg_oos_sharpe']:.3f}")
print(f"Results saved to: {output_file}")

for window in result['windows']:
    print(f"Window {window['window']}: OOS Return={window['oos_result'].total_return_pct*100:.1f}%")
```

---

## REST API (cURL)

### Basic Request
```bash
curl -X POST http://localhost:8010/backtest/walk-forward \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "SPY",
    "interval": "1h"
  }' | jq .
```

### With Filters
```bash
curl -X POST http://localhost:8010/backtest/walk-forward \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "MES",
    "interval": "1h",
    "train_months": 6,
    "test_months": 2,
    "adaptive_regime": true,
    "volume_filter": true
  }' | jq .summary
```

### Extract WFE from Response
```bash
curl -s -X POST http://localhost:8010/backtest/walk-forward \
  -H "Content-Type: application/json" \
  -d '{"symbol":"SPY","interval":"1h"}' | \
  jq '.summary.wfe'
```

---

## REST API (Python)

```python
import requests
import json

response = requests.post(
    "http://localhost:8010/backtest/walk-forward",
    json={
        "symbol": "SPY",
        "interval": "1h",
        "train_months": 6,
        "test_months": 2,
        "adaptive_regime": False,
    }
)

result = response.json()
print(f"WFE: {result['summary']['wfe']:.3f}")
print(f"Results saved to: {result['results_file']}")

# Save full result to file
with open("wf_result.json", "w") as f:
    json.dump(result, f, indent=2)
```

---

## Interpreting Results

### Quick Check
```python
import json

with open("engine/backtest/results/WF_SPY_1h_walk_forward.json") as f:
    data = json.load(f)

wfe = data["summary"]["wfe"]
if wfe > 0.7:
    print("✓ EXCELLENT — Strategy is robust")
elif wfe > 0.5:
    print("✓ GOOD — Strategy likely viable")
elif wfe > 0.3:
    print("⚠ MARGINAL — Use with caution")
else:
    print("✗ OVERFIT — Parameters don't generalize")

print(f"\nWFE: {wfe:.3f}")
print(f"OOS Sharpe: {data['summary']['avg_oos_sharpe']:.3f}")
print(f"OOS Profit Factor: {data['summary']['avg_oos_profit_factor']:.3f}")
print(f"Profitable Windows: {data['summary']['windows_profitable']}/{data['summary']['total_windows']}")
```

### Parameter Stability Check
```python
import json

with open("engine/backtest/results/WF_SPY_1h_walk_forward.json") as f:
    data = json.load(f)

print("Optimal Parameters Across Windows:")
for window in data['windows']:
    params = window['best_params']
    print(f"Window {window['window']}: STC_OB={params['stc_overbought']}, Stop={params['atr_stop_mult']:.2f}, T1={params['atr_target_mult']:.1f}")

# If parameters vary significantly → unstable strategy
```

---

## File Locations

- **Results:** `engine/backtest/results/WF_*.json`
- **Code:** `engine/backtest/walk_forward.py`
- **CLI:** `engine/backtest/run_walk_forward.py`
- **Tests:** `engine/test_walk_forward_system.py`
- **Docs:** `engine/WALK_FORWARD_GUIDE.md`

---

## Test the System

```bash
cd engine
python test_walk_forward_system.py
```

Expected output:
```
✓ Created WalkForwardValidator
✓ Generated 4 rolling windows
✓ Walk-forward validation complete!
✓ Results saved to: engine/backtest/results/WF_SPY_1h_walk_forward.json
✓ All core tests passed!
```

---

## Common Scenarios

### I want to validate SPY parameters for paper trading
```bash
python -m backtest.run_walk_forward --symbol SPY --interval 1h --start 2024-06-01 --end 2026-03-27
```
Then check: `engine/backtest/results/WF_SPY_1h_walk_forward.json` for WFE > 0.50

### I want to detect if MES parameters are overfit
```bash
python -m backtest.run_walk_forward --symbol MES --interval 1h --full-grid
```
If WFE < 0.30, parameters are overfit. Adjust parameter ranges or add filters.

### I want to compare static vs adaptive regime parameters
```bash
# Static (baseline)
python -m backtest.run_walk_forward --symbol MCL --interval 1h

# Adaptive (with regime filter)
python -m backtest.run_walk_forward --symbol MCL --interval 1h --adaptive-regime
```
Compare results: which has higher WFE?

### I want to check parameter stability across market regimes
Run walk-forward with 3-month windows (more granular):
```bash
python -m backtest.run_walk_forward --symbol MGC --interval 1d --train-months 6 --test-months 3 --step-months 1
```
Check JSON for parameter consistency across windows.

---

## Performance Tips

- **Fast mode (default):** 162 parameter combinations, runs in minutes
- **Full grid mode:** 2,500 combinations, runs in 10-30 minutes
- **Smaller windows:** 3mo train/1mo test → more windows, faster per-window, noisier results
- **Larger windows:** 12mo train/3mo test → fewer windows, slower, cleaner results

**Recommended:**
- First pass: `--full-grid` on 3 months of data → 1-2 minutes
- Final validation: `--full-grid` on 12+ months → 10-20 minutes

---

## Integration with Paper Trading

After walk-forward validation, use best parameters:

```python
# From results: WF_MES_1h_walk_forward.json
# Use the best_params from highest OOS Sharpe window

MGC_PAPER_CONFIG = {
    "stc_oversold": 15,        # ← From best window
    "stc_overbought": 88,      # ← From best window
    "atr_stop_mult": 0.30,     # ← From best window
    "atr_target_mult": 1.50,   # ← From best window
}
```

Then run paper trades with validated parameters.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Not enough data" | Increase date range |
| Slow execution | Use `--no-full-grid` (default) |
| Different results each run | Normal (grid search is stochastic); run multiple times |
| WFE < 0.3 | Parameters are overfit; try wider param ranges |
| No profitable windows | Strategy doesn't work for this symbol/timeframe |

---

## See Also

- **Full Guide:** `engine/WALK_FORWARD_GUIDE.md`
- **Implementation Details:** `WALK_FORWARD_IMPLEMENTATION_SUMMARY.md`
- **API Docs:** `http://localhost:8010/docs` (when engine is running)
