# Macro Trend Overlay — Activation Runbook (Phase 3)

The advisory SPX macro-trend overlay (PR #265, Phase 3) ships **flag-off and inert**.
This is the exact sequence to move it from shipped → shadow-observed → trusted. Every
step here is reversible; nothing routes capital at any point.

## What ships (already on the branch)

- `engine/backtest/macro_regime.py` — `compute_macro_regime()` → `{state, weekly_trend,
  monthly_momentum, bias_line, ...}` (RISK_ON / RISK_OFF / NEUTRAL / UNKNOWN).
- `GET /macro/regime` — read-only endpoint (5-min cache).
- Feature flag `ENABLE_MACRO_TREND_BIAS` (default **False**).
- `engine/agents/pipeline.py` — when the flag is on, appends one `MACRO TREND: ...`
  line to the technical agent's existing `REGIME CONTEXT` (advisory LLM context only;
  never a mechanical gate, never overrides the CRISIS/VOLATILE hard-block).
- Dashboard `MacroRegimeBadge` on the home grid.

While the flag is off, `macro_ctx == ""` and the pipeline context is **byte-identical to
baseline**. NEUTRAL/UNKNOWN states also inject nothing.

## Step 0 — land the code (Amo-gated)

The engine and scheduled loops run from the **main checkout** (`jarvis-trader/`), not the
worktree, so the overlay is dormant until PR #265 merges to `master`:

1. **Merge PR #265** (your call — I do not merge).
2. **Restart the engine** — `./restart_engine.ps1` (your gated action; ~229s steady-state).
   Verify `/health` is GREEN (`status=ok` AND `tradingview_mcp_healthy` AND
   `llm_path_healthy`) per `rules/verification.md`.
3. Confirm the endpoint is live:
   ```powershell
   Invoke-RestMethod http://127.0.0.1:8010/macro/regime | ConvertTo-Json -Depth 4
   ```
   Expect a `state` + `components`. (Module-verified pre-merge: returns RISK_ON on the
   current SPY cache.)

## Step 1 — shadow period (flag still off in effect, observe the endpoint)

The endpoint and badge are safe to watch immediately after Step 0 with the flag OFF —
the state is computed and displayed but never injected. Watch a few sessions to confirm
the state tracks your read of the market and doesn't flap.

## Step 2 — enable the injection (runtime, reversible)

```powershell
# Turn the advisory injection ON (persisted runtime override — no restart needed):
Invoke-RestMethod -Method Put http://127.0.0.1:8010/flags/ENABLE_MACRO_TREND_BIAS `
  -Body (@{enabled=$true} | ConvertTo-Json) -ContentType 'application/json'

# ...and OFF again (or reset to the config default):
Invoke-RestMethod -Method Put http://127.0.0.1:8010/flags/ENABLE_MACRO_TREND_BIAS `
  -Body (@{enabled=$false} | ConvertTo-Json) -ContentType 'application/json'
# DELETE /flags/ENABLE_MACRO_TREND_BIAS resets to the config default (off).
```

The flag is visible/toggleable in the dashboard Feature Flags panel too.

## Step 3 — review the shadow log before trusting it

Every injection is logged (no separate tracker table — the log IS the audit trail):

```
[Pipeline] <SYMBOL> — macro trend bias (RISK_ON) injected: MACRO TREND: RISK_ON ...
```

Grep the engine log for `macro trend bias` over N sessions. Only after the injected
bias reads as sane (state matches regime, no thrashing, no surprising interaction with
the LLM debate) should it be considered trusted. If anything looks off, flip the flag
off — the pipeline instantly returns to baseline.

## Data-freshness caveat

`macro_regime` reads the SPY daily cache and appends only strictly-newer Polygon bars.
If the cache goes >10 calendar days stale, the state fail-safes to **UNKNOWN** (inert —
injects nothing). Keeping SPY daily bars fresh (a small daily `DataLoader.load("SPY",…)`
refresh) keeps the overlay live. As of this writing the cache is current to 2026-06-24.

## Hard boundaries (unchanged by activation)

- Advisory only. Never sizes, never places orders, never flips a paper/live flag.
- `engine/agents/trader.py`, `engine/config.py`, `engine/risk/`, `kill_switch.py`,
  `.env` — untouched by this feature.
- Routing authorization is entirely separate (`gate_v2_policy.py`); the overlay cannot
  influence what routes to capital.
