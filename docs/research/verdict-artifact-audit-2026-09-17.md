# Verdict Artifact Audit — 2026-09-17

Reproduce with one command (from `engine/`):

    env -u PYTHONPATH .venv/Scripts/python.exe backtest/audit_verdict_artifacts.py

Scope: the whole `engine/data/gate_v2_verdicts/` store (76 JSON artifacts, including `archive/`).
Tool: `engine/backtest/audit_verdict_artifacts.py` (added with this report).
Status: research evidence. No live routing, config, risk, kill-switch, or order-path change.

## Why this audit exists

Two corrections shipped on 2026-09-17 (PR #866) showed that the program's bottleneck is not
"find more strategies" — it is that recorded evidence cannot be trusted at a glance:

- `p_edge` had been read as if `PF = inf` implied a single trade (it does not).
- The cost ledger was explained twice by inference and was wrong twice.

Both errors came from reading artifacts instead of measuring them. This audit measures the store
itself. It answers: *if a verdict says PASS, can I tell from the artifact what it actually ran on?*

**The answer is no** — see finding 5.

## 1. Duplicate artifact contents — 8 groups, 19 files

Content-addressed by sha256. Two genuinely separate runs can never share bytes, since they differ
at minimum in `created_at`.

| bytes (sha256/16) | files | labels present |
|---|---|---|
| `b413e4e67334e6d5` | 4 | `deep`, `pre-deep`, `pre-rereval` |
| `b88a7fa797597bd3` | 3 | `deep`, `pre-deep` |
| `511abeee1c48833a` | 2 | `deep`, `shallow-contaminated` |
| `8ace5e5379584d93` | 2 | `deep`, `shallow-contaminated` |
| `d44ae45c747c53ee` | 2 | `deep`, `shallow-contaminated` |
| `554adb019f6fbee7` | 2 | `deep`, `pre-deep` |
| `9adefe838909f806` | 2 | `deep`, `pre-deep` |
| `6eb388f99f868a3d` | 2 | `deep`, `shallow-contaminated` |

Affected candidates: `MGC_trend_rank4`, `MGC_trend_rv_filter_rank1`, `MES_trend_rank11`,
`MES_trend_rv_filter_rank1`, `MES_donchian_rank1`, `MES_meanrev_rank1`, `MES_pre_fomc`,
`MES_turn_of_month`.

**What this proves and what it does not.** It proves the `-deep-` label does **not** correspond to a
distinct execution for these candidates — the same bytes are filed under `deep`, `pre-deep`, *and*
`shallow-contaminated`. It does **not** prove the runs used shallow data. Checked directly: for
`MGC_trend_rv_filter_rank1` the three identical files carry `created_at 2026-08-16T17:53:39`
(PASS via alt), while `pre-rereval-2026-08-16` is a genuinely different run — `created_at
2026-07-27T02:53:28`, `n_alt_passed` 4 vs 5, verdict **FAIL**. Two real runs, four file names.

The operational consequence is the same either way: **for those four MES candidates the artifact
labelled `deep` is byte-identical to the one labelled `shallow-contaminated`, so the store cannot
distinguish a deep-certified result from a contaminated one.** Under the standing rule that shallow
data does not certify edge, those labels cannot be relied on. (For all four MES cases both variants
are FAIL, so no PASS is at stake there. The MGC rv_filter PASS *is* at stake.)

## 2. NaN in a gating metric — 7 files, fails SAFELY

`MES_trend_rank9`, `MES_trend_rank10`, `MES_trend_rv_filter_rank1`, `MGC_trend_rank1`,
`MGC_trend_rank2`, `MGC_trend_rank3`, `MGC_trend_rank4_pre-refresh-2026-05-06` carry
`pf_ci_lower = NaN`.

The gates compare `pf_ci_lower >= GATE_PF_CI_LOWER`; `NaN >= x` is `False`, so these fail closed —
verified, not assumed: `MES_trend_rank9` reads `p_edge 0.75`, `dsr 0.9988`, and is correctly
classified **FAIL**. There is no silent-pass risk.

The real issue is that NaN is *uninformative*: the bootstrap produced nothing, which means fewer
than two windows carried trades. That is a **sample-adequacy** signal and should be surfaced as
such in the verdict rather than presented as an ordinary threshold failure.

## 3. Recorded deflation input — 67 of 76 files, and all of them under-deflate

`wfo_config.n_combos` is recorded for 67 files. Distinct values:

`1`×7, `3`×12, `4`×2, `6`×3, `8`×9, `9`×9, `16`×8, `18`×5, `27`×4, `36`×1, `48`×2, `54`×4, `64`×1

Every one of these is the **runner's own grid size**, not the campaign trial count. Against the deep
cache the true campaign count is in the hundreds, and DSR is a cliff — measured on the current
candidate: 0.977 at 4 trials → 0.7315 at 50 → 0.2885 at 200 → 0.0505 at 500 (ALT floor 0.30).
So **every recorded DSR in this store is deflated against a number 1-2 orders of magnitude too
small**, and seven artifacts deflate against a single trial, where DSR is not even defined.

## 4. PASS inventory — 10, of which one is live

| artifact | via | p_edge | dsr | trials recorded |
|---|---|---|---|---|
| `MES_trend_rank7` | alt | *(absent)* | *(absent)* | — |
| `MES_trend_rank11_pre-refresh-2026-05-06` | alt | 0.75 | 1.0 | 3 |
| `MES_trend_rank11_pre-refresh-2026-05-20` | alt | 0.75 | 1.0 | 3 |
| `MGC_trend_rank4_pre-refresh-2026-05-06` | alt | 0.75 | 1.0 | 8 |
| `MGC_trend_rank4_pre-refresh-2026-05-20` | alt | 0.6842 | 1.0 | 8 |
| `MGC_trend_rv_filter_rank1` ×3 (identical bytes) | alt | 0.625 | 0.8868 | 3 |
| `MES_trend_rank11_deep-2026-08-17-refresh` | **core** | 0.9968 | 0.9861 | 3 |
| `MES_trend_vix_pctile_rank1` *(only live, non-archive)* | alt | 0.5926 | 0.9752 | 4 |

Two observations:

- Nine of ten PASS on the **ALT** path, and the ALT conjunction does not reference `p_edge` at all —
  so "PASS via alt" can sit below the documented 0.60 activation bar, as the one live verdict does.
- The `MGC_trend_rv_filter_rank1` PASS appears three times because one artifact was filed under
  three names. It is one run, not three confirmations — and its deep provenance is unverifiable
  (finding 1). Deflated against 3 trials, it would not survive the campaign count.
  MGC is halted; this matters for the queue item, not for live risk.

## 5. Root cause — no verdict records its data provenance

The decisive check: **no artifact records the cache file, span, or row count it ran on.** The only
provenance field present is `symbol`. `windows[].oos_period` gives date ranges but not which cache
produced them.

So deep-vs-shallow provenance exists only as a **filename convention**, and findings 1 and 4 show
that convention is demonstrably unreliable. Consequences:

1. No "validated on deep data" claim in this store can be independently verified from the artifact.
2. Any future re-audit must re-run the strategy to establish provenance — expensive and
   non-deterministic, instead of opening a file.
3. The MGC rv_filter PASS, and any candidate whose label is ambiguous, cannot be resolved cheaply.

This is the cheapest high-value fix in the program: the runner *already knows* which cache it
selected (`_find_latest_cache` prints it). Writing `cache_file`, `cache_rows`, `cache_span`, and a
content hash into every verdict JSON makes all future provenance audits a one-line check.

## Recommended actions (ranked)

1. **Record cache provenance in every verdict** — additive field set written by each runner; makes
   findings 1 and 5 auditable forever. Small, testable, no verdict changes.
2. **Remove the duplicate filenames** (archive, never delete) and state in the queue doc that one
   artifact filed under several labels is one run — so it is never counted as multiple confirmations.
3. **Campaign-level DSR as standing runner output** (finding 3) — pass the true trial count.
4. **Surface NaN as INSUFFICIENT_SAMPLE** rather than an ordinary threshold failure (finding 2).
5. **Re-run, don't re-label, where the label is ambiguous and a PASS is at stake** — specifically
   `MGC_trend_rv_filter_rank1`, whose PASS cannot currently be attributed to the deep cache.

## Limits of this audit

- Hash equality establishes that files are copies; it cannot establish which data a run used, because
  that is exactly what the artifacts do not record (finding 5).
- The audit reads artifacts only. It does not re-run any strategy, so it cannot say whether a given
  PASS would survive campaign DSR — it says the recorded number is not enough to know.
- Filename tags are read as provenance hints, not as facts. Where a tag conflicts, the conflict is
  reported rather than resolved.
