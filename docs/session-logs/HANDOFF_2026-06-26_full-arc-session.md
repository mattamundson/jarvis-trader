# HANDOFF — 2026-06-26 — Full-Arc: Trading-System Convergence → Scripts Maintenance → PR #3 Merge

> **Purpose:** zero-context-loss continuation doc for the next AI session. Deliberately exhaustive.
> **Span:** session crossed the 2026-06-25 → 2026-06-26 date boundary; two phases —
> **(A)** pre-compaction trading-system convergence (ATR-trail merge, family-fdr→master PR #145,
> daily-calendar PR #151, pre-holiday operationalization, bridge modernization) and
> **(B)** post-compaction `~/scripts` maintenance drain + PR #3 conflict-resolve-and-merge.
> **Reading order:** §0 orientation → §1 narrative → §2–§9 structured handoff fields →
> §10–§14 deep-dives → §15–§22 reference appendices. Forward-looking parts: §5, §7, §8, §22,
> and the final Suggested Next Action. Everything else is landed + verified.
> **Repos touched:** `home-scripts` (all Phase-B work), `jarvis-trader` (Phase-A merges via the
> `_spread_track` worktree + this handoff to `docs/session-logs/` via PR #156 — MAIN checkout never
> touched), and `claude-config-backup` (this handoff + index). **Handoff is triple-stored:** local
> `~/.claude/handoffs/`, private `claude-config-backup` (`5110183`), jarvis-trader master (PR #156).

---

## 0. ORIENTATION MAP — the three moving pieces

This session spanned **two code repos** + **one detached worktree** + **one config-backup repo**.
Keep them straight; confusing them is the #1 way to break something:

| Piece | Path | Branch / HEAD (session end) | Role |
|---|---|---|---|
| **home-scripts** | `C:\Users\mattm\scripts` | `main` @ `68ee426` (clean, synced) | All Phase-B maintenance. PR #3 merged here. |
| **jarvis-trader MAIN** | `C:\Users\mattm\ThinkorSwim\jarvis-trader` | `claude/beautiful-fermi-yeecq4` @ `af35329` | Active campaign checkout. **Peer territory — NOT touched.** 37 unmerged commits; lacks forward-track producers. |
| **`_spread_track` BRIDGE** | `C:\Users\mattm\ThinkorSwim\_spread_track` | detached @ `0ab1fa5` | Worktree carrying converged master code so the 3 forward-track tasks run producers the MAIN checkout lacks. **Modernized** `ce14931`→`0ab1fa5`. |
| **claude-config-backup** | `C:\Users\mattm\.claude` | `main` (PRIVATE remote) | Where THIS handoff is committed + pushed. `handoffs/` tracked; `projects/` gitignored (secret-leak vector). |

**Critical drift facts (both new this session):**
- `jarvis-trader origin/master` advanced **`0ab1fa5` → `66d2db3` (+11 commits)** via 10 peer PRs.
  Bridge is functionally correct but behind tip. See §3, §5-Blocker-2.
- MAIN checkout HEAD moved **`8806f4c` → `af35329`** (peer commit) mid-session. Live peer territory.

---

## 1. SESSION SUMMARY — granular narrative, in order

### PHASE A — Trading-system convergence (pre-compaction; reconstructed from carried summary + re-verified)

**A0. Entry.** Conversation opened with `get clipboard` → surfaced two git commands; user approved:
```
cd /c/Users/mattm/ThinkorSwim/jarvis-trader/engine
git pull origin claude/beautiful-fermi-yeecq4
```

**A1. Resolved the `git pull` merge conflict** (merge `be44c47`). The pull delivered 4
cloud-authored commits adding two NEW untested ATR-trail-flip **confluence variants** to
`engine/backtest/run_atr_trail_bounce.py`:
- **`kelt`** — keep only flips aligned with the 4H Keltner channel
  (`generate_atr_trail_kelt_confluence_signals`, `engine/backtest/atr_trail_bounce_signals.py:317`)
- **`tpotgt`** — keep only flips whose direction agrees with the prior-session TPO measured-move
  projection (`...:386`)
- 3 conflict hunks → resolved toward remote (kelt/tpotgt superset). Loader hunk merged to retain
  broad timestamp-column support + sort:
  ```python
  for tcol in ("timestamp", "datetime", "date", "time"):
      if tcol in df.columns:
          df[tcol] = pd.to_datetime(df[tcol], utc=True)
          df = df.set_index(tcol).sort_index()
          break
  ```
- 54 tests passed.

**A2. Ran/validated kelt + tpotgt** (the actual payoff — the cloud session that authored them
could not run them; bar caches + venv live only on this machine). Two issues + the verdict:
- **Cache-loader bug:** the runner auto-picked a ~2-month slice
  (`MES_2026-03-21_2026-05-20_1h.csv`) by **lexicographic filename sort** instead of newest
  end-date. Re-ran with the explicit deep cache `MES_2024-04-26_2026-06-22_1h.csv`. (A peer later
  generalized the fix via `_pick_cache_file` at `run_atr_trail_bounce.py:58`, end-date-keyed,
  mirroring `_find_latest_cache` — see memory `project_atr_trail_loader_fix_2026_06_25`.)
- **Verdict: ATR-trail-flip is DEAD** — 1h is an anti-edge; the 5m flip is MCPT-REJECT +
  non-stationary across H1/H2; kelt/tpotgt confluence gates are dominated by the base flip.
  Per explicit user instruction: kept "on the board," NOT declared exhausted.

**A3. Operationalized the pre-holiday calendar forward-shadow.** Pre-holiday was the standout of
the free-daily discovery (SPY 1993–2026, 302 pre-holiday days, Sharpe ~1.32 net@2bps; SPY+GLD
PASS gate-v2 ALT — stronger than turn-of-month). The producer + `preholiday_spy_v1`
pre-registration + installer had ALREADY shipped via **PR #144 (MERGED)** — did NOT rebuild
(applied "check origin before concluding absent"). The missing step was the daily task → installed
**`Jarvis-PreHolidayPaperTrack`** (daily 5:10 PM, Ready, `mattm` LIMITED/Interactive, battery gate
cleared). Baseline: 0 forward days since inception 2026-06-25.

**A4. Saved memory** `project_preholiday_forward_shadow_2026_06_25.md` documenting the bridge
load-bearing dependency.

**A5. Scoped, then merged `feat/family-fdr-campaign` → `master`** = **PR #145** (merge `8caa81e`).
88 ahead / 29 behind; exactly ONE content conflict in `engine/backtest/forward_test.py`:
- Resolved as **UNION** of master's `trade_shuffle`/`ts_p` diagnostic + family-fdr's
  `strategy_type` column. Auto-merged row-renderer emitted BOTH → lineage-table header widened to
  **9 columns**: `| lineage | type | pre-reg | n_oos | p_edge | pf_ci_lo | ts_p | fdr | graduated |`.
- `engine/tests/test_forward_test_diag.py`: mocks `lambda lineage: True` → `lambda lineage, reg:
  True` (family-fdr's 2-arg `is_pre_registered`).
- **Pre-existing master bug discovered** (NOT merge-induced; proven on pure origin/master):
  `engine/backtest/vix_percentile_regime.py:204` + `engine/backtest/trend_signals.py:129` raise
  `AttributeError: 'str' object has no attribute 'value'` because `Momentum(str, Enum)` is coerced
  to `str` by pandas 3.x `.iloc[-1]`.
- 3 e2e tests hung (`test_ib_paper_e2e`, `test_paper_trading_flow`, `test_pipeline_e2e`) — live
  environment (port 4002 IB Gateway UP → async hang); pre-existing on base/master; CI excludes via
  `-m "not slow and not manual"`.
- **Read-the-summary lesson:** a background `echo "EXIT=$?"` wrapper masked pytest's real
  "1 failed, 2744 passed" — must read the summary line, not the wrapper exit.
- **Safety-config gate** failed requiring `[safety-review]` in the PR body when safety files
  change — NOT a bug; user reviewed + authorized the tag; full green CI; merged.

**A6. "Proceed with all of the above"** → two follow-ups:
- **#1 Retire `_spread_track` bridge** — **BLOCKED + REFUSED.** Inspecting the main checkout
  revealed `claude/beautiful-fermi-yeecq4` holds **37 unmerged commits** (morning-brief Phases A–F,
  ATR-trail visualizer, $10K risk profile) + dirty files + live peers. I had earlier
  mischaracterized this branch as transient. **STOPPED, refused the destructive main-checkout
  sync, surfaced the discrepancy, offered safe alternatives.** (Highest-stakes judgment call.)
- **#2 Fold `daily_calendar_discovery` into master** = **PR #151** (merge `0ab1fa5`). 2 commits
  (`free_daily_export.py` + `daily_calendar_discovery.py`), 0 conflicts, 19 tests, green CI, merged.
  (`.gitignore` `575a7f9` earlier added the paper-track ledger ignores.)

**A7. Modernize the bridge** (chosen safe alternative to the refused sync): planned to move
`_spread_track` `ce14931` → `origin/master` (`0ab1fa5`).

### PHASE B — Post-compaction: bridge verification + scripts maintenance + PR #3 (everything I directly executed)

**B1. Completed + verified bridge modernization.**
`git -C _spread_track checkout --detach origin/master` → `0ab1fa5`. Confirmed all 4 producers
present; producer runs clean observe-only via the exact launcher invocation (MAIN `.venv` python +
bridge cwd): `Pre-holiday tick: recorded 0 new forward day(s); latest=2026-06-25`, exit 0; durable
ledger in MAIN checkout untouched; `Jarvis-PreHolidayPaperTrack` triggered → **0x0**. Updated the
memory file with the "BRIDGE MODERNIZED 2026-06-26" paragraph.

**B2. `/jarvis-trader` + `/jarvis-loop`** ("fix everything until all tasks, even sub-tasks, complete").

**B3. jarvis-loop discovery Round 1** (signals A–G — definitions in §18):
4 untracked + 18 modified + 1 deleted in `~/scripts`; 2 failing tasks
(`Jarvis-DataIntegritySentinel` 0x1, `Jarvis-IBGateway-AtLogon` 0xC); MEMORY 18460 B clean; 0
broken refs; night tasks 82/84 OK (no 0xFFFD0000 → not actionable).

**B4. P2 — both failing tasks fixed (transient → self-healed):**
- `Jarvis-IBGateway-AtLogon` 0xC(12) "no stored cred AND op empty." Root cause: 07:00 logon, gateway
  not up yet + op locked. Verified **CredMan HAS the cred** (`Jarvis/IBKR-Paper`, user `Wolfof216`)
  and **port 4002 UP** now → re-triggered → **0x0**.
- `Jarvis-DataIntegritySentinel` 0x1: worker ran clean now ("OK - all integrity checks passed",
  exit 0); 05:35 failure = transient data-freshness window → re-triggered → **0x0**.
- Re-verify: **84/84 tasks OK, 0 FAIL.**

**B5. P4 — committed 4 untracked files** (secret-scanned clean first): 3 VBS launchers (`f2ee936`)
+ `inbox-rotate.ps1` (`e652eb1`).

**B6. P3 — reviewed + committed all 18 modified + 1 deletion in 11 semantic commits** (full table
in §2). Each diff read; clustered by intent; no secrets; all PS ASCII-verified for PS 5.1.

**B7. jarvis-loop discovery Round 2: every signal clean → loop stop conditions met** (§18 matrix).

**B8. Pushed** `~/scripts` `fix/scorecard-c2-llm-live` (explicit user auth): `b1cb852..7e8e0f7`,
verified local HEAD == origin.

**B9. PR handling.** PR **#3** already existed for the branch; updated its title + body to the full
36-commit / 80-file maintenance scope rather than duplicate.

**B10. Merged PR #3** (was CONFLICTING, branch 2 behind main):
- `start-ibc-gateway.ps1` conflict → UNION (main `e820bb2` manual-fallback + token-gate × my
  `7e8e0f7` CredMan-primary + Force). `moc_gen.py` (`77cad8b`) merged clean.
- Verified: no markers, 0 non-ASCII, AST parse — caught + fixed a dropped `else`-closing brace,
  re-parsed clean. Merge `8dd55c7`, pushed → MERGEABLE/CLEAN → **merged** (`68ee426`), 37 commits
  preserved.

**B11. Cleanup.** Working tree → `main` (synced `68ee426`); re-verified merged file (AST clean +
live `Jarvis-IBGateway-AtLogon` → 0x0); deleted merged branch (local + remote); confirmed 3 other
local branches all unmerged → left untouched.

**B12. Handoff** written, then expanded twice on request (deeper each time).

### PHASE C — Handoff distribution to two GitHub repos + branch-cleanup saga

**C1. Pushed handoff to `claude-config-backup`** (private). Verified `gh repo view --json
isPrivate` → true BEFORE pushing (the doc carries operational detail: CredMan username `Wolfof216`,
chat_id, op:// item names, infra paths — fine in a private backup, would be a leak in a public
repo). Regenerated `handoffs/INDEX.md` via `~/scripts/handoff-index-gen.ps1` (169 rows). Committed
ONLY the 2 handoff files (left unrelated `CLAUDE.md` drift untouched). Commit `5110183`,
`adb350f..5110183 main -> main`. Verified local HEAD == origin.

**C2. Loaded handoff to jarvis-trader** (also verified PRIVATE first). **Could not** use the MAIN
checkout — it was on the peer-active `claude/beautiful-fermi-yeecq4` (37 unmerged commits, live
peers, already ahead 1 with an unpushed peer commit); committing/pushing there would race peers and
publish their unpushed work. **Isolated-worktree approach instead:**
`git worktree add -b docs/handoff-2026-06-26 ../jt-handoff-doc origin/master` → copied the handoff
to `docs/session-logs/HANDOFF_2026-06-26_full-arc-session.md` → committed (`4e3cca6`) → pushed the
branch → opened **PR #156** → **merged to master**. Required checks (Security Scan, Safety-config
gate, Lint, Claude Review) were green; slow pytest/mypy/dashboard were pending but NOT
merge-blocking, so it merged immediately. Confirmed the doc on `origin/master`. Removed the temp
worktree (`git worktree remove`).

**C3. Branch cleanup saga** (illustrative of the guardrails):
- Remote branch `origin/docs/handoff-2026-06-26` deleted by Amo via `! git push origin --delete ...`
  (one earlier attempt failed on a `-ddocs` typo — missing space).
- Local `git branch -d` **REFUSED** ("not fully merged") — a FALSE alarm: git checks merge against
  the current HEAD, but the MAIN checkout had been switched by a peer to `fix/corey-cache-stale-nodata`
  (it switched branches TWICE mid-session: `beautiful-fermi` → `fix/corey-cache-stale-nodata`), which
  doesn't contain `4e3cca6`. Verified `git merge-base --is-ancestor 4e3cca6 origin/master` = TRUE
  (zero data loss), then Amo force-deleted via `! git branch -D docs/handoff-2026-06-26`.
- **The agent-initiated `git branch -D` was BLOCKED by the `destructive-op-guard.sh` PreToolUse
  hook** — by design; force-delete must route through Amo's `!` shell (human-in-the-loop). This is
  the correct behavior, not a bug.

**C4. (This update) Phase C added to the handoff + re-uploaded to jarvis-trader master** (same
isolated-worktree-off-master → PR pattern; the MAIN checkout remained peer territory throughout).

> **Master velocity note:** `jarvis-trader origin/master` advanced FOUR times during the session —
> `0ab1fa5` → `66d2db3` → `34a48c7` (PR #152 auction signals) → `8b32d46` (PR #156, this handoff).
> It is an extremely active branch; any worktree pin is stale within minutes.

---

## 2. FILES CREATED OR MODIFIED — full paths, what, why

### Phase A — jarvis-trader (`C:\Users\mattm\ThinkorSwim\jarvis-trader\`)

| File | Where | Change | Why |
|---|---|---|---|
| `engine/backtest/run_atr_trail_bounce.py` | campaign branch (merge `be44c47`) | Resolved 3 hunks toward remote (kelt/tpotgt); merged loader hunk (broad cols + sort) | Cloud variants needed local merge. NOTE: on campaign branch, NOT master. |
| `engine/backtest/forward_test.py` | master (PR #145 `8caa81e`) | UNION of `trade_shuffle`/`ts_p` + `strategy_type`; 9-col lineage header | Both sides edited the row-renderer |
| `engine/tests/test_forward_test_diag.py` | master (PR #145) | Mocks → 2-arg `is_pre_registered(lineage, reg)` | Match family-fdr signature |
| `engine/backtest/daily_calendar_discovery.py` | master (PR #151 `0ab1fa5`) | NEW — 5-ETF × 13-effect calendar screener (end-date-keyed `_find_latest_cache`) | Fold calendar discovery into master |
| `engine/backtest/free_daily_export.py` | master (PR #151) | NEW — deep free ETF daily puller | Lifts IB-intraday starvation for calendar class |
| `C:\Users\mattm\.gitignore` | `575a7f9` (earlier) | +`engine/data/*_paper_track/`, `wfo_live_match/`, `results/*.log{,.*}`, `*.out`, `requirements-frozen-*.txt` | Stop ledger churn polluting `git status` |
| `engine/scripts/install_preholiday_paper_track_task.ps1` | PR #144 (pre-existing) | Installed `Jarvis-PreHolidayPaperTrack` | Daily 5:10 PM producer trigger |

### Phase A — memory (`...\memory\`) + bridge

| Path | Change |
|---|---|
| `project_preholiday_forward_shadow_2026_06_25.md` | Created; updated 3× (live → merge-DONE → gap-RESOLVED → BRIDGE-MODERNIZED) |
| `PLAN_2026-06-25_family-fdr-to-master-scope.md` | PR #145 scope doc |
| `C:\Users\mattm\ThinkorSwim\_spread_track` (worktree) | Moved `ce14931` → `0ab1fa5` (`checkout --detach origin/master`); no commit |

### Phase B — home-scripts (`C:\Users\mattm\scripts\`) — all on `main` via PR #3

| File(s) | Commit | Change | Why |
|---|---|---|---|
| `hidden-launchers/jarvis-{preholiday,spread,tom}-paper-track.vbs` | `f2ee936` | NEW — 3 hidden wscript launchers | Forward-track tasks invoke these; resolve producer bridge→main fallback |
| `inbox-rotate.ps1` | `e652eb1` | NEW — move-only Inbox→Archive (pillar-protected, DRY-RUN default, exit 0/1) | Replaces inbox half of retired `archive-rotate.ps1`; never deletes |
| `scan-credentials.ps1`, `git-precommit-secret-scan.sh`, `scan-whitelist.txt` | `be7f19b` | Neg-lookbehind word-boundary on `sk-`; restore segment-bounded multi-segment whitelist; skip reparse points; +4 whitelist entries | Kill `risk-`/`ask-` FPs; fix 0x41306 AppData re-walk; restore ~30 broken FP-suppressions |
| `load-secrets.ps1` | `880e9ed` | +`DISCORD_BOT_TOKEN` → `op://Amo Personal/Discord-Bot-Jarvis/credential` | Reference only (no secret) |
| `launch-tv-cdp.ps1`, `watch-tv-cdp.ps1`, `tv-cdp-watchdog.ps1` | `a6475ed` | Probe `:9222/json/version` not port LISTENING; consolidate self-heal (kill+relaunch hung-but-bound TV, 90s grace); strip BOM+em-dash from watch-tv-cdp | Hung TV held 9222 in LISTEN >24h undetected (2026-06-05) |
| `archive-rotate.ps1` (DELETED) + `install-regression-tasks.ps1` | `12065d4` | Delete purge script; installer `Jarvis-ArchiveRotate`→`Jarvis-InboxRotate` (weekly Sun 02:00, move-only) | Purge deleted ~28 GB on 2026-06-24 (recovered from D: Passport). NEVER re-add. XML at `~/Archive/2026/retired-tasks/` |
| `notify-on-fail.ps1` | `8532a36` | Workers under pwsh7 (Store shim→PATH→powershell.exe); Telegram token → `op://Amo Personal/Telegram-Bot-Jarvis/password`; default chat_id `8676240038` | em-dash false exit-1 under PS5.1; old `Telegram-Hermes-Bot` op item never existed → silent no-op |
| `hermes-state-sync.ps1` | `bc89b84` | Enumerate WSL `profiles/` dynamically | Hardcoded list skipped scout/analyst/briefer |
| `obsidian-mcp-wrapper.ps1` | `116a425` | Warn (stderr) if `CC-WMI-PATCH-v1` missing from main.js | WMI-wedge hung MCP server (50-min hang 2026-06-17/18) |
| `north-star-scorecard.ps1` | `ae9fae2` | Automate C1 4th point from `/forward-test/status?symbol=MGC` | Replaces manual stub (phantom fix PRs #90/#91) |
| `refresh-jarvis-verdicts.ps1` | `99b3755` | Status=recovery\|live tags; recovery+INSUFFICIENT_SAMPLE = tracked-not-alarmed | MES R11 sample-starved → kill permanent-red alarm |
| `run-finance-sync.ps1` | `807ef9a` | `Invoke-SyncModule` EAP=Continue; judge `$LASTEXITCODE`; bounded URL-redacted log | EAP=Stop NativeCommandError pre-empted Write-Log → silent 4-day gap |
| `sweep-orphan-claude-procs.ps1` | `c4e9b25` | Reap orphaned Discord MCP pythons (opt-in + never-kill + TCP-LISTEN guard, fail-safe) | Leaked 70+ MCP pythons |
| `vault/moc_gen.py` | `aacc9b0` | `EMIT_COMPANY_MOCS=False`; strip ALL trailing `.md` in `link()` | 252 GMS/career stubs off-mission; re-ingest made `name.md.md` |
| `disk-watch.ps1` | `c6070c3` | em-dash → `--` | PS 5.1 safety |
| `start-ibc-gateway.ps1` | `7e8e0f7`, merge-resolved `8dd55c7` | CredMan primary + `-Force`; UNION-merged with main's manual-fallback + token-gate | Unattended-robust creds (deep-dive §12c) |

### Phase B — config-backup

| File | Change |
|---|---|
| `C:\Users\mattm\.claude\handoffs\HANDOFF_2026-06-26_scripts-maintenance-and-bridge.md` | This doc (written, expanded ×2 + Phase C, committed + pushed to claude-config-backup) |
| `C:\Users\mattm\.claude\handoffs\INDEX.md` | Regenerated by `handoff-index-gen.ps1` to include this handoff |
| `jarvis-trader: docs/session-logs/HANDOFF_2026-06-26_full-arc-session.md` | Mirror on master via PR #156 (Phase C); re-uploaded with Phase C added |

---

## 3. CURRENT STATE — running / stopped / broken

**home-scripts:** `main` @ `68ee426`, **clean**, synced. PR #3 merged. Feature branch deleted. 3
other local branches unmerged (untouched).

**jarvis-trader `origin/master`:** `66d2db3` — **+11 commits past the bridge `0ab1fa5`** via peer
PRs **#153** (lint I001), **#139** (MCP docs), **#116** (vol-target test + to_thread crash fix),
**#129** (/analyze/technical 500 — signal is float not str), **#128** (/trading-status/live),
**#115** (vol-targeting sizing overlay [safety-review], DEFAULT OFF), **#111** (edge-research
wave), **#142** (MCPT bootstrap CI), **#136** (DSR docs), **#147** (phantom-P&L safety guard).
Master is a **live moving target**.

**jarvis-trader MAIN checkout:** `claude/beautiful-fermi-yeecq4` @ **`af35329`** — peer-moved from
`8806f4c` this session (`fix(backtest): DSR degenerate variance fails conservative, not fake 1.0`);
ahead 1 of its origin; 2 untracked. **NOT touched — active peer territory.** Lacks producers →
bridge load-bearing.

**`_spread_track` bridge:** detached @ `0ab1fa5`. Valid worktree. Carries `preholiday/tom/
spread_paper_track.py` + `daily_calendar_discovery.py` + `free_daily_export.py`.
`run_atr_trail_bounce.py` is NOT here (campaign-branch-only; irrelevant to tracks).

**Forward-track DARK tasks (all verified):**
| Task | Trigger | Run-as | State | LastResult | LastRun |
|---|---|---|---|---|---|
| `Jarvis-PreHolidayPaperTrack` | Daily 5:10 PM | `mattm` LIMITED | Ready | **0** | 6/25 11:24 PM |
| `Jarvis-TomPaperTrack` | Daily 5:00 PM | `mattm` | Ready | **0** | 6/25 5:00 PM |
| `Jarvis-SpreadPaperTrack` | Hourly (time trigger) | `mattm` | Ready | **0** | 6/26 12:05 AM |

**Pre-holiday ledger** `engine/data/preholiday_paper_track/preholiday_state.json`:
`{"inception_date": "2026-06-25", "last_recorded_date": null}` — 0 fwd days (correct; next
pre-holiday eve = July 3).

**Scheduled tasks overall:** **84/84 OK, 0 FAIL.**
**IB Gateway:** port 4002 (paper) UP; CredMan `Jarvis/IBKR-Paper` = `Wolfof216`; port 4001
permanently blocked (expected).
**Engine venv:** `engine/.venv/Scripts/python.exe` = **Python 3.12.10** (correct; never 3.14/Store).
**MEMORY.md:** 18460 B (< 20480). 0 broken refs.
**Engine (port 8010):** NOT health-checked this session (focus = scripts/git, not live engine).
`/forward-test/status` referenced by scorecard but not exercised here.

**Nothing broken.**

---

## 4. IN-PROGRESS WORK
**None half-done.** No uncommitted edits, no open worktree mutations, no partial merges. Passive/
external only: master drifting ahead of the bridge (peer merges) + pre-holiday track accruing
observations. Neither needs action now.

---

## 5. BLOCKERS DISCOVERED
1. **`_spread_track` bridge cannot be RETIRED** until the MAIN checkout lands on master AND all 3
   forward tasks verify 0x0 from it. Blocked on 37 unmerged campaign commits + live peers. Biggest
   open thread. **Do NOT prune the worktree.**
2. **Bridge is 11 commits behind master** (`0ab1fa5` vs `66d2db3`). Not urgent — producers
   unchanged across those PRs. If a future master PR touches a forward-track producer, the bridge
   would run stale code. Repeatable fix: `git -C _spread_track checkout --detach origin/master`.
3. **Pre-existing master bug (carried, unfixed):** `Momentum(str, Enum)` AttributeError at
   `vix_percentile_regime.py:204` + `trend_signals.py:129` (pandas 3.x `.iloc[-1]` coercion).
   Proven on pure origin/master. Out of scope; flagged.
4. **IBGateway-AtLogon cold-logon recurrence (LOW):** merged union now falls to manual dialog
   (non-regressive) instead of hard-exit; a cold logon without `OP_SERVICE_ACCOUNT_TOKEN` + a
   CredMan import hiccup surfaces the manual dialog.
5. **No secret-remediation incidents found.** No rotation needed.

---

## 6. KEY DECISIONS MADE (rationale + tradeoffs)

**Phase A:** resolve ATR-trail toward-remote (LOCKED-SPEC, no post-p-value re-tune); do NOT rebuild
pre-holiday producer (PR #144 merged); family-fdr→master full convergence (Option B) via PR #145
with UNION forward_test.py resolution + authorized `[safety-review]` tag; **REFUSED the destructive
main-checkout sync** when it would clobber 37 unmerged commits + race 4 peers (surfaced instead of
complied — the session's most important call); **modernize the bridge instead of retiring it**
(zero main-checkout risk, real benefit).

**Phase B:** PR #3 updated in place not duplicated (PRs track branch head); `start-ibc-gateway.ps1`
conflict resolved as ORDERED UNION (CredMan primary → token-gated op → manual fallback + Force) —
strictly better than either side; merge-commit not squash (37 meaningful commits); branch deleted
post-merge (safe — fully in main; archive-never-delete is about files not merged branches);
per-file staging + one-semantic-change-per-commit throughout; chat_id `8676240038` treated as
non-secret (Telegram chat IDs aren't credentials); both failing tasks treated as transient
(verified workers clean + re-triggered) rather than over-engineered fixes.

---

## 7. TODO ITEMS (planned, not started)
- [ ] **Retire `_spread_track` bridge** once MAIN checkout reaches master + 3 tasks verify 0x0 (Blocker 1).
- [ ] **(Optional) Re-bump bridge** `0ab1fa5`→`66d2db3` if a master PR touches a forward-track producer (Blocker 2).
- [ ] **Fix the `Momentum(str,Enum)` master bug** (`vix_percentile_regime.py:204`, `trend_signals.py:129`) — Blocker 3.
- [ ] **Triage 3 unmerged `~/scripts` local branches** (user-gated): `chore/moc-gen-mdmd-fix`
  (1 ahead; change also landed via `77cad8b` → likely near-duplicate, verify-then-delete);
  `feat/hermes-state-backup-scripts` (2 ahead, has remote); `fix/scorecard-c2-live-llm-health`
  (2 ahead, has remote — DIFFERENT from merged `c2-llm-live`).
- [ ] **Pre-holiday forward-track** — passive; first data point ~July 3; gate-v2 verdict after enough fwd days.
- [ ] **(Carried) ATR-trail family** — kept on the board per user, validation concluded DEAD.

---

## 8. FULL CURRENT TO-DO LIST
**No active formal TaskCreate/TodoWrite list** — the harness repeatedly noted task tools unused;
the jarvis-loop discovery backlog (signals A–G) ran inline, NOT as a tracked prd.json, and is
**fully drained** (Round 2 = zero actionable). The complete remaining set = exactly §7 (all
user-gated or time-gated; none in flight). No hidden/partial/implicit todos.

---

## 9. GIT STATE (verbatim)

### `~/scripts` — `git status`
```
On branch main
Your branch is up to date with 'origin/main'.
nothing to commit, working tree clean
```
### `~/scripts` — `git log --oneline -20`
```
68ee426 Merge pull request #3 from mattamundson/fix/scorecard-c2-llm-live
8dd55c7 Merge remote-tracking branch 'origin/main' into fix/scorecard-c2-llm-live
7e8e0f7 feat(ibc-gateway): Credential Manager primary + Force recovery path
c6070c3 chore(disk-watch): normalize em-dash to ASCII for PS 5.1 safety
aacc9b0 fix(moc-gen): stop emitting career/GMS company MOCs; strip repeated .md
c4e9b25 feat(orphan-sweep): also reap orphaned Discord MCP server pythons
807ef9a fix(finance-sync): log failed syncs instead of dying silently
99b3755 fix(verdicts): track recovery setups without weekly false alarm
ae9fae2 feat(scorecard): automate C1 forward-test confirmation from DB
116a425 chore(obsidian-mcp): warn if CC-WMI-PATCH-v1 is reverted on reinstall
bc89b84 fix(hermes-sync): enumerate WSL profile dirs dynamically
8532a36 fix(notify-on-fail): run workers under pwsh7 + fix Telegram alert creds
12065d4 chore(tasks): retire archive-rotate, install non-destructive inbox-rotate
a6475ed fix(tv-cdp): probe DevTools endpoint instead of port LISTENING
880e9ed chore(load-secrets): add DISCORD_BOT_TOKEN 1Password reference
be7f19b fix(secret-scan): word-boundary anchors + restore multi-segment whitelist
e652eb1 feat(inbox-rotate): non-destructive Inbox->Archive rotation worker
f2ee936 chore(launchers): add hidden VBS launchers for forward paper-tracks
e853dac feat(ops): safe land-family-fdr-to-main propagation runbook
96020f0 feat(recall): graph-aware recall — seeds + their linked documents
```
### `~/scripts` — `git diff --stat`
```
(empty — clean)
```
### jarvis-trader `origin/master` — `git log --oneline -12`
```
66d2db3 fix(lint): silence I001 on late import blocking Engine Lint on master (#153)
b26960f docs: add repo-integration analyses for ai-market and financial-datasets MCP (#139)
622e47e test(engine): cover live vol-target overlay + offload path; fix unguarded to_thread crash (#116)
4ac73b8 fix(analysis): /analyze/technical 500 -- signal field is float, not str (#129)
a8c536f feat(observability): /trading-status/live -- per-symbol runtime state (#128)
278fac9 feat(risk): volatility-targeting sizing overlay [safety-review] (DEFAULT OFF) (#115)
733f132 feat(backtest): strategy-edge research wave — vol-targeting win + 3 gate studies (#111)
09030cd feat(mcpt): add bootstrap CI alongside the trade sign-flip test (#142)
223d206 docs: correct pitfall #3 — DSR is already gated in gate-v2 (#136)
8ebf7d7 fix(safety): guard phantom P&L from implausible marks + refuse trades on degraded-feed prices (#147)
0ab1fa5 Merge pull request #151 from mattamundson/integration/free-daily-to-master-2026-06-26
718af90 Merge free-daily calendar discovery into master
```
### jarvis-trader MAIN checkout — `git status -sb` (context only)
```
## claude/beautiful-fermi-yeecq4...origin/claude/beautiful-fermi-yeecq4 [ahead 1]
HEAD: af35329 fix(backtest): DSR degenerate variance fails conservative, not fake 1.0
dirty: 0 tracked-modified, 2 untracked
```
### `git worktree list` (jarvis-trader)
```
C:/Users/mattm/ThinkorSwim/jarvis-trader   af35329 [claude/beautiful-fermi-yeecq4]
C:/Users/mattm/ThinkorSwim/_spread_track   0ab1fa5 (detached HEAD)
```

---

## 10. PR LEDGER — every PR across the conversation
| PR | Repo | Status | What | Session role |
|---|---|---|---|---|
| **#144** | jarvis-trader | MERGED (pre-session) | Pre-holiday producer + registration + installer | Did NOT rebuild; installed missing daily task |
| **#145** | jarvis-trader | **MERGED `8caa81e`** | family-fdr→master (88/29) | Scoped, UNION-resolved forward_test.py, [safety-review], merged |
| **#151** | jarvis-trader | **MERGED `0ab1fa5`** | free_daily_export + daily_calendar_discovery | Integration worktree, 0-conflict merge |
| **#3** | home-scripts | **MERGED `68ee426`** | 37-commit maintenance batch | Updated title/body, resolved start-ibc-gateway.ps1, merged, cleaned |
| **#156** | jarvis-trader | **MERGED `8b32d46`** | This handoff → `docs/session-logs/` (Phase C) | Isolated worktree off master, PR, merged, branch cleaned |
| #90/#91 | jarvis-trader | MERGED (prior) | forward-test phantom fix | Referenced by scorecard C1 |
| #153/#139/#116/#129/#128/#115/#111/#142/#136/#147 | jarvis-trader | MERGED (peers, this session) | Advanced master `0ab1fa5`→`66d2db3` | Not mine; explains drift |

---

## 11. ARCHITECTURE CONTEXT — the forward-track / bridge system
**DARK forward paper-tracks** = observe-only validators for backtest-passing edge candidates needing
forward OOS confirmation before promotion. Each producer pulls fresh data, evaluates a
**pre-registered** signal, appends to an **isolated ledger** under `engine/data/<track>_paper_track/`
in the **MAIN checkout** (durable; survives worktree prune). They route **no orders**, touch **no
live DB/positions**, grade against the same **gate-v2** bar (`pf_ci_lower≥1.10`, `p_edge≥0.95`,
`mc_95th_dd≤5%`/4% ALT, `dsr≥0.10`) with a mandatory chronological **H1/H2 split** (pooled bootstrap
passes non-stationary edges — only the split exposes back-loaded ones).

**Why the bridge exists:** the scheduled tasks must run producers the MAIN checkout (on the campaign
branch) lacks. The hidden VBS launchers resolve the producer from `_spread_track` (converged master
code) FIRST, then fall back to the main checkout. **Launcher resolution order:** `_spread_track/
engine` → `jarvis-trader/engine` → (spread only) old verify-before-build worktree. The launchers
use the MAIN `.venv` python with cwd = bridge engine dir, so module resolution comes from the bridge.

**Why "modernize not retire":** retire = prune worktree → breaks tasks (fallback lacks producers).
Modernize = repoint worktree at fresher master → zero risk, real benefit. Chosen.

---

## 12. CONFLICT RESOLUTIONS — deep dive (3 this conversation)
**(a) `run_atr_trail_bounce.py` (A1, `be44c47`)** — toward-remote; kept kelt/tpotgt superset;
merged loader hunk (broad timestamp cols + `.sort_index()`); 54 tests green.

**(b) `forward_test.py` (A5, PR #145)** — UNION: master `trade_shuffle`/`ts_p` diagnostic +
family-fdr `strategy_type`; row-renderer emits both → 9-col lineage header
`| lineage | type | pre-reg | n_oos | p_edge | pf_ci_lo | ts_p | fdr | graduated |`;
`test_forward_test_diag.py` mocks → 2-arg `is_pre_registered`.

**(c) `start-ibc-gateway.ps1` (B10, PR #3)** — UNION + brace fix. main `e820bb2` added
`Invoke-ManualFallback` (bare manual dialog) + `OP_SERVICE_ACCOUNT_TOKEN` gate (op hangs ~30s at
unattended logon); mine `7e8e0f7` added CredMan PRIMARY + `-Force` stale-JVM recovery. Resolved:
```
idempotency (port 4002 up & !Force -> exit 0)
  -> [Force] stop stale Jts/ibgateway JVM, relaunch
  -> CredMan (Jarvis/IBKR-Paper) PRIMARY
       hit -> use
       miss -> op ONLY if OP_SERVICE_ACCOUNT_TOKEN set
                 (no op / no token / throw / empty -> Invoke-ManualFallback)
  -> inject TWSUSERID/TWSPASSWORD, launch IBC, scrub creds
```
Pitfall: the Edit consumed the `else`-closing brace; PS 5.1 AST parser caught `Missing closing
'}'`; re-added; re-parse clean (0 non-ASCII, balanced); live task → 0x0.

---

## 13. LESSONS / PITFALLS REINFORCED
- **Check `origin`/merged-PRs before concluding-absent or destroying state** (saved a redundant
  pre-holiday rebuild; prevented a 37-commit main-checkout clobber).
- **"Proceed" ≠ adjacent destructive actions** — STOP + surface when scope turns risky.
- **Read pytest's summary line, not a wrapper exit** (`EXIT=$?` masked "1 failed, 2744 passed").
- **PS 5.1 = ANSI + brace-strict** — em-dashes cascade to false exit-1; always ASCII-verify +
  AST-parse scheduled-task scripts.
- **Pooled bootstrap passes non-stationary edges** — chronological H1/H2 split mandatory.
- **Per-file staging always** (large uncommitted backlog; `git add -A` sweeps drift).
- **Archive, never delete** (the ~28 GB archive-rotate incident drives `inbox-rotate.ps1` design;
  merged git branches are the one safe-delete exception).
- **CredMan > op for unattended** — survives app-lock/reboot, no token needed (why the IBGateway
  task self-healed).

---

## 14. SUGGESTED NEXT ACTION (one)
When the MAIN jarvis-trader checkout next lands on `master`: **verify all 3 forward-track tasks run
from the main checkout (0x0), then retire the `_spread_track` bridge** (prune the worktree). Closes
the one real open dependency. Until then the bridge is correct and load-bearing — leave it.
Everything else is time-gated (pre-holiday accrual) or user-discretionary (3 stale branches, the
carried `Momentum` bug).

---

## 15. GLOSSARY — campaign + infra terms
- **gate-v2** — strategy promotion gate (`GATE_V2_ENFORCE_ROUTING=1`): `pf_ci_lower≥1.10`,
  `p_edge≥0.95`, `mc_95th_dd≤5%` core / ≤4% ALT, `dsr≥0.10`. Missing/stale → `NO_TRADE`.
- **MCPT** — Monte-Carlo permutation test (bar-permutation / trade sign-flip). PASS = in-sample
  p<0.01 AND walk-forward p<0.05. REJECT when in-sample PF≤1.0 (in-sample excellence).
- **DSR** — deflated Sharpe ratio (penalizes multiple-trial selection). Gate floor 0.10 core / 0.30 ALT.
- **H1/H2 split** — chronological first-half/second-half stationarity check; mandatory because
  pooled bootstrap passes back-loaded/non-stationary edges.
- **DARK track** — observe-only forward paper-track; no orders, no live DB, isolated ledger.
- **pre-holiday edge** — long bias into the session before US market holidays; SPY+GLD PASS gate-v2 ALT.
- **TOM** — turn-of-month effect (first stationary cost-surviving multi-regime edge of the arc).
- **kelt / tpotgt** — ATR-trail-flip confluence variants (4H-Keltner gate / TPO measured-move gate). DEAD.
- **FDR** — false-discovery-rate control across the lineage of pre-registered candidates.
- **lineage / pre-reg / graduated** — forward-test diagnostic columns: candidate identity, whether
  pre-registered, whether it has graduated the promotion gate.
- **`_spread_track` bridge** — worktree carrying converged master code for the forward-track tasks.
- **CredMan** — Windows Credential Manager; `Jarvis/IBKR-Paper` target holds the IBKR paper login.

---

## 16. ENVIRONMENT & TOOLING REFERENCE
- **jarvis-trader engine venv:** `engine/.venv/Scripts/python.exe` = **Python 3.12.10** (bootstrap
  `requirements-core.txt`; never system 3.14 / Store). Engine API port **8010**, dashboard **3010**,
  IB paper **4002** (live **4001** permanently blocked), Redis **6379**. Restart (Tier-3, Amo-gated):
  `.\restart_engine.ps1` (never `--reload`).
- **home-scripts repo:** `C:\Users\mattm\scripts`, remote `home-scripts.git`, default `main`.
- **config-backup repo:** `C:\Users\mattm\.claude`, remote `claude-config-backup.git` (PRIVATE),
  `handoffs/` tracked, `projects/` gitignored (secret-leak vector). Handoff index auto-gen:
  `~/scripts/handoff-index-gen.ps1` (164 HANDOFF_*.md files as of this session).
- **Key launchers (home-scripts):** `hidden-launchers/jarvis-{preholiday,spread,tom}-paper-track.vbs`
  (wscript, hidden), `start-ibc-gateway.ps1` (IBC unattended login), `notify-on-fail.ps1` (worker
  wrapper, exit-2-on-finding contract), `verify-jarvis-tasks.ps1 -FailOnly` (task health),
  `memory-hygiene.ps1` (broken-ref + size guard).
- **1Password refs used:** `op://Amo Personal/IBKR-Paper/{username,password}`,
  `op://Amo Personal/Telegram-Bot-Jarvis/password`, `op://Amo Personal/Discord-Bot-Jarvis/credential`.
  CredMan target `Jarvis/IBKR-Paper`. `OP_SERVICE_ACCOUNT_TOKEN` env gates unattended `op`.

---

## 17. SCHEDULED-TASK INVENTORY (relevant subset)
| Task | Trigger | Worker | This session |
|---|---|---|---|
| `Jarvis-PreHolidayPaperTrack` | Daily 5:10 PM | VBS → `preholiday_paper_track.py` | Installed (Phase A); verified 0x0 |
| `Jarvis-TomPaperTrack` | Daily 5:00 PM | VBS → `tom_paper_track.py` | Verified 0x0 |
| `Jarvis-SpreadPaperTrack` | Hourly | VBS → `spread_paper_track.py` | Verified 0x0 |
| `Jarvis-IBGateway-AtLogon` | At logon | `start-ibc-gateway.ps1` | Was 0xC (transient) → fixed → 0x0; worker merge-resolved |
| `Jarvis-DataIntegritySentinel` | Daily 5:35 AM | `jarvis_data_integrity_sentinel.py` | Was 0x1 (transient) → 0x0 |
| `Jarvis-InboxRotate` | Weekly Sun 02:00 | `inbox-rotate.ps1` | New worker committed (replaces archive-rotate) |
| (overall) | — | `verify-jarvis-tasks.ps1 -FailOnly` | **84/84 OK, 0 FAIL** (both rounds) |

---

## 18. JARVIS-LOOP SIGNALS — definitions + Round-1/Round-2 results
| Signal | Checks | Round 1 | Round 2 |
|---|---|---|---|
| **A** untracked in ~/scripts | new `.ps1/.ts/.py/.vbs/.md` | 4 (3 VBS + inbox-rotate) → committed | **0** |
| **B** modified tracked | unstaged changes | 18 + 1 deletion → 11 commits | **0** |
| **C** failing tasks | `verify-jarvis-tasks -FailOnly` | 2 (0x1, 0xC) → fixed | **0 / 84 OK** |
| **D** MEMORY.md size | >20480 B | 18460 ✓ | 18460 ✓ |
| **E** broken refs | `memory-hygiene.ps1` brokenRefs | 0 ✓ | 0 ✓ |
| **F** large untracked | >15 remaining | 4 ✓ | 0 ✓ |
| **G** night-time tasks | 00:00–05:59 risk | many but 82/84 OK, no 0xFFFD0000 → not actionable | clean |
**Stop conditions met:** all signals zero-actionable, no prd stories pending, no new stories Round 2.

---

## 19. PER-COMMIT ROLLBACK GUIDE (home-scripts; all on `main` @ `68ee426`)
To revert any single change without disturbing the rest: `git revert <hash>` (safe, creates an
inverse commit). High-value notes:
- **`12065d4` (archive-rotate retirement):** reverting RESTORES the deleted purge script AND the
  installer's `Jarvis-ArchiveRotate` entry — **do NOT** revert this casually (re-introduces the
  ~28 GB-deletion risk). If only the installer line is wrong, hand-edit, don't revert.
- **`8dd55c7` (the merge):** reverting a merge commit needs `-m 1`; prefer reverting the specific
  file commit (`7e8e0f7`) instead.
- **`7e8e0f7` (ibc-gateway):** the live `Jarvis-IBGateway-AtLogon` runs this file; after any
  revert, re-trigger the task + confirm 0x0.
- **`be7f19b` (secret-scan):** touches the credential scanners; after revert, re-run
  `scan-credentials.ps1` to confirm no FP regression.
- All others are isolated single-file improvements; revert is low-risk.

---

## 20. VERIFICATION MATRIX (claim → how verified, this session)
| Claim | Verification |
|---|---|
| Bridge at `0ab1fa5`, producers present | `git -C _spread_track log -1` + file existence loop |
| Pre-holiday producer runs observe-only | Ran exact launcher invocation → "0 new forward day(s)", exit 0 |
| Durable ledger untouched | `ls -la` of `preholiday_paper_track/` before+after (mtime/size unchanged) |
| 3 forward tasks healthy | `Get-ScheduledTaskInfo` → all LastResult 0 |
| Both failing tasks fixed | Ran workers (exit 0) + re-triggered tasks → 0x0; `verify-jarvis-tasks` 84/84 |
| 4 untracked clean | grep secret-pattern scan → 0 matches |
| 18 modified clean | read every `git diff` before commit; ASCII `grep -cP '[^\x00-\x7F]'` |
| start-ibc-gateway resolution valid | `[Parser]::ParseFile` AST → clean; 0 non-ASCII; live task 0x0 |
| PR #3 mergeable post-resolve | `gh pr view 3 --json mergeable,mergeStateStatus` → MERGEABLE/CLEAN |
| Pushed landed | local HEAD == `origin/...` rev-parse compare |
| config-backup is PRIVATE | `gh repo view --json isPrivate` → true (gate before pushing handoff) |
| master drift | `git log origin/master` → tip `66d2db3` ≠ bridge `0ab1fa5` |

---

## 21. CROSS-REFERENCE MAP (memory files + rules consulted)
- **Memory:** `project_preholiday_forward_shadow_2026_06_25`, `project_atr_trail_loader_fix_2026_06_25`,
  `project_daily_calendar_discovery_2026_06_24`, `project_session_anomaly_tom_edge_2026_06_24`,
  `feedback_check_origin_before_concluding_absent`, `feedback_git_concurrent_session_race`,
  `feedback_archive_never_delete`, `project_archive_rotate_purge_recovery_2026_06_24`,
  `feedback_notify_on_fail_exit_code_contract`.
- **Rules:** `rules/jarvis-trader.md` (gate-v2, ports, restart), `rules/git-hygiene.md` (per-file
  staging, HEREDOC, pathspec-commit), `rules/windows-pitfalls.md` (PS 5.1 ASCII, CredMan,
  localhost→IPv6), `rules/secret-hygiene.md` (patterns, forbidden paths), `rules/verification.md`
  (health gates), `rules/cleanup-and-archive.md` (archive-never-delete), `rules/handoffs.md`
  (this doc's structure), `rules/destructive-op-gates.md` (the refused main-checkout sync).

---

## 22. OPEN QUESTIONS FOR THE NEXT SESSION
1. When will the MAIN checkout land on master? (Unblocks bridge retirement.) Watch for the campaign
   branch `claude/beautiful-fermi-yeecq4` to merge — it had 37 unmerged commits.
2. Should the bridge auto-refresh to master tip on a schedule, or bump-on-touch? (Blocker 2.)
3. Is the `Momentum(str,Enum)` bug worth a standalone PR, or fold into the next regime-code touch?
4. Are the 3 stale `~/scripts` branches abandoned (delete) or parked work (keep)? Needs user call.
5. Does the live engine (port 8010) need a health pass next session? Not exercised here.
