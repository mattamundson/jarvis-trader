# Start here — new session handoff (Cursor chat → disk)

**Project:** `C:\Users\mattm\ThinkorSwim\jarvis-trader`  
**Use:** Open a **new** Cursor chat and **@ mention this file** (or paste its path) so the next agent loads full context without re-reading the old thread.

**Companion (deeper detail + full file manifest + commands):**  
[SESSION_LOG_2026-04-02_DASHBOARD_ENGINE_HARDENING.md](SESSION_LOG_2026-04-02_DASHBOARD_ENGINE_HARDENING.md)

---

## Copy-paste prompt for your next session

```
Read and follow:
- docs/session-logs/START_NEW_SESSION_HANDOFF_2026-04-02.md
- docs/session-logs/SESSION_LOG_2026-04-02_DASHBOARD_ENGINE_HARDENING.md

Project: jarvis-trader. Continue from verified state: dashboard tsc clean, CI pytest slice passing, components use fetchEngine only. Tell me what's left (pnpm build Windows, manual Watchlist VIX checklist) and next priority.
```

---

## Everything this chat covered (chronological topics)

1. **Eight follow-ups (1-hour plan)** — Dynamic backtest baselines on `BacktestVsPaperWidget` + `validation/page`; CI grep `app`/`hooks`; jarvis-trader skill docs (`main.py` not `notifications_router`); `scorecardBaseline` trades mean PnL; `test_portfolio_paper_trade_post.py`; mypy gate; `approvedSymbols.ts`; validation copy MCL/MNQ.
2. **Top-10 / recommendations** — Scorecard still had `BACKTEST` (later fixed in nine-stream pass); VIX; CI contract tests; widget migration; `notifications_router` dedupe; pytest noise; etc.
3. **Nine workstreams plan** — Full implementation: scorecard baseline, migrate **all** `dashboard/components` off bare `fetch`, CI grep on `components`, pytest slice, delete orphan `notifications_router.py`, pytest-timeout, P0 runbook updates (paper_runner + Watchlist VIX checklist), docs (`ROUTE_VERIFICATION_GUIDE`, endpoint report).
4. **Q&A** — VIX fix location: **`VIXRegimeCard.tsx`**, page **`/watchlist`**, dev URL **`http://localhost:3010/watchlist`** (dashboard port 3010, engine 8010).
5. **Next steps / recommendations** — Repeated prioritization (build truth, manual VIX smoke, paper A→B ops).
6. **Session logging request** — User asked for full chat → `.md`; created engineering log (not verbatim transcript); explained Git diff for every code line.
7. **This handoff** — You are reading it: single entry point for **new session**.

---

## State the next agent should assume

| Area | State |
|------|--------|
| **Dashboard API calls** | Prefer `fetchEngine` / `postEngine` / `fetchEngineRaw` from `dashboard/lib/api.ts`. CI **fails** on `await fetch(` in `dashboard/app`, `dashboard/hooks`, `dashboard/components`. |
| **Scorecard + validation** | Backtest column / pills from `/backtest/results` + `pickApprovedBacktestBaseline` (`dashboard/lib/scorecardBaseline.ts`, `approvedSymbols.ts`). No hardcoded MES `BACKTEST` on those pages. |
| **VIX** | `dashboard/components/VIXRegimeCard.tsx` uses engine proxy paths; visible on **`/watchlist`**. |
| **Engine** | `engine/routers/notifications_router.py` **removed**; VIX/notification routes live on **`engine/main.py`**. |
| **Tests (CI slice)** | `pytest` files: `test_signals`, `test_rolling_wfe`, `test_cold_start_degraded`, `test_portfolio_paper_trade_post`, `test_api_contract_minimal`, `test_routes_wired` (see `.github/workflows/ci.yml`). |
| **Pytest** | `pytest-timeout` in `engine/requirements-core.txt`; `timeout = 30` in `engine/pyproject.toml` — run `python -m pip install -r requirements-core.txt` in venv if plugin missing. |
| **Build** | `dashboard`: `tsc --noEmit` was green last run; `pnpm run build` may still hit Windows `pages-manifest` flake — **trust Linux CI** if local fails. |

---

## Still manual / follow-up

- [x] **`pnpm run build`** locally or confirm GitHub **dashboard-build** job green after push. *(2026-04-02: passed on Windows after `Remove-Item dashboard/.next -Recurse -Force`; first run hit ENOENT `page.js.nft.json`.)*
- [x] **P0 runbook** — Watchlist VIX checklist in [P0_PAPER_IB_VERIFICATION.md](../runbooks/P0_PAPER_IB_VERIFICATION.md) §4 — code paths verified; DevTools smoke when engine is running.
- [x] **Commit** — Handoff stack + P0 §4 are on `master` (session verification commit). Remaining working-tree changes are outside that snapshot; use `git status` before a wider commit.

---

## Verbatim chat transcript

Cursor does not auto-save the full chat into this repo. For word-for-word export, use **Cursor’s chat export/history** for this conversation. This folder holds **engineering** logs only.

---

## Session log index

See [INDEX.md](INDEX.md) — rows **18** (dashboard/engine hardening log) and **19** (this handoff).
