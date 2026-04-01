# JARVIS TRADER — Regime-Specific Performance Analysis

## Overview

This feature breaks down backtest results by market regime to identify which regimes produce profitable edges and which should be avoided or optimized.

## Core Components

### 1. `engine/backtest/regime_analysis.py`
The `RegimeAnalyzer` class provides:

- **Regime Classification**: Classifies trades into regimes based on embedded data or OHLCV indicators
  - `TRENDING_UP`: EMA ribbon bullish + positive momentum
  - `TRENDING_DOWN`: EMA ribbon bearish + negative momentum  
  - `TRENDING_BULL`/`TRENDING_BEAR`: From full backtest trades
  - `RANGE_BOUND`: Compressed EMAs + low ATR consumed
  - `HIGH_VOLATILITY`: ATR consumed > 80% or extreme phase
  - `COMPRESSION`: Compressed phase oscillator
  - `EXHAUSTED`: Extreme volatility (>90% ATR consumed)
  - `TRANSITION`: Regime changed within last 5 bars

- **Performance Metrics Per Regime**:
  - Trade count, win rate, profit factor
  - Gross profit/loss, avg win/loss
  - Total P&L, Sharpe ratio
  - Max win/loss, expectancy

- **Edge Source Identification**:
  - Which regimes are profitable (PF > 1.0)
  - Which regimes should be avoided (PF < 1.0)
  - Best/worst performing regimes
  - Distribution of trades across regimes

### 2. `engine/backtest/run_regime_analysis.py`
CLI tool for standalone regime analysis:

```bash
# Usage with embedded regime data (no OHLCV needed)
python -m backtest.run_regime_analysis \
    --results-file backtest/results/MCL_1h_2024-06-01_2026-03-27.json

# Optional: Use OHLCV data to classify regimes
python -m backtest.run_regime_analysis \
    --results-file backtest/results/MCL_1h_2024-06-01_2026-03-27.json \
    --data-file backtest/cache/MCL_1h_730d.csv \
    --output-dir backtest/results/
```

**Output**:
- `{symbol}_{interval}_regime_analysis.json` — Metrics and edge sources
- `{symbol}_{interval}_regime_analysis.html` — Interactive visualization

### 3. `engine/main.py` - FastAPI Endpoint
Added `POST /backtest/regime-analysis`:

```python
# Request
{
    "symbol": "MCL",
    "start": "2024-06-01",
    "end": "2026-03-27",
    "interval": "1h",
    "capital": 100000.0,
    "risk_per_trade": 0.01
}

# Response
{
    "regime_metrics": {
        "TRENDING_BULL": {
            "regime": "TRENDING_BULL",
            "trade_count": 31,
            "winning_trades": 19,
            "losing_trades": 12,
            "win_rate": 0.6129,
            "profit_factor": 1.998,
            "total_pnl": 11093.73,
            "sharpe_ratio": 3.41,
            ...
        },
        ...
    },
    "edge_sources": {
        "profitable_regimes": ["TRENDING_BULL", "RANGE_BOUND"],
        "unprofitable_regimes": ["TRENDING_BEAR"],
        "best_regime": "RANGE_BOUND",
        "best_pf": 3.443,
        "worst_regime": "TRENDING_BEAR",
        "worst_pf": 1.129,
        "regime_distribution": {
            "TRENDING_BULL": 0.477,
            "TRENDING_BEAR": 0.323,
            "RANGE_BOUND": 0.2
        }
    },
    "backtest_summary": {
        "total_trades": 65,
        "win_rate": 0.6,
        "profit_factor": 1.835,
        "total_return_pct": 0.206,
        "sharpe_ratio": 0.153
    }
}
```

### 4. Interactive HTML Visualization
Generated automatically with 4 charts:

1. **Profit Factor by Regime** — Bar chart showing which regimes have the best edges
2. **Trade Count Distribution** — Pie chart showing regime mix
3. **Win Rate by Regime** — Bar chart for win rate comparison
4. **Total P&L by Regime** — Stacked bar showing profit/loss per regime
5. **Detailed Metrics Table** — Full statistics for each regime

## Usage Examples

### Example 1: Analyze MCL 1h Backtest
```bash
cd engine
python -m backtest.run_regime_analysis \
    --results-file backtest/results/MCL_1h_2024-06-01_2026-03-27.json
```

**Output Summary**:
```
TRENDING_BULL
  Trades: 31 | Win Rate: 61.3% | Profit Factor: 1.998
  Total P&L: $11,093 | Avg Win: $1,169 | Avg Loss: $-926
  Sharpe: 3.41 | Expectancy: $358

RANGE_BOUND
  Trades: 13 | Win Rate: 69.2% | Profit Factor: 3.443
  Total P&L: $8,187 | Avg Win: $1,282 | Avg Loss: $-838
  Sharpe: 2.23 | Expectancy: $630

===  EDGE SOURCES ===
Profitable regimes: TRENDING_BULL, TRENDING_BEAR, RANGE_BOUND
Best regime: RANGE_BOUND (PF 3.443)
Worst regime: TRENDING_BEAR (PF 1.129)
```

**Key Insights**:
- **Best edge**: RANGE_BOUND regime with 69.2% win rate and 3.44x profit factor
- **Trading distribution**: 47.7% TRENDING_BULL, 32.3% TRENDING_BEAR, 20% RANGE_BOUND
- **Performance by regime**: All three regimes are profitable; focus on RANGE_BOUND for highest PF

### Example 2: Use FastAPI Endpoint
```bash
curl -X POST http://localhost:8010/backtest/regime-analysis \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "MES",
    "start": "2025-01-01",
    "end": "2026-01-01",
    "interval": "1d",
    "capital": 50000,
    "risk_per_trade": 0.01
  }'
```

Returns JSON with regime metrics, edge sources, and backtest summary.

## Implementation Details

### Regime Data Flow

1. **Backtest Execution**: When `Backtester.run()` executes, each trade captures:
   - Entry timestamp
   - P&L
   - Regime classification (from `layer1_regime()` in signals.py)
   - Bias (from `layer3_bias()`)

2. **Regime Analysis**: `RegimeAnalyzer.analyze_trades()`:
   - Groups trades by regime
   - Computes metrics for each regime bucket
   - Identifies profitable vs. unprofitable regimes

3. **Output Generation**:
   - JSON file with detailed metrics
   - HTML visualization with interactive charts
   - FastAPI endpoint returns both metrics and edge sources

### Regime Classification Logic

From `signals.py.layer1_regime()`:
```python
- ATR consumed > 90% → EXHAUSTED
- Compression + ATR < 50% → COMPRESSION  
- Bullish EMA + ATR < 70% + positive phase → TRENDING_BULL
- Bearish EMA + ATR < 70% + negative phase → TRENDING_BEAR
- Otherwise → RANGE_BOUND
```

Extended by RegimeAnalyzer for multi-regime classification when using OHLCV data.

## Key Findings (MCL 1h Example)

| Regime | Trades | Win Rate | PF | Total P&L | Sharpe |
|--------|--------|----------|----|-----------| -------|
| TRENDING_BULL | 31 | 61.3% | 1.998 | $11,093 | 3.41 |
| TRENDING_BEAR | 21 | 52.4% | 1.129 | $1,317 | 19.16 |
| RANGE_BOUND | 13 | 69.2% | 3.443 | $8,187 | 2.23 |

**Insights**:
- RANGE_BOUND has the highest profit factor (3.44) and best win rate (69.2%)
- TRENDING_BEAR barely profitable (PF 1.13) — consider filtering these trades
- TRENDING_BULL solid performance (PF 1.998) — provides 47.7% of trades

## Files Modified/Created

Created:
- `engine/backtest/regime_analysis.py` — Core RegimeAnalyzer class
- `engine/backtest/run_regime_analysis.py` — CLI runner
- `REGIME_ANALYSIS_README.md` — This documentation

Modified:
- `engine/main.py` — Added `POST /backtest/regime-analysis` endpoint

## Future Enhancements

1. **Regime-Specific Filtering**: Block entries or tighten stops in unprofitable regimes
2. **Adaptive Parameters**: Adjust STC thresholds per regime using adaptive_regime flag
3. **Transition Analysis**: Identify false signals at regime boundaries
4. **Live Monitoring**: Add regime breakdown to dashboard for live trading
5. **Monte Carlo by Regime**: Run separate Monte Carlo sims per regime

## Testing

```bash
# Test with existing backtest result
cd engine
python -m backtest.run_regime_analysis \
    --results-file backtest/results/MCL_1h_2024-06-01_2026-03-27.json

# Check output files
ls -lh backtest/results/MCL_1h_regime_analysis.*

# View the HTML visualization
open backtest/results/MCL_1h_regime_analysis.html
```

---

**Status**: Complete ✓  
**Integration**: Ready for production use  
**Next Steps**: Deploy to staging, test with live data, add regime-specific entry filters
