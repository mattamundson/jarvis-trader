# ATLAS/GIC autoresearch risk contract

Status: docs/tests-only research-control artifact. No live trading config, paper trading config, risk limits, kill-switch state, broker routing, API keys, `.env` files, PM2 process definitions, active instrument gates, or order behavior are changed.

## Source evidence

| Source repo | Reference commit | License | Files reviewed |
|---|---:|---|---:|
| `mattamundson/atlas-gic` | `fcfc40dcf628f6af091c28cb2c33827f42cef8fd` (`main`, 2026-05-27) | `NOASSERTION` | 6 selected files |

Selected source files were downloaded through the GitHub API and hashed in `C:/Users/mattm/AppData/Local/Temp/repo_consolidation_sources/wave27_atlas_autoresearch/`.

Representative files:

- `README.md`
- `architecture/autoresearch.md`
- `architecture/overview.md`
- `architecture/layers.md`
- `results/summary.json`
- `results/autoresearch_log.json`

## Why this is not covered by prior waves

Wave 15 covers multi-agent debate QA. `docs/n-autoresearch-integration.md` covers an older JARVIS sidecar for RL hyperparameter search and explicitly defers sweeps until the metric is proven. ATLAS/GIC adds a different failure mode: **prompt evolution can show local Sharpe improvements while the portfolio-level campaign still loses money**.

The mined ATLAS fixture reports:

- 378 trading days from 2024-09-01 to 2026-03-07.
- Starting value: 1,000,000.
- Ending value: 940,937.77.
- Campaign return: -5.91%.
- Autoresearch modifications attempted: 54.
- Kept: 16.
- Reverted: 37.
- Keep rate: 29.6%.
- Parsed log rows with pre/post Sharpe: 16.
- Parsed pre/post rows improved: 14.
- Parsed rows with non-positive post-change Sharpe: 15 of 16.

JARVIS import rule: local prompt-metric improvement is not alpha evidence unless the campaign-level economic scoreboard, out-of-sample stability, and risk gates also improve.

## Transferable controls

### 1. Optimize the campaign scoreboard, not the prompt scoreboard

ATLAS describes rolling agent Sharpe as the loss function for prompt edits. JARVIS may store prompt-level metrics, but promotion decisions must rank the campaign by:

- net P&L and CAGR,
- max drawdown and drawdown duration,
- trade count and trades/year,
- profit factor and confidence interval,
- walk-forward or out-of-sample stability,
- bootstrap/Monte Carlo ruin risk,
- transaction-cost survival,
- parameter/prompt sensitivity,
- blocked-symbol and instrument-universe compliance.

If prompt Sharpe improves but the campaign return, drawdown, or validation gate worsens, the edit is a failed research experiment.

### 2. Keep/revert decisions need statistical and economic floors

A prompt edit can be `kept` only when all hard floors pass:

| Gate | Required evidence | Pass condition |
|---|---|---|
| Baseline identity | Prompt hash, model/provider, tool list, data window | Baseline and candidate differ only by the intended prompt change |
| Sample horizon | Forward-test window and minimum observations | Enough independent decisions to avoid one-event survival |
| Economic scoreboard | P&L/CAGR, drawdown, cost model, trade count | Campaign-level economics improve after costs |
| Statistical scoreboard | Sharpe/Sortino, PF CI, bootstrap/MC, DSR where applicable | Improvement survives uncertainty adjustment |
| Regime split | VIX/macro/session regime buckets | Improvement is not isolated to one accidental regime unless explicitly scoped |
| Safety boundary | allowed_symbols, blocked_symbols, config/risk diff receipt | No live/risk/kill-switch/broker/symbol mutation |
| Revert receipt | Branch, commit, revert decision, blocked reasons | Failed edits leave an auditable trail and no active behavior change |

### 3. Darwinian weights are research weights only

ATLAS uses weight floors/ceilings of 0.3 and 2.5. In JARVIS, any Darwinian or historical-IC weight may only affect research prioritization until separately validated. It must not:

- override deterministic risk gates,
- route orders,
- add or remove tradable symbols,
- alter position sizing,
- suppress a risk reviewer,
- bypass human approval for promotion.

### 4. Agent spawning requires a no-routing quarantine

ATLAS spawns new specialists when repeated blind spots appear. JARVIS may create research-only specialist prompts, but a spawned agent must be quarantined until it has:

- explicit mandate and instrument universe,
- prompt hash and owner/run id,
- no broker/order/tool access,
- point-in-time data rules,
- static safety scan for any generated code,
- at least one failed-safe output schema,
- evidence of useful critique against known verdict artifacts.

Spawning a role is never permission to trade a role.

### 5. Reflexivity scenarios are stress tests, not forecasts

ATLAS includes reflexive loops such as price-to-fundamentals, P&L-to-behavior, narrative-to-flows, market-to-policy, and reflexive reversal detection. In JARVIS these belong in scenario analysis and market briefs only. They can enrich invalidation logic, but they cannot serve as trade-entry proof without independent price/data validation.

## JARVIS prompt-autoresearch gate

Before an autonomous prompt or research-agent mutation can affect dashboards, strategy registry state, or promotion queues, require this gate:

| Gate | Required evidence | Fail-closed condition |
|---|---|---|
| Immutable source | Source repo/commit, file hashes, license/status | Missing source hash or unknown modified source |
| Experiment branch | Dedicated worktree/branch, one intended prompt delta | Main-branch mutation or broad unreviewed diff |
| Prompt identity | Before/after prompt hash, model/provider, temperature | Opaque prompt/model drift |
| Data boundary | Decision timestamps, as-of data, no future leakage | Outcome-aware data available to the candidate |
| Economic score | P&L/CAGR/DD/cost/trade count | Local score improved but economics degraded |
| Statistical score | Sharpe/Sortino/PF CI/DSR/MC where applicable | Improvement not robust to uncertainty |
| Safety score | Config/risk/broker/.env/PM2/symbol diff receipt | Any live trading or runtime surface changed |
| Revertability | Keep/revert verdict and rollback receipt | Failed candidate leaves active artifacts behind |
| Promotion verdict | `RESEARCH_ONLY`, `REJECTED`, or `VALIDATION_CANDIDATE` | Any missing hard gate yields `RESEARCH_ONLY` or `REJECTED`, never `VALIDATION_CANDIDATE` |

## Safe implementation candidates

Allowed follow-ups from this artifact:

1. Add a schema for `prompt_autoresearch_experiment` artifacts.
2. Add fixture-only validation tests for prompt hash, model config, source hash, economic scoreboard, and keep/revert receipts.
3. Add read-only dashboard display of prompt-autoresearch experiments as `research-only` evidence.
4. Add a static check that blocks generated strategy snippets with top-level broker/network/credential side effects.
5. Add a report template that compares prompt-level improvement against campaign-level economic score.

Blocked without a dedicated `[safety-review]` PR and explicit human approval:

- Running autonomous prompt sweeps against live paper order routing.
- Changing `engine/config.py`, `engine/risk/`, kill-switch logic, active instrument gates, `.env`, PM2, broker routing, or order behavior.
- Allowing prompt weights to alter position sizing or route orders.
- Promoting a prompt-mutated strategy from narrative or local Sharpe improvement alone.

## Recommended next implementation candidate

Create a docs/tests-only `prompt_autoresearch_experiment` JSON schema and fixture validator. The first fixture should intentionally include the ATLAS evidence pattern where most local pre/post Sharpe deltas improve but campaign return remains negative, proving JARVIS fails closed on campaign-level economics.
