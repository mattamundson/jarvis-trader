# LLM trading-agent evidence checklist

Status: docs-only research-control artifact. No live trading config, paper trading config, risk limits, kill-switch state, broker routing, API keys, `.env` files, PM2, symbol gates, or order behavior are changed.

## Source mined

- Reference repo: `mattamundson/LLM-Trading-Lab`
- Reference commit: `589c92abe36616e3495cc46c05019d2c451c566f` (`main`, 2026-06-23)
- Files reviewed through GitHub API:
  - `README.md`
  - `Other/AUTOMATION_README.md`
  - `Experiments/chatgpt_micro-cap/evaluation/evaluation_report.md`
  - `Experiments/chatgpt_micro-cap/tables/metrics.txt`
  - `Experiments/chatgpt_micro-cap/scripts/metrics/episode_pcr.py`
  - `Experiments/chatgpt_micro-cap/scripts/metrics/load_dataV3.py`
  - `Experiments/multi_model_ipo/prompts/starting_prompt.py`
  - `Experiments/multi_model_ipo/prompts/daily_prompt.py`
  - `Experiments/multi_model_ipo/prompt_orchestration/main_functions.py`
  - `Experiments/multi_model_ipo/prompt_orchestration/prompt_models.py`

## Transferable findings for JARVIS

The reference project is valuable because it treats an LLM trader as an observable behavioral system, not as a magic alpha source.

Source facts worth importing into JARVIS discipline:

1. Forward-only recordkeeping is the core control. The reference README describes a six-month experiment with historical artifacts, research artifacts, and logs preserved for transparency and auditability.
2. The evaluation report says decisions used only information available before execution, with no future market data or post-close outcomes in model inputs.
3. Human involvement was limited to prompting/data entry/trade execution; the study explicitly separates model decisions from human discretionary overrides.
4. The model showed high concentration and tail-risk exposure. Reported source metrics include max drawdown `-50.33%`, 46 FIFO lot exits, 50.00% lot win rate, `0.82` profit factor, and `-0.41` per-lot expectancy.
5. A single adverse position dominated results. The report states that excluding the ATYR tail event improved profit factor from `0.82` to `1.52`, proving aggregate LLM-trader results can be fragile to one catalyst gap.
6. The prompt framework forces a source-of-truth input block and asks for strict JSON orders. That pattern is useful; the execution automation pattern is not safe to copy into JARVIS without a separate `[safety-review]` PR.
7. The multi-model IPO prompts encode hard whitelist rules, eligibility proofs, and action-specific constraints. JARVIS should reuse the checklist shape: eligibility is asserted by data, not inferred by the model.
8. `prompt_models.py` dispatches multiple model providers at `temperature=0.0` for some providers. The transferable control is deterministic model configuration disclosure, not the provider code.

## JARVIS research-agent gate

Before any LLM-generated trading idea can be promoted from narrative to JARVIS research candidate, attach this evidence bundle:

| Gate | Required evidence | Pass condition |
|---|---|---|
| Input timebox | Input snapshot timestamp, market close timestamp, execution decision timestamp | Every feature available before the decision timestamp; no future bars/news/outcomes |
| Source-of-truth block | Exact prompt input block or API payload | Holdings, cash, prices, regime features, and eligibility are data-sourced; no hidden tickers or inferred eligibility |
| Model configuration | Provider, model, temperature, seed if available, prompt version, tool list | Re-run is reproducible enough for audit; stochastic settings are disclosed |
| Decision JSON | Machine-readable proposed action, thesis, invalidation, expected holding window, risk, confidence | JSON parses; no free-text-only order intent |
| Constraint restatement | Model restates hard rules before analysis | Any missed hard rule is a fail, not a warning |
| Eligibility proof | Instrument allowlist/gate verdict and data freshness | The model cannot introduce symbols outside the allowed universe |
| Position concentration | Proposed exposure by instrument/family/regime | Concentration is measured before score uplift; tail-event sensitivity is explicit |
| Tail-risk shock | Worst single-position/catalyst gap scenario | Candidate survives a defined adverse move or is blocked from promotion |
| Outcome attribution | PnL split by realized lot, position, day, and thesis | One outlier cannot be hidden by aggregate PF/Sharpe |
| Re-entry audit | Prior exits/losses for the same symbol or thesis | Re-entry after a loss requires new evidence, not repeated narrative conviction |
| Benchmark context | Comparable passive/naive baseline | LLM result beats an appropriate baseline after costs or remains research-only |
| Human override log | Any manual intervention after model output | Overrides are labeled; model behavior and operator behavior are not conflated |

## Failure modes to explicitly test

1. Narrative persistence: model keeps a thesis after price action or data invalidates it.
2. Re-buying losers: model re-enters prior realized-loss names without fresh evidence.
3. Concentration creep: a small account drifts into two or three thesis-heavy positions.
4. Stop-loss false comfort: overnight/catalyst gaps bypass intended stops.
5. Prompt drift: formatting improvements quietly change decision logic.
6. Benchmark mismatch: apparent alpha disappears against a naive or risk-matched baseline.
7. Hallucinated constraints: model references tools, hedges, data, or instruments that the setup forbids.
8. Tail-event masking: one binary outcome determines the study while averages look acceptable.

## JARVIS implementation boundary

Allowed from this artifact:

- Add a research report template or validation checklist.
- Add offline tests that require prompt payloads to include timestamp, source-of-truth, model config, and JSON decision sections.
- Add dashboard-only visibility for evidence completeness, if scoped separately.

Blocked from this artifact without a dedicated `[safety-review]` PR:

- Any automatic order placement or order parser wired to broker routes.
- Any change to `engine/config.py`, risk limits, kill-switch logic, active instrument gates, `.env`, PM2, or broker routing.
- Any provider-key, API-key, or secret configuration change.
- Any change that lets an LLM introduce a new tradable symbol or bypass the JARVIS gate/verdict system.

## Recommended next implementation candidate

Create a docs/tests-only follow-up that defines a `research_agent_decision_evidence` JSON schema and validates archived decision payloads for:

- `input_snapshot_ts`
- `decision_ts`
- `model_provider`, `model_name`, `temperature`
- `allowed_symbols`
- `source_of_truth_payload_hash`
- `proposed_action_json`
- `hard_rule_restatement`
- `concentration_before_after`
- `tail_risk_scenario`
- `human_override_log`

That follow-up should remain paper-only and validation-only unless a separate `[safety-review]` scope is opened.
