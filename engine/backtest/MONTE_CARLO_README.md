# JARVIS TRADER — Monte Carlo Simulation Suite

Validates backtest robustness by randomizing trade order with optional slippage modeling.

## Overview

The Monte Carlo module runs N simulations of your backtest by:
1. Shuffling the original trade sequence randomly
2. Optionally applying uniform random slippage (0-N ticks per trade)
3. Recalculating equity curves and metrics for each simulation
4. Computing percentile statistics and confidence intervals

If your strategy is truly robust, the original equity curve should sit in the upper portion of the shuffled distribution.

## Features

### Core Simulation (`monte_carlo.py`)

- **Vectorized NumPy operations** — 1,000 simulations in ~0.1-0.5 seconds
- **Slippage modeling** — Uniform random 0-N ticks per trade, with instrument-specific tick values:
  - MES (Micro E-mini S&P 500): $1.25 per tick
  - MNQ (Micro E-mini Nasdaq): $0.50 per tick
  - SPY (equity index): $0.01 per share
  - MCL (Oil): custom per instrument
- **Comprehensive metrics**:
  - Percentile statistics: 5th, 25th, 50th (median), 75th, 95th
  - Confidence metrics: probability of profit, probability of any loss under permutation
    (`prob_any_loss_permuted`), 2x return target
  - Risk metrics: Value-at-Risk (5%), Conditional Value-at-Risk, worst-case max drawdown
  - Verdict classification: EXCELLENT / GOOD / MARGINAL / POOR
  - Bootstrap-resampled VaR/CVaR/probability-of-ruin (`compute_var`, `compute_cvar`,
    `probability_of_ruin` — distinct from the permutation-based `prob_any_loss_permuted`
    above; see docstrings in `monte_carlo.py`)

### CLI Runner (`run_monte_carlo.py`)

```bash
# Basic usage: 1,000 sims, no slippage
python -m backtest.run_monte_carlo --results-file results/MES_1h_2024-06-01_2026-03-27.json

# With slippage: uniform 0-2 ticks per trade (MES default)
python -m backtest.run_monte_carlo \
  --results-file results/MES_1h_2024-06-01_2026-03-27.json \
  --simulations 1000 \
  --max-slippage 2

# Different instrument: MCL with 1 tick slippage
python -m backtest.run_monte_carlo \
  --results-file results/MCL_1h_2024-06-01_2026-03-27.json \
  --symbol MCL \
  --simulations 1000 \
  --max-slippage 1
```

Output files saved to `results/{SYMBOL}_{INTERVAL}_monte_carlo.json` or with `_slip{N}tk` suffix if slippage applied.

### Visualization (`monte_carlo_viz.py`)

Generates interactive HTML equity curve fan charts:

```bash
# Generate chart from original backtest JSON
python -m backtest.monte_carlo_viz --json results/MES_1h_2024-06-01_2026-03-27.json

# Output: results/MES_1h_monte_carlo_chart.html
```

The HTML visualization shows:
- **Median equity curve** (solid line) — the 50th percentile outcome
- **Core range band** (darker shading) — 25th-75th percentile
- **Confidence interval band** (lighter shading) — 5th-95th percentile
- **Breakeven line** (dashed) — starting capital reference

## API Endpoints

### POST `/backtest/monte-carlo`

Run Monte Carlo simulation on backtest results.

**Request:**
```json
{
  "results_file": "MES_1h_2024-06-01_2026-03-27.json",
  "simulations": 1000,
  "max_slippage_ticks": 2,
  "symbol": "MES",
  "initial_capital": 100000
}
```

**Response:**
```json
{
  "original": {
    "final_capital": 95968.82,
    "total_return_pct": -0.40,
    "max_drawdown_pct": 5.36,
    "sharpe_ratio": -0.125,
    "profit_factor": 0.963
  },
  "distribution": {
    "final_capital": {
      "p5": 95000,
      "p25": 95500,
      "median": 96000,
      "p75": 96500,
      "p95": 97000
    },
    "max_drawdown_pct": {...},
    "sharpe_ratio": {...}
  },
  "confidence": {
    "prob_profitable": 45.2,
    "prob_any_loss_permuted": 54.8,
    "prob_achieving_2x_return": 0.0,
    "value_at_risk_5pct": 95000,
    "expected_shortfall": 94500,
    "worst_case_max_drawdown": 7.5
  },
  "verdict": "MARGINAL",
  "bootstrap_var": {
    "var_pct": -0.021,
    "median_var": -0.020,
    "var_ci_95_low": -0.028,
    "var_ci_95_high": -0.013,
    "confidence": 0.95,
    "n_trades": 42
  },
  "bootstrap_cvar": {
    "cvar": -0.031,
    "median_cvar": -0.030,
    "cvar_ci_95_low": -0.040,
    "cvar_ci_95_high": -0.021,
    "confidence": 0.95,
    "n_trades": 42
  },
  "bootstrap_probability_of_ruin": {
    "probability_of_ruin": 0.02,
    "ruin_threshold_pct": 0.5,
    "ruin_equity_level": 50000.0,
    "n_resamples": 10000,
    "n_trades": 42
  }
}
```

### POST `/backtest/monte-carlo/chart`

Generate interactive HTML visualization (calls `/backtest/monte-carlo` first).

**Request:**
```json
{
  "results_file": "MES_1h_2024-06-01_2026-03-27.json",
  "simulations": 1000,
  "max_slippage_ticks": 2,
  "symbol": "MES"
}
```

**Response:**
```json
{
  "chart_path": "/full/path/to/MES_1h_monte_carlo_chart.html",
  "status": "success",
  "message": "Chart generated: MES_1h_monte_carlo_chart.html"
}
```

## Interpretation Guide

### Verdict Levels

| Verdict | Probability of Profit | Original vs Distribution | Meaning |
|---------|----------------------|--------------------------|---------|
| **EXCELLENT** | >80% | Original ≥ 75th percentile | Strategy is robust across trade sequences; high confidence |
| **GOOD** | >65% | Original ≥ median | Strategy shows decent robustness; reasonable confidence |
| **MARGINAL** | >50% | Original ≥ p25 | Strategy is sequence-dependent; caution advised |
| **POOR** | ≤50% | Original < median | Strategy is fragile; likely overfitted to specific trade order |

### Key Metrics Explained

- **Probability of Profit (PoP)**: % of simulations that end with equity > starting capital
- **Probability of Ruin**: % of simulations that lose money (ending equity < start)
- **Probability 2x Return**: % of simulations achieving 2x starting capital
- **Value-at-Risk (VaR) 5%**: Worst 5% outcome (tail risk)
- **Conditional Value-at-Risk (CVaR)**: Average of worst 5% outcomes (expected shortfall)
- **Worst-Case Max DD (p5)**: Maximum drawdown at 5th percentile

### Visual Interpretation

**Tight bands** (p5-p95 close together) → Low variance in outcomes → Robust strategy

**Wide bands** → High variance in outcomes → Strategy depends on trade sequence

**Median line in upper half of bands** → Original trades favorable → Strategy is exploitative

**Median line in lower half of bands** → Original trades unfavorable → Check for overfitting

## Example Output

```
=== MONTE CARLO ANALYSIS (1000 simulations) ===
Original Strategy: Return=+20.6%  MaxDD=3.9%  Sharpe=4.14  PF=1.83

DISTRIBUTION OF OUTCOMES:
                      P5%       P25%     Median       P75%       P95%
Final Cap:     $  120,597 $  120,597 $  120,597 $  120,597 $  120,597
Max DD:              3.0%       3.7%       4.6%       5.6%       7.4%
Sharpe:              3.86       3.97       4.03       4.09       4.17

CONFIDENCE ANALYSIS:
  Probability of Profit:       100.0%
  Probability of Ruin:         0.0%
  Probability 2x Return:       8.3%
  Original beats X% of sims:   100.0%
  5% Value at Risk:            $120,597
  Expected Shortfall (CVaR):   $120,597
  Worst-case Max DD (p5):      3.0%

VERDICT: EXCELLENT
```

## Performance

- **1,000 simulations**: ~0.1-0.5 seconds (NumPy vectorized)
- **100,000 simulations**: ~10-50 seconds
- Memory efficient: O(n_sims × n_trades)

## Implementation Details

### Tick Value Lookup

Per-instrument tick values ($/tick):
```python
{
    "MES": 1.25,    # Micro E-mini S&P
    "MNQ": 0.50,    # Micro E-mini Nasdaq
    "SPY": 0.01,    # Stock index
    "ES": 50.0,     # E-mini S&P
    "NQ": 20.0,     # E-mini Nasdaq
}
```

### Slippage Model

For each simulation and each trade:
```python
slippage_ticks = uniform_random(0, max_slippage_ticks)
slippage_dollars = slippage_ticks * tick_value
adjusted_pnl = original_pnl - slippage_dollars
```

### Equity Curve Calculation

```python
# Original
equity_curve = [initial_capital]
for pnl in original_trades:
    equity_curve.append(equity_curve[-1] + pnl)

# Simulations (per simulation)
shuffled_pnls = random_shuffle(original_trades)
adjusted_pnls = shuffled_pnls - random_slippage
equity_curve_sim = cumsum([initial_capital] + adjusted_pnls)
```

## Testing

Run the suite on your backtest results:

```bash
# Test with 100 simulations for quick feedback
python -m backtest.run_monte_carlo --results-file backtest/results/MCL_1h_2024-06-01_2026-03-27.json --simulations 100

# Production run: 1,000+ simulations with slippage
python -m backtest.run_monte_carlo \
  --results-file backtest/results/MCL_1h_2024-06-01_2026-03-27.json \
  --simulations 1000 \
  --max-slippage 1

# Generate visualization
python -m backtest.monte_carlo_viz --json backtest/results/MCL_1h_2024-06-01_2026-03-27.json
```

## Files

- `monte_carlo.py` — Core simulation engine (vectorized)
- `run_monte_carlo.py` — CLI runner
- `monte_carlo_viz.py` — HTML visualization generator
- `main.py` — FastAPI endpoints (`/backtest/monte-carlo`, `/backtest/monte-carlo/chart`)

## References

Monte Carlo analysis in trading validates robustness by simulating alternative trade sequences. This helps distinguish:
- **Skill**: Strategy performs well across different trade orderings
- **Luck**: Strategy only works for specific trade sequences (overfitted)

See:
- Pardo, R. *The Evaluation and Optimization of Trading Strategies* (2nd ed.)
- De Prado, M. L. *Machine Learning for Asset Managers* (Chapter 4)

---

Generated with JARVIS TRADER Monte Carlo Suite
