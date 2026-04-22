---
repo: freqtrade/freqtrade-strategies
url: https://github.com/freqtrade/freqtrade-strategies
stars: 5044
language: Python
license: GPL-3.0
archived: false
pushed_at: 2026-02-26T19:29:59Z
analyzed_at: 2026-04-17
recommendation: partial-integrate
surfaces_with_value: [dev-tooling]
---

# freqtrade/freqtrade-strategies

## Core value proposition

Repository of 50+ free crypto trading strategies for Freqtrade bot, most derived from Hyperopt parameter optimization (2018-era backtest windows). Strategies are simple rule-based signal generators with minimal ROI, stoploss, and entry/exit rules tuned to historical data; documentation emphasizes strategy structure conventions and Hyperopt workflow patterns.

## Surface analysis

### 1. Engine code

**no-fit** — Repo contains no agent logic, risk management, backtest harness, indicator research, or data infrastructure applicable to jarvis-trader. Freqtrade strategy class hierarchy (minimal_roi dict, stoploss scalar, populate_indicators method signature) differs fundamentally from jarvis-trader's pipeline-based signal composition and WFE/PF/Sharpe scoring framework. The only reusable element would be indicator implementations (talib/qtpylib), but jarvis-trader already has comprehensive `engine/backtest/indicators.py` with 30+ indicators. No tactical win.

### 2. Project rules

**no-fit** — Repo has no coding discipline rules, safety invariants, testing patterns, or operational guidelines. README contains only risk disclaimers (standard crypto boilerplate: "do not risk money you're afraid to lose"). No transfer to `.claude/rules/`.

### 3. Project skills

**no-fit** — No reusable workflow automation or domain-specific procedures. No MCP servers, CLI patterns, or multi-stage task orchestration applicable to jarvis-trader skill library.

### 4. Slash commands

**no-fit** — Repo is strategy distribution only. No command patterns, parameter parsing, or quick-action scaffolding relevant to `/pretrade-check` or other jarvis-trader commands.

### 5. Subagents

**no-fit** — No evidence of specialized reviewers, analyzers, or multi-agent decision patterns. Strategies are standalone implementations; no agent-to-agent feedback loop, debate, or consensus logic.

### 6. Docs

**partial-integrate** — README at `user_data/strategies/` documents Freqtrade's required interface contract: (a) INTERFACE_VERSION=3; (b) minimal_roi dict (time-based profit targets); (c) stoploss scalar; (d) timeframe string; (e) populate_indicators() signature; (f) populate_entry_trend() / populate_exit_trend() signal methods; (g) optional order_types dict. These conventions are structurally similar to how jarvis-trader's strategy_lab/ might define a pluggable strategy interface. Applicable only if jarvis-trader formalizes a strategy interface spec (currently informal). Cross-reference: `engine/strategy_lab/strategy_evaluator.py` and `engine/strategy_lab/competition_harness.py` already define internal competitions; formalizing a `BaseStrategy` abstract class with Freqtrade-inspired interface signatures would improve type safety and testability.

### 7. Dev tooling

**integrate-now** — Freqtrade repository structure provides a reference pattern for multi-strategy deployment, backtest orchestration, and dry-run management:
- **Directory layout**: `user_data/strategies/` (flat file convention, one class per file, import-friendly) mirrors a candidate `engine/strategy_lab/library/` pattern for future strategy variants.
- **Backtest workflow**: README documents `freqtrade backtesting --strategy Strategy001` and `freqtrade download-data --days 100`, defining a CLI interface contract. Jarvis-trader's `engine/backtest/run_all_backtests.py` and `engine/backtest/paper_runner.py` are ad-hoc; formalizing a `pnpm run backtest <strategy> <timeframe> <daterange>` CLI subcommand aligned with Freqtrade's pattern would improve iteration speed.
- **Test-harness convention**: Freqtrade separates data download, backtesting, and hyperparameter optimization into discrete CLI subcommands (`download-data`, `backtesting`, `hyperopt`). Jarvis-trader's backtest logic is monolithic (single `backtester.py` + `optimizer.py`); refactoring into smaller CLI commands (e.g., `pnpm run backtest:fetch`, `pnpm run backtest:run`, `pnpm run backtest:optimize`) would improve modularity and parallel test execution.
- **CI pattern**: Freqtrade repo has no CI workflows visible in `.github/workflows/` (likely stored in main freqtrade repo, not strategies mirror). Jarvis-trader's `ci.yml` is comprehensive; no direct upside from strategies repo structure.

### 8. Dashboard

**no-fit** — Freqtrade strategies repo contains no dashboard code, Tailwind components, or UI monitoring patterns. Visualization is out-of-scope for strategy storage repository.

### 9. Ops / messaging

**no-fit** — No alerting, cron jobs, WhatsApp integrations, or execution guardrails. Freqtrade strategies are passive definitions; orchestration is handled by the main freqtrade bot runtime.

## Integration plan

**Surface 7 (Dev tooling) — Partial integration:**

1. **Immediate (S, <2 hours)**: Document the Freqtrade interface contract (INTERFACE_VERSION, minimal_roi dict, stoploss, populate_indicators, populate_entry_trend/exit_trend signatures) in `docs/strategy-lab-interface.md` for future reference when designing a pluggable strategy loader.

2. **Deferred (M, 2-8 hours)**: If and when jarvis-trader needs to support third-party strategy imports (not currently a requirement), use Freqtrade's pattern as a reference. This warrants a separate user request; do not ship speculatively.

3. **Backlog item**: Create a `pnpm run backtest:cli` wrapper that mimics Freqtrade's command structure (`--strategy <name> --timeframe <tf> --daterange <start>-<end> --days <n>`). Currently deferred pending PM roadmap prioritization.

## License & attribution

**License**: GPL-3.0 (copyleft). Integration of Freqtrade's design patterns (strategy interface conventions, CLI subcommand structure) does not require code attribution under GPL (design patterns are not copyrightable). **Recommendation**: If any code snippets or specific signal implementations are copied, attribute explicitly in file header with source URL and author.

## Effort estimate

**Deferred** — The partial-integrate surface (dev tooling) is a documentation + architecture discussion, not implementation. Estimated 2 hours for docs, 6-8 hours for optional CLI refactoring if requested. No changes to core logic required. No risk of regression.

## Red flags

1. **GPL-3.0 license**: Copyleft. If jar vis-trader source is ever published, all GPL-derived changes must be open-sourced. **Mitigation**: Copy only design patterns (non-copyrightable), not code.
2. **Obsolete backtest data**: Strategies were optimized on 2018-01-10 to 2018-01-30 (8 years old). Performance metrics are not transferable to 2026 market conditions. Historical value is educational only.
3. **Crypto-only domain**: All strategies target crypto exchange pairs (BTC/USDT, ETH/USDT). No futures, no US equity market regime, no options. Inverse mapping to futures (MES, MNQ, MCL) would require complete reimplementation.
4. **Hyperopt overfit**: Acknowledged in README ("strategies designed from Hyperopt calculations"). Walk-forward validation not applied. Avoid using any strategy parameters directly; reference Freqtrade's methodology if designing a Bayesian optimizer replacement.

## Recommendation detail

**No direct code reuse**; strategies themselves are out-of-scope (crypto, overfit, obsolete). **Value lives in structure and workflow**: Freqtrade's directory layout (one strategy per file), interface contract (minimal_roi dict, populate_indicators signature), and CLI subcommand pattern are sound design precedents for jarvis-trader's emerging `engine/strategy_lab/` module. Recommend reviewing Freqtrade's conventions when next designing a formal strategy interface or refactoring backtest CLI, but do not proceed with integration until an explicit user request (e.g., "add pluggable strategy support" or "improve backtest CLI"). Document the pattern now; integrate later. **Classify as `defer` until concrete need surfaces.**
