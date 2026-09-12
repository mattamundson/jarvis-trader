# Repository consolidation Wave 1 imports

**Date:** 2026-09-12  
**Branch:** `chore/repo-consolidation-wave1-20260912`  
**Scope:** documentation/research/script consolidation only. No live trading config, risk limits, kill switch, broker routing, or order placement behavior changed.

This directory preserves useful artifacts from small standalone repositories identified in the GitHub estate audit. The goal is to keep `jarvis-trader` as the canonical trading-system monorepo while preserving provenance and avoiding silent loss of research context.

## Imported repositories

| Source repo | Imported to | Disposition | Notes |
|---|---|---|---|
| `mattamundson/jarvis-positions-check` | `engine/scripts/check_positions.py`, `engine/tests/test_check_positions_script.py` | Replace standalone repo with maintained in-tree script after PR merge. | Original README/script contained a hardcoded API-key-like value. The in-tree version reads `JARVIS_API_KEY`/`API_KEY` or `--api-key`; no secret is embedded. |
| `mattamundson/jarvis-quant` | `engine/research/imported/jarvis-quant/` | Preserve as non-production IBKR learning sandbox. | Imported notebooks/scripts/config/readme only. Parquet data snapshots were intentionally skipped to avoid promoting stale research data as canonical. |
| `mattamundson/autotrade` | `engine/research/imported/autotrade/` | Preserve as LLM strategy-iteration reference. | Imported loop docs, risk/profit references, trainer skeleton, and one generated strategy example. `.env.example` and lockfile were intentionally skipped. |

## Promotion rules

Imported research artifacts are **not production trading logic** until they satisfy the normal JARVIS promotion gates:

1. Explicit strategy hypothesis and instrument/timeframe scope.
2. Deterministic data provenance with feed, symbol mapping, timestamp range, timezone, freshness, and adjustment policy.
3. Backtest result with slippage, fees, position sizing, max drawdown, Sharpe/Sortino, profit factor, trade count, and regime split.
4. Walk-forward/out-of-sample validation plus parameter-stability evidence.
5. Monte Carlo or equivalent path-risk analysis.
6. Paper shadow run with observable drift checks.
7. Explicit promotion record in the strategy registry / decision ledger.
8. Safety review for anything touching execution, risk, kill switch, broker adapters, or active instrument gates.

## Next consolidation candidates

- Convert the imported `autotrade` loop into a JARVIS-native `strategy_idea -> backtest -> WFO -> paper shadow -> promote/reject` workflow.
- Turn the useful pieces of `jarvis-quant` into a maintained IBKR research runbook and archive the raw sandbox after verification.
- If the standalone source repos are retained on GitHub, mark them with topics such as `archive-candidate`, `imported-into-jarvis-trader`, or `reference` after this PR is merged.
