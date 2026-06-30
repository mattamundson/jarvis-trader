# HANDOFF — IB sub-hour backfill, GitHub force-commit, branch/giants review toolkits, full tag-backup

- **Date:** 2026-06-29
- **Session:** 1f104e33-e104-4bd8-837e-655ef595d729
- **Repo:** `C:\Users\mattm\ThinkorSwim\jarvis-trader` (main checkout currently on `fix/corey-cache-stale-nodata`)
- **Author model:** Claude Opus 4.8 (1M context)
- **Reader:** another AI session continuing this work with zero prior context.

---

## 1. Session summary — what was accomplished, in order

1. **IB sub-hour (5m/15m) backfill for 9 micros** (MES MNQ MGC M2K MCL ZN ZB M6E M6B) to reopen single-instrument intraday discovery beyond MES. Diagnosed the *real* cause of the original total failure (`n_fetched:0` on all 18 combos): `--duration "730 D"` exceeds IB's single-request size cap for sub-hour bars (~30–45 days). It was **not** a farm/gateway/permission problem. Switched to **chunked mode** (`--depth-days`). Recovered MGC 5m / MCL 5m / MCL 15m via a retry pass after diagnosing the clientId-71 per-chunk reconnect race (transient; retry often returns *deeper* data).
2. **Forced the cache data into GitHub** at Amo's explicit instruction ("I want all of this data in the github, override anything stopping you"). `engine/backtest/cache/` is gitignored (`.gitignore` line ~101–102). Committed the 23 sub-hour CSVs (~35 MB) via **git plumbing + temp index** → branch `data/ib-subhour-caches` (`5ccdf29`, off `origin/master`) → **PR #192** (open, Amo merges).
3. **Built two review toolkits** (Amo: "review the 98 branches… and the 48 giants… create comprehensive scripts I can run in claude code that will review each in separate sessions"). Non-destructive, archive-first, per-item review in separate headless sessions: `~/scripts/branch-review/` and `~/scripts/giants-review/`.
4. **Found + fixed a runtime bug** the toolkits' parse-validation missed: a `function Git { … & git … }` helper recursed infinitely (PowerShell resolves the `Git` function above the `git` binary, case-insensitively) → "call depth overflow" on the first git call → zero output. Fixed by calling `git.exe` explicitly.
5. **Verified the branch toolkit end-to-end** — stage 1 inventoried all **159 local branches**, wrote SUMMARY.md + inventory.json + 159 dossiers.
6. **Risk-assessed Amo's "push everything then start over" idea** (read-only) → recommended **tag-backup + clean in place** instead of blind push/nuke or full reclone.
7. **Executed the full tag-backup** (the data-loss-closing half): created 153 new `archive/<branch>` tags (177 total incl. pre-existing), **pushed to origin, verified 177/177 on remote**. Every committed line of work — including the 37 local-only branches a reclone would have erased — is now recoverable from GitHub.
8. **Persisted memory** + relaunched gbrain re-index detached.

---

## 2. Files created or modified — full paths, what changed, why

### Modified this session
- `C:\Users\mattm\scripts\branch-review\01-inventory-branches.ps1` — **bug fix**: line ~54 (`Git` helper) and line ~128 (`merge-base --is-ancestor`) changed `& git` → `& git.exe` to stop infinite recursion. Added an explanatory comment block above the function.
- `C:\Users\mattm\scripts\branch-review\03-archive-then-delete.ps1` — **same bug fix**: line ~43 `& git` → `& git.exe`.
- `C:\Users\mattm\.claude\projects\C--Users-mattm\memory\MEMORY.md` — added the IB-backfill index pointer at the top of `## Recent (2026-06-29)`.
- `C:\Users\mattm\.claude\projects\C--Users-mattm\memory\project_ib_subhour_backfill_2026_06_29.md` — added the "Runtime bug found + fixed" section (parse-OK ≠ runtime-OK; smoke-run every script).

### Created this session (toolkits — both parse-validated AND smoke-run for branch toolkit)
- `C:\Users\mattm\scripts\branch-review\01-inventory-branches.ps1` — stage 1: deterministic inventory + auto-classification (WORKTREE-PINNED / OPEN-PR / MERGED-SAFE / UNIQUE-WORK / STALE-EMPTY) + per-branch dossiers with embedded review prompts. No deletion, no LLM, pure git facts.
- `C:\Users\mattm\scripts\branch-review\02-run-reviews.ps1` — stage 2: `claude -p <dossier>` per branch → verdict files. `-DryRun` default; `-Apply`, `-MaxBranches`, `-Classes`.
- `C:\Users\mattm\scripts\branch-review\03-archive-then-delete.ps1` — stage 3: tag `archive/<branch>` (pushed) THEN `git branch -d` (never `-D`). Gated behind `-Apply`; `PROPOSING_DESTRUCTIVE_OP` marker; re-checks worktree/PR.
- `C:\Users\mattm\scripts\branch-review\README.md` — 3-stage workflow doc.
- `C:\Users\mattm\scripts\giants-review\01-discover-giants.ps1` — stage 1: 4 categories (dir ≥1GB, loose-file ≥500MB, top-48 diverged branches from branch inventory, opt-in `-IncludeGitHistory` blobs ≥50MB). Protected-pillar list. Classifies PROTECTED / NEEDS-REVIEW / ARCHIVE-CANDIDATE.
- `C:\Users\mattm\scripts\giants-review\02-run-reviews.ps1` — stage 2: per-giant headless review.
- `C:\Users\mattm\scripts\giants-review\03-archive-forward.ps1` — stage 3: **MOVE** to `~/Archive/<year>/<topic>` (robocopy /MOVE for dirs; never deletes); delegates branch giants to the branch toolkit; **refuses** history-blob purges (owner-only). Gated; `PROPOSING_DESTRUCTIVE_OP`.
- `C:\Users\mattm\scripts\giants-review\README.md` — workflow doc.
- `C:\Users\mattm\.claude\projects\C--Users-mattm\memory\project_ib_subhour_backfill_2026_06_29.md` — memory file documenting all backfill quirks + force-commit + toolkits.

### Generated this session (verification artifacts — safe to delete/regenerate)
- `C:\Users\mattm\scripts\branch-review\out-jarvis-trader\` — `SUMMARY.md`, `inventory.json` (branchCount=159), `dossiers\*.md` (159 files), `verdicts\` (empty dir, stage-2 writes here).

### Scratchpad (ephemeral, this session dir)
- `…\scratchpad\ib_deep_backfill.ps1`, `ib_retry_failed.ps1`, `commit_caches.sh`, `branch_inventory_smoke.log[.err]`, `gbrain_ingest.log[.err]`.

### Git artifacts created
- Branch `data/ib-subhour-caches` (`5ccdf29`) → **PR #192**.
- 23 sub-hour cache CSVs under `engine/backtest/cache/` (gitignored locally; force-committed only on the PR branch).
- **153 new `archive/<branch>` tags** (177 total), pushed to `origin`, verified.

---

## 3. Current state — what's running, stopped, broken

- **IB backfill:** COMPLETE. All 9 micros have 5m + 15m caches. SPY/RTY intraday still uncovered (exporter has no stock/ETF path — `MES/MNQ/MGC/MCL/M2K/ZN/ZB/M6E/M6B` only, NOT SPY/RTY/full-size, NOT 30m).
- **Tag-backup:** COMPLETE + VERIFIED. 177 `archive/*` tags on both local and `origin`. Committed work is safe.
- **Branch toolkit:** WORKING (bug fixed, smoke-run produced full inventory).
- **Giants toolkit:** parse-validated; NOT yet smoke-run (the giants `01-discover-giants.ps1` uses bare `& git` but defines **no** `Git` function, so it has no recursion bug — left as-is).
- **gbrain re-index:** relaunched detached (PID 36004, log `…\scratchpad\gbrain_ingest.log`). Status UNVERIFIED — confirm it completed; if not, re-run `~/tools/gbrain-memory-ingest.ps1` or POST `:8077/ingest {raw_dir, embed:"stale"}`.
- **Engine / IB Gateway:** not health-checked this session. The 238 MB `engine/data/vec_index.db.tmp` suggests a vector-index rebuild may have run/be-running — do NOT delete that .tmp while a rebuild is active.
- **3 peer Claude sessions LIVE** (see Blockers).
- Nothing is broken.

---

## 4. In-progress work — started but not finished

- **Clean-in-place prune** — designed, agreed by Amo, NOT started (blocked on peer sessions). Plan: capture 6 dirty worktree deltas → `git worktree remove` the ~21 clean stale worktrees → `git branch -d` the 134 already-safe branches → keep master + active branches. Everything recoverable from `archive/*` tags.
- **7 dirty worktrees** have uncommitted deltas not yet captured (tags only capture committed tips). Breakdown below in §5.
- **gbrain re-index** detached, completion unverified.

---

## 5. Blockers discovered

1. **3 live peer Claude sessions** (from `~/.claude/session_manifest.json`):
   - `7f55c1dd` — `C:\Users\mattm\master-jarvis\jarvis-trader`, branch `feat/tradingview-mcp-gamma-kraken` (a DIFFERENT clone).
   - `a97408b3` — owns worktree `…\a97408b3-…\scratchpad\jt-134-extract` = `feat/corey-compare-forecast-journal` (the 4 STAGED files are its in-flight work — DO NOT touch).
   - `daea2db5` — owns worktree `…\daea2db5-…\scratchpad\wt-freshness` = `feat/autonomous-price-freshness-gate` (was clean/0-dirty).
   - **Consequence:** the clean-in-place prune (worktree removals + branch deletes) CANNOT run until these close — doing so would corrupt live sessions. This is a real coordination gate, not a deferral.
2. **7 dirty worktrees** (the only data-loss-sensitive surface; committed tips already tagged):
   - `fix/corey-cache-stale-nodata` (main checkout, 19 dirty) — almost all junk/dupes/runtime-data. Unique items: `dashboard/AGENTS.md`, `docs/architecture/DASHBOARD_PAGE_ROUTER_MAP.md` (2 real docs). The untracked `engine/systematic/` is a DUPLICATE of already-committed PR #177 work (`7e90464`); the untracked vwap scripts are already on `feat/funnel-vwap-shadow`; `engine/data/vec_index.db.tmp` is 238 MB junk.
   - `feat/corey-compare-forecast-journal` (4 staged) — PEER-OWNED (a97408b3); let that session commit.
   - `worktree-cryptic-purring-pond` (7) — real code (llm/client.py, pnl_monitor.py, tests).
   - `patch09-llm-fallback` (4) — real code (debate.py, trader.py, client.py, test).
   - `worktree-quirky-swinging-lollipop` (6) — dashboard tsx + test + runtime audit log.
   - `feat/discovery-round3` (1) — safety_layer.py.
   - `fix/price-fallback-staleness` (1) — entry_price_sanity.py.
3. **FS I/O contention** on the giant repo makes git ops slow; long pulls/inventories must run detached (foreground 2-min harness cap; harness reaps long background Bash tasks).

---

## 6. Key decisions made

- **Backfill: chunked mode, not `--duration`.** Single-request sub-hour duration cap ~30–45d. Deep history is bounded by the current front-month ContFuture's liquid life (chunks before the pinned contract existed → `Error 162 HMDS`).
- **Cache → GitHub via git plumbing (temp index)**, not normal `git add`. Required because the giant working tree + concurrent I/O hang normal worktree ops; plumbing also avoids the shared `.git/index` (peer-safe) and bypasses gitignore. Side effect: bypasses pre-commit secret-scan hook — acceptable, OHLCV only.
- **Toolkits call `git.exe` explicitly** — a bare `& git` inside a `function Git` recurses. AST parse-validation does NOT catch this; smoke-run every script.
- **"Start over" → tag-backup + clean IN PLACE, not reclone.** Reclone forces rebuilding engine `.venv` (Python 3.12.10, `requirements-core.txt`), `.env` from 1Password, dashboard `pnpm install`, worktree re-pointing — hours + footguns. Clean-in-place keeps the environment.
- **Backup via archive-tags, not branch-pushes.** Tags preserve every tip on origin without polluting it with 159 branches; tag creation is peer-safe (doesn't touch working trees). Pushed all 159 (177 total incl. pre-existing) for robustness rather than only the 37 local-only.
- **Standing constraint reaffirmed:** NEVER disable MES. Always archive, never delete. `PROPOSING_DESTRUCTIVE_OP` before destructive ops. Never `git add -A` / `--no-verify` / push shared branches without auth.

---

## 7. TODO — planned but not started

- Merge ready PRs in order: **#186** (ruff lint fix — unblocks merge-refs for ALL PRs) → **#192** (caches) → **#177** → **#183** (dedup/bridge stack; both default-OFF, dormant when merged).
- Reconcile the two signal→paper-order paths (#177 bridge vs `AUTONOMOUS_AUTO_APPROVE_PAPER` queue) before activating either — pick ONE canonical path; shared dedup guard partly built (`engine/execution/submission_dedup.py`, #183). See `project_systematic_exec_path_reconciliation_2026_06_29.md`.
- Clean-in-place prune (after peers close): commit 6 worktree deltas → remove ~21 stale worktrees → `git branch -d` 134 safe branches → keep master + active.
- Delete `engine/data/vec_index.db.tmp` (238 MB junk) once the engine isn't rebuilding the vector index.
- Run branch-review stage 2 over the 117 UNIQUE-WORK branches, then stage 3 (tag-then-delete).
- Run giants-review (smoke-test stage 1 first, then 2 → 3).
- Close the SPY/RTY intraday data gap (needs a stock/ETF data path; not in `export_ibkr_history.py`).
- Verify gbrain re-index completed.

---

## 8. Full current TODO list (verbatim working set — no Task tool was used this session)

1. ✅ DONE — IB sub-hour backfill (9 micros, 5m+15m).
2. ✅ DONE — Force caches into GitHub (PR #192).
3. ✅ DONE — Build branch + giants review toolkits.
4. ✅ DONE — Fix toolkit `git.exe` recursion bug; verify branch toolkit end-to-end (159 branches).
5. ✅ DONE — Persist memory (MEMORY.md pointer + project file + bug-fix note).
6. ✅ DONE — Risk-assess "start over"; choose tag-backup + clean-in-place.
7. ✅ DONE — Tag-backup: 177 archive/* tags created + pushed + verified on origin.
8. ⏳ PENDING (Amo gate) — Merge PRs #186 → #192 → #177 → #183.
9. ⏳ BLOCKED (peer sessions) — Clean-in-place prune (worktrees + branches).
10. ⏳ PENDING — Capture 6 dirty worktree deltas (1 peer-owned → that session does it).
11. ⏳ PENDING (engine-idle gate) — Delete 238 MB `vec_index.db.tmp`.
12. ⏳ PENDING — branch-review stage 2 → 3 over 117 UNIQUE-WORK branches.
13. ⏳ PENDING — giants-review stage 1 smoke → 2 → 3.
14. ⏳ PENDING — Verify gbrain re-index (PID 36004) completed.
15. ⏳ OPEN — SPY/RTY intraday data path (exporter gap).
16. ⏳ OPEN (Tier-3) — Reconcile #177 vs auto-approve canonical exec path.

---

## 9. Git state (verbatim)

### `git status` (main checkout `fix/corey-cache-stale-nodata`)
```
On branch fix/corey-cache-stale-nodata
Your branch and 'origin/fix/corey-cache-stale-nodata' have diverged,
and have 2 and 172 different commits each, respectively.

Changes not staged for commit:
	modified:   .gitignore
	modified:   dashboard/dashboard.code-workspace
	modified:   docs/reports/METRICS_SNAPSHOT.json
	modified:   engine/data/forecast_reports/2026-06-25.md

Untracked files:
	dashboard/AGENTS.md
	docs/architecture/DASHBOARD_PAGE_ROUTER_MAP.md
	docs/reports/tearsheets/2026-06-27_07-00_paper_paper.html
	engine/backtest/run_mes_vwap_rank1.py
	engine/backtest/vwap_paper_track.py
	engine/data/forecast_reports/2026-06-26.md
	engine/data/forecast_reports/2026-06-27.md
	engine/data/forecast_reports/2026-06-28.md
	engine/data/forecast_reports/calibration_2026-06-28.md
	engine/data/morning_forecasts/2026-06-26.json
	engine/data/morning_forecasts/2026-06-27.json
	engine/data/morning_forecasts/2026-06-28.json
	engine/data/morning_forecasts/2026-06-29.json
	engine/data/vec_index.db.tmp
	engine/systematic/
```
NOTE: the local corey branch has **2 commits not on its own remote** (`a326d75`, `a81cf29`) — both captured by tag `archive/fix/corey-cache-stale-nodata` and safe on origin. The "172 behind" is normal long-lived-branch drift vs its remote.

### `git log --oneline -20`
```
a326d75 feat(data): request IB delayed market data as subscription-gap stopgap
a81cf29 feat(risk): add bar-timestamp freshness anchor to entry-price sanity
1f5e6d4 docs(session-logs): add 2026-06-29 deploy-consolidation handoff + conversation
36c2b7c data(discord): 2026-06-27 digest
8bd65d3 data(discord): 2026-06-26 digest
c590ef1 docs(deploy): add credential-rotation section to Vercel runbook
d701868 docs(deploy): rewrite Vercel runbook to as-built ngrok + 3-layer auth
54ada57 feat(autonomous): opt-in paper-only auto-approve (default OFF) (#173)
e82fe8e data(discord): 2026-06-25 digest
c820bbe fix(market_data): map MHG (COMEX) and MYM (CBOT) futures exchanges
a91670a feat(dashboard): proxy injects tunnel basic-auth server-side
40e9f96 fix(market_data): map ZB/ZN (CBOT) futures exchange — unfreeze bond bars
f359240 test(corey,harmonic): cover guardrail branches + prove harmonic detector fires
5960aca feat(dashboard): live Price column on Hidden Pivots page
1386713 feat(corey): signal-propagation guardrail for trade_outcomes
2898aa1 feat(corey): on-demand session-bias extract viewer
aa3f9bb feat(backtest): H1/H2 chronological stationarity gate (library + wrapper)
97b53a6 fix(dashboard): bypass ngrok browser-warning interstitial in proxy
1f14843 chore(dashboard): .vercelignore + Cloudflare deploy runbook
a438098 fix(paper-config): disable MGC — enabled on a now-FAIL rank4 verdict
```

### `git diff --stat` (unstaged, tracked files)
```
 .gitignore                                 |  3 +++
 dashboard/dashboard.code-workspace         | 16 +++++++++++-
 docs/reports/METRICS_SNAPSHOT.json         | 40 ++++++++++++++---------------
 engine/data/forecast_reports/2026-06-25.md |  6 ++---
 4 files changed, 41 insertions(+), 24 deletions(-)
```
`git diff --stat --cached`: empty (nothing staged in main checkout).

### Repo summary
- HEAD branch: `fix/corey-cache-stale-nodata`
- Local branches: **159**
- `archive/*` tags (local AND origin, verified): **177**
- Worktrees: **28**
- Branch classes (from `out-jarvis-trader\SUMMARY.md`): WORKTREE-PINNED 28 · OPEN-PR 2 · MERGED-SAFE 12 · UNIQUE-WORK 117 · STALE-EMPTY 0
- Local-only branches a reclone would lose (now tag-backed-up): 37 (23 no-upstream + 14 ahead-of-upstream); 122 fully synced.

---

## Suggested next action (one thing)

**Merge PR #186** (ruff lint fix) — it unblocks the merge-ref for every other open PR — then #192, #177, #183 in that order. This is the only thing not blocked on peers and it clears the path for the eventual clean-in-place prune. Hold the prune until the 3 peer sessions (`7f55c1dd`, `a97408b3`, `daea2db5`) close.
