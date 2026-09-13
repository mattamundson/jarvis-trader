# Multi-agent trading research QA gate

Status: docs-only research-control artifact. No live trading config, paper trading config, risk limits, kill-switch state, broker routing, API keys, `.env` files, PM2 process definitions, active instrument gates, or order behavior are changed.

## Sources mined

| Source repo | Reference commit | License | Files reviewed |
|---|---:|---|---:|
| `mattamundson/TradingAgents` | `9dee508c44662702281a8dbaad1f7b42179b5ba7` (`main`, 2026-09-01) | Apache-2.0 | 19 |
| `mattamundson/Vibe-Trading` | `f51fc8f829da04d13cfe1e54f83525e973a4cbf3` (`main`, 2026-06-30) | MIT | 20 |

Selected source files were downloaded through the GitHub API and hashed in `C:/Users/mattm/AppData/Local/Temp/repo_consolidation_sources/wave15_source/selected_files_manifest.json`.

Representative files:

- `TradingAgents/README.md`
- `TradingAgents/tradingagents/default_config.py`
- `TradingAgents/tradingagents/agents/schemas.py`
- `TradingAgents/tradingagents/agents/utils/agent_states.py`
- `TradingAgents/tradingagents/agents/utils/structured.py`
- `TradingAgents/tradingagents/graph/trading_graph.py`
- `TradingAgents/tradingagents/graph/conditional_logic.py`
- `TradingAgents/tradingagents/graph/reflection.py`
- `TradingAgents/tradingagents/graph/signal_processing.py`
- `TradingAgents/tradingagents/agents/trader/trader.py`
- `TradingAgents/tradingagents/agents/managers/research_manager.py`
- `TradingAgents/tradingagents/agents/managers/portfolio_manager.py`
- `TradingAgents/tests/test_debate_opening.py`
- `TradingAgents/tests/test_risk_router_path_map.py`
- `TradingAgents/tests/test_memory_pointintime.py`
- `TradingAgents/tests/test_structured_agents.py`
- `Vibe-Trading/README.md`
- `Vibe-Trading/agent/SKILL.md`
- `Vibe-Trading/agent/backtest/validation.py`
- `Vibe-Trading/agent/backtest/run_card.py`
- `Vibe-Trading/agent/src/scheduled_research/models.py`
- `Vibe-Trading/agent/src/scheduled_research/executor.py`
- `Vibe-Trading/agent/src/live/runtime/liveness.py`
- `Vibe-Trading/agent/src/live/runtime/reconcile.py`
- `Vibe-Trading/agent/src/swarm/runtime.py`
- `Vibe-Trading/agent/src/swarm/presets/risk_committee.yaml`
- `Vibe-Trading/agent/src/swarm/presets/quant_strategy_desk.yaml`
- `Vibe-Trading/agent/src/swarm/presets/macro_strategy_forum.yaml`
- `Vibe-Trading/agent/tests/test_backtest_runner_security.py`
- `Vibe-Trading/agent/tests/test_scheduled_research_executor.py`
- `Vibe-Trading/agent/tests/test_runtime_liveness.py`

## Transferable controls

The two reference projects are useful for JARVIS only as research-process controls. They are not evidence that an LLM or multi-agent stack has tradable edge on SPY, QQQ, VIX, MES, or any other instrument.

### 1. Role separation must be observable

`TradingAgents` separates analyst, researcher, trader, risk, and portfolio-manager roles. The useful control is not the role names; it is the forced handoff chain:

1. analysts create evidence reports,
2. bull/bear researchers debate the reports,
3. a research manager summarizes the debate,
4. a trader converts the plan into a proposal,
5. conservative/neutral/aggressive risk debaters challenge the proposal,
6. a portfolio manager makes the final decision.

JARVIS should treat any multi-agent trading research result as invalid unless the artifact preserves each role output separately. A single merged narrative is insufficient because it hides whether risk review happened before or after the bullish thesis was accepted.

### 2. Debate rounds need protocol tests

`TradingAgents/tests/test_debate_opening.py` protects against a failure mode where the first speaker rebuts a nonexistent opponent. `tests/test_risk_router_path_map.py` protects graph routing by requiring every risk/debate branch to map to a known node.

JARVIS import rule: every debate-style research workflow must log:

- first-speaker opening statement with no synthetic opponent claim,
- speaker order,
- debate round count,
- node/role identifiers,
- terminal routing decision,
- rejected branch reasons.

If the run cannot prove that the risk branch executed in the expected order, it remains research-only and cannot feed strategy promotion scoring.

### 3. Structured outputs are mandatory, free-text is supporting evidence only

`TradingAgents/agents/schemas.py` defines typed schemas for research plans, trader proposals, and portfolio decisions. `agents/utils/structured.py` binds provider-native structured output where available and falls back to free text only when structured invocation is unsupported.

JARVIS import rule: the promotion artifact must contain parseable JSON fields for:

- `role_outputs[]`,
- `instrument_universe`,
- `allowed_symbols`,
- `thesis`,
- `invalidation`,
- `data_sources`,
- `decision`,
- `risk_review`,
- `promotion_verdict`,
- `blocked_reasons[]`.

Free-text analysis can explain the decision, but cannot be the decision record.

### 4. Point-in-time memory is a hard gate

`TradingAgents/tests/test_memory_pointintime.py` enforces point-in-time-safe memory lookups for backtests, excluding legacy entries whose resolution date cannot prove they were known at the decision date.

JARVIS import rule: an agent memory snippet may be used in historical research only when it has:

- memory creation timestamp,
- resolution/outcome timestamp when outcome is referenced,
- query `as_of` timestamp,
- provenance path or hash,
- explicit flag for legacy entries with unknown resolution date.

Unknown-resolution historical memories are excluded from backtest evidence. They can be used for operator context only.

### 5. Model configuration must be replayable enough to audit

`TradingAgents/default_config.py` exposes debate-round counts, risk-round counts, temperature, memory-log path, and provider/model settings. The README documents setting `temperature = 0.0` for tighter reproducibility when the provider supports it.

JARVIS import rule: every multi-agent research artifact must disclose:

- provider and model for each role,
- temperature or equivalent sampling controls,
- debate and risk-round counts,
- prompt or prompt-version hash,
- tool list per role,
- memory-log path/hash if memory was used.

If any role uses opaque model configuration, the artifact can be stored but not promoted.

### 6. Research swarms need dependency and cancellation evidence

`Vibe-Trading/agent/src/swarm/runtime.py` models parallel layers, serial dependencies, cancellation, and dependency failure handling. Its quant and risk preset YAML files explicitly separate screening/factor/backtest/risk-audit roles.

JARVIS import rule: any parallel research swarm must emit a dependency graph with:

- role id,
- declared inputs,
- declared outputs,
- required predecessor ids,
- actual start/end timestamps,
- status,
- cancellation flag,
- skipped-because-predecessor-failed flag.

A portfolio/risk summary produced without its required predecessor evidence is a failed run, not a partial pass.

### 7. Backtest claims need run cards and validation receipts

`Vibe-Trading/agent/backtest/run_card.py` emits JSON/Markdown run cards with config summaries, hashes, metrics, and validation sections. `agent/backtest/validation.py` includes walk-forward validation, bootstrap-style stability checks, and parameter-sensitivity controls.

JARVIS import rule: agent-generated strategy ideas may not enter the strategy registry unless the candidate has a run card containing:

- immutable config hash,
- data source and date range,
- instrument universe,
- entry/exit logic hash,
- cost/slippage assumptions,
- metrics and validation receipts,
- walk-forward or out-of-sample partition summary,
- parameter-sensitivity result,
- bootstrap or confidence interval where applicable,
- failure reasons for any missing validation.

A narrative strategy idea without a run card remains an idea, not a candidate.

### 8. Tool-generated code is not trusted by default

`Vibe-Trading/agent/tests/test_backtest_runner_security.py` rejects signal-engine files with top-level or class-level execution. This is directly relevant to LLM-generated strategy code.

JARVIS import rule: generated research code must pass static safety checks before execution:

- no top-level network, subprocess, file-write, broker, or order-router actions,
- no class-level execution side effects,
- no `.env` or credential reads,
- no imports from live broker/order modules,
- no mutation of JARVIS config, risk, kill-switch, or instrument gates.

Failing this check blocks execution and promotion.

### 9. Scheduled research needs fail-closed liveness

`Vibe-Trading/agent/src/scheduled_research/models.py` and `executor.py` model persisted scheduled jobs and due-job dispatch. `agent/src/live/runtime/liveness.py` treats unreadable or malformed liveness state as no signal; `agent/tests/test_runtime_liveness.py` verifies the fail-closed behavior.

JARVIS import rule: scheduled multi-agent research must record:

- job id,
- prompt/query hash,
- schedule definition,
- next due timestamp,
- last dispatch timestamp,
- terminal status,
- retry count,
- liveness heartbeat,
- malformed-heartbeat handling.

If liveness cannot be read, the job is stale/unknown and must not produce a green promotion signal.

### 10. Reconciliation is separate from decision generation

`Vibe-Trading/agent/src/live/runtime/reconcile.py` classifies broker/runtime deltas through injected read callables and persists state only after clean reconciliation. JARVIS should import the separation, not the live-runtime behavior.

JARVIS import rule: a research-agent decision must never imply execution truth. Decision artifacts and account/runtime truth must remain separate ledgers. Any future execution adapter would require a dedicated `[safety-review]` PR and explicit human approval.

## JARVIS multi-agent research QA gate

Before a multi-agent trading research run can affect JARVIS dashboards, strategy registry entries, or promotion queues, require this gate:

| Gate | Required evidence | Pass condition |
|---|---|---|
| Source provenance | Reference repo/commit or local code commit, file list, file hashes | Every imported idea is traceable to an immutable artifact |
| Run identity | Run id, created timestamp, operator/session id, prompt hash | One run maps to one immutable artifact set |
| Instrument boundary | Allowed symbols and blocked symbols | No generated symbol outside the JARVIS allowed universe; halted symbols remain blocked |
| Role separation | Raw output for every analyst/research/trader/risk/PM role | Each role output exists and is timestamped before downstream roles consume it |
| Dependency graph | DAG with predecessors and terminal status | No downstream role passes if required predecessor failed, skipped, or was canceled |
| Debate protocol | Speaker order, round count, opening markers, router path | No phantom-opponent rebuttal; risk branch executed in the expected order |
| Structured decision | Valid JSON schema for the final decision | Parses without free-text inference; missing required fields fail the run |
| Point-in-time data | Feature timestamps, memory `as_of`, data source timestamps | No future data, unresolved historical memory leakage, or unknown-resolution memory |
| Model configuration | Provider, model, temperature, prompt hash, tool list per role | Replay/audit metadata is complete enough to reproduce the decision path |
| Evidence grounding | Source URLs/files/endpoint snapshots attached per claim | Claims about price, macro, news, order book, or fundamentals cite raw evidence |
| Risk review | Conservative/neutral/aggressive or equivalent risk analyses | Tail risk, liquidity, concentration, and invalidation are addressed before final verdict |
| Static code safety | Generated code scanner receipt | No top-level/class-level side effects, no credential reads, no live broker/order imports |
| Backtest run card | Config hash, data range, cost model, metrics, validation receipts | Strategy ideas have deterministic backtest evidence before registry promotion |
| Liveness | Scheduled-job heartbeat and terminal status | Stale, malformed, or missing heartbeat fails closed |
| Reconciliation boundary | Decision ledger distinct from runtime/account truth | No research artifact claims execution, fill, or PnL truth without separate source-of-truth readback |
| Promotion verdict | PASS/FAIL/RESEARCH_ONLY plus blocked reasons | Any missing hard gate yields FAIL or RESEARCH_ONLY, never PASS |

## Failure modes to test explicitly

1. Role collapse: one model writes both bullish thesis and final risk approval.
2. Phantom debate: first risk speaker rebuts a nonexistent prior argument.
3. Router drift: renamed role/node silently skips a risk or debate branch.
4. Free-text decision: final action requires regex/LLM inference instead of schema parsing.
5. Memory leakage: historical backtest sees outcome-aware reflections not known at the trade date.
6. Hidden model drift: role model, temperature, or prompt changes without artifact versioning.
7. Generated-code side effects: strategy code reads secrets, writes files, opens network calls, or touches live broker modules at import time.
8. Backtest promotion without run card: metrics are copied into prose without deterministic config/data hashes.
9. Stale scheduled run: liveness heartbeat is missing/malformed but promotion stays green.
10. Reconciliation confusion: research decision is reported as execution/account truth.
11. Risk-audit bypass: final recommendation is emitted after backtester output but before risk-auditor output.
12. Symbol-boundary drift: agent suggests a halted or unregistered symbol and downstream summaries normalize it away.

## Safe implementation candidates

Allowed follow-ups from this artifact:

1. Add a docs/tests-only `multi_agent_research_run` JSON schema for archived research artifacts.
2. Add fixture-only validation tests that fail when role outputs, dependency graph, model config, point-in-time data, run card, or risk review are missing.
3. Add a read-only dashboard evidence-completeness card that displays gate status without changing strategy, risk, order, broker, or symbol behavior.
4. Add static generated-code safety tests for research-only strategy snippets.
5. Add a report template that stores every role output and final verdict under a single run id.

Blocked without a dedicated `[safety-review]` PR and explicit human approval:

- Any automatic order placement or order parser wired to broker routes.
- Any change to `engine/config.py`, `engine/risk/`, kill-switch logic, active instrument gates, `.env`, PM2, or broker routing.
- Any provider-key, API-key, credential, or secret configuration change.
- Any change that lets an LLM introduce a new tradable symbol or bypass JARVIS gate/verdict systems.
- Any change that promotes an LLM-generated strategy to active paper/live execution from narrative evidence alone.

## Recommended next implementation candidate

Create a docs/tests-only schema and fixture validator for `multi_agent_research_run` artifacts. The minimum fixture should include:

- `run_id`, `created_at`, `prompt_hash`, `source_manifest_hash`,
- `allowed_symbols`, `blocked_symbols`,
- `roles[]` with provider/model/temperature/tool-list metadata,
- `dependency_graph[]`,
- `role_outputs[]`,
- `debate_protocol`,
- `point_in_time_context`,
- `generated_code_safety_receipt`,
- `backtest_run_card`,
- `risk_review`,
- `liveness`,
- `promotion_verdict`,
- `blocked_reasons[]`.

Keep that follow-up validation-only unless a separate `[safety-review]` scope is opened.
