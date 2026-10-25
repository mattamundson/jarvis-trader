# Reference repository mining — Wave 3 (close-out)

**Date:** 2026-09-23
**Scope:** close-out read of the 8 priority reference/vendor forks from the 2026-09-12 audit, tying each repo to the specific JARVIS doc it produced. No vendor code vendored; no live trading surfaces touched.

## Repos reviewed (close-out)

| Repo | Role in audit | JARVIS artifact(s) produced | Status |
|---|---|---|---|
| `mattamundson/claude-trading-skills` | fork/reference — Claude Code skills for traders | `docs/research/claude-trading-skills-intake-gate.md` (authority-tier intake gate), contributed workflow discipline to `strategy-registry-schema.md`, `backtest-critique-checklist.md`, `drawdown-circuit-breaker` pattern influences Sentinel runbook | Mined; intake gate written |
| `mattamundson/awesome-quant` | fork/reference — curated quant library catalog | `docs/research/awesome-quant-tool-intake-gate.md` (tool intake scorecard + 10-point adoption gate), category snapshot (498 parsed entries) | Mined; intake gate written |
| `mattamundson/TradingAgents` | fork/reference — multi-agent LLM trading framework | `docs/research/tradingagents-multi-agent-distillation.md` (role-separated agent architecture, 9-role mapping to JARVIS analogs) | Mined; distillation written |
| `mattamundson/Vibe-Trading` | fork/reference — natural-language multi-agent finance agent | Reviewed as multi-agent/backtest-engine reference; no separate doc created because `tradingagents-multi-agent-distillation.md` already covers the multi-agent decomposition pattern and `awesome-quant-tool-intake-gate.md` covers the backtest-engine intake class. Duplicate doc avoided. | Mined; pattern covered by existing docs |
| `mattamundson/tradingview-mcp` | fork/reference — TradingView Desktop CDP bridge | `docs/research/tradingview-mcp-chart-control-checklist.md` (TVC-1 through TVC-7 boundaries, execution_authority = none contract, screenshot/artifact journal path) | Mined; checklist written |
| `mattamundson/sunday-quant-scientist` | fork/reference — quant newsletter | `docs/research/sunday-quant-scientist-regime-feature-checklist.md` (SQ-1 through SQ-9: HMM regimes, Hurst/ACF gates, tail diagnostics, regime-split reporting, feature-card contract, macro-aware split, walk-forward discipline, window-quality gate, over-fit guard) | Mined; checklist written |
| `mattamundson/fredapi` | source fork — Python FRED/ALFRED API | `docs/research/fredapi-transport-resilience-checklist.md` (H-1 through H-11: client construction side effects, proxy global-opener hazard, XML parse fragility, pagination, ALFRED vintage semantics, Treasury yield-curve hit-testing, offline YAML fixtures) + `docs/research/fred-macro-data-adapter-spec.md` (Wave 5, extended by this pass) | Mined; transport checklist written |
| `mattamundson/lightweight-charts` | fork/reference — HTML5 financial charts | `docs/research/lightweight-charts-dashboard-integration-contract.md` (LC-1 through LC-7: data shape, update/setData semantics, attribution, SSR/client-only boundary, render-lateness classification, visual-regression harness, screenshot parity) | Mined; integration contract written |

## Coverage proof

Every repo in the audit's "Vendor/reference forks to mine" list now has either:
- a dedicated JARVIS doc artifact in `docs/research/`, or
- an explicit "covered by existing doc" note in this summary.

No repo is left with an unverified "TODO" in the consolidation map for the mining dimension.

## What was NOT done (by design)

- No vendor library was installed, vendored, or added as a runtime dependency.
- No backtest engine, market-data connector, or charting library was wired into engine code.
- No live/paper execution, risk limit, kill-switch, broker routing, `.env`, PM2, or scheduled task was changed.
- `Vibe-Trading` and `TradingAgents` were mined for architecture patterns only; their venue-specific execution (crypto, prediction markets) was explicitly excluded from futures JARVIS.
- `awesome-quant` high-visibility entries (OpenBB, freqtrade, ccxt, Qlib, NautilusTrader, backtrader, zipline, Lean) are captured as "requires intake review" examples, not endorsements.

## Next implementation candidates (still open)

These are doc-complete but not yet implemented in engine/dashboard code — they remain research/control artifacts until a separate safety-reviewed PR wires them in:

1. Strategy registry — machine-readable JSON entries per `strategy-registry/schema.json`; the YAML schema (`strategy-registry-schema.md`) and worked example (`strategy-registry/examples/`) are written; an initial seed entry is the next concrete step.
2. Backtest critique — the checklist is written; a filled-in example critique artifact for a real candidate strategy is the next concrete step.
3. Chart review runbook — written; the dashboard-side Lightweight Charts harness and TradingView MCP capture script are open implementation items.
4. Macro/FRED regime-context spec — written; the engine-side adapter with offline fixtures and vintage policy is an open implementation item.
5. Sentinel/observability runbook — written; concrete probe scripts owned by ops/home-scripts are an open implementation item.
6. Agent operating commands — the claude-trading-skills workflow discipline (market brief, pretrade check, strategy review, backtest critique, journal entry, postmortem) is the template; encoding these as audited Hermes skills / JARVIS commands is a later wave.

## Related

- Wave 2 mining summary: `docs/research/reference-repo-mining/2026-09-12-wave2-reference-mining.md`
- Strategy registry schema: `docs/research/strategy-registry-schema.md`
- Strategy registry machine-readable ledger: `docs/research/strategy-registry/README.md`
- Backtest critique checklist: `docs/research/backtest-critique-checklist.md`
- Chart review runbook: `docs/research/chart-review-runbook.md`
- Macro/FRED regime-context spec: `docs/research/macro-regime-context-spec.md`
- Sentinel/observability runbook: `docs/research/sentinel-observability-runbook.md`
- Wave 1 import provenance: `docs/research/imported-repos/2026-09-12-wave1/README.md`
- Audit: `C:/Users/mattm/AppData/Local/Temp/github_repo_deep_dive/GITHUB_REPO_CONSOLIDATION_TRADING_AUDIT_2026-09-12.md`
