# Window quality on the repaired ruler — rank11 (2026-09-18, round 3 T5)

Wired `window_quality()` (PR #866) into `run_mes_trend_rank11.py`, mirroring the vix_pctile runner.
Three additive edits, report-only: no threshold reads the block. Run at `origin/master` (`dfb261d0`),
deep cache `MES_2019-05-05_2026-08-26_1h.csv` (43,010 rows). Verdict unchanged: PASS via core.

## Measured

| metric | rank11 | vix_pctile (PR #866) |
|---|---|---|
| windows / with trades | 82 / 59 | 82 / 54 |
| **single-trade windows** | **51 (86 %)** | **47 (87 %)** |
| median trades per window | 1.0 | 1.0 |
| windows at the gate floor (5 trades) | **0** | **0** |
| gate `p_edge` (trade-level, all windows) | **0.9959** | 0.5926 |
| honest `p_edge` (window decomposition) | **0.6271** | 0.5926 |
| `p_edge` excluding single-trade windows | 0.75 | 0.7143 |
| `p_edge` at the gate's own 5-trade floor | **0.0** | **0.0** |

## What this establishes

**1. The thin-window pattern is structural, not specific to one candidate.** Two independent
strategies, 86 % and 87 % of traded OOS windows carrying exactly one trade, zero windows clearing the
gate's own 5-trade floor in either. The cause is known and deliberate: 37 runners override
`MIN_OOS_TRADES_PER_WINDOW` from the standard 5 down to 1, because trend strategies generate 1-3
trades per 2-month window. Raising the floor would send every trend strategy to
`INSUFFICIENT_SAMPLE` — so this is a designed trade-off, not an oversight. It is now measured in two
places rather than argued in one.

**2. A third honest-basis number, and it disagrees with the other two for this candidate.**

| honest basis applied to rank11 | value | floor that applies | outcome |
|---|---|---|---|
| campaign-count DSR (T6) | 0.2676 | CORE 0.10 | **passes** |
| window-decomposition `p_edge` (T5) | 0.6271 | CORE 0.95 | **fails** |
| `p_edge` at the gate's 5-trade floor | 0.0000 | CORE 0.95 | **fails** |

rank11's CORE PASS survives campaign deflation and does **not** survive an honest window-decomposition
`p_edge`. The recorded 0.9959 is a trade-level statistic that the 1-trade-window floor makes
permissive: a window with one trade cannot be wrong in more than one direction, so a high share of
them inflates the pass rate without adding independent evidence.

This is the same defect T2 identified for DSR, appearing independently in the second gate metric. Two
of the ALT/CORE conjunction's terms are computed on a basis their own inputs do not support.

**3. Implication for the promotion question.** The T2 dossier's recommendation — raise the ALT path's
deflation basis prospectively — extends naturally to `p_edge`: the honest decomposition exists (#866,
`GATE_P_EDGE_ALT`), is unwired, and would change this verdict. Neither metric should be made binding
retroactively (nine PASSes cannot be evaluated), but the case for fixing *both* bases prospectively is
now backed by measurement on two candidates rather than by one.

## Reproduce

    cd engine
    env -u PYTHONPATH .venv/Scripts/python.exe backtest/run_mes_trend_rank11.py
    # expect: 82 windows, 51 single-trade, p_edge 0.9959, honest p_edge 0.6271, at-floor 0.0
