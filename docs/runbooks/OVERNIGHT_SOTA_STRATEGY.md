# OVERNIGHT SOTA STRATEGY

A phased roadmap for evolving the overnight cloud Routine
(`.claude/commands/overnight.md`) from a read-only morning-brief generator into the
**meta-loop that makes the trader better over time** — without ever loosening the
read-only-on-trading guardrails. Companion to `OVERNIGHT_ROUTINE_RUNBOOK.md` (setup)
and the `loop-brakes` skill (safety).

## The decisive finding

jarvis-trader's autonomy / learning / cost machinery is **~60-70% built but largely
dormant** — the intelligence is computed and logged, then not used:

| Capability | Built | Live? | Evidence |
|---|---|---|---|
| IC-weighted ensemble + Brier calibration | yes | **no** (debate uses simple averaging) | `engine/analytics/ic_ensemble.py`, `agent_feedback.py` |
| Token tiering / prompt caching / context pruning | yes | **no** (not wired) | `engine/utils/token_optimizer.py` |
| HERMES morning/hourly/EOD jobs | yes | **not auto-started** | `engine/schedulers/eod_scheduler.py` |
| Autonomous pipeline | yes | **dead-configured** (`AUTONOMOUS_ACTIVE_SYMBOLS=MCL,MNQ`, both DO_NOT_TRADE; live paper = MES+MGC) | `engine/scheduler/pipeline_autonomous.py` |
| LLM cost tracking | yes | **observational, no budget gate** | `engine/llm/cost_tracker.py` |
| Forward-test graduation / rolling-WFE decay | yes | **diagnostic-only** | `engine/backtest/forward_test.py`, `rolling_wfe_scheduler.py` |

**Implication:** the SOTA move is NOT to build a new autonomous brain. It is to make
the overnight Routine the **nightly auditor + activation driver** — surface the dormant
intelligence into the morning report, then drive each piece live via draft PRs flagged
`[safety-review]`, one verified step at a time.

## Sequencing: observe -> enrich -> cheapen -> decide

Never wire a control loop before you have watched its signal in the morning report for
weeks (`loop-brakes`: verifiable-before-live; `testing.md`: live/forward is the honest
scoreboard). Each phase is its own PR; the Routine drafts, the human merges.

### Phase A — Make the night report a real cockpit (safe now, no safety files)
Extend `/overnight` Phase 1 to surface dormant metrics every morning — **surface only,
never auto-act**:
- **IC drift** — rolling 30-day IC per analyst (`ic_ensemble.py`); flag any analyst
  whose IC moved > 0.20 from baseline.
- **Brier calibration** — predicted-vs-realized confidence (do 75%-confidence trades
  win ~75%?).
- **Cost** — `/health` `llm_daily_cost_usd` + the `cost_tracker` ledger vs a soft
  budget; flag > 80%.
- **Decay** — `forward_test.py` graduation verdicts and `rolling_wfe_scheduler` WFE vs
  halt thresholds.

### Phase B — Cross-system enrichment (gbrain / vault / gstack)
- **gbrain (bidirectional)** — Phase 1 queries the gbrain `search_knowledge` MCP tool /
  `http://127.0.0.1:8077/search` for active symbols + open theses to enrich the brief;
  Phase 4 writes the night's findings back to the gbrain sink
  (`~/.gbrain-trading/raw/discord-feed/`-style) so the second brain compounds. Graceful
  no-op if the daemon is down (`engine/discord/knowledge.py`, `gbrain_sink.py`).
- **Vault timing fix (important)** — vault synthesis runs **06:00 CT, after** the 02:30
  Routine, so the Routine must read the **previous** day's synthesis + contradiction
  briefs (`00-Inbox/brief-*.md`, `contradictions-*.md`) and may write a trade-relevant
  note into `00-Inbox/` for the morning. Closes the loop:
  trades -> outcomes -> lessons -> vault -> synthesis -> next decision. Reuse
  `engine/vault/paths.py`; respect `JARVIS_VAULT_ROOT`. (Alternative: shift the Routine
  cadence later than 06:00.)
- **gstack** — Phase 2 dev triage uses gstack `/qa` (dashboard at :3010), `/review`
  (pre-PR), `/investigate` (regressions) so overnight dev output is validated, not raw.

### Phase C — Efficiency: wire TokenOptimizer live (biggest single win)
Activate model tiering (Haiku for weak-signal analysts, Sonnet for deciders, Opus only
for tiebreaks via `advisor_client.py`), Anthropic prompt caching (~60-70% on cache
hits), and context pruning (drop IC<0.05 analysts). Add a **budget gate**: at >X% daily
spend, auto-fallback to Haiku. The Routine itself already runs Haiku-tier per
`jarvis-cost-routing`. This is the loop-engineering "small, capped, $20-200-plan"
discipline made real. Touches the debate/LLM path -> **`[safety-review]` PR**, behind a
flag, validated against `cost_tracker` before/after on a replay.

### Phase D — Close the learning loop (the SOTA core; gated)
Wire the already-computed IC-weighted consensus + Brier calibration into the **live
debate vote** (replacing simple averaging); let the nightly IC-drift/Brier report gate
confidence thresholds. Highest value, most sensitive -> **`[safety-review]` + Tier-3**,
shipped only after Phase A has surfaced the metrics long enough to trust them. Defensive
companion: forward-test auto-halt (rolling Sharpe < -0.5 -> add to
`DO_NOT_TRADE_SYMBOLS`), also `[safety-review]`.

## Guardrails that never change

- Never place an order; `REQUIRE_HUMAN_APPROVAL = True` is invariant.
- Never edit `engine/risk/**`, `engine/config.py`, kill-switch, `engine/.env`,
  `CURRENT_STATE.md`, `MEMORY.md` (harness-enforced via `.claude/settings.json` deny).
- Every market-affecting wiring change is a separate `[safety-review]` PR a human reads.
- MCPT / backtest / forward parity before any live wiring (`ml-pitfalls-defense.md`,
  `mcpt-validation` skill). Diagnostics stay diagnostics until explicitly gated.

## Verification per phase

- **A**: assert the new report sections render against a fixture; docs/report-only diff.
- **B**: gbrain/vault no-op cleanly when unavailable; vault writes land in `00-Inbox/`
  only; gstack invocations are read-only QA.
- **C**: diff `cost_tracker` spend before/after on a fixed replay; behavior-identical
  decisions at equal inputs (tiering must not change verdicts, only cost).
- **D**: backtest + forward parity + MCPT p-values on the live symbol set before
  enabling the live vote; shadow-run the IC vote against simple averaging first.

---

*Last verified 2026-06-27. Roadmap doc — nothing here ships without its own PR + review.*
