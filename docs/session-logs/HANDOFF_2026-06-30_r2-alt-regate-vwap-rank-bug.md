# HANDOFF — 2026-06-30 — R2 ALT-survivor re-gate + the vwap `rank` authorization bug

> **Exhaustive continuation document.** Written so a fresh AI session (or human) can resume with
> zero context loss. Read this top-to-bottom before touching anything. The single open decision is
> the **vwap `rank` fix**, which is **proposed and awaiting Amo's explicit go** (§4, §7, §11).
>
> Companion artifacts in this same `docs/session-logs/` directory:
> - `SUMMARY_2026-06-30_r2-regate-vwap-rank-bug.md` — narrative/analytical session summary.
> - `CONVERSATION_2026-06-30_r2-regate-vwap-rank-bug.md` — full transcript render (3,209 turns).
>
> Canonical memory record (read alongside this): `~/.claude/projects/C--Users-mattm/memory/`
> `project_alt_gate_permissiveness_audit_2026_06_26.md` (R2/R3 sections appended this session).

---

## 0. Orientation — repo, branch, machine

| Field | Value |
|---|---|
| Repo | `C:\Users\mattm\ThinkorSwim\jarvis-trader` |
| Branch this session | `fix/corey-cache-stale-nodata` (diverged: 2 ahead / 172 behind `origin`) |
| `master` carries | **#178** `4c73631` (DSR runner migration) and **#188** `677a174` (R3b beta-harvest calendar) — both relevant; not on this branch |
| Engine venv | `engine/.venv/Scripts/python.exe` (Python 3.12.10; never 3.14 / Store) |
| Engine API / Dashboard | `http://127.0.0.1:8010` / `:3010` (use `127.0.0.1`, not `localhost`) |
| Verdict store | `engine/data/gate_v2_verdicts/` — **GITIGNORED** (top-level), with a few **tracked** files under `archive/` |
| Date | Work spanned 2026-06-29 evening → 2026-06-30 |

**Standing safety constraints (NON-NEGOTIABLE) — see §11 for full list:** never disable MES; archive
never delete; per-file staging only; no force-push / no shared-branch push without auth; verify before
reporting; gate changes governing tradeability are Tier-3 / Amo-gated.

---

## 1. Session summary — what was accomplished, in order

This session continued from a compaction summary. The prior session had merged **R3b** (beta-harvest
calendar routing, PR #188 squash `677a174`) and activated `BETA_HARVEST_GATE_ENFORCE=1` in
`engine/.env:468`. The user's first actionable instruction this session was "both" — accepting two
offered loose ends: (a) remove the merged R3b worktree, (b) set a watch to auto-pick-up R3a when the
DSR migration merged. Sequence of work:

1. **Removed the merged R3b worktree** `C:\Users\mattm\ThinkorSwim\_r3b_beta_harvest` and deleted its
   local branch `r3b-beta-harvest-calendar` (content already on `master` via #188 squash `677a174`).
   Verified 0 worktrees remain. (The background command reported "exit 1" only because the trailing
   `grep -i r3b` found no match — the success case.)

2. **Started to build the R3a-migration watcher → discovered it was unnecessary.** Wrote
   `~/scripts/watch-dsr-migration.ps1` (a one-shot scheduled-task watcher that would notify when
   `fix/dsr-runner-migration` landed). Before registering it, I validated its trigger signal against
   `origin/master` and found the migration **had already merged** as **PR #178** (`4c73631`,
   "fix(backtest): migrate all gate runners off mean-of-window-Sharpes DSR", committed 2026-06-29
   19:13). Confirming details:
   - All target runners (`run_mnq_breakout_rank2..7`, etc.) already compute `trade_level_dsr` on
     `origin/master`.
   - The branch `fix/dsr-runner-migration` still exists (local `c35d534` / remote `bd9572f`) but its
     single "unmerged" commit is the **squash-merge artifact** — content is fully on master.
   - **No peer session is on the gate-runner files** (the one repo-active peer, `7f55c1dd`, is on
     `feat/tradingview-mcp-gamma-kraken`).
   Conclusion: **R3a is unblocked**; the watcher would be watching for a past event → **deleted the
   never-deployed script** (`rm -f`, ephemeral self-authored scaffolding, never registered).

3. **Recommended PARKING R3a** after grounding it in code. R3a = "centralize the copy-pasted CORE/ALT
   gate conjunction across ~50 runners + retire the `run_mnq_breakout_rank3.py:82` local override."
   On inspection the actual divergence is only **2 files** (`run_mnq_breakout_rank3.py`,
   `run_mnq_breakout_rank7.py`), and the only behavioral difference is `GATE_WFO_CONSISTENCY="STRONG"`
   (vs central `["MODERATE","STRONG"]`) — a **stricter** gate that **fails safe**. The other local
   constant (`GATE_FIXED_PARAMS_MIN_PF=1.20`) is **identical** to central. "Killing the shadow" would
   *loosen* rank3/rank7 (let MODERATE-WFO MNQ through) — the wrong direction for a capital-safety
   system. So R3a's value collapses to cosmetic dedup; parked.

4. **The user chose R2 over R3a** ("yes" to kicking off R2). **Executed R2 — re-gate the ALT-path
   survivors through the now-honest DSR (#178).** Full results in §6. Headline: of the 3 live
   ALT-PASS verdicts (the *entire* live PASS surface; zero CORE passes exist), **only `MES_vwap_rank1`
   holds under honest DSR**; `MES_trend_rank7` and `MGC_singlefinder_fill_rank1` are stale,
   orphaned, and fall.

5. **Attempted to retire (archive) the 2 stale verdicts → verification caught a load-bearing bug.**
   Moved the 2 stale canonicals + 3 backups into `gate_v2_verdicts/archive/`. Immediately ran
   `is_strategy_authorized('MES')` → returned **`(False, ...)`**. Root cause: the honest survivor
   `MES_vwap_rank1.json` is **unreadable by `gate_v2_policy`** because it lacks a top-level `rank`
   field — so MES's authorization had been riding entirely on the now-retired stale `rank7`. Full
   mechanics in §5. **Reverted all 5 file moves**; `is_strategy_authorized('MES') -> (True,
   'authorized')` restored.

6. **Repaired a self-inflicted git regression from the retire/revert dance.** The `mv` into
   `archive/` had **clobbered a *tracked* historical file** `archive/MES_trend_rank7.json` (a
   2026-04-25 archived record, distinct from my 06-27 top-level stale verdict); the revert then moved
   it out, leaving git showing it `deleted`. **`git restore`d** it to the committed HEAD content.
   Verdict dir now shows no tracked changes.

7. **Recorded everything in memory** and **proposed the corrected 3-step fix** (§4). The user then
   asked twice for "recommendations and suggestions" (answered in §10/§11), then requested this
   handoff package.

---

## 2. Conceptual background a resumer needs (the gate machinery)

This is the domain model the rest of the doc assumes. Three distinct layers, often conflated:

### 2a. `gate_v2_verdict` — the GATE (does a strategy pass?)
Computed per strategy by each runner (e.g., `run_mes_vwap_rank1.py`) via
`_gate_v2_helpers.compute_gate_v2` / `wfo_lifecycle`. Dual-path:

| metric | CORE | ALT |
|---|---|---|
| `pf_ci_lower` (bootstrap PF 5th-pctile) | ≥ 1.10 (`GATE_PF_CI_LOWER`) | **dropped** |
| `p_edge` (frac of OOS windows PF>1) | ≥ 0.95 (`GATE_P_EDGE`) | **dropped** |
| `dsr` (deflated Sharpe) | ≥ 0.10 (`GATE_DSR`) | ≥ 0.30 (`GATE_DSR_ALT`) |
| `mc_95th_dd` (Monte-Carlo 95th-pctile drawdown) | ≤ 5% (`GATE_MC_DD_CORE`) | ≤ 4% (`GATE_MC_DD_ALT`) |
| `wfo_consistency` | — | ∈ {MODERATE, STRONG} |
| `fixed_params_min_pf` | — | ≥ 1.20 |
| cost survival | — | ≥ realistic tier |
| OOS trade floor | ≥ 100 (`MIN_TOTAL_OOS_TRADES`) | ≥ 100 |

ALT's design trade: it swaps noisy small-N bootstrap significance (`pf_ci_lower`, `p_edge`, which blow
out at the campaign's chronic n≈16–30) for point-estimate robustness (3× DSR + param stability + cost
survival + tight DD). Defensible at small N. **But the entire live survivor set passes only via ALT.**

### 2b. `gate_v2_policy` — AUTHORIZATION (is a *symbol* allowed to trade?)
`engine/backtest/gate_v2_policy.py`. Key functions: `is_strategy_authorized(symbol)`,
`is_ungate_eligible(symbol)`, `get_last_verdict(symbol)`, `list_verdicts`, `_iter_verdict_files`.
Model: a symbol is authorized if it has **any non-stale PASS verdict across all its rank files**
(`MAX_VERDICT_AGE_DAYS = 14`). It reads **top-level `*.json` only** (the `archive/` subdir is treated
as retired history). **CRITICAL:** `_iter_verdict_files` does `int(doc["rank"])` and **skips any file
missing a top-level `rank`** with a logged warning "unreadable verdict file ...: Missing required
verdict field: 'rank'". This is the locus of the bug (§5).

### 2c. `paper_config` — EXECUTION (what actually paper-trades?)
`engine/backtest/paper_config.py`. Per-symbol dicts with `enabled: bool`. Current state (§3). This is a
**second, independent gate** below authorization — even an authorized symbol won't trade unless its
config is `enabled` AND the policy doesn't block it.

### 2d. DSR honesty history (why R2 exists)
- The **degenerate fake-1.0 bug** (fixed by `af335299`, "D1"): when a window had ~1–2 trades, variance
  was undefined and the old code returned a **fake `dsr=1.0`**, which sails over both the 0.10 CORE and
  0.30 ALT floors. The D1 fix maps the degenerate case to **`0.0` + a flag** instead.
- The **mean-of-window-Sharpes inflation** (fixed by `4dd58d8` for legacy MGC, and **#178 `4c73631`**
  for all remaining runners): the old DSR averaged per-window Sharpes (inflated); the fix uses
  `trade_level_dsr` computed from per-trade returns with global trial count.
- **Consequence:** every ALT-PASS verdict created **before #178 (2026-06-29 19:13)** used possibly
  inflated/degenerate DSR. ALT is entirely load-bearing on DSR. → R2: re-gate them honestly.

---

## 3. Current state — running / stopped / broken

- **MES authorization: HEALTHY but on STALE evidence.** `is_strategy_authorized('MES') -> (True,
  'authorized')` (verified post-revert). It resolves via the **stale `MES_trend_rank7`** (rank=7,
  created 06-27, pre-#178), **NOT** the honest `MES_vwap_rank1` (which the policy can't read). This is
  the integrity defect, not a crash.
- **Live top-level PASS surface (3 files):**
  | file | via | rank field | status |
  |---|---|---|---|
  | `MES_trend_rank7.json` | alt | `7` (readable) | **STALE** (pre-#178, family re-validates FAIL) — currently authorizes MES |
  | `MES_vwap_rank1.json` | alt | **MISSING** (policy can't read) | **HONEST PASS** but invisible to authorization |
  | `MGC_singlefinder_fill_rank1.json` | alt | `1` (readable) | **STALE** (MGC family eliminated 06-26; MGC paper-disabled) |
- **`paper_config` enabled states (verified):** MCL=False, MNQ=False, **MGC=False** (disabled 06-26:
  "rank4 re-run FAILs gate v2"), **MES_TREND=True** (but comment: "gate_v2_policy blocks trades
  (INSUFFICIENT_SAMPLE); runner still polls for data"), MES_15M=False. **No MES_VWAP config entry** —
  vwap is **dark-shadow/observe-only** via task `Jarvis-VWAP-PaperTrack` (`vwap_paper_track.py`),
  deliberately (per the funnel work).
- **Net live-trading exposure of the stale verdicts: NONE.** paper_config provides a correct second
  gate (MGC disabled; MES_TREND policy-blocked). The stale PASSes are verdict-ledger cruft, not active
  trades.
- **git verdict dir:** clean (no tracked changes). The archive-clobber is repaired.
- **Engine:** not touched this session (no restart). Health unverified — if needed, hit `/health` and
  require `status=ok` + `tradingview_mcp_healthy` + `llm_path_healthy` before claiming healthy
  (`rules/verification.md`). Steady-state startup ≈ 229s.
- **Broken:** exactly one thing — the gate↔policy disconnect for vwap (§5). Nothing else.

---

## 4. In-progress work — the corrected 3-step fix (PROPOSED, NOT STARTED)

**Status: awaiting Amo's explicit go.** The user asked for recommendations, then this handoff; he has
NOT said "proceed" on the fix. **Do not apply any source edit or verdict retirement until he does.**

The fix, in this exact order (sequencing guarantees MES is never left unauthorized):

1. **Make the honest vwap verdict policy-readable.**
   - Edit `engine/backtest/run_mes_vwap_rank1.py`, the `verdict_doc` dict that begins at **line 684**.
     It currently has `"hypothesis": "rank1"` (line 687) but **no top-level `"rank"`**. Add
     `"rank": 1,`. (A nested `"rank": 1` already exists ~line 768 inside a sub-structure; the policy
     reads the *top* level only.)
   - ALSO patch the **current on-disk** `engine/data/gate_v2_verdicts/MES_vwap_rank1.json` to add
     `"rank": 1` at top level. That file is already the honest re-run output (created_at
     `2026-06-30T01:53Z`); adding the field is **metadata completion, not re-derivation** — avoids
     another ~20-min WFO/MC re-run. (If you prefer a clean regenerate instead, just re-run
     `python -m backtest.run_mes_vwap_rank1` from `engine/` after editing the runner.)
2. **Verify** `is_strategy_authorized('MES')` now resolves via `MES_vwap_rank1` (PASS, rank 1) — i.e.,
   MES authorized on its HONEST edge. Confirm `get_last_verdict('MES')` no longer points at rank7.
3. **Then** retire the 2 stale verdicts (`MES_trend_rank7`, `MGC_singlefinder_fill_rank1`) + their
   `_pre-r2-regate-2026-06-29.json` backups into `gate_v2_verdicts/archive/`.
   - **⚠️ Do NOT clobber tracked `archive/` files.** This session clobbered
     `archive/MES_trend_rank7.json` (a 2026-04-25 record) and had to `git restore` it. Before moving,
     check whether `archive/<name>.json` exists; if so, use a timestamped suffix (the codebase's
     `verdict_lifecycle.py` archives as `{stem}_{ISO8601}.json` — prefer that mechanism, or
     `archive/MES_trend_rank7_2026-06-30T...Z.json`).
   - Re-verify `is_strategy_authorized('MES') -> True` (now via vwap) AND the live PASS surface is
     `MES_vwap_rank1` alone.

**Why this is strictly safe:** step 1 *adds* an honest authorization path before step 3 removes the
stale one, so MES is authorized at every intermediate state. It also never edits any metric or verdict
— only the `rank` identifier — so it cannot "manufacture" a pass.

---

## 5. Blockers discovered — issues needing resolution (priority order)

### B1 — [LOAD-BEARING BUG, P1] Honest vwap survivor invisible to `gate_v2_policy`
- **Mechanism:** `run_mes_vwap_rank1.py` writes `verdict_doc` with `"hypothesis":"rank1"` but no
  top-level `"rank"`. `gate_v2_policy._iter_verdict_files` calls `int(doc["rank"])` → raises "Missing
  required verdict field: 'rank'" → the file is **silently skipped**. So `MES_vwap_rank1` (an honest
  PASS) never authorizes MES; the **stale `rank7`** does.
- **Evidence:** retiring rank7 flipped `is_strategy_authorized('MES')` to False; the policy log
  emitted "unreadable verdict file ...MES_vwap_rank1.json: Missing required verdict field: 'rank'";
  the vwap JSON top-level keys are `[alt_verdict, aux_freshness, champion_params, contract_spec,
  core_verdict, created_at, family, gate_v2, gate_v2_metrics, hypothesis, lineage, n_alt_passed,
  n_core_passed, passed_via, symbol, thresholds, verdict, wfo_config, windows]` — **no `rank`**.
- **Impact:** validation (gate PASS) and authorization (policy) are disconnected for the campaign's
  one real edge. **Fix = B-fix in §4.** This is the headline finding.

### B2 — [BROADER SCHEMA GAP, P2] Other verdict files also policy-unreadable
- `M2K_orb_rank1.json` (missing `rank`), `M6B/M6E/ZB/ZN_trend_diversifier.json` (`rank: None`) all
  throw in `_iter_verdict_files` and are skipped. Mostly non-PASS, so lower urgency.
- **⚠️ Do NOT "fix" by making `gate_v2_policy` tolerant of missing/`hypothesis`-style rank** without an
  audit first: a tolerant parser could **silently auto-authorize a previously-invisible PASS** for some
  symbol. Prefer the narrow per-runner fix (B1). If a general fix is wanted, first enumerate what each
  unreadable file's verdict *is*, and confirm none would newly authorize a symbol.

### B3 — [POLICY GAP, pre-existing, P3] any-PASS-across-families
- `is_strategy_authorized(symbol)` authorizes on **any** family's PASS. So once vwap is readable, it
  also "authorizes" the *failing* `MES_TREND` config (different family). Noted in the audit memory,
  not in scope unless Amo wants the gate↔policy↔paper_config layers reconciled (it touches live
  trading config = Tier-3).

### B4 — [CLEANUP, P4] Stale merged remote branch
- `r3b-beta-harvest-calendar` is still on `origin` (= #188 squash `677a174`). The auto-classifier
  blocks me deleting it without explicit scope. Amo deletes with:
  `! git -C "C:\Users\mattm\ThinkorSwim\jarvis-trader" push origin --delete r3b-beta-harvest-calendar`

### B5 — [DATA HYGIENE, P5] vwap runner writes no `rank` → future re-runs regress
- Even after patching the on-disk file, a future re-run of `run_mes_vwap_rank1.py` will overwrite it
  *without* `rank` unless the runner is also fixed. **B1's runner edit closes this.** Verify any other
  runner that writes `hypothesis`-style verdicts (not `rank`) has the same latent issue.

---

## 6. R2 dataset — the re-gate results in full

The entire **live** top-level PASS surface before R2 was **3 verdicts, all via ALT, all created
before #178** (DSR honesty landed 2026-06-29 19:13). **Zero CORE passes exist anywhere in the system.**

### `MES_vwap_rank1` — ✅ HOLDS (honest)
Re-ran `python -m backtest.run_mes_vwap_rank1` (background, ~20 min: WFO + bootstrap CIs + Monte
Carlo). New verdict written `created_at 2026-06-30T01:53:24Z`:
```
GATE v2 VERDICT: PASS (via alt)
  pf_ci_lower   = 1.8349   (need >= 1.1)      <- passes CORE too
  p_edge        = 0.8571   (need >= 0.95)     <- the ONLY CORE failure
  mc_95th_dd    = 2.0257%  (core<=5% / alt<=4%)
  dsr           = 1.000000 (core>=0.1 / alt>=0.3)
  wfo_consistency = STRONG
  fixed_params_min_pf = 1.3690 (need >= 1.2)
  cost_survives_through = catastrophic
  trades = 339
  core_verdict = FAIL  | alt_verdict = PASS
```
- **The "fake-1.0 DSR" hypothesis is REFUTED.** With **339 trades** variance is well-defined (nowhere
  near the 1–2-trade degenerate case the D1 fix maps to 0.0), so `dsr=1.0` is a genuinely **saturated**
  deflated Sharpe (the CDF rounds to 1.0 for a large z, expected for PF 3.43 / 339 trades). And the
  PASS does **not** lean on DSR precision — it clears every ALT floor by wide margins (pf_ci_lower 1.83
  vs 1.1; fixed_params 1.37 vs 1.2; cost to catastrophic; DD 2.0% vs 4%). **The campaign's lone
  validated survivor is real.**

### `MES_trend_rank7` — ❌ FALLS (stale, orphaned)
- **No runner exists** (`run_mes_trend_rank7.py` absent; superseded by rank8–11). The family rank9/11
  already re-validate **FAIL** post-fix (edge evaporated on fresh data per prior memory). The on-disk
  06-27 PASS (dsr 0.667) is pre-#178 (likely mean-of-window-Sharpes). Regenerated on 06-27 06:00 by the
  weekly verdict-refresh, but that queue (`jarvis-strategy-rd-queue.txt`) only contains
  `run_mes_trend_rank11` + `run_mgc_trend_rank4` — so rank7 is an orphan that won't self-heal.

### `MGC_singlefinder_fill_rank1` — ❌ FALLS (stale, orphaned)
- No runner writes it (`backtest/singlefinder.py` is the signal library, not the verdict writer; no
  script greps to `singlefinder_fill`/`MGC_singlefinder`). MGC family **ELIMINATED 06-26** (all
  variants honest FAIL); MGC is `enabled:False` in paper_config. The on-disk 06-26 PASS is pre-#178.

### Net
**The honest live authorization surface is `MES_vwap_rank1` alone** — once it's made policy-readable.
One validated edge; everything else stale or failed. All 3 stale verdicts backed up as
`*_pre-r2-regate-2026-06-29.json` (gitignored).

---

## 7. TODO items — planned but not started

- [ ] **(AWAITING AMO GO) Execute the refined 3-step vwap-`rank` fix** (§4). **P1.**
- [ ] Audit the other policy-unreadable verdict files (M2K_orb, ×4 `_diversifier`) **before** any
      `gate_v2_policy` schema-tolerance change (B2). Enumerate each file's verdict; confirm none would
      newly authorize a symbol.
- [ ] (Amo / Tier-3) Reconcile gate↔policy↔paper_config so the one honest edge (vwap) is what's
      *authorized AND configured*, and failing trend configs retired (B3). Touches live trading config.
- [ ] (Amo) Delete stale remote branch `r3b-beta-harvest-calendar` (B4).
- [ ] (Parked) R3a — only if Amo wants central gate **tightened to STRONG** (NOT a loosen-rank3
      refactor). 2 files: `run_mnq_breakout_rank3.py:82`, `run_mnq_breakout_rank7.py`.
- [ ] (Strategic, Amo) Point discovery at less-exhausted spaces (cross-instrument / regime-conditional;
      Phase-D instruments VIX/VXX/options) — simple intraday / calendar / relval edge space is largely
      exhausted (recent discovery: calendar → mostly null, relval → clean null, intraday-simple → 0
      survivors). The campaign has exactly ONE validated edge (MES VWAP). One edge isn't a portfolio.

---

## 8. The full to-do list currently held

**No formal TodoWrite/Task-tool list is active.** This session was a short, linear
investigate-then-act sequence; state was tracked inline rather than via the task tool (the periodic
"consider TaskCreate" reminders were intentionally not acted on — the work didn't warrant a parallel
task board). **The authoritative, exhaustive task state is §7.** The single blocking, actionable item:
execute the 3-step vwap-`rank` fix once Amo says go (§4).

---

## 9. Files created / modified / moved — full inventory

### Repo working tree (`C:\Users\mattm\ThinkorSwim\jarvis-trader`)
| Path | Action | Tracked? | Why / note |
|---|---|---|---|
| `engine/data/gate_v2_verdicts/MES_vwap_rank1.json` | **rewritten** | gitignored | Honest re-gate output (created_at 06-30T01:53Z, PASS via alt). Still missing top-level `rank` (the bug). |
| `engine/data/gate_v2_verdicts/MES_vwap_rank1_pre-r2-regate-2026-06-29.json` | **created** | gitignored | Backup of pre-re-run vwap. Idempotent same-symbol PASS; harmless. |
| `engine/data/gate_v2_verdicts/MES_trend_rank7_pre-r2-regate-2026-06-29.json` | **created** | gitignored | Backup of stale rank7. |
| `engine/data/gate_v2_verdicts/MGC_singlefinder_fill_rank1_pre-r2-regate-2026-06-29.json` | **created** | gitignored | Backup of stale singlefinder. |
| `engine/data/gate_v2_verdicts/archive/MES_trend_rank7.json` | **clobbered → `git restore`d** | **tracked** | Net zero (back to committed 2026-04-25 content). |
| `docs/session-logs/HANDOFF_2026-06-30_r2-alt-regate-vwap-rank-bug.md` | **created** | tracked | This document. |
| `docs/session-logs/SUMMARY_2026-06-30_r2-regate-vwap-rank-bug.md` | **created** | tracked | Narrative summary. |
| `docs/session-logs/CONVERSATION_2026-06-30_r2-regate-vwap-rank-bug.md` | **created** | tracked | Full transcript render (3,209 turns, ~2.8 MB). |

**No source code was modified.** `engine/backtest/run_mes_vwap_rank1.py` is the **proposed** edit
target (B1) but was only *read* this session; it remains untracked-and-unmodified.

### Non-repo filesystem
- `C:\Users\mattm\scripts\watch-dsr-migration.ps1` — **created then deleted** (obsolete; net zero).
- `C:\Users\mattm\ThinkorSwim\_r3b_beta_harvest\` — **removed** (merged worktree).
- `...\scratchpad\transcript_to_md.py` — converter used to build the CONVERSATION doc (scratch).

### Memory (`~/.claude/projects/C--Users-mattm/memory/`)
- `project_alt_gate_permissiveness_audit_2026_06_26.md` — **appended** the R3a-unblocked/R3b-cleanup
  note, the "R2 EXECUTED" results, and the "R2 EXPOSED A LOAD-BEARING BUG" section with the corrected
  fix sequence. **Canonical record — read first next session.**

### Remote
- Deleted local + worktree branch `r3b-beta-harvest-calendar`. Stale **merged remote** branch of the
  same name remains on origin (B4).

---

## 10. Key decisions made (with rationale)

1. **R2 over R3a.** R3a reframed as low-value/cosmetic (2-file divergence; the divergent `STRONG` is
   *stricter/safer* — retiring it loosens the gate). R2 (honest re-gate of ALT survivors) chosen as
   the higher-value integrity check, now possible because #178 landed.
2. **vwap `dsr=1.0` is honest, not the degenerate fake** (339 trades ⇒ defined variance ⇒ saturated
   deflated Sharpe). The fake-1.0 hypothesis is refuted; vwap is a real survivor.
3. **Narrow per-runner `rank` fix, not a `gate_v2_policy` tolerance change** (B2 rationale: avoid
   silently auto-authorizing other invisible PASSes).
4. **Patch the on-disk verdict + fix the runner, not a full re-run** (on-disk file is already the
   honest output; `rank` is metadata completion).
5. **Do NOT change vwap's trading status.** It's deliberately dark-shadow/observe-only. The fix is
   integrity-only (gate↔policy alignment), not a promotion to active paper trading.
6. **never-disable-MES upheld.** Reverted the retirement the instant MES went unauthorized; any
   retirement must be sequenced AFTER vwap is policy-readable.
7. **Archive, never delete.** Used the codebase's `archive/` convention + `_pre-r2-regate` backups;
   `git restore`d the clobbered tracked archive rather than losing it; deleted only the
   ephemeral/obsolete watcher script.
8. **Did not register the migration watcher** — the event (migration merge, #178) had already occurred.

---

## 11. Recommendations & suggestions (the standing guidance Amo asked for)

1. **Do the fix — narrow, no re-run** (B1 / §4). It corrects a genuine integrity defect and puts MES
   on honest evidence; low risk; strictly strengthens MES.
2. **Don't generalize the policy parser yet** (B2). Narrow fix the one verified PASS; audit the rest
   first.
3. **Don't touch vwap's trading status** (deliberately observe-only).
4. **Strategic read:** R2 leaves the campaign with **one** validated edge (MES VWAP) and **zero** CORE
   passes. The plumbing fix makes that edge correct/visible; it doesn't create new edges. Recent
   discovery says the simple-edge space is largely exhausted (calendar→mostly null, relval→clean null,
   intraday-simple→0 survivors). Suggested direction after the fix: stop re-mining simple intraday;
   aim discovery at less-exhausted spaces (cross-instrument/regime-conditional structure; Phase-D
   instruments VIX/VXX/options) and harden the one real edge + calendar shadows into a robust
   observe-then-size pipeline. **One edge isn't a portfolio**, and mining the exhausted space would
   just manufacture noise.

### Constraints the next session MUST preserve (verbatim-critical)
- **NEVER disable MES** ("10000% never"): never set `paper_config[MES].enabled=False`, gate-block MES,
  or make `is_strategy_authorized('MES')` False. Any verdict retirement touching MES must keep MES
  authorized at every step. (`feedback_never_disable_mes`.)
- **Archive, never delete.** Never clobber a tracked `archive/` file (use timestamped suffix /
  `verdict_lifecycle.py`).
- **The 3-step fix is NOT yet authorized** — Amo asked for recommendations + this handoff, not
  "proceed." Do not apply edits until he explicitly says go.
- **Verify before reporting** — always run `is_strategy_authorized('MES')` + the live-PASS enumeration
  after any verdict-dir change.
- Per-file staging only (no `git add -A`); no force-push / no shared-branch push without auth; no
  `--no-verify`. `gate_v2_verdicts/` is gitignored; engine venv = `engine/.venv/Scripts/python.exe`.

---

## 12. Git state (verbatim, annotated)

`gate_v2_verdicts/` is **gitignored** (verified via `git check-ignore`), so this session's verdict
re-run + backups do NOT appear in git. This session made **no commits**.

### `git status` (key lines)
```
On branch fix/corey-cache-stale-nodata
Your branch and 'origin/fix/corey-cache-stale-nodata' have diverged,
and have 2 and 172 different commits each, respectively.

Changes not staged for commit:
	modified:   .gitignore
	modified:   dashboard/dashboard.code-workspace
	modified:   docs/reports/METRICS_SNAPSHOT.json
	modified:   engine/data/forecast_reports/2026-06-25.md
	(archive/MES_trend_rank7.json was 'deleted' — RESTORED this session; no longer shown)

Untracked files:
	dashboard/AGENTS.md
	docs/architecture/DASHBOARD_PAGE_ROUTER_MAP.md
	docs/reports/tearsheets/2026-06-27_07-00_paper_paper.html
	engine/backtest/run_mes_vwap_rank1.py      <-- vwap runner (untracked, pre-existing; the B1 fix target)
	engine/backtest/vwap_paper_track.py
	engine/data/forecast_reports/2026-06-26.md ... 2026-06-28.md
	engine/data/forecast_reports/calibration_2026-06-28.md
	engine/data/morning_forecasts/2026-06-26.json ... 2026-06-29.json
	engine/data/vec_index.db.tmp
	engine/systematic/
	docs/session-logs/HANDOFF_2026-06-30_*.md / SUMMARY_2026-06-30_*.md / CONVERSATION_2026-06-30_*.md  (this package)
```
**None of the pre-existing modified/untracked files were changed by this session** (branch drift).

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
`master` separately carries **#178** (`4c73631`, DSR migration) and **#188** (`677a174`, R3b). This
branch is 172 behind origin — **do not reflexively merge/rebase; confirm intent with Amo**
(`rules/git-hygiene.md`).

### `git diff --stat`
```
 .gitignore                                  |  3 ++
 dashboard/dashboard.code-workspace          | 16 ++++++-
 docs/reports/METRICS_SNAPSHOT.json          | 40 ++++++++--------
 engine/data/forecast_reports/2026-06-25.md  |  6 +--
 (archive/MES_trend_rank7.json deletion restored — not shown post-restore)
 4 files changed (pre-existing drift; not this session's work)
```

---

## 13. Exact verification commands (copy/paste to re-confirm state)

```bash
cd /c/Users/mattm/ThinkorSwim/jarvis-trader/engine
PY=".venv/Scripts/python.exe"
# 1) MES authorization (MUST be True):
"$PY" -c "import sys;sys.path.insert(0,'.');from backtest import gate_v2_policy as P;print(P.is_strategy_authorized('MES'))"
# 2) Live top-level PASS surface:
"$PY" - <<'PYEOF'
import json,glob,os
for f in sorted(glob.glob('data/gate_v2_verdicts/*.json')):
    if 'pre-r2-regate' in f: continue
    j=json.load(open(f)); g=j.get('gate_v2',j)
    if (j.get('verdict') or g.get('verdict'))=='PASS':
        print(os.path.basename(f),'| via',j.get('passed_via') or g.get('passed_via'),'| rank',j.get('rank','<MISSING>'))
PYEOF
# 3) Verdict dir git-clean check (from repo root):
cd .. && git status --short engine/data/gate_v2_verdicts/
```
Expected now: (1) `(True, 'authorized')`; (2) three PASS lines incl. `MES_vwap_rank1 ... rank <MISSING>`;
(3) empty. After the B1 fix: (1) still True (now via vwap); after step-3 retirement: (2) only
`MES_vwap_rank1 ... rank 1`.
