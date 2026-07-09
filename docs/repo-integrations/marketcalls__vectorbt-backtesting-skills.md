---
repo: marketcalls/vectorbt-backtesting-skills
url: https://github.com/marketcalls/vectorbt-backtesting-skills
stars: 168
language: Python
license: MIT
archived: false
pushed_at: unknown (active — recent commits on master)
analyzed_at: 2026-06-26
recommendation: partial-integrate
surfaces_with_value: [skills, docs]
---

# marketcalls/vectorbt-backtesting-skills

## Core value proposition
A Claude Code Skill pack (`.claude/skills/`) that teaches an agent to write and run vectorbt
backtests across Indian (OpenAlgo), US (yfinance), and crypto (CCXT) markets, with realistic
transaction-cost modeling, tearsheets, and a `vectorbt-expert` skill carrying ~20 modular rule
files and ~12 pre-built strategy templates. It ships five workflow skills — `/setup`,
`/backtest`, `/optimize`, `/quick-stats`, `/strategy-compare`. It is a *skills-and-templates*
asset, not a backtest engine.

## How it maps onto jarvis-trader
jarvis-trader lists `vectorbt==0.26.2` in `engine/requirements.txt` but does **not import it
anywhere** — a grep for `import vectorbt` / `vbt.` across `engine/` returns zero hits. The
backtest stack is home-grown and far more sophisticated: `engine/backtest/` includes
`optimizer.py`, `bayesian_optimizer.py`, `walk_forward.py`, `monte_carlo.py`,
`deflated_sharpe.py`, `cpcv.py`, `bar_permute.py`, plus gate-v2 policy. A wholesale skill import
is therefore **dedup** against the engine. The residual value is narrow and lives on the
*skills* surface: the repo's `/optimize`, `/quick-stats`, and `/strategy-compare` skills are
output-formatting/workflow templates that could sharpen the existing
`.claude/skills/backtest-report/SKILL.md` (which today has a six-section report template and a
two-run comparison table).

## Surface analysis

### 1. Engine code
dedup — vectorbt is already a declared (but unused) dependency; `engine/backtest/`
(optimizer.py, bayesian_optimizer.py, walk_forward.py, monte_carlo.py, deflated_sharpe.py,
cpcv.py) supersedes every backtest capability the repo offers. Adopting vectorbt runners would
be a downgrade and a parallel code path.

### 2. Project rules
no-fit — the repo's rule files are vectorbt-API usage rules (data loading, indicator calls,
fees). jarvis-trader's `.claude/rules/` are governance/safety/style rules; point-in-time
discipline is already codified in `.claude/rules/testing.md`.

### 3. Project skills
partial-integrate — the one surface with real value. The `/quick-stats`, `/optimize`, and
`/strategy-compare` skill structures are worth mining as *templates* to enrich
`.claude/skills/backtest-report/` (e.g. an N-way strategy comparison layout, a compact
quick-stats variant). Do NOT add a new vectorbt skill — fold the formatting ideas into the
existing skill.

### 4. Slash commands
no-fit — repo skills carry no standalone commands mapping to jarvis-trader's `.claude/commands/`.

### 5. Subagents
no-fit — jarvis-trader's `backtest-runner` agent already covers WFE/PF/Sharpe/Monte-Carlo
validation against its own engine.

### 6. Docs
defer — the ~12 strategy templates (EMA cross, RSI, Donchian, Supertrend, MACD, Dual Momentum,
Walk-Forward, Realistic-Costs) are readable references; most already have engine equivalents
(`donchian_signals.py`, `generate_supertrend_signals.py`, `meanrev_signals.py`,
`walk_forward.py`). Worth a one-time skim of the cost-modeling and dual-momentum templates only.

### 7. Dev tooling
no-fit — generic `.env.sample`/`requirements.txt`/`.gitignore`; jarvis-trader has stricter
equivalents and pnpm/venv discipline.

### 8. Dashboard
no-fit — pure Python repo, no UI.

### 9. Ops / messaging
no-fit — no ops, scheduling, or messaging surface.

## Integration plan
1. Read the repo's `/quick-stats` and `/strategy-compare` SKILL.md bodies once, purely to
   harvest formatting ideas.
2. If they add a section the current report lacks, propose a small additive edit to
   `.claude/skills/backtest-report/SKILL.md` (e.g. an N-way comparison table, a quick-stats
   one-liner). No new skill file.
3. Optionally note the realistic-costs / dual-momentum templates in a research backlog as ideas.
4. Do NOT wire vectorbt into `engine/backtest/`. Separately worth a housekeeping note that
   `vectorbt==0.26.2` in requirements is a dead dependency.

## License & attribution
MIT — reuse permitted with attribution. Any formatting patterns folded into
`backtest-report/SKILL.md` get a one-line credit ("layout adapted from
marketcalls/vectorbt-backtesting-skills, MIT").

## Effort estimate
S — at most a small additive edit to one existing skill file plus an optional backlog note.

## Red flags
- High risk of *accidental dedup*: importing the vectorbt skills wholesale would create a
  second, weaker backtest path parallel to the mature `engine/backtest/` suite — avoid.
- Market focus is India/OpenAlgo/crypto; jarvis-trader is US micro-futures (MCL/MNQ/MES/MGC) —
  most templates and all fee models are off-target.
- `vectorbt==0.26.2` is a listed-but-unused dependency; the more useful finding is that it is
  removable, not that this repo justifies activating it.
