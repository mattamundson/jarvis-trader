---
repo: freqtrade/freqtrade
url: https://github.com/freqtrade/freqtrade
stars: 27100
language: Python
license: GPL-3.0
archived: false
pushed_at: 2026-04-17
analyzed_at: 2026-04-17
recommendation: partial-integrate
surfaces_with_value: [engine-code, dev-tooling, docs]
deferred:
  - what: "Multi-version Python CI matrix (3.11, 3.12, 3.13)"
    reason: "jarvis-trader explicitly targets 3.12 only per project rules; running the suite against 3.11/3.13 would ~3x CI wall-clock for zero production benefit. Revisit only if the deployment target shifts."
    evaluated_at: 2026-04-17
  - what: "Hyperopt loss function library (Sharpe, Sortino, MaxDrawDown)"
    reason: "M effort + futures-specific calibration. Orthogonal to current single-composite-score optimizer at engine/backtest/bayesian_optimizer.py. Gate on strategy-discovery roadmap review."
  - what: "Lookahead bias detection"
    reason: "already implemented at engine/backtest/walk_forward.py:validate_no_lookahead()"
audit_correction:
  - original_claim: "multi-Python CI matrix is a quick win"
    actual_state: "Jarvis-trader pins 3.12. Adding 3.11+3.13 would test versions the project doesn't deploy to — CI cost without corresponding reliability gain. Declined rather than shipped."
    caught_by: "verify-before-reporting against engine/.venv + project rules before modifying .github/workflows/ci.yml"
---

# freqtrade/freqtrade

## Core value proposition

Freqtrade is a production-grade cryptocurrency trading bot written in Python 3.11+ with integrated backtesting, hyperparameter optimization (Hyperopt), exchange connectors (Binance, Kraken, OKX, etc.), Telegram/WebUI control, and walk-forward validation. It shares fundamental architectural patterns (strategy interface, backtest harness, optimizer, risk management) with JARVIS TRADER but targets crypto spot/futures exclusively while JARVIS focuses on futures (MES, MCL, MNQ).

## Surface analysis

### 1. Engine code

**partial-integrate** — Freqtrade's `freqtrade/strategy/interface.py` base class and backtest harness (`freqtrade/optimize/`) parallel JARVIS's `engine/strategies/base_strategy.py` and `engine/backtest/backtester.py`, but domain is crypto-only. Value lies in three sub-patterns: (a) walk-forward validation (`freqtrade/optimize/hyperopt_loss.py`), already implemented at `engine/backtest/walk_forward.py:1-50`; (b) OHLCV data pipeline (`freqtrade/data/dataprovider.py`), dedup with `engine/backtest/data_loader.py:BacktestDataLoader`; (c) position sizing (`freqtrade/exchange/exchange.py:_calculate_trade_amount`), dedup with `engine/backtest/position_sizer.py:PositionSizer`. Hyperopt loss functions (`freqtrade/optimize/hyperopt_loss/`) could inspire new loss metrics but require futures-specific tuning. **Cross-reference finding**: JARVIS already implements Bayesian optimization at `engine/backtest/bayesian_optimizer.py:47-120` with scikit-optimize fallback — freqtrade uses same library, no new insights.

### 2. Project rules

**no-fit** — Freqtrade's CONTRIBUTING.md enforces Python 3.11+, pytest, and black formatting. JARVIS already enforces equivalent discipline via `.claude/rules/engine-python.md`, `.claude/rules/testing.md`, and `.claude/rules/coding-style.md`. No new safety or testing invariants specific to freqtrade apply to equities/futures trading.

### 3. Project skills

**no-fit** — Freqtrade's Discord-driven workflow (community strategy sharing, Docker quick-start) is documentation-adjacent, not a reusable skill. JARVIS's `/pipeline-rerun`, `/pretrade-check`, `/wfe-check` (at `.claude/skills/backtest-report/`) serve equivalent analysis needs.

### 4. Slash commands

**no-fit** — Freqtrade CLI commands (`freqtrade trade`, `freqtrade backtesting`, `freqtrade hyperopt`) are wrapped by freqtrade's argument parser. JARVIS's command surface (`engine/routers/*.py` + `.claude/commands/jarvis-*.md`) is API-first and already covers strategy testing via `/jarvis-wfe-check`. Freqtrade's `new-strategy` scaffold is superseded by JARVIS's `engine/strategies/base_strategy.py:BaseStrategy` + `engine/llm/` code generation.

### 5. Subagents

**no-fit** — Freqtrade has no agent architecture; all decisions are rule-based configuration. JARVIS's multi-agent debate (`engine/agents/debate.py`), learning system (`engine/learning/`), and advisor client (`engine/agents/advisor_client.py`) are unique to the Claude-powered architecture.

### 6. Docs

**dedup-docs** — Freqtrade's runbooks (installation, backtesting guide, hyperopt, exchange setup) are already surfaced in JARVIS's `docs/troubleshooting.md` and `docs/strategy/` for futures trading. Freqtrade's "Data download" and "Lookahead bias detection" workflows are implemented at `engine/backtest/fetch_intraday.py` and `engine/backtest/walk_forward.py` respectively. No new documentation patterns.

### 7. Dev tooling

**partial-integrate** — Freqtrade uses GitHub Actions (`freqtrade/.github/workflows/ci.yml`) for multi-version Python testing (3.11, 3.12, 3.13) and coverage gates. JARVIS uses equivalent CI at `.github/workflows/ci.yml` (1443+ passing tests). Freqtrade's test matrix (`strategy_test_.*`) could inspire JARVIS's test naming convention, but JARVIS's PM2 + TypeScript + Python stack is orthogonal. Value: adopt freqtrade's multi-Python-version test matrix (not currently in JARVIS's CI — only tests on active .venv). Effort: add tox or nox config to test against 3.11, 3.12, 3.13.

### 8. Dashboard

**no-fit** — Freqtrade's WebUI (FreqUI, JavaScript/Vue) targets crypto exchange balances and trade history. JARVIS's dashboard (`dashboard/components/`, Tailwind + React) already includes trade tracking, P&L, agent insights, and approval panels. Freqtrade's WebSocket price feed is dedup with `engine/websocket/price_feed.py`.

### 9. Ops / messaging

**dedup-ops** — Freqtrade's Telegram RPC (`freqtrade/rpc/telegram.py`) commands (`/start`, `/stop`, `/status`, `/profit`, `/balance`) are functionally equivalent to JARVIS's OpenClaw WhatsApp + Telegram via `engine/notifications/openclaw_notifier.py:notify_signal` and `engine/notifications/telegram.py`. Freqtrade's dry-run safety layer is parallel to JARVIS's paper trading validation at `engine/backtest/paper_tracker.py` + `engine/execution/paper_trade_logger.py`. No new messaging patterns.

## Integration plan

Three candidate integrations (all partial, risk-averse):

1. **Multi-version Python CI (Surface 7, S effort)**
   - Add `tox.ini` or update `.github/workflows/ci.yml` to test against Python 3.11, 3.12, 3.13 (freqtrade tests all three)
   - Place: `.github/workflows/ci.yml` matrix strategy
   - Rationale: freqtrade discovered issues in py3.13 numpy interop; JARVIS is currently only tested on active .venv
   - Risk: low; CI-only change

2. **Hyperopt loss function library (Surface 1, M effort, deferred pending strategy rotation)**
   - Freqtrade's `freqtrade/optimize/hyperopt_loss/*.py` (5 pre-built loss functions: Sharpe, SortinoHyperOptLoss, MaxDrawDownHyperOptLoss, etc.)
   - Adapt for futures: instead of crypto profit%, use Sharpe ratio + max drawdown + win rate (already at `engine/backtest/metrics.py:compute_sharpe, compute_max_dd, compute_win_rate`)
   - Place: new file `engine/backtest/loss_functions.py`
   - Risk: medium; requires futures-specific calibration; freqtrade uses profit% as signal, JARVIS uses Sharpe (orthogonal metrics)
   - Status: **defer** — valuable only if JARVIS rotates strategy discovery toward multi-loss-function hyperopt (currently uses single composite score)

3. **Lookahead bias detection (Surface 7, M effort, already mostly wired)**
   - Freqtrade's `freqtrade/commands/lookahead_analysis.py` detects when strategy uses future bars in indicator calculations
   - JARVIS already has: `engine/backtest/walk_forward.py:validate_no_lookahead()` (line 62-85, checks trade entry vs. OHLCV timestamps)
   - Action: no integration; status quo at `engine/backtest/walk_forward.py` is sufficient

## License & attribution

GPL-3.0 (freqtrade). Integration requires legal review before copying code. Architectural patterns (walk-forward, Bayesian hyperopt, position sizing) are genre conventions, not IP. If Surface 7 multi-Python CI is adopted, attribute in `.github/workflows/ci.yml` header comment: "Matrix strategy inspired by freqtrade/freqtrade CI."

## Effort estimate

- Multi-version Python CI: S (under 2 hours)
- Hyperopt loss functions: M (2-8 hours, futures calibration required)
- Lookahead bias: skip (already implemented)

**Overall for surfaces 1+7: M** (if adopting both; 6-10 hours total, CI first, loss functions deferred pending strategy discovery roadmap review)

## Red flags

1. **GPL-3.0 copyleft**: Any code copied from freqtrade must be attributed and kept under GPL-3.0. JARVIS's license is not GPL; legal must review before shipping GPL code. Safe path: study patterns only, reimplement in JARVIS style.
2. **Crypto-only**: Freqtrade's exchange connectors (Binance, Kraken, OKX), symbol resolution, and leverage models are crypto-specific. Adapting to equities/futures is nontrivial (e.g., freqtrade assumes 0 or negative funding rates; JARVIS has no funding cost model for MES/MCL/MNQ).
3. **Domain mismatch**: Freqtrade optimizes for 24/7 crypto markets; JARVIS optimizes for 23.5-hour futures (RTH + pre/post-market). Different time-of-day biases, holiday handling, liquidity assumptions.
4. **Maintenance burden**: Freqtrade is active (develop branch pushed Apr 2026) but large (27k stars, 30+ contributors). Diverging from its patterns increases long-term resync cost.

## Recommendation summary

**partial-integrate** with low risk (CI only) + medium future value (loss functions, pending strategy discovery work). Study walk-forward and Bayesian patterns; reuse architectural ideas, not code. Do not copy GPL source without legal review.
