# Strategy registry operating contract

The strategy registry is the promotion ledger for JARVIS research. It exists to stop promising ideas from drifting into paper or production without the same evidence package every time.

## Source-of-truth files

- Schema: `engine/research/strategy_registry.schema.json`
- Example entry: `engine/research/examples/strategy_registry_entry.example.json`
- Lightweight validator: `engine/scripts/validate_strategy_registry_entry.py`

## Required lifecycle

1. **Idea** — record a falsifiable hypothesis, instruments, timeframe, source repos, and intended data contract.
2. **Research** — notebooks/scripts may explore the idea under `engine/research/`, but production modules must not import notebooks.
3. **Backtest** — attach exact runner path, train/test windows, data file/version, and standard metrics.
4. **Robustness** — record walk-forward, parameter-stability, regime-split, and Monte Carlo/ruin-risk outcomes.
5. **Risk envelope** — state maximum size, loss limit, kill-switch dependencies, and the paper-only boundary.
6. **Promotion gate** — fail closed unless the entry has a passing verdict, required evidence, and explicit human approval before production routing.

## Minimum evidence before paper-shadow status

- Exact data source and timestamped artifact path.
- Leakage-control notes, including OOS-access discipline.
- Profit factor, max drawdown, and trade count.
- Regime split or reason it is unavailable.
- Current gate/verdict file path.

## Minimum evidence before production-candidate status

- Fresh honest gate-v2 PASS or successor promotion-gate PASS.
- Walk-forward consistency across enough windows for the strategy family.
- Parameter stability report.
- Monte Carlo drawdown/ruin-risk report.
- Paper-shadow report with drift and slippage notes.
- Explicit approval outside the registry file itself.

## Consolidation link

This contract implements the repository audit recommendation to turn `jarvis-quant`, `autotrade`, `claude-trading-skills`, `awesome-quant`, and related forks into one repeatable JARVIS research workflow instead of another pile of disconnected scripts.
