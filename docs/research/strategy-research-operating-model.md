# Strategy research operating model

This note turns the repo-consolidation findings into a JARVIS-native trading research loop.

## Canonical flow

```text
idea
  -> data contract
  -> baseline backtest
  -> robustness checks
  -> walk-forward / OOS validation
  -> paper shadow
  -> promotion decision
  -> live/paper operating telemetry
```

## Required strategy record fields

Every candidate strategy should have a durable record with:

- `strategy_id`
- `source_repo_or_note`
- `hypothesis`
- `asset_class`
- `symbols`
- `timeframe`
- `data_sources`
- `feature_set`
- `entry_rules`
- `exit_rules`
- `position_sizing`
- `risk_limits`
- `fees_and_slippage_model`
- `train_window`
- `test_window`
- `walk_forward_config`
- `metrics`
- `known_failure_modes`
- `promotion_state`
- `evidence_paths`

## Metrics floor

At minimum, every backtest or paper verdict should report:

- Net PnL / return.
- Max drawdown.
- Sharpe and/or Sortino.
- Profit factor.
- Trade count and exposure time.
- Win rate and payoff ratio.
- Fees/slippage assumptions.
- Regime split.
- Parameter sensitivity.
- Monte Carlo / path-risk estimate where applicable.
- Data-leakage and lookahead checks.

## How imported repos map into this model

- `jarvis-quant`: IBKR connection and data-pull learning artifacts. Use it for operator intuition and future data/runbook improvements, not direct production imports.
- `autotrade`: LLM-driven strategy iteration loop. Use it to harden the strategy ideation/evaluation cadence, but require JARVIS data contracts and promotion gates before any generated strategy is eligible.
- `jarvis-positions-check`: replaced by an in-tree utility script that reads credentials from environment/CLI and has unit coverage.
- `awesome-quant`, `sunday-quant-scientist`, `claude-trading-skills`, `TradingAgents`, `Vibe-Trading`: reference/mining inputs for checklists, feature ideas, and research workflows.
- `lightweight-charts`, `tradingview-mcp`: chart-review and discretionary-analysis tooling candidates.
- `fredapi`: macro/regime context feature candidate. It should inform regime filters and briefs, not bypass promotion gates or place trades.
