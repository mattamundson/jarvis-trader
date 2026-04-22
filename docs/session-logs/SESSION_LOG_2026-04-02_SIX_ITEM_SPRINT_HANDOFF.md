# Six-item sprint handoff — Working TODAY / CI / IB markers / dashboard / safety

**Date:** 2026-04-02  
**Branch / PR:** Operator to push; not created from this session.  
**Plan reference:** Exhaustive six-item sprint (smoke, env, CI, `integration_ib`, paper dashboard `/health` chip, safety checklist).

---

## Item 1 — Smoke + engine health

| Step | Result |
|------|--------|
| `GET http://127.0.0.1:8010/health` | **200** (engine was already running) |
| `.\scripts\smoke_working_today.ps1` | **Smoke Working TODAY: OK** — POST MCL open; positions count increased |

**Note:** [`scripts/smoke_working_today.ps1`](../../scripts/smoke_working_today.ps1) resolves API key: `JARVIS_API_KEY` → parse `API_KEY` from `engine/.env` → default `jarvis-dev-key-change-me`.

---

## Item 2 — Env posture (`ALLOW_PAPER_SIMULATED_ORDERS`)

| Check | Result |
|-------|--------|
| [`engine/.env.example`](../../engine/.env.example) | `ALLOW_PAPER_SIMULATED_ORDERS=False` + comment on portfolio path |
| [`docs/CURRENT_STATE.md`](../CURRENT_STATE.md) | Configuration notes portfolio API vs gated connector path |
| `pytest engine/tests/test_ib_gateway_connector_offline.py` | **3 passed** |
| `pytest engine/tests/test_allow_paper_simulated_gating.py` | **3 passed** (optional local confidence; not in tier-1 CI list) |

---

## Item 3 — CI parity (pytest + dashboard build)

**Pytest (tier-1 list from [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)):**

```text
91 passed, 48 warnings in ~52s
```

Command used (repo root):

```powershell
.\engine\.venv\Scripts\python.exe -m pytest engine/tests/test_signals.py engine/tests/test_rolling_wfe.py `
  engine/tests/test_cold_start_degraded.py engine/tests/test_portfolio_paper_trade_post.py `
  engine/tests/test_api_contract_minimal.py engine/tests/test_p0_verify_mirror.py `
  engine/tests/test_paper_runner_engine_sync.py engine/tests/test_exception_handler.py `
  engine/tests/test_paper_trade_logger_tracker_mirror.py engine/tests/test_routes_wired.py `
  -q --tb=line --cov=engine --cov-report=term-missing --cov-report=xml --config-file engine/pyproject.toml
```

**Local setup:** `pytest-cov==5.0.0` was not initially in the venv; installed with `engine\.venv\Scripts\python.exe -m pip install pytest-cov==5.0.0` (CI installs it in the workflow). Consider adding `pytest-cov` to [`engine/requirements-core.txt`](../../engine/requirements-core.txt) or dev extras for one-command parity.

**Dashboard:**

```text
cd dashboard && pnpm run build  →  success (after paper page change)
```

**Push PR:** Run `git push` and open PR when ready; confirm all GitHub Actions jobs green.

---

## Item 4 — `integration_ib` marker

| Check | Result |
|-------|--------|
| [`engine/pyproject.toml`](../../engine/pyproject.toml) | Marker `integration_ib` registered |
| [`docs/runbooks/WORKING_TODAY.md`](../runbooks/WORKING_TODAY.md) | IB-marked pytest section |
| [`engine/tests/README.md`](../../engine/tests/README.md) | IB Gateway subsection |

**Change this session:** Added missing `@pytest.mark.integration_ib` on `test_get_positions_list_shape_for_order_manager` in [`engine/tests/test_ib_gateway_connector_safety_wiring.py`](../../engine/tests/test_ib_gateway_connector_safety_wiring.py) so all three IB-connection tests carry the marker.

---

## Item 5 — Dashboard paper page + `/health` chip

| Check | Result |
|-------|--------|
| [`dashboard/components/OpenPositionsWidget.tsx`](../../dashboard/components/OpenPositionsWidget.tsx) | Uses `fetchEngine("/portfolio/paper/positions")` (~line 84) |
| [`dashboard/app/paper/page.tsx`](../../dashboard/app/paper/page.tsx) | **Added** SWR poll of `GET /health` — header pill: `ENGINE ok` / `ENGINE offline` / loading / non-ok status |
| `pnpm run build` | **Green** |

Uses `fetchEngine` only (CI grep for bare `await fetch` remains satisfied).

---

## Item 6 — Safety review checklist (pre-merge)

**Diff vs `master` includes safety-adjacent paths** (among many files): e.g. `engine/risk/safety_layer.py`, `engine/config.py`, `engine/execution/ib_gateway_connector.py`.

**Actions for PR author:**

1. Run gstack **`/review`** (or human checklist per [`AGENTS.md`](../../AGENTS.md)) before merge if those files are in the PR.
2. **Grep guardrails:** No `LIVE_TRADING_ENABLED=True` introduced; port **4001** only in “blocked / documentation” context — spot-check with:

   ```powershell
   git diff master | Select-String -Pattern "LIVE_TRADING_ENABLED\s*=\s*True|4001"
   ```

   This session’s sample output showed 4001 only in documentation-style lines about blocking live port, not enabling it.

3. If gating or safety layer changes in the PR: run `pytest engine/tests/test_safety_layer.py` and `pytest engine/tests/test_allow_paper_simulated_gating.py` locally.

**PR body snippet (copy-paste):**

```text
## Safety
- Tier-1 pytest + dashboard build run locally green (2026-04-02).
- Diff touches safety_layer/config/IB paths: [ ] /review completed / [ ] human checklist
- Confirmed no LIVE_TRADING_ENABLED=True; port 4001 references are block/docs only.
```

---

## Files touched in this sprint execution (agent)

| File | Change |
|------|--------|
| `engine/tests/test_ib_gateway_connector_safety_wiring.py` | `@pytest.mark.integration_ib` on `test_get_positions_list_shape_for_order_manager` |
| `dashboard/app/paper/page.tsx` | Engine `/health` status chip in header (SWR + `fetchEngine`) |

**Pre-existing from earlier work (verified, not re-edited here):** `scripts/smoke_working_today.ps1` (.env API_KEY fallback), `engine/.env.example`, `docs/CURRENT_STATE.md`, `engine/pyproject.toml`, `docs/runbooks/WORKING_TODAY.md`, `engine/tests/README.md`.

---

## Decisions

1. Smoke script reads `engine/.env` for `API_KEY` when `JARVIS_API_KEY` is unset — reduces 401 friction for non-default keys.
2. Offline pytest does **not** require `ALLOW_PAPER_SIMULATED_ORDERS=True`; that flag is for the gated SafetyLayer → connector path only.
3. Paper page health uses the same exempt `GET /health` as the CLI smoke.

---

## Open follow-ups

1. Add `pytest-cov` to tracked dev dependencies if you want fresh clones to run the exact `--cov` line without an extra `pip install`.
2. Consider adding `test_allow_paper_simulated_gating.py` to the CI tier-1 list in `ci.yml` (product decision).
3. **Push PR** and wait for GitHub Actions (operator).

---

## Verbatim conversation history

This file is a **structured handoff**, not a byte-for-byte Cursor transcript. For full chat export: use **Cursor → Chat → Export** (or your workspace transcript path under `.cursor/projects/.../agent-transcripts`) and optionally save under [`docs/session-logs/transcripts/`](transcripts/).

---

## Master checklist (sprint)

- [x] Item 1: `/health` + smoke OK  
- [x] Item 2: `.env.example` + CURRENT_STATE + offline (+ gating) pytest  
- [x] Item 3: CI pytest line + `pnpm run build` locally (PR push pending operator)  
- [x] Item 4: `integration_ib` + docs + all three wiring tests marked  
- [x] Item 5: OpenPositionsWidget path; `/health` chip; build green  
- [x] Item 6: Checklist + grep guidance documented (run `/review` on full PR)  
- [x] This handoff file created  
