---
name: jarvis-search-discipline
description: Research-before-coding workflow adapted for jarvis-trader. Search existing engine modules, trading libraries (vectorbt, optopsy, mlfinlab), installed MCP servers, and the Obsidian second-brain vault BEFORE writing custom code. Triggers on adding a new signal, indicator, agent, backtest, data source, or utility — anywhere a new abstraction is about to be created. Replaces ad-hoc "just grep and start typing" habits.
---

# jarvis-search-discipline

_Adapted from [affaan-m/everything-claude-code](https://github.com/affaan-m/everything-claude-code) `search-first` skill (MIT). Originals are domain-neutral; this version routes specifically to the trading stack._

## When to use

Before writing ANY of the following, run this workflow:

- A new signal in `engine/backtest/signals.py` or `engine/agents/composite_signals.py`
- A new indicator helper in `engine/indicators/` or `engine/analytics/`
- A new agent in `engine/agents/`
- A new backtest harness in `engine/backtest/`
- A new data source in `engine/data/`
- A new Python utility that feels "general-purpose"
- A new TypeScript helper in `dashboard/lib/`
- A new MCP tool wrapper

## The five-step flow

```
1. NEED ANALYSIS        What exactly is needed? Inputs, outputs, constraints.
2. PARALLEL SEARCH      engine/ grep | trading libs | MCP tools | vault | GitHub
3. EVALUATE             Score: fit, license, maintenance, WFE impact if applicable
4. DECIDE               Adopt | Extend | Compose | Build
5. IMPLEMENT            Install / wire MCP / write minimal custom code
```

## Step 1 — `engine/` grep (always first)

Duplicate code is worse than missing code. Before anything external:

```bash
cd /c/Users/mattm/ThinkorSwim/jarvis-trader
grep -rn "<concept>" engine/ --include="*.py" | head
ls engine/indicators/ engine/analytics/ engine/utils/ engine/agents/
```

Specific known locations to grep:

| Need | Existing likely-home |
|---|---|
| Signal / indicator | `engine/backtest/signals.py`, `engine/backtest/composite_signals.py`, `engine/indicators/` |
| Multi-agent orchestration | `engine/agents/debate.py`, `engine/agents/pipeline.py` |
| Risk / sizing | `engine/risk/safety_layer.py`, `engine/agents/trader.py:290-293` |
| Regime detection | `engine/agents/pipeline.py:537-585` (hidden pivots), `engine/indicators/` |
| LLM calls | `engine/llm/client.py`, `engine/agents/advisor_client.py` |
| Backtest | `engine/backtest/`, `engine/strategy_lab/` |
| Data fetch | `engine/data/`, `engine/discord/`, `engine/scanner/` |
| Cache / token budget | `engine/utils/token_optimizer.py`, `engine/utils/token_proxy.py` |

## Step 2 — trading-library shortlist

Before reaching for scipy + pandas from scratch, check these first (all paper-approved, where listed):

### Backtest + walk-forward
- `vectorbt` — fast backtest, already-compatible with pandas frames
- `backtrader` — event-driven backtest engine
- `mlfinlab` (López de Prado) — purged CV, meta-labeling, fractional differentiation
- `bt` — composable strategies

### Options
- `optopsy` — options backtester (**already integrated**: `engine/backtest/options_backtester.py`)
- `QuantLib-Python` — pricing / Greeks

### Indicators
- `ta-lib` (wraps TA-Lib binary) — already available
- `pandas-ta` — pure-Python, often faster to install than ta-lib on Windows
- `finta` — minimal dependency-free lib

### Regime / stat-arb
- `arch` — GARCH, volatility models
- `statsmodels` — Engle-Granger, VAR, Kalman (already used in `engine/analysis/pair_spread.py`)

### Microstructure
- `tradingview-technical-analysis` — TV-parity indicators
- `polygon-api-client` — already in use, rate-limited free tier

## Step 3 — MCP shortlist

```bash
claude plugin list
# or inspect /.mcp.json and ~/.claude.json
```

Known available MCPs on this machine:
- Alpaca MCP (`uvx alpaca-mcp-server`) — quotes, orders, account
- TradingView MCP — if `npm link tv` has run
- Chrome DevTools MCP — CDP for chart capture (Pattern Agent prerequisite)
- Playwright MCP — browser automation
- Brave search, Codex CLI, Firecrawl, Claude Mem — already wired

## Step 4 — vault / digest lookup

The Obsidian second-brain vault at `C:/Users/mattm/second-brain/` has ~283 wiki pages indexing Discord + X bookmarks by jarvis-trader module. Before inventing something, check:

```bash
grep -rl "<concept>" C:/Users/mattm/second-brain/wiki/discord-bookmarks/
ls C:/Users/mattm/ThinkorSwim/jarvis-trader/docs/repo-integrations/
```

If an analysis doc exists, the research is done — read it and decide adopt/defer/noise.

When the engine is running, prefer the structured `/vault status` query (or `curl
/vault/status`) over raw `grep` — it reports per-folder note counts and the latest
synthesis / lint / contradiction reports. See `.claude/skills/jarvis-vault/SKILL.md`.

## Step 5 — GitHub code search (last resort)

```bash
gh search code "<keywords>" --owner <likely_owner> --limit 20
gh search repos "<concept> futures trading" --limit 20
```

## Decision matrix

| Signal | Action |
|---|---|
| Exact match in `engine/`, well-tested | **Stop — reuse**, do not re-implement |
| Exact match in trading library, MIT/Apache/BSD | **Adopt** — add to `engine/requirements.txt`, thin wrapper if style mismatch |
| Partial match in trading library | **Extend** — install + wrapper in `engine/utils/` or `engine/analysis/` |
| Multiple weak matches | **Compose** — combine 2 small packages rather than one large |
| Nothing suitable | **Build** — write custom; document why in module docstring |
| Match exists but GPL / unclear license | **Ideas only** — read the paper/code for patterns, do not copy |

## Anti-patterns

- Jumping to code without a 60-second `engine/` grep — you'll duplicate existing helpers.
- Installing a huge dependency (e.g., `scikit-learn`) for one small function — prefer `scipy.stats` or hand-rolled if tiny.
- Writing a new agent in `engine/agents/` without checking whether `advisor_client.py` or `debate.py` can absorb the logic.
- Grep-bypassing: if you can't find something, assume it *might exist* under a different name before writing net-new code.
- Ignoring the repo-integrator backlog: `docs/repo-integrations/` already has 15 analyses; future reads belong there.

## Integration with existing skills

- **Before `ce:plan`** — run this skill to surface pre-existing code the plan should reuse.
- **Before launching 10 parallel agents** — run this skill to save agent time on duplicated lookups.
- **Before a Tier 3 safety review** — verifies the change isn't reinventing a safety-layer helper.

## Examples

**Example 1 — "Add an ADX filter to the debate stack"**
```
Step 1 (engine grep):  grep -rn "adx" engine/indicators/ engine/backtest/
                       → already exists at engine/indicators/adx.py? (check first)
Step 2 (lib):          pandas-ta has ADX; ta-lib has ADX.
Step 3 (MCP):          N/A — indicator is local math.
Step 4 (vault):        no relevant analysis.
Decision:              REUSE existing helper if found, else ADOPT pandas-ta (already in engine/requirements.txt).
Result:                zero new code if already in engine/, else one-line import.
```

**Example 2 — "Add volume profile to dashboard"**
```
Step 1:     grep -rn "volume.profile\|vp" dashboard/components/ engine/indicators/
Step 2:     tradingview lightweight-charts already has the primitives, but not a built-in VP.
Step 3:     N/A.
Step 4:     docs/repo-integrations/Algoman123__Dashboard123.md has monitoring panel patterns.
Decision:   EXTEND — compute VP in engine, render via Tailwind grid on dashboard side.
Result:     one new engine helper + one React component, no new deps.
```

## Attribution

Original: [affaan-m/everything-claude-code](https://github.com/affaan-m/everything-claude-code) (MIT). Adapted for jarvis-trader's trading stack — shortcuts rewritten to target Python scientific + trading libraries, MCP server inventory swapped to this machine's installed set, vault-lookup step added. See `docs/repo-integrations/affaan-m__everything-claude-code.md` for the full cross-reference analysis.
