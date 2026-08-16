---
repo: mattamundson/autotrade
url: https://github.com/mattamundson/autotrade
stars: 0
language: Python
license: none (Amo's own repo, no separate license needed)
archived: false
pushed_at: 2026-04-22T22:48:09Z
analyzed_at: 2026-08-15
recommendation: partial-integrate
surfaces_with_value: [engine code, docs]
---

# mattamundson/autotrade

## Core value proposition

An early (2026-04-22), never-revisited prototype for autonomous LLM-driven strategy research: `src/program.md` specs an experiment loop that hands a full CLI coding agent (Claude Code / Codex / Gemini CLI, with Read/Write/Edit/Bash) the ability to author entirely new `BaseStrategy` subclasses from scratch — different indicators, pyramiding/position-scaling logic, long/short state machines — backtest them, log verdicts to `results.jsonl`, and iterate indefinitely. It also ships a self-contained `ccxt`-based crypto exchange abstraction (`src/data/crypto/exchange.py`) with caching and normalization. This surfaced during a GitHub repo-consolidation audit as a genuine, unimplemented-elsewhere capability rather than a duplicate of anything in jarvis-trader — it was flagged for archiving on name/README alone in a first pass, then found on a content-level re-check to contain real, novel design.

## Surface analysis

### 1. Engine code
`partial-integrate` — two genuinely distinct, unimplemented capabilities, not a duplicate of `engine/strategy_lab/strategy_loop.py` or `engine/strategies/discovery_loop.py` (which credit a *different* third-party repo, `rv64m/autotrade`, as inspiration — a naming coincidence, not the same codebase). jarvis-trader's own `strategy_generator.py` only varies 7 numeric params of one fixed STC+ATR template via a JSON-constrained LLM call; it never authors freeform strategy *code*. This repo's pattern does. Also checked against `.claude/skills/rl-strategy-discovery/SKILL.md` — that's a PPO/reinforcement-learning approach to filling `engine/strategies/`, a different mechanism entirely (trained agent vs. LLM code-generation loop); no overlap.
- Crypto (`src/data/crypto/exchange.py`, ccxt): jarvis-trader currently has zero crypto support and is scoped to futures/options per `CLAUDE.md`. This is a genuine product-scope decision for Amo (add an asset class?), not an engineering task — flagged `defer` pending that call, not `integrate-now`.
- Open-ended strategy-code-generation loop: would let an LLM agent write and backtest arbitrary new `BaseStrategy` subclasses unattended. This is a real capability gap worth having, but per `meta-discipline.md`/`safety.md`, anything that generates code destined for backtesting-then-possible-execution needs a `[safety-review]` tag and a human-loop design before any live-adjacent wiring — flagged `defer`, not `integrate-now`, pending that review.

### 2. Project rules
`no-fit` — no coding-discipline or safety pattern beyond what's already in `.claude/rules/`.

### 3. Project skills
`no-fit` — distinct from `rl-strategy-discovery` (see above), but not itself a packaged skill; the underlying idea could become one if item 1 above is greenlit.

### 4. Slash commands
`no-fit`.

### 5. Subagents
`no-fit`.

### 6. Docs
`integrate-now` — this doc itself preserves the design (`src/program.md`'s experiment-loop spec and `src/reference/risk.md`) so it isn't lost to a read-only archive. No further doc action needed beyond this file.

### 7. Dev tooling
`no-fit`.

### 8. Dashboard
`no-fit`.

### 9. Ops / messaging
`no-fit`.

## Integration plan

No code changes proposed in this pass — both real findings (crypto asset-class expansion, open-ended strategy-code-generation loop) are product/safety decisions for Amo, not mechanical ports. If greenlit:
- Crypto: would land as a new `engine/data/crypto/` source module, gated behind an explicit config flag, with its own safety/risk review before any execution path exists.
- Code-generation loop: would extend `engine/strategy_lab/` with an LLM-authored-strategy path (distinct from today's param-only `strategy_generator.py`), requiring a `[safety-review]`-tagged PR and a backtest-only gate before any live-adjacent consideration.

## License & attribution

Amo's own unlicensed personal repo — no third-party attribution required. If ideas are ported, credit `mattamundson/autotrade` in the relevant commit message per house convention (see e.g. `strategy_loop.py`'s existing "Inspired by" comment style).

## Effort estimate

M (2-8hr) to prototype the code-generation loop behind a flag; separate scope decision (not an effort estimate) for whether crypto support is wanted at all.

## Red flags

Repo itself is stale (last pushed 2026-04-22, never revisited) and was originally misjudged as safe to archive outright on a README-only pass — this doc exists specifically to correct that. No security or license concerns. The crypto and code-generation items are genuinely optional, not urgent; this doc's purpose is to make sure the design isn't lost if `mattamundson/autotrade` is archived later, not to force integration now.
