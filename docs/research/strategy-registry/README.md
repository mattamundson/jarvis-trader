# Strategy registry

Machine-readable ledger of every candidate strategy in the JARVIS research loop.
Companion to `../strategy-research-operating-model.md` (the prose loop) and
`../backtest-critique-checklist.md` (review gate).

## Why this exists

The GitHub estate audit (2026-09-12) called out a strategy registry as the "best
immediate add" for the strategy research loop. The operating-model doc listed the
required fields in prose; this registry pins them as a validated JSON schema so
provenance, evidence paths, and promotion state cannot drift apart across docs,
gate cards, and the dashboard.

## Layout

- `schema.md` — human-readable field definitions and lifecycle states.
- `schema.json` — JSON Schema (draft 2020-12) for entry files.
- `entries/<strategy_id>.json` — one record per strategy.
- `seed/2026-09-12-initial-seed.md` — provenance for the initial seed.

## How to add an entry

1. Copy the shape of an existing entry in `entries/`.
2. Fill every required field (`schema_version`, `strategy_id`, `name`, `source`,
   `hypothesis`, `asset_class`, `symbols`, `timeframe`, `data_sources`,
   `feature_set`, `rules`, `windows`, `promotion_state`, `updated`).
3. Set `promotion_state` to the honest current state — `idea` if nothing has run.
4. Add every artifact (gate card, backtest output, notebook, journal entry, PR) to
   `evidence_paths`.
5. Validate:

   ```bash
   pip install jsonschema  # once
   python -c "import json, jsonschema; \
     jsonschema.validate(json.load(open('entries/YOUR_ID.json')), \
     json.load(open('schema.json'))); print('ok')"
   ```

   (On this machine run it from a clean shell with `env -u PYTHONPATH` if using the
   engine venv.)
6. Commit in a small docs PR with the evidence artifacts.

## Hard rules

- A record only becomes `promoted` with a `PASS` gate verdict, the gate card in
  `evidence_paths`, and a PR/decision-ledger reference.
- A registry entry never authorizes routing by itself. Live trading eligibility
  is read from `GET /paper/validation/approved-paper-gates` (dashboard
  `/trading-eligibility`) — the registry is the research ledger, not the gate.
- Never edit `engine/config.py`, risk limits, kill-switch, broker routing, or
  instrument gates as part of a registry change. Changes touching those need a
  `[safety-review]`-tagged PR.
- Supersede, don't rewrite: when a strategy is re-scoped, create a new
  `strategy_id` and set `supersedes`.
