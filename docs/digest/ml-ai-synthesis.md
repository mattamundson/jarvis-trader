# ML/AI Synthesis — from Discord digest

_Source: `C:\Users\mattm\discord-export\digest-raw\by-module\ml-ai.json` (31 items, 2026-04-10 to 2026-04-16)_

## TL;DR
- The 31 ml-ai items cluster into three buckets: trading-specific multi-agent frameworks (4), Hermes-agent ecosystem / self-improvement infra (18), and generic AI tutorials/guides (9). Most of the Hermes content is noise for jarvis-trader — we already run an equivalent 5-analyst async debate + Opus advisor + IC-weighted ensemble. Two items offer genuinely novel techniques worth evaluating.
- Novel techniques worth evaluating: **3** (GEPA skill evolution, QuantAgent Pattern Agent via annotated K-line charts, TensorTrade commission-aware reward scheme)
- **Status as of 2026-04-17: 2 of 3 SHIPPED, Novel #2 UNBLOCKED** (Novel #1 GEPA scaffold and Novel #3 PBR commission both integrated; Novel #2 vision Pattern Agent is now INFRASTRUCTURE-READY, IMPLEMENTATION-PENDING — `chrome-devtools` MCP was registered in `.mcp.json` on 2026-04-16 via commit `d99fad4`, so the prior "Chrome CDP chart capture pending" blocker no longer applies. See `docs/repo-integrations/ChromeDevTools__chrome-devtools-mcp.md` for the integration surface analysis.)
- Already implemented: **4** patterns are already in jarvis-trader (multi-agent debate, Polymarket-style research RAG, tool-use orchestration, cross-session memory via `engine/utils/token_proxy.py`)
- Noise: **24** (Hermes UIs, OpenClaw bridges, Polymarket-crypto demos, generic Claude tutorials)

## Already in jarvis-trader (dedup)

- **Multi-agent debate with role-specialized researchers** — `HKUDS/QuantAgent` (Indicator/Pattern/Trend/Decision agents) — already implemented: `engine/agents/pipeline.py` (5-analyst async) + `engine/agents/debate.py` (bull/bear/neutral verdict) + `engine/agents/advisor_client.py:78` (Opus tiebreak)
- **IC-weighted ensemble of analyst signals** — `HKUDS/Vibe-Trading` claims "Factor IC/IR analysis" — already implemented: `engine/analytics/ic_ensemble.py:87` (Spearman rank correlation over 30-day realized pnl_usd window)
- **Cross-market / cross-session context memory** — `HKUDS/Vibe-Trading` "5-layer context compression" — already implemented (functionally equivalent): `engine/utils/token_proxy.py` (prompt compression + 300s response cache + context trimming) plus `engine/utils/token_optimizer.py`
- **LangChain/LangGraph orchestration for trading agents** — `Polymarket/agents`, `Y-Research-SBU/QuantAgent` — already implemented natively via `asyncio.gather` 5-analyst pipeline in `engine/agents/pipeline.py`. Adding LangGraph would be duplicate indirection, not a win.

## Novel techniques — ranked by expected impact

### 1. GEPA (Genetic-Pareto Prompt Evolution) for analyst prompts — **SHIPPED 2026-04-16 (scaffold)**
- **Source**: `NousResearch/hermes-agent-self-evolution` — https://github.com/NousResearch/hermes-agent-self-evolution
- **Technique**: DSPy + GEPA reads execution traces to understand *why* an agent failed (not just that it failed), then proposes targeted prompt mutations evaluated against a pareto frontier of objectives. No GPU training, ~$2-10 per optimization run. ICLR 2026 Oral.
- **Implementation**: `engine/llm/prompt_evolution.py` (~280 lines). Pure-Python evolutionary loop — no DSPy dependency. `GEPAOptimizer.evolve(n_generations, variants_per_member)` reads from any `TradeEvalSource` (Protocol), mutates frontier members via any `PromptMutator` (Protocol), and scores candidates via any `PromptScorer` (Protocol). Pareto-non-dominated-set algorithm at `select_pareto_frontier()` keeps tradeoffs (e.g. long-but-accurate AND short-but-decent both survive). Brevity is min/max-normalised across the cohort each generation so scores are comparable. `ParetoFrontier.update()` is monotone — adding new candidates can shrink frontier (better dominators) but never lose the current best. History snapshots written to `optimizer.history` per generation for offline analysis.
- **NOT live-wired (deliberate)**: Does NOT modify `engine/agents/bull_researcher.py`, `bear_researcher.py`, `neutral_researcher.py`, `technical_analyst.py` system prompts. Produces evolved prompts as JSON artifacts; promoting one to production is a separate human-reviewed PR. Reason: the system prompt of a debate-stack agent is debate-critical — an over-fit prompt could poison the ensemble even if it scores well on the eval window. The PR review gate is the safety belt. Production binding: a `TradeEvalSource` adapter over `engine/analytics/agent_feedback.py` (the `trade_outcomes` SQLite table) + an LLM-backed mutator + scorer is left as the live-wiring follow-up.
- **Tests**: `engine/tests/test_prompt_evolution.py` — 24 tests covering Pareto-frontier algorithm (empty, single, dominated, tradeoffs preserved, strict dominance), brevity normalisation, candidate ID stability, optimiser construction validation, end-to-end evolve() with deterministic mock mutator + perfect/contrarian/broken scorers, history snapshot shape, identical-variant skipping, custom token counter swappable, exception-tolerant scoring. All passing 2026-04-16 in 0.39s.
- **Expected impact**: measurable lift in debate accuracy vs realized pnl — GEPA paper claims 10-15% task-performance lift on complex reasoning. Could feed the existing `AgentFeedbackTracker` outcome DB as its eval source (already has 30-day trade_outcomes table).
- **Risk**: must gate with `advisor_client.py` guardrails and `ic_ensemble` weighting — an over-fit prompt could dominate IC without truly improving pnl. Evolutionary variants need the existing test suite (1484 passing) as constraint gate. Mitigated by the offline-only / human-PR pattern of the scaffold.
- **Effort**: ~3 hours actual for the scaffold + tests (vs medium 1-2 day estimate). Live wiring (TradeEvalSource adapter + LLM mutator/scorer + first 90-day evolve run) is the deferred work.

### 2. Chart-image reasoning (Pattern Agent via annotated K-line)
- **Source**: `Y-Research-SBU/QuantAgent` — https://github.com/Y-Research-SBU/QuantAgent — arxiv 2509.09995
- **Technique**: Pattern Agent draws the recent price chart, annotates highs/lows/trend channels, and sends the **image** to a vision-capable LLM (Claude/Opus) which matches the shape to known patterns and returns plain-language classification. Trend Agent does the same with fitted channel overlays.
- **Touch point**: new `engine/agents/pattern_vision_analyst.py`; called from `engine/agents/pipeline.py` as a 6th analyst. Consumes the `chrome-devtools` MCP registered in `.mcp.json` (commit `d99fad4`, 2026-04-16) — **no longer a blocker**, just needs the agent-side wiring.
- **Expected impact**: jarvis-trader currently does pattern recognition via numeric indicators (STC, ATR, regime filter) — Hidden Pivots is the only visual-pattern signal and it's heuristic. A vision-based pattern analyst catches shapes (head-and-shoulders, triangle breakouts, channel breaks) that numeric pipelines miss. Likely +2-4pp on debate accuracy for setups where candlestick context matters.
- **Risk**: adds a non-trivial token cost (image inputs are expensive) — must gate via `TokenProxy` cache (300s TTL is already appropriate for 1h/5m charts). Could fight the existing `advisor_client` budget — only invoke when `ic_ensemble` weight for technical analyst is high.
- **Effort**: medium-large (needs chart capture → PNG encode → Anthropic vision API → classification schema → wire into debate)
- **Test sketch**: run on 30 historical MCL 1h setups with known Hidden Pivots signals; compare HP + vision-pattern combined verdict vs HP alone on realized 2h forward pnl.

### 3. Commission-aware reward scheme for RL strategy discovery — **SHIPPED 2026-04-16**
- **Source**: `tensortrade-org/tensortrade` — https://github.com/tensortrade-org/tensortrade
- **Audit**: `engine/strategies/rl_environment.py:523-590` — existing reward had `entry_cost = -0.01` (behavioural penalty in ATR-normalised space) but NO real-dollar broker commission. So PBR addition is additive, not duplicate.
- **Implementation**: `engine/strategies/rl_environment.py:533-541` deducts `commission_usd_per_contract * contracts_per_trade` from `realized_pnl` BEFORE ATR normalisation. Defaults `commission_usd_per_contract=0.0` so legacy training runs are reproducible. New `COMMISSION_BY_INSTRUMENT` table at `engine/strategies/rl_config.py:148-153` provides realistic IBKR-micro commissions (MCL $1.30, MNQ $0.45, MES $0.50 round-trip).
- **Wiring**: `REWARD_CONFIG.update(COMMISSION_BY_INSTRUMENT[symbol])` is the one-line activation. No code change to `rl_trainer.py` or `rl_evaluator.py` needed.
- **Tests**: `engine/tests/test_rl_commission_pbr.py` — 8 tests covering default-zero behaviour, ATR-units deduction, contract scaling, winner→loser inversion, no-charge-on-entry, per-instrument table sanity. All passing 2026-04-16.
- **Still pending**: actual retraining run on MCL 1h with PBR enabled, compared to baseline; accept only if WFE > 0.60 (paper-eligible threshold).
- **Effort**: ~30 min actual (vs "small if swap, medium if restructure" estimate).

## Noise / passed

- `outsourc-e/hermes-workspace`, `garrytan/gbrain`, `nesquena/hermes-webui`, `xaspx/hermes-control-interface`, `howardpen9/hermes-gbrain-bridge`, `ksimback/hermes-ecosystem`, `nousresearch/hermes-agent` (Orchestra skills PR), `orchestra-research/ai-research-skills` — Hermes Agent infrastructure. jarvis-trader is Claude-SDK-native (`engine/llm/client.py`); adopting Hermes would be a rewrite without net benefit. Already have equivalent in `engine/agents/managed_agent_bridge.py` for MA-infra fallback.
- `Polymarket/agents`, `agent-next/polymarket-paper-trader`, `kaustubhpatange/polymarket-trade-engine`, `runesleo/polymarket-toolkit` — Polymarket is binary prediction markets (crypto); jarvis-trader trades CME futures (MCL/MNQ/MES). Zero carryover.
- `HKUDS/AI-Trader` — copy-trading social platform for AI agents; not a technique.
- x.com posts (aleiahlock, noisyb0y1, marko_poly, atenov_d, saccc_c, chooseliberty, gkisokay Day 5/Day 8, neoaiforecast, shaughnessy119, ruffy0369, lufzzliz, carlosvillu, tom_doerr) — all Hermes/Polymarket/AGI-scorecard content; no actionable techniques beyond what's already above.
- `passiveincomehabit.gumroad.com/l/hermesagent` — paid beginner tutorial.

## Raw grep receipts

```bash
# Verified existing multi-agent stack
Grep "class.*Ensemble|class.*Advisor|class.*Debate" engine/
  → engine/agents/advisor_client.py (AdvisorVerdict, AdvisorRefinement, AdvisorClient)
  → engine/agents/debate.py
  → engine/analytics/ic_ensemble.py (class ICWeightedEnsemble at :87)

# Verified no existing DSPy/GEPA wiring
Grep "dspy|GEPA|self.evolve|prompt_optim" engine/
  → No files found  (confirms GEPA is novel to jarvis-trader)

# Verified no existing vision/chart-pattern wiring
Grep "pattern.*agent|chart_pattern|pattern_recognit" engine/
  → only engine/database/migrations.py (table name match, not an agent)

# Verified existing RL strategy skeleton
ls engine/strategies/
  → rl_agent.py, rl_config.py, rl_environment.py, rl_evaluator.py,
    rl_executor.py, rl_trainer.py, discovery_loop.py
  → TensorTrade PBR reward swap is a function-level change, not greenfield
```

## Next actions (if Matt approves)

1. **Spike GEPA (highest leverage)** — 1 day to wire `evolution.skills.evolve_skill --eval-source sessiondb` against `AgentFeedbackTracker`. Evolve `bull_researcher` first; gate PR via existing test suite + out-of-sample IC threshold.
2. **Audit `rl_environment.py` reward function** against TensorTrade PBR — 30min. If current reward ignores commission, do the swap; if not, pass.
3. **Pattern Vision Analyst** — **READY TO SPIKE.** `chrome-devtools` MCP is live in `.mcp.json` (commit `d99fad4`, 2026-04-16). Remaining work is the agent wiring (chart capture via MCP → PNG encode → Anthropic vision API → classification schema → debate hook). M–L effort (2–8 hr for the scaffold, not counting eval-window validation). Gate the live invocation via `TokenProxy` 300s cache + `ic_ensemble` weight threshold on the technical analyst so vision calls don't burn budget on setups where they add no signal.
