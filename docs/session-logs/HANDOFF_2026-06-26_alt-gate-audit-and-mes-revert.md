# HANDOFF — 2026-06-26 — ALT Gate Audit, MES Re-Validation, and Full Revert

> Written at Amo's explicit request (delivered via clipboard). This is an **exhaustive** handoff,
> designed so a fresh AI session can continue with zero context loss. It factors in the entire
> conversation, including the pre-compaction portion (pandas-3 convergence) and the live portion
> (spread gate, ALT audit, MES re-validation, revert).
>
> **Repo:** `jarvis-trader`. **Where the work happened:** the **`jt-campaign` git worktree** at
> `C:\Users\mattm\ThinkorSwim\jt-campaign`, branched off `origin/master`. The MAIN checkout
> (`C:\Users\mattm\ThinkorSwim\jarvis-trader`) is **peer-active** on branch
> `fix/corey-cache-stale-nodata` and was never touched. All edits, commits, and PRs were made from
> the worktree against `origin/master`.

---

## 0. THE OVERRIDING RULE — READ FIRST

**NEVER disable MES. NEVER gate-block MES. Regardless of any backtest or gate-v2 verdict.**

Amo's emphatic standing directive, given verbatim this session: *"I 10000% never want to disable MES."*

Operationally this means: do **not** propose, build, or merge anything that
- sets `paper_config[MES].enabled = False`, or
- causes `is_strategy_authorized("MES")` to return `(False, ...)`, or
- causes `is_ungate_eligible("MES")` to return `False`, or
- adds MES to a `DO_NOT_TRADE` / validation-only / gate-exemption-that-blocks set.

It is **fine and welcome to REPORT** that MES backtests weakly (it does — see §5). It is **not
fine to ACT** on that by disabling it. If you design any gate tightening that would, as a side
effect, block MES, you must **exempt MES explicitly** or not ship the change. Flag the conflict
once, then honor the directive.

Persisted to: `~/.claude/projects/C--Users-mattm/memory/feedback_never_disable_mes.md`
and indexed in `MEMORY.md`. This rule is **non-negotiable and durable across sessions.**

Why it matters: MES is the flagship instrument of the system (the original validated edge — MES 1h,
PF 5.27, Sharpe 4.16). Amo's trading-desk judgment on what runs in paper is his call and outranks any
model's read of a backtest. Per global CLAUDE.md: never push back on taste/preference.

---

## 1. SESSION SUMMARY — the full narrative arc, in order

This was a long multi-arc session. The throughline: a routine "improve the gate" task drilled down,
via honest re-validation, into discovering that the only live paper symbol (MES) was authorized on a
stale verdict for a strategy that no longer has an edge — and then Amo decisively chose to keep MES
running anyway, so everything gate-related was reverted. Below is the arc with the reasoning at each
fork, because the *why* is what decays fastest.

### Arc A — pandas-3.x convergence (pre-compaction; MERGED, still on master)

**Problem:** `pandas>=3.0` coerces `str`-subclass Enum members to plain `str` when they live inside a
`pd.Series`. So `VixTier(str, Enum)` and `Momentum(str, Enum)` members, once put through a Series,
came back as bare `str` — and downstream `.value` / `.map(t.value)` either returned a raw string or
raised `AttributeError`. Two concrete live defects in `engine/backtest/`:
- `vix_percentile_regime.classify_latest` — `momentum=mom_series.iloc[-1]` stayed a `str`, so
  `regime_snapshot().momentum.value` raised `AttributeError`. **Fix:** wrap as `Momentum(...)`.
- `trend_signals.generate_sma_trend_signals` vix_regime_block — `.map(lambda t: t.value)` raised.
  **Fix:** `.map(lambda t: getattr(t, "value", t))`.

**Deeper structural issue found:** `requirements-core.txt` pinned `pandas>=2.2.3` UNBOUNDED, so CI
resolved 2.2.x (enums preserved) and stayed green while local dev ran 3.0.2 (enums coerced) — a
silent CI-vs-local drift that masked the bug class. Other str-Enum-in-Series sites stay latent until
CI happens onto 3.x.

**Decision (Amo: "best option no matter how aggressive and risky"):** converge production to pandas
3.x rather than pin CI back to 2.x. Bounded the pin to `>=3.0,<4.0` (the `<4.0` guards the Pandas4
break the deprecation warnings foreshadow); numpy → `>=2.2.6`.

**Shipped:**
- PR **#161** (`18e658e`) — str-Enum rebuild fix (the two files above).
- PR **#162** (`5393799`) — `requirements-core.txt` + `requirements.txt` pandas/numpy convergence.
  Note: a force-push to retitle was BLOCKED by the destructive-op-guard hook → resolved by soft-reset
  to `origin/chore/pandas3-ci` + a stacked fast-forward commit `6385427` (no force).
- PR **#164** (`b061b74`) — cross-platform fix: `engine/vault/paths.py` `read_notes_text` label uses
  `.as_posix()` (OS-independent LLM citation labels); `engine/tests/test_integration.py` added
  `_engine_testable()` (requires an authed 200) and switched `TestPortfolioEndpoints` to skip when the
  engine isn't authable, because `TradingConfig` now requires `API_KEY` even for offline tests.

**Auth/tooling gotchas encountered:** `gh auth refresh -h github.com -s workflow` didn't take until the
device-code flow completed; git uses GCM (`credential.helper=manager`) separately from `gh`, so I ran
`gh auth setup-git` before the push succeeded.

**Durable hazard noted in memory:** even after #162, if CI ever resolves a different pandas, latent
str-Enum-in-Series sites can resurface. Recorded in
`memory/project_vix_enum_pandas3_coercion_2026_06_26.md`.

### Arc B — Spread loader fix + magnitude-balance gate (MERGED, still on master)

**Context:** the relative-value (RV) spread research lives in `engine/backtest/spread_pairs_scan.py`,
which runs the ES-NQ-validated pipeline (z-score signal, no-look-ahead, rolling-OOS WFO, pooled
bootstrap, mandatory chronological H1/H2 split) across MES-M2K, MNQ-M2K, ZN-ZB.

**Bug found:** `PAIRS_REG` pinned each leg to a HARDCODED cache filename
(`MES_2024-04-26_2026-06-22_1h.csv` etc.). The moment the bar cache rotates (new export → new
end-date in the filename), the scan dies with `FileNotFoundError`. This is the **recurring
loader-staleness bug class** (same shape as the 2026-06-25 `run_atr_trail` `_pick_cache_file` fix).
The stale pin had been silently masking the MES and MNQ legs entirely — only ZN-ZB was running.

**Fix:** `PAIRS_REG` now holds symbol ROOTS `("MES","M2K","1h")`; `load_pair(root_a, root_b,
timeframe, cache_dir)` resolves each leg via the canonical `_find_latest_cache` (end-date keyed,
in `_gate_v2_helpers.py`). Added a regression test asserting latest-END-DATE selection beats a
lexicographically-greater STALE filename (the bug's exact failure mode).

**Then a deeper finding drove a second change.** With the loader fixed, the full scan ran on freshest
caches:
```
MES-M2K | OOS 264 | pf_ci_lo 2.26 | p_edge 1.0 | H1 pf 1.252/sum +0.087 | H2 pf 5.614/sum +1.213 | CANDIDATE
MNQ-M2K | OOS 251 | pf_ci_lo 1.175| p_edge 0.994| H1 pf 0.999/sum -0.001 | H2 pf 2.572/sum +0.460 | NON-STATIONARY
ZN-ZB   | OOS 131 | pf_ci_lo 1.662| p_edge 1.0  | H1 pf 1.213/sum +0.010 | H2 pf 5.44 /sum +0.093 | CANDIDATE
```
The two "CANDIDATE" pairs pass the BINARY both-halves-profitable gate but are badly MAGNITUDE-
asymmetric: MES-M2K's H1 carries only ~7% of total profit (PF 1.25 vs H2's 5.61); ZN-ZB's H1 ~9%.
That is a recent-regime edge wearing a stationary mask — a 2024-like regime would yield only the thin
H1 PF. This is the **binary-vs-magnitude insight**: "both halves > 0" is necessary but not sufficient.

**Decision (Amo-approved via question):** add a magnitude-balance criterion. `classify_verdict` now
requires the weaker chronological half to carry ≥20% of total profit (`MIN_HALF_SHARE=0.20`) for
CANDIDATE; stationary-but-imbalanced earns a new `BACK-LOADED` rung. Re-judged: **both MES-M2K and
ZN-ZB reclassify to BACK-LOADED → zero clean magnitude-balanced RV candidates exist.** That is the
honest read of the RV class.

**Shipped:** PR **#167** (`bbb8564`), two commits squashed: `33c82c4` (loader fix) + `5601a1f`
(magnitude-balance gate). 10 tests pass. (Both changes touch the same `classify_verdict` module, so
they shipped together to avoid a same-file conflict between two open PRs.)

### Arc C — Full PASS-verdict re-audit (read-only)

Audited every PASS verdict the system holds. **Headline: only 4 PASS verdicts exist system-wide, and
NONE is a clean CORE-gate pass — the ALT path carries every survivor.**
- `MGC_trend_rv_filter_rank1` — re-ran → **FAIL** (`dsr=0.0`, `p_edge=0.857`). The RV filter destroys
  the edge; rank4 no-filter remains MGC production. Confirms the earlier D1 DSR-integrity conclusion.
- `adx` — degenerate (18/19 thin windows; the window-independence fingerprint).
- `MGC_singlefinder` — param-robust (97.6/100 ROBUST) but its subperiod-stability path CRASHES on a
  missing verdict file `MGC_singlefinder_fill_rank1.json` — the robustness number is real, the
  certification leg is unreachable.
- `MES_trend_rank7` — the only genuine-but-marginal one (ALT-pass, `dsr 0.667`, `pf_ci_lower 0.92`).

Conclusion: the ALT path may be too permissive — it is doing all the load-bearing work, and one of its
survivors (rank7) has `pf_ci_lower 0.92`, i.e. a NET LOSER in the worst 5% of bootstrap resamples.

### Arc D — ALT-path permissiveness audit (read-only)

Traced the gate logic to ground. **The two paths, exactly:**

| metric | CORE | ALT |
|---|---|---|
| `pf_ci_lower` | ≥ 1.10 (`GATE_PF_CI_LOWER`) | **— dropped entirely** |
| `p_edge` | ≥ 0.95 (`GATE_P_EDGE`) | **— dropped entirely** |
| `dsr` | ≥ 0.10 (`GATE_DSR`) | ≥ 0.30 (`GATE_DSR_ALT`, 3×) |
| `mc_95th_dd` | ≤ 5% (`GATE_MC_DD_CORE`) | ≤ 4% (`GATE_MC_DD_ALT`) |
| `wfo_consistency` | — | ∈ {MODERATE, STRONG} (`GATE_WFO_CONSISTENCY_VALUES`) |
| `fixed_params_min_pf` | — | ≥ 1.20 (`GATE_FIXED_PARAMS_MIN_PF`) |
| cost survival | — | ≥ realistic tier |
| trade floor | ≥ 100 OOS (`MIN_TOTAL_OOS_TRADES`) | ≥ 100 OOS |

Canonical conjunction: `run_index_breakout_gate_v2.py:380-405`; matched in `ib_wfo_runner.py:245-247`.
Threshold floats live in `_gate_v2_helpers.py:33-50`; ALT-secondary constants
(`GATE_FIXED_PARAMS_MIN_PF=1.20`, `GATE_WFO_CONSISTENCY_VALUES=["MODERATE","STRONG"]`) in `_constants.py`.

**The audit's three findings, in priority order:**
1. **ALT has NO `pf_ci_lower` floor at all — it deleted the gate, did not relax it.** `MES_trend_rank7`
   ALT-passed at `pf_ci_lower 0.92`. The defensible-in-principle trade is "swap noisy small-N bootstrap
   significance for point-estimate robustness," but deleting the floor lets through a strategy that
   loses in >5% of resamples. **Cheapest fix (R1):** add `pf_ci_lower ≥ 1.00`.
2. **ALT is entirely load-bearing on DSR, which was buggy until THIS week.** The D1 fixes (`af35329`,
   `4dd58d8`) killed fake-1.0 degenerate DSR and mean-of-window-Sharpes inflation. Any ALT-PASS produced
   before those used a possibly-inflated DSR. **R2:** re-run ALT-PASS verdicts post-fix and purge failures.
3. **The conjunction is copy-pasted across ~50 runners.** Constants centralized, logic not.
   `run_mnq_breakout_rank3.py:82-83` already LOCALLY redefines the gate constants (its own
   `GATE_FIXED_PARAMS_MIN_PF=1.20`, stricter `GATE_WFO_CONSISTENCY="STRONG"`) — the drift vector, live.
   **R3:** wire `live_promotion_gate.resolve_gate_verdict` (built by PR #141 but has ZERO prod callers —
   inert) and kill the rank3 shadow.

Recorded in `memory/project_alt_gate_permissiveness_audit_2026_06_26.md`.

### Arc E — R1 implementation + MES re-validation (MERGED, THEN REVERTED)

Amo authorized "proceed with recommended next steps" → R1 first.

**Where R1 belongs:** I traced consumers. `live_promotion_gate.resolve_gate_verdict` (the intended
central function) has ONLY test callers — confirmed inert. Production verdicts are produced by the ~50
runners and stored as JSON in `engine/data/gate_v2_verdicts/`; they are consumed for authorization by
`gate_v2_policy.is_strategy_authorized`, whose condition 3 routes through `is_ungate_eligible`. So the
single highest-leverage place for R1 is the READ path (`is_ungate_eligible`): re-gate stored ALT
verdicts there and you cover every existing verdict in one edit, no 50-runner rewrite.

**R1 as built (PR #172, now reverted):**
- `gate_v2_policy.py`: added `GATE_PF_CI_LOWER_ALT = 1.00` (defined here, NOT in `_gate_v2_helpers`,
  to keep the read path free of the write path's numpy/statistics deps) + helper `_passes_alt_pf_floor(v)`:
  a PASS counts only if, when `passed_via=="alt"`, its stored `gate_v2_metrics["pf_ci_lower"] ≥ 1.00`.
  CORE passes unaffected (CORE already enforced 1.10). **Fail-conservative:** an ALT pass whose verdict
  file predates the `gate_v2_metrics` key (no stored `pf_ci_lower`) cannot be confirmed → denied.
  Rewired `is_ungate_eligible` to use the helper.
- Because `is_strategy_authorized` calls `is_ungate_eligible`, one edit covered both the advisory and
  the actual paper-order authorization gate.
- Tests: 5 new + 2 updated in `test_gate_v2_policy.py`; extended the `_write_verdict` fixture with a
  `pf_ci_lower` param.

**Runner bug found while doing R2 (the MES re-validation):** I tried to re-run the MES trend strategy
to learn R1's blast radius. There is no `run_mes_trend_rank7.py` anymore — ranks 8/9/10/11 are its
successors. The verdict on disk, `MES_trend_rank7.json`, is OLD (empty `gate_v2_metrics`). Running
`rank9` crashed: `NameError: GATE_DSR_ALT is not defined`. Cause: `run_mes_trend_rank9.py` and
`rank10.py` reference six gate constants (`GATE_DSR`, `GATE_DSR_ALT`, `GATE_MC_DD_ALT`,
`GATE_MC_DD_CORE`, `GATE_P_EDGE`, `GATE_PF_CI_LOWER`) but only import two from `_constants`; the six
primary thresholds live in `_gate_v2_helpers` and were never imported. **These runners NameError-crash
on EVERY run — they have never produced a verdict.** Only `rank11` (which imports all eight) ever ran,
and rank11 is the MOST grid-pruned version. I fixed the imports in rank9/rank10 to enable the
re-validation (this fix shipped inside #172 and was reverted with it).

**The grid-pruning tell:** rank8→9→10→11 each "refresh" NARROWS the grid after seeing results —
rank10 drops `slow=210` ("the only combo below the 1.20 ALT floor"), rank11 drops `slow=190` (same
reason). That is iterative removal of losing params until survivors pass — a classic overfit signature.

**MES re-validation result (the decisive data).** Ran the least-pruned `rank9` (full
`[190,200,210]×[50,55,60]` grid) AND the most-pruned `rank11` (`[200]×[50,55,60]`) on the freshest
cache `MES_2024-04-26_2026-06-25_1h.csv` (12,477 bars, through yesterday), through post-DSR-fix code:

| metric | rank9 (full grid) | rank11 (pruned) | need |
|---|---|---|---|
| pf_ci_lower | **0.734** | **0.932** | ≥1.10 (≥1.00 even for the proposed ALT floor) |
| p_edge | 0.40 | 0.43 | ≥0.95 |
| fixed_params_min_pf | 0.686 | 0.724 | ≥1.20 (ALT) |
| wfo_consistency | WEAK | WEAK | MODERATE/STRONG |
| dsr | 0.0 | 0.99999 *(degenerate)* | ≥0.30 ALT |
| OOS trades | 20 | 17 | ≥100 (also fails the floor) |
| **verdict** | **FAIL via NONE** | **FAIL via NONE** | — |

The old rank7 baseline (`fixed_params 1.275`, `dsr 0.667`) does NOT reproduce — on more data the edge
evaporated (`fixed_params` collapsed to ~0.7). rank11's `dsr 0.99999` is the degenerate thin-window
artifact (OOS windows have 0–1 trades each; PF flips between `inf` (single winner, no loser) and `0.00`
(no winner)). **MES trend has no statistical edge on current data — under either grid.**

So R1 was not "might disable a marginal MES" — it was "would correctly stop authorizing a strategy that
no longer has an edge." Critically: I verified MES is the **only `enabled=True` paper symbol**, and its
SOLE non-stale PASS is `MES_trend_rank7` (ALT, empty metrics, created 2026-06-20, age 6.3d, NOT stale,
expires ~2026-07-04). Under R1's fail-conservative floor, that metric-less ALT pass is denied →
`is_ungate_eligible("MES")=False` → MES loses authorization.

I also confirmed (read-only) that the MAIN checkout already had a `MES_trend_rank11.json` FAIL from a
06/25 run sitting beside the stale rank7 PASS — but `is_ungate_eligible` uses "ANY PASS across families,"
so a newer same-family FAIL does NOT supersede an older PASS (a separate policy gap, noted not fixed).

**Surfaced as a Tier-3 decision** (keeping/disabling a paper symbol is CONFIRM-before in the
jarvis-trader standing orders). Amo's choice: "Re-validate MES first (R2), then R1." After the
re-validation came back FAIL, I shipped:
- PR **#172** (`f1ea97a`) — R1 ALT floor + the rank9/rank10 import repairs. CI initially failed on TWO
  pre-existing tests (`test_gate_v2_sample_adequacy::test_pass_still_authorizes`,
  `test_gate_v2_routing_enforcement::test_flag_on_pass_verdict_allows_trading`) that built metric-less
  ALT passes and asserted eligibility — exactly the case R1 now denies. Fixed by giving the valid-PASS
  fixtures a clearing `pf_ci_lower` (commit `a02d865`). 67 → then full targeted suites green.
- PR **#174** (`e23e34a`) — `paper_config[MES].enabled=False` with a comment citing the re-validation,
  the config-layer kill (belt-and-suspenders with #172's read-path floor). Mirrors the MGC disable
  already in that file (line ~108: "rank4 re-run FAILs gate v2; was enabled on a stale 2026-05-06 PASS").
  92 paper_config-dependent tests pass.

Both merged to master via auto-merge.

### Arc F — Amo's veto and the FULL REVERT (MERGED)

Amo: *"i 10000% never want to disable MES."* I flagged the concern once (MES re-validates to no edge)
and then executed his preference. Because the engine had NOT been restarted, MES was still authorized
in the running engine the entire time — there was **no live interruption** at any point; the merges sat
on master only.

Mechanism mattered: just reverting #174 would NOT fully restore MES, because #172's ALT floor still
gates the metric-less rank7 verdict. I surfaced the options; Amo chose **"Revert both #172 and #174
fully"** — restore the exact prior state (MES authorized via rank7; ALT floor removed for all symbols;
runner-import fixes revert too, returning rank9/rank10 to their already-broken pre-today state).

**Shipped:** PR **#175** (`2ee4c58`) — `git revert e23e34a f1ea97a` (clean, no conflicts despite the
intervening peer merges #171/#173). Two revert commits squashed. Verified post-revert:
`paper_config[MES].enabled=True`, `is_ungate_eligible("MES")=True`, `_passes_alt_pf_floor` no longer
exists, 58 gate tests pass on the reverted code. Saved the standing directive to memory.

### Net effect of the whole session

Still on master (kept): pandas-3 convergence (#161/#162/#164), spread loader-fix + magnitude-balance
gate (#167). Reverted (net zero): the ALT floor and MES disable (#172/#174 undone by #175). The
gate-audit FINDINGS remain on file as a record; the CODE that acted on them is gone.

---

## 2. FILES — created/modified, full paths, what & why

### A. On master and KEPT (not reverted)
| File | Change | PR | Why |
|---|---|---|---|
| `engine/requirements-core.txt` | `pandas>=2.2.3` → `pandas>=3.0,<4.0` | #162 | end CI-vs-local drift; bound below Pandas4 break |
| `engine/requirements.txt` | `pandas==2.2.3`→`>=3.0,<4.0`; `numpy==2.2.4`→`>=2.2.6` | #162 | same |
| `engine/backtest/vix_percentile_regime.py` | `classify_latest`: `momentum=Momentum(mom_series.iloc[-1])` | #161 | rebuild str-Enum after pandas-3 Series coercion |
| `engine/backtest/trend_signals.py` | vix_regime_block `.map(lambda t: getattr(t,"value",t))` | #161 | same coercion class |
| `engine/vault/paths.py` | `read_notes_text` label `= path.relative_to(base).as_posix()` | #164 | OS-independent LLM citation labels |
| `engine/tests/test_integration.py` | added `_engine_testable()`; `TestPortfolioEndpoints` skips if not authable | #164 | `TradingConfig` now requires `API_KEY` even offline |
| `engine/backtest/spread_pairs_scan.py` | `PAIRS_REG` roots; `load_pair` via `_find_latest_cache`; `classify_verdict` magnitude-balance + `BACK-LOADED`; summary | #167 | kill loader-staleness bug; binary→magnitude stationarity |
| `engine/tests/test_spread_pairs_scan.py` | contract load_pair test, latest-end-date regression test, 3 balance-gate tests | #167 | lock the fixes |

### B. Modified, MERGED, then REVERTED by #175 (NET ZERO on master)
| File | Change that was reverted | PR |
|---|---|---|
| `engine/backtest/gate_v2_policy.py` | `GATE_PF_CI_LOWER_ALT=1.00` + `_passes_alt_pf_floor` + rewired `is_ungate_eligible` | #172 → reverted |
| `engine/tests/test_gate_v2_policy.py` | 5 R1 tests + `pf_ci_lower` fixture param | #172 → reverted |
| `engine/tests/test_gate_v2_sample_adequacy.py` | `_verdict_doc` clearing `pf_ci_lower` | #172 → reverted |
| `engine/tests/test_gate_v2_routing_enforcement.py` | `_write_verdict` `pf_ci_lower` param | #172 → reverted |
| `engine/backtest/run_mes_trend_rank9.py` | added 6 missing gate-constant imports (NameError fix) | #172 → reverted (re-broken) |
| `engine/backtest/run_mes_trend_rank10.py` | same import fix | #172 → reverted (re-broken) |
| `engine/backtest/paper_config.py` | `MES enabled=False` + rationale comment | #174 → reverted (back to `True`) |

### C. Memory files (local disk, `~/.claude/projects/C--Users-mattm/memory/`)
- `feedback_never_disable_mes.md` — **NEW.** The §0 directive.
- `project_alt_gate_permissiveness_audit_2026_06_26.md` — **NEW**, with a prominent "BOTH REVERTED"
  banner at the top so no future session re-ships R1 in a MES-blocking form.
- `project_vix_enum_pandas3_coercion_2026_06_26.md` — pandas-3 hazard (created/updated).
- `project_dsr_degenerate_fix_2026_06_26.md` — updated earlier (DSR-integrity corrections).
- `MEMORY.md` — index pointers added for the above (top of "Recent (2026-06-26)").

### D. Handoffs
- `~/.claude/handoffs/HANDOFF_2026-06-26_alt-gate-audit-and-mes-revert.md` — **this file** (expanded).
- `~/.claude/handoffs/HANDOFF_2026-06-26_pandas3-and-spread-balance-gate.md` — earlier, superseded.

### E. Re-validation artifacts (gitignored; jt-campaign worktree ONLY)
- `jt-campaign/engine/data/gate_v2_verdicts/MES_trend_rank9.json`, `MES_trend_rank11.json` — the FAIL
  verdicts from the re-validation. Local-only; the worktree's `data/` is a real dir, NOT a junction, so
  these did NOT pollute the peer/main checkout's verdict dir (verified by mtime: main's rank11.json was
  06/25, mine 06/26). A `cache` junction WAS created in the worktree → `jarvis-trader/engine/backtest/cache`.

---

## 3. CURRENT STATE — running / stopped / broken

- **`origin/master` = `2ee4c58`** (PR #175 revert). Clean. MES restored. pandas-3 + spread-gate kept.
  The ALT floor and MES disable are gone.
- **jt-campaign worktree:** on `master`, working tree CLEAN (no diff, nothing staged).
- **Live engine:** PM2-managed, running on the **peer branch** `fix/corey-cache-stale-nodata` (peer
  session's checkout at `C:\Users\mattm\ThinkorSwim\jarvis-trader`). That branch cherry-picks selected
  master commits — e.g. paper-auto-approve (#173) was deployed there via cherry-pick `54ada57` + a
  restart, NOT a master merge (the branch carries divergent aggressive risk limits 0.06/0.20 + VOL_TARGET
  fields that a full merge would disturb). **My #172/#174 never reached the running engine** (they went
  to master, not that branch), so MES was live-authorized throughout.
- **MES authorization:** RESTORED. `paper_config[MES].enabled=True`; `is_ungate_eligible("MES")=True`
  (verified against the live verdict dir). MES trades in paper.
- **Paper auto-approve:** live on the peer branch (`AUTONOMOUS_AUTO_APPROVE_PAPER=1`), but no actual
  auto-approval observed yet (first post-restart tick had 0 candidates ≥0.65 conf). Not my work; context.
- **Broken:** `run_mes_trend_rank9.py` + `rank10.py` (NameError on every run — re-broken by the revert);
  see Blockers.

---

## 4. IN-PROGRESS WORK — started but not finished

- **None active.** Every branch created this session is merged or reverted; no half-done edits; nothing
  mid-execution. The gate audit's R2/R3 recommendations were intentionally NOT carried to completion
  after the revert.

---

## 5. BLOCKERS DISCOVERED

1. **`run_mes_trend_rank9.py` / `run_mes_trend_rank10.py` are broken** — they reference 6 gate constants
   (`GATE_DSR`, `GATE_DSR_ALT`, `GATE_MC_DD_ALT`, `GATE_MC_DD_CORE`, `GATE_P_EDGE`, `GATE_PF_CI_LOWER`)
   without importing them → NameError on every invocation. My import fix was reverted with #175. They were
   already broken before today (never produced a verdict; only `rank11`, which imports all 8, ever ran).
   Re-fixing is safe and orthogonal to MES — but the fix must NOT also re-disable MES (it won't, by itself).
2. **`MES trend has no current edge`** (the substantive finding, not a code blocker): p_edge ~0.40,
   pf_ci_lower 0.73–0.93, fixed_params ~0.7, wfo WEAK on fresh data, both grids. Amo wants MES traded
   anyway (§0). Keep this in mind if MES paper performance is questioned — the backtest does not support
   a current edge; that is a known, accepted state.
3. **`MGC_singlefinder_fill_rank1.json` missing** from `engine/data/gate_v2_verdicts/` →
   `singlefinder_sensitivity.subperiod_stability` raises `FileNotFoundError`. Param sensitivity still
   computes (97.6/100 ROBUST) but the stability certification leg is unreachable.
4. **`is_ungate_eligible` supersession gap:** a newer same-family FAIL does NOT override an older
   same-family PASS (any-PASS-across-families semantics). This is WHY MES stayed authorized on the stale
   rank7 PASS even though a newer rank11 FAIL sits beside it. Noted, not fixed (and any fix must exempt MES).
5. **3 unreadable verdict files** in the live dir: `M2K_orb_rank1.json`, `M6B_trend_diversifier.json`,
   `M6E_trend_diversifier.json` (missing/None `rank`). The policy loader logs a warning and skips them.
6. **Local full fast-suite cannot complete** — it hangs on environment-dependent async tests
   (pytest-timeout dumps, no summary). Rely on CI for authoritative full-suite green; verify targeted
   files locally.

---

## 6. KEY DECISIONS MADE (with rationale / values)

- **pandas → 3.x convergence** (not pin-back). Aggressive option chosen by Amo. Pin `>=3.0,<4.0`.
- **Spread magnitude-balance gate:** `MIN_HALF_SHARE = 0.20`; weaker half must carry ≥20% of profit
  for CANDIDATE, else `BACK-LOADED`. Conclusion: no clean magnitude-balanced RV candidate.
- **R1 lives at the policy READ path** (`is_ungate_eligible`), not in the 50 runners — single highest-
  leverage site; fail-conservative on missing metrics; constant in `gate_v2_policy.py` to keep the read
  path numpy-free. `GATE_PF_CI_LOWER_ALT = 1.00`. (Now reverted.)
- **MES re-validation via two grids** (least-pruned rank9 + most-pruned rank11) to test fragility — both
  FAIL, so the failure is not a grid artifact.
- **REVERT BOTH #172 and #174 fully** (Amo's explicit choice over "exempt MES, keep R1" and "revert #174
  only") — restore exact prior state; accept runner re-breakage as part of "full" revert.
- **Did NOT restart the engine** — Amo-gated activation step; never on a bare "proceed."
- **Did NOT touch the peer-active main checkout** — all work via the `jt-campaign` worktree.
- **Standing rule recorded:** never disable MES (§0). Future gate work must exempt MES.

---

## 7. TODO — planned but not started

- **Re-fix rank9/rank10 NameError imports** (orthogonal, safe) on a fresh branch off `origin/master` →
  PR. Ensure nothing in it disables/gate-blocks MES.
- **R3 — gate de-duplication:** wire `live_promotion_gate.resolve_gate_verdict` (inert; 0 prod callers)
  so the core/ALT conjunction stops being copy-pasted across ~50 runners; kill the
  `run_mnq_breakout_rank3.py:82` constant shadow. **If revisited, MUST exempt MES.**
- **Fix `MGC_singlefinder_fill_rank1.json` missing verdict** (regenerate or harden the read path).
- **Fix the 3 unreadable verdict files** (schema drift: missing `rank`).
- **Decide the supersession policy** — should a newer same-family FAIL override an older PASS in
  `is_ungate_eligible`? (Must exempt MES if implemented.)
- **(Optional) ALT permissiveness for OTHER symbols** — Amo may still want ALT tightened where it does
  not affect MES; the audit findings stand.

---

## 8. THE FULL TO-DO LIST CURRENTLY HELD

No active TodoWrite/Task list is open in this session. The implicit, complete to-do list = Section 7
above. All items are deferred/optional; none are in-flight or blocking. The session's committed work is
done: every PR is merged or reverted, master is clean, MES is restored.

---

## 9. GIT STATE (live output)

**Status (jt-campaign worktree):**
```
## master...origin/master
```
(clean — no modified, no staged, no untracked of note)

**`git log --oneline -20` (origin/master):**
```
2ee4c58 revert: restore MES authorization (revert #172 + #174) (#175)
e23e34a chore(paper): disable MES paper trading -- trend FAILS fresh re-validation (#174)
f1ea97a feat(gate): ALT pf_ci_lower>=1.00 floor (R1) + repair broken MES trend runners (#172)
fd2b567 feat(autonomous): opt-in paper-only auto-approve (default OFF) (#173)
7e27487 feat(backtest): _find_latest_cache prefers complete over fresh (prefer_complete) (#171)
9514dc6 WS-1.2/1.4: H1/H2 stationarity ENFORCEMENT + beta-harvest p_edge relaxation (#170)
ebc81d6 WS-5: bar-cache completeness / gap detector + fleet scan (#166)
1fbc870 Gate-integrity consolidation: DSR honesty + H1/H2 stationarity + loader fixes (#165)
bbb8564 fix+feat(backtest): latest-cache resolution + magnitude-balance gate for spread scan (#167)
b061b74 test+fix: cross-platform vault label; skip live smoke when not authable (#164)
5393799 build(deps): converge pandas to 3.x (CI + production) (#162)
18e658e fix(regime): rebuild str-Enum after pandas-3.x Series coercion (#161)
4c501b7 Merge pull request #159 from mattamundson/docs/handoff-2026-06-26-phasec
57b2630 docs(session-log): add Phase C (handoff distribution) to 2026-06-26 handoff
b93ac7e chore(gitignore): ignore runtime artifacts (paper-track ledgers, logs, discovery dumps) (#158)
8b32d46 Merge pull request #156 from mattamundson/docs/handoff-2026-06-26
4e3cca6 docs(session-log): full-arc 2026-06-26 handoff (convergence + scripts + PR #3)
34a48c7 feat(analytics): evaluate auction signals via the gate-v2 pipeline (#152)
3d0a855 fix(analytics): make confluence audit a screen, add entry-funnel diagnostic (#146)
6d3cd76 Index breakout: locked spec + MCPT runner (Nikkei-breakout critique) (#131)
```

**`git diff --stat` (working tree):** empty (clean).

**PRs this session:** #161, #162, #164, #167, #172, #174 merged; #175 merged (reverts #172+#174).
All session branches deleted on remote after squash-merge. Many unrelated stale local branches exist
(`git branch -vv`); none are mine-in-progress.

**Peer-session caveat:** the live engine's checkout is the peer branch `fix/corey-cache-stale-nodata`
at `C:\Users\mattm\ThinkorSwim\jarvis-trader` — do NOT edit it. Use the `jt-campaign` worktree.

---

## 10. ENVIRONMENT / HOW-TO NOTES (so the next session doesn't re-derive)

- **venv / python:** the `jt-campaign` worktree has NO venv. Use the main checkout's interpreter
  read-only: `C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe`, with cwd in
  `jt-campaign/engine` so imports resolve to the worktree's code.
- **API_KEY for offline backtests:** `TradingConfig` (Pydantic) now REQUIRES `API_KEY`. Export a dummy
  for backtests: `export API_KEY="backtest_only_dummy_..."` (backtests don't use the value).
- **Bar caches are gitignored** and absent in a fresh worktree → created a junction:
  `cmd.exe //c "mklink /J cache C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\backtest\cache"`.
- **`_find_latest_cache(data_dir, prefix, suffix="_1h.csv")`** is the canonical end-date-keyed loader;
  filename contract `<PREFIX>_<START>_<END>_<tf>.csv`. Use it — never hardcode a cache filename.
- **Hooks active:** destructive-op-guard (blocks force-push, `git branch -D`, etc. — route via the
  user's `!` shell), bash-anti-tool-guard (blocks naked `cat`/`tail`/`grep`/etc — use Read/Grep;
  pipelines/chains pass), credential-guard, memory-size-guard (MEMORY.md > 22 KB blocks edits).
- **Engine restart is Amo-gated:** `.\restart_engine.ps1` (no `--reload`). Health gate: `/health` →
  `status=ok` AND `tradingview_mcp_healthy` AND `llm_path_healthy`; steady-state startup ≈ 229s.
- **Test bar endpoints with `curl.exe`, NOT PowerShell `Invoke-RestMethod`** (it mangles `?a=1&b=2`).

---

## 11. SUGGESTED NEXT ACTION

If continuing, the single safest high-value item: **re-fix the `run_mes_trend_rank9/rank10` NameError
imports** (add the 6 missing constants from `_gate_v2_helpers`) on a fresh branch off `origin/master`,
open a PR — verifying nothing in it disables or gate-blocks MES. Everything else (R3 de-duplication,
verdict-file hygiene, supersession policy, ALT-for-other-symbols) is optional and lower priority.

**Two hard constraints for whoever continues:** (1) do NOT disable or gate-block MES, ever (§0);
(2) do NOT restart the engine without Amo, and do NOT edit the peer-active main checkout.
