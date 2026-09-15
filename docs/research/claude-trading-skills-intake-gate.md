# Claude trading skills intake evidence gate

Status: research/control artifact only. No live trading config, paper trading
config, risk limits, kill-switch state, broker routing, API keys, `.env` files,
PM2, active instrument gates, scheduled tasks, or order behavior are changed.

## Source mined

- Reference repo: `mattamundson/claude-trading-skills`
- Reference commit: `9ef78d6`
- Source role: fork/reference catalog of Claude skills for traders and investors.
- Selected files reviewed locally:
  - `docs/en/skills/index.md`
  - `docs/en/skills/backtest-expert.md`
  - `docs/en/skills/pre-trade-discipline-gate.md`
  - `docs/en/skills/edge-strategy-reviewer.md`
  - `docs/en/skills/drawdown-circuit-breaker.md`
  - repo `CLAUDE.md` skill architecture and API-key warnings

## Coverage proof

Waves 3, 12, 15, 25, and 27 already cover strategy registry, LLM research-agent
evidence, multi-agent review, candidate inventory, and prompt-autoresearch risk.
This repo adds a different non-duplicative control: **agentic trading skills must
be classified by what they are allowed to influence before their outputs enter
JARVIS**.

The source catalog mixes backtest scoring, edge ideation, market analysis,
position sizing, pre-trade discipline, drawdown circuit breakers, and portfolio
coaching. Those are useful workflows, but they are not equally safe. JARVIS needs
an intake gate that keeps each skill in its lane.

## Transferable findings

1. Skill outputs should declare their authority tier before use: research note,
   candidate idea, evidence critique, risk advisory, dashboard context, or manual
   pre-trade checklist.
2. A skill that sounds operational, such as position sizing or pre-trade gating,
   is still advisory unless JARVIS has a separate enforcement integration.
3. API requirements matter. FMP, FINVIZ, Alpaca, or other paid/provider-backed
   skills need source/freshness/error evidence before outputs can affect scores.
4. Backtest review and edge-strategy review are high-leverage as adversarial
   critique, not as promotion authority. They can fail or revise candidates, but
   cannot override registry gates.
5. Discipline/circuit-breaker workflows are durable process controls, but they
   must stay separate from broker/risk enforcement unless a dedicated safety PR
   wires them in.
6. Skill catalog metadata should be treated as an intake queue, not as validated
   trading edge.

## JARVIS skill intake classes

| Class | Allowed influence | Blocked influence |
|---|---|---|
| `research_context` | Market notes, dashboard annotations, journal context | Strategy promotion, position sizing, orders |
| `candidate_generator` | Draft hypotheses or tickets requiring backtest | Direct registry approval or routing |
| `adversarial_reviewer` | Fail/revise candidates, flag overfit/sample/execution realism | Promote failed candidates |
| `risk_advisory` | Explain exposure, drawdown, sizing, and checklist concerns | Change risk limits or broker controls |
| `operator_checklist` | Manual pre-trade checklist artifact | Automated order approval |
| `provider_dependent` | Use only with provider/source/freshness evidence | Silent score uplift with missing/stale data |

## Acceptance gate for importing a trading skill into JARVIS

A future JARVIS skill integration must include:

1. Source repo and commit.
2. Skill name, category, and authority class.
3. Required inputs and provider/API dependencies.
4. Output artifact schema and storage path.
5. Explicit allowed influence on research cards, dashboards, registry, or manual
   workflow.
6. Explicit blocked influence on trading runtime, routing, risk limits, kill
   switches, `.env`, PM2, and broker configuration.
7. A fixture proving missing/stale provider data fails closed.
8. A fixture proving advisory outputs cannot override failed strategy-registry
   or gate-v2 verdicts.

## Recommended implementation boundary

Allowed after this wave:

- Add skill-intake JSON evidence for candidate workflows.
- Add offline validators for authority class, provider dependency, and blocked
  influence fields.
- Use skills as research helpers, critique helpers, or manual checklist prompts.

Blocked without a separate `[safety-review]` PR:

- Installing or enabling third-party trading skills as runtime dependencies.
- Letting any skill output place orders, change risk, edit config, or override
  strategy-registry verdicts.
- Storing provider keys or unredacted payloads in evidence.
