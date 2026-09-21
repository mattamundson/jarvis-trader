# Wave 2 — trading-system leverage docs

**Status:** draft · **Created:** 2026-09-20 · **Source audit:** `GITHUB_REPO_CONSOLIDATION_TRADING_AUDIT_2026-09-12.md`

Distilled docs from reference repos mined for JARVIS strategy/tooling additions. All files are new JARVIS-native content, not vendored forks. Each doc lists its source notes.

## Docs

| Doc | Purpose | Primary sources mined |
|---|---|---|
| `strategy-registry.md` | Strategy registry schema, fields, promotion gate | `claude-trading-skills/skills-index.yaml` (verification-contract pattern), audit report |
| `backtest-critique-checklist.md` | Backtest critique checklist before `backtest_pass` | `claude-trading-skills/backtest-expert`, audit report |
| `chart-review-runbook.md` | TradingView + Lightweight Charts review workflow | `tradingview-mcp/README.md`, `lightweight-charts` |
| `macro-fred-regime-context-spec.md` | FRED/macro as regime context, never direct trade signal | `fredapi/README.md`, `claude-trading-skills/macro-regime-detector` |
| `observability-sentinel-runbook.md` | JARVIS observability probe inventory and alert contract | `claude-trading-skills/drawdown-circuit-breaker`, `pre-trade-discipline-gate`, `position-sizer` |

## Reference repos mined (not vendored)

- `mattamundson/claude-trading-skills` — skill index + backtest expert + pre-trade discipline + position sizer + drawdown circuit breaker + macro regime detector
- `mattamundson/tradingview-mcp` — TradingView CDP chart-capture workflow and safety stance
- `mattamundson/fredapi` — FRED/ALFRED Python API, point-in-time/vintage handling
- `mattamundson/lightweight-charts` — open-source charting library (native review candidate)

## Provenance rule

Each doc's "Source notes" section records what was mined and that content was distilled, not vendored. No reference repo code is copied into the JARVIS tree without an explicit per-repo decision and a separate PR.

## Next

- Review these docs with Amo before promoting any to a formal registry record or backtest gate.
- After review, the registry schema can be implemented as a YAML schema + registry table; the checklist can attach to the existing backtest journal workflow.
