# Jarvis Robust Strategy Funnel

A meta-orchestration layer over jarvis-trader's existing backtest primitives.
Transforms scattered strategy ideas (repo code + X bookmarks + analysis docs)
into a ranked, statistically defensible list of Tier A paper-trade candidates —
without the combinatorial blowup of "test every strategy × instrument × timeframe."

## Quick start

From a Windows machine with the jarvis-trader repo cloned locally:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:JARVIS_FUNNEL_SYNC_ROOT = "$HOME\OneDrive\jarvis-trader-handoff"
.\Run-JarvisFunnelPhase1.ps1 -JarvisRepo "C:\path\to\jarvis-trader"
```

Output lands in `$JARVIS_FUNNEL_SYNC_ROOT\cards\strategies_v1.jsonl`.

## What's in here

- `SKILL.md` — the entry point read by Perplexity Computer when the skill is loaded
- `references/` — decision framework docs
  - `lopez_de_prado_vs_brute_force.md` — the methodology argument
  - `thresholds.md` — Tier A/B/C cutoffs with rationale for each number
  - `strategy_card_schema.md` — JSONL data model for strategy cards
  - `bookmark_to_code_mapping.md` — dedup logic for cross-source merging
- `scripts/` — executable pipeline
  - `phase1_inventory.py` — repo + bookmark inventory
  - `funnel_gate.py` — Tier A/B/C decision engine (independent of gate_v2)
  - `tracker.py` — weekly OneDrive-synced status dashboard
  - `run_phase.py` — CLI orchestrator
- `tests/` — test suite (15 tests, all passing)
  - `test_funnel_gate_vs_gatev2.py` — locks in the funnel_gate behaviour incl.
    intentional divergences from gate_v2 on false-negative patterns
- `Run-JarvisFunnelPhase1.ps1` — one-paste Windows launcher

## Related work in this repo

- `engine/backtest/meanrev_v2_signals.py` — first strategy family authored via
  the funnel's audit process (see `docs/audits/meanrev_audit.md`)
- `docs/funnel-audits/` — forensic reports produced by the skill
