---
repo: gianfrancopiana/openclaw-autoresearch
url: https://github.com/gianfrancopiana/openclaw-autoresearch
stars: 167
language: TypeScript
license: MIT
archived: false
pushed_at: 2026-04-05T18:39:04Z
analyzed_at: 2026-04-17
recommendation: defer
surfaces_with_value: [dev-tooling, docs, ops-messaging]
---

# gianfrancopiana/openclaw-autoresearch

## Core value proposition

OpenClaw plugin for autonomous experiment loops. Three tools (`init_experiment`, `run_experiment`, `log_experiment`) orchestrate iterative optimization: edit code, measure results, keep/discard, auto-commit to git. Stateful via six repo-root files. Port of `davebcn87/pi-autoresearch` with statistical confidence scoring. File-first design enables agent hand-off without context loss.

## Surface analysis

### 1. Engine code
**no-fit** — Autoresearch is a workflow/orchestration layer, not a trading signal or risk component. jarvis-trader already has manual WFE loop (backtester + Bayesian optimizer at `engine/backtest/bayesian_optimizer.py` + `engine/routers/wfe_router.py:347-383`). Autoresearch would *wrap* that loop, not replace it.

### 2. Project rules
**no-fit** — No coding discipline or safety invariants specific to autoresearch that aren't already in `.claude/rules/`. The plugin enforces its own contract (e.g., "run_experiment refuses to start until prior run is logged") but those are OpenClaw-specific, not trading-domain rules.

### 3. Project skills
**defer** — jarvis-trader has manual experiment loop skills (RL config at `engine/strategies/rl_config.py` + backtest harness at `engine/strategy_lab/competition_harness.py`). Autoresearch could abstract that into `/autoresearch-setup` + `/autoresearch-status` skill, but requires: (a) OpenClaw gateway already deployed on the engine side (currently WSL-based, not integrated into engine startup), (b) decision on whether jar vis-trader runs its own OpenClaw or delegates to user's OpenClaw instance.

### 4. Slash commands
**no-fit** — Autoresearch ships `/autoresearch` + `/skill autoresearch-create` as OpenClaw-native commands. jarvis-trader does not expose OpenClaw shell to engine code; commands are Claude Code side (`.claude/commands/`), not agent-side.

### 5. Subagents
**no-fit** — Autoresearch assumes OpenClaw multi-agent hand-off. jarvis-trader uses synchronous debate/advisor pattern, not async checkpoint files. Different concurrency model.

### 6. Docs
**partial-integrate** — README + `docs/non-parity.md` document the autoresearch contract and OpenClaw-specific gaps well. Value: serve as a reference for documenting jarvis-trader's own experiment loop checkpoint format (currently ad-hoc across RL backtest + WFE + strategy-lab). Not a direct copy, but a design pattern worth studying for `docs/strategy/wfe-loop-checkpoint-contract.md`.

### 7. Dev tooling
**partial-integrate** — Autoresearch's file-based state machine (`.checkpoint.json`, `.lock`, `.jsonl` append log) could inform jarvis-trader's own experiment checkpointing. Currently WFE results live in `.db` only; no resumable state file on disk. Pattern: export `autoresearch.checkpoint` from `engine/backtest/bayesian_optimizer.py` when optimization halts, to enable resume across sessions. Needs: define Pydantic schema for checkpoint (experiment ID, best params, iteration count, timestamp). Effort M (design phase only; actual implementation deferred).

### 8. Dashboard
**no-fit** — Autoresearch explicitly has "no Pi-style widget, dashboard, or editor shortcut layer" (per README). Dashboard value would be generic OpenClaw + file-watch UI (not trading-specific).

### 9. Ops / messaging
**defer** — Autoresearch's cron/scheduler (implied by checkpoint + lock files) could inform jarvis-trader's notification flow when optimization completes (e.g., WhatsApp "WFE complete: best MCL params found"). However, jarvis-trader uses OpenClaw for notifications already (`engine/notifications/openclaw_notifier.py`), so the pattern is already deployed. Autoresearch adds: stateless alerting on checkpoint transitions (`init` → `run` → `log`). Low value unless we surface live experiment progress in morning brief (deferred decision).

## Integration plan

**No immediate integration.** Autoresearch is a *wrapper* around our existing WFE loop, not a replacement. Path forward (if pursued later):

1. **If jarvis-trader auto-restarts its own OpenClaw gateway**: add skill `/autoresearch setup` that wraps `engine/backtest/bayesian_optimizer.py` as `autoresearch.sh` (calls backtest binary with CLI args, emits `METRIC name=value`). Effort: M.
2. **If we keep manual WFE**: study Autoresearch's checkpoint design for inspiration. Add `engine/backtest/wfe_checkpoint.py` Pydantic schema + export at optimization end. Effort: S.
3. **Reference docs**: Save Autoresearch README + non-parity.md into `docs/external-references/` for pattern reference during WFE refactor.

Recommend **defer** until: (a) WFE loop hits a bottleneck (hand-off between sessions, state loss on crash), or (b) OpenClaw integration is prioritized for other reasons.

## License & attribution

MIT. If checkpoint pattern is adopted, attribute in file header of `engine/backtest/wfe_checkpoint.py` (if created).

## Effort estimate

**defer-S** (reference pattern, no code copy needed). If later pursued as full integration: **M** (OpenClaw wiring) to **L** (full autoresearch harness replacement).

## Red flags

- **OpenClaw dependency**: Autoresearch is a plugin, not a library. Using it requires OpenClaw `2026.3.13+` running on the same system. jarvis-trader currently has OpenClaw in WSL only; engine doesn't call OpenClaw directly.
- **Workflow mismatch**: Autoresearch assumes agent hand-off via file state. jarvis-trader uses in-process synchronous debate. Architectural fit is low without refactoring `debate.py` → async checkpoints.
- **No trading-specific value**: Autoresearch is a generic ML optimization tool. No market-aware features (e.g., regime filtering, walk-forward splits by market phase). Would require jarvis-specific instrumentation in `autoresearch.sh`.
