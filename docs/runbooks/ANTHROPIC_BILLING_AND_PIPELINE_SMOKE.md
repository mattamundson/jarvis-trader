# Anthropic billing & pipeline smoke (P2)

## P2.1 — Billing (external)

- Confirm organization has credits or an active plan at [Anthropic Console](https://console.anthropic.com).
- Engine needs `ANTHROPIC_API_KEY` in the environment for full pipeline agent stages; without it, pipeline initialization may be incomplete (see `/pipeline/run` behavior).

## P2.2 — Pipeline smoke

With engine running and `JARVIS_API_KEY` set to match `API_KEY`:

```bash
cd engine
.venv/Scripts/python scripts/smoke_pipeline.py
```

Capture `status_code` and body in the session log. **200** with `running`/`halted` is OK; **500** usually means pipeline or safety initialization issue — fix env before paper ops.

## P2.3 — Degraded LLM UX

When the engine is unreachable, the dashboard shows a top hint via `EngineAvailabilityHint` (root layout). LLM-specific errors remain on pipeline/backtest pages — do not route safety decisions through the LLM.
