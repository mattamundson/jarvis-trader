# MGC deep cache is absent — `MGC_trend_rv_filter_rank1`'s PASS cannot be re-established

Date: 2026-09-17. Status: research evidence. **No config, routing, gate, or risk change.**
MGC remains HALTED (`DO_NOT_TRUST`-equivalent: `DO_NOT_TRADE_SYMBOLS`, `paper_config.py enabled=False`).

## Why this was checked

The queue item `MGC_trend_rv_filter_rank1` carries a `needs_data_contract` state, and the
2026-09-17 artifact audit (PR #867) found its archived `PASS via alt` (p_edge 0.625, dsr 0.8868,
deflated at 3 trials) is filed under three names with identical bytes — the `-deep-` artifact being
byte-identical to its own `-pre-deep-` file. So the question was: *does that PASS rest on the deep
cache, and can it be reproduced there?*

The provenance mechanism shipped in PRs #868/#869 answers it directly, because it records the cache
by content hash instead of trusting the filename.

## Finding 1 — there is no deep MGC cache on disk

Recursive search for the cache files the standing documentation cites
(`MGC_2015-01-01_2026-08-16_1h.csv`, `MGC_2015-01-01_2026-08-19_5m_cont.csv`) returns **nothing** —
in either the canonical tree or a fresh worktree. The MGC 1h caches that do exist span
**2024-04-26 → 2026-06-25 (~2.2y)**.

The documented MGC "deep" inventory was therefore stale or wrong. The MES deep cache is a separate
matter and **is** present and verified (43,010 bars, 7.307y, `sha256 e26631c0…`); the gap is
MGC-specific and must not be generalised.

## Finding 2 — what the runner would actually use (measured)

`_find_latest_cache(cache_dir, "MGC")` in a fresh checkout returns, via the completeness preference
(the newest-end file `MGC_2024-04-26_2026-06-25_1h.csv` is holed):

```
selected: MGC_2024-04-26_2026-05-20_1h.csv
cache_rows         : 11822
cache_span_first   : 2024-04-26 05:00:00
cache_span_last    : 2026-05-20 09:00:00
cache_span_years   : 2.064
cache_sha256       : b4572300ac25664db5e19b8e354536b6715fab0871b7ab2b987f83acd93198a9
provenance_note    : span 2.06y < 5.0y: does not meet the deep-data standard
```

The helper flagged it automatically — which is the behaviour the feature was built for.

## Finding 3 — conclusion for the candidate and the queue item

- `MGC_trend_rv_filter_rank1`'s archived "deep" PASS **cannot be re-established**, and the only data
  reachable today is a 2.064y cache that the standing rule says **does not certify edge**. Combined
  with the audit's byte-identity result, the `-deep-` label on that artifact should be treated as
  misapplied rather than as evidence.
- This is consistent with, and explains, the duplicate-label finding: if no deep MGC cache existed at
  the time, the `-deep-` name could never have corresponded to a distinct deep execution.
- Because MGC is halted and the gate fail-closes new routing, there is **no live risk** here. The
  consequence is evidentiary: **MGC cannot be re-authorized on a fresh deep PASS until a deep cache
  is rebuilt** — the re-authorisation path is blocked at the data layer, not the strategy layer.
- The queue item should therefore be parked with a dated reason ("blocked: no deep MGC cache on
  disk; provenance unverifiable") rather than left implying pending work.

## What would resolve it

1. Rebuild a deep MGC cache (≥5y, verified clean, 0 dupes/NaN/OHLC violations) and record its
   provenance hash in the rules.
2. Re-run `run_mgc_trend_rv_filter_rank1.py` — it now writes `cache_provenance` into its verdict, so
   the result is attributable by construction rather than by filename.
3. Only then can a deep PASS be claimed for MGC.

## Method / reproducibility

- Absence: recursive `find` for `MGC_2015*` / `MGC_2019*` across canonical tree + worktree.
- Selection and provenance: `_find_latest_cache()` + `_gate_v2_helpers.cache_provenance()`.
- Cross-reference: `docs/research/verdict-artifact-audit-2026-09-17.md` (PR #867),
  `docs/research/mes-vix-pctile-champion-economics.md` (PR #866).

## Limits

- A cache could exist outside the two trees searched (e.g. another drive or an archived tarball); the
  claim is bounded to the paths examined, which are the ones the runners read.
- No strategy was re-run. The finding is about the *data basis available*, not about MGC's edge —
  MGC's edge is simply not measurable at the required standard right now.
