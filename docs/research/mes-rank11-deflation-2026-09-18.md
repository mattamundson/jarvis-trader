# `MES_trend_rank11` at campaign-count deflation (2026-09-18, round 3 T6)

## What was done

Wired the two-basis deflation report into `run_mes_trend_rank11.py`, mirroring
`run_mes_trend_vix_pctile_rank1.py` (PR #873). Three additive edits, all report-only:

1. `_compute_gate_v2` computes `deflation_report(SYMBOL, n_grid_combos)` where `dsr` is already
   computed, and recomputes the trade-level DSR at the campaign trial count;
2. the gate dict carries `"deflation"`;
3. the written verdict records it at both `gate_v2_metrics.deflation` and top level.

No threshold reads it; `"enforcement": "report-only"` ships inside the block itself. `py_compile` on
the candidate, applied as one atomic three-edit step.

## Result — the program's second campaign-count DSR

Run at `origin/master` (`5b6db636`), deep cache `MES_2019-05-05_2026-08-26_1h.csv` (43,010 rows):

| | trials | DSR | applicable floor | |
|---|---|---|---|---|
| grid count | 3 | **0.9818** | CORE 0.10 / ALT 0.30 | passes both |
| campaign count | **217** | **0.2676** | CORE 0.10 | **PASSES** |
| | | | ALT 0.30 | would fail |

Verdict unchanged: **PASS via core**. So this is the first PASS in the store whose significance has
been tested at the honest trial count and **survives its applicable floor**.

## Correction: T4's prediction was wrong

The T4 document predicted, from the cliff measured on the *vix_pctile* candidate's return series, that
rank11's `dsr` would fall "far below even the CORE floor of 0.10". Measured, it is **0.2676**.

The error is instructive: a cliff measured on one candidate's return series is a property of *that*
series, not of the method. Extrapolating it across candidates is exactly the kind of
recollection-instead-of-measurement this program exists to remove. T4's document has been corrected in
place, pointing here.

## Contrast with the live verdict — and what it does to the T2 question

| PASS | path | dsr (grid) | dsr (campaign) | floor that applies | outcome |
|---|---|---|---|---|---|
| `MES_trend_rank11` | **core** | 0.9818 @3 | **0.2676 @217** | 0.10 (CORE) | **survives** |
| `MES_trend_vix_pctile_rank1` (live) | alt | 0.9688 @4 | **0.1815 @214** | 0.30 (ALT) | **fails** |

Both lose roughly 0.7 of absolute DSR when deflated honestly. The **consequence differs by path**:
CORE's 0.10 floor is survivable at ~217 trials; ALT's 0.30 floor is not at ~214.

This **refines** the T2 dossier's framing. The accurate statement is not "two of two examined PASSes
fail" — it is "two of two collapse under honest deflation, and one of the two crosses its applicable
floor". The ALT floor is the one doing the work, which is a point in favour of the dossier's
recommendation to raise the ALT path's basis rather than the CORE path's.

## Property worth recording: the count is self-inclusive

`n_trials_campaign` rose from **214** (PR #872, measured before this run) to **217** — because this
re-run's own 3 grid combos are now a distinct artifact in the store. Each new MES verdict therefore
raises every future MES verdict's deflation count. The one-sided direction is conservative and the
caveat ("lower bound") ships with the number, but the drift is real and should be stated whenever the
campaign figure is quoted.

## Reproduce

    cd engine
    env -u PYTHONPATH .venv/Scripts/python.exe backtest/run_mes_trend_rank11.py
    # expect the deflation block: n_trials_grid 3, n_trials_campaign >= 217, dsr_campaign ~0.2676

The campaign count is a function of the artifact store, so it increases as artifacts are added; the
grid value and the verdict reproduce exactly.
