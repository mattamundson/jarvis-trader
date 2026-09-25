# Look-ahead impact quantification: #751 (IB) and #752 (VWAP), 2026-09-25

Step 1 of both issues' "Required remediation" list: measure how far each defect
moves historical signals and backtest metrics before anyone patches production.
**Research only. No production module, verdict file, cache, or authorization
was changed.**

- Script: `engine/scripts/audit_lookahead_defects_751_752.py` (read-only; the
  causal variants exist only inside the script as comparators)
- Raw output: `lookahead-impact-751-752-2026-09-25.json`
- Regression pins: `engine/tests/test_lookahead_defect_pins_751_752.py`
  (`xfail(strict=True)`, so a fix fails the suite until the marker is removed)
- Evidence level: **E1/E2 research replay** on committed caches. Full-sample
  backtests only, **not** a WFO or gate-v2 re-run. No verdict JSON was written.

## Live-path reachability (both defects): not reachable today

| Path | Status |
|---|---|
| `ib_signals.compute_initial_balance` | Only research caller is `ib_breakout_signals` -> `ib_wfo_runner`. `signals.py` layer4 still uses a `shift(1)` proxy (TODO at `signals.py:425`). |
| `vwap_signals.generate_vwap_signals` | Research runners plus `composite_signals`. `composite_signals` feeds `TechnicalAnalyst` metadata only for `COMPOSITE_INSTRUMENTS`, which is empty (`signals.py:95`). |

Neither defect can change a live or paper order today. Both change research
evidence.

## #751: Initial Balance leaks into premarket rows

Mechanism, confirmed: premarket rows (00:00-08:29 CT) carry the session's
**completed** IB. In `ib_breakout_signals`, the per-session `_first_cross`
"fresh breakout" flag is computed across those rows. A premarket close beyond
the future IB uses up the session's single fresh flag, so the RTH breakout
that should have traded is dropped. The effect is a look-ahead filter on
which days trade.

Data: `ib_wfo_runner` pinned caches (`MES_2024-09-22_2026-05-29_5m_cont.csv`,
`MGC_2024-05-01_2026-05-29_5m_cont.csv`), the runner's own 4-combo grid, and
realistic costs. Current = production function. Causal = IB exposed only at or
after the IB window closes.

| Sym | Mode | TM | OM | Trades cur -> causal | PF cur -> causal | Net $ cur -> causal |
|---|---|---|---|---|---|---|
| MES | go | 1.5 | 30 | 217 -> 362 | 1.088 -> 1.007 | 1,020 -> 141 |
| MES | go | 1.5 | 60 | 262 -> 313 | 1.031 -> 1.014 | 426 -> 222 |
| MES | go | 2.0 | 30 | 255 -> 340 | 1.268 -> 1.110 | 3,651 -> 1,968 |
| MES | go | 2.0 | 60 | 225 -> 224 | 1.027 -> 1.082 | 316 -> 1,012 |
| MES | fade | 1.5 | 30 | 258 -> 541 | 0.654 -> 0.790 | -1,442 -> -1,727 |
| MES | fade | 1.5 | 60 | 279 -> 478 | 0.625 -> 0.865 | -1,459 -> -906 |
| MES | fade | 2.0 | 30 | 259 -> 534 | 0.697 -> 0.779 | -1,315 -> -1,900 |
| MES | fade | 2.0 | 60 | 279 -> 474 | 0.641 -> 0.887 | -1,396 -> -745 |
| MGC | go | 1.5 | 30 | 105 -> 283 | 0.805 -> 0.888 | -1,278 -> -1,613 |
| MGC | go | 1.5 | 60 | 131 -> 313 | 1.346 -> 1.327 | 2,070 -> 4,686 |
| MGC | go | 2.0 | 30 | 145 -> 424 | 1.019 -> 0.975 | 171 -> -658 |
| MGC | go | 2.0 | 60 | 149 -> 369 | 0.976 -> 1.244 | -184 -> 4,542 |
| MGC | fade | 1.5 | 30 | 154 -> 444 | 0.940 -> 1.029 | -241 -> 294 |
| MGC | fade | 1.5 | 60 | 169 -> 381 | 0.872 -> 0.869 | -494 -> -1,051 |
| MGC | fade | 2.0 | 30 | 159 -> 440 | 0.906 -> 0.887 | -412 -> -1,212 |
| MGC | fade | 2.0 | 60 | 172 -> 384 | 0.905 -> 0.851 | -386 -> -1,244 |

Findings:
1. **Material.** The leak removes 0-52% of MES trades and 55-66% of MGC
   trades. Full-sample PF moves by up to 0.27, in **both** directions. The
   leak is not a simple optimistic bias, so current IB metrics cannot be
   corrected by haircut.
2. **No false authorization.** All four recorded IB gate-v2 verdicts
   (`MES/MGC_ib_go/fade_rank1`, per `engine/data/family_fdr_report.md`) are
   FAIL. The leak never produced a PASS.
3. **The recorded FAILs are still not valid evidence.** They measured a
   leaky strategy. The causal MGC `go` 2.0/60 variant (369 trades, full-sample
   PF 1.244) shows these numbers would change under a re-run. It is **not** a
   candidate on this evidence: it is one cell of a 16-cell grid, has no WFO,
   no DSR, and adds to the campaign trial count.

## #752: VWAP signals trade the Globex overnight

Mechanism, confirmed: on the near-continuous 1h cache, VWAP accumulates
overnight and entries are blocked only at hour >= 15 ET.

Data: `MES_2024-04-26_2026-06-25_1h.csv`, picked by the runner's own
`_find_data_file`. 12,477 bars, of which 3,783 are 09:00-15:59 ET. Full
36-combo grid from `run_mes_vwap_rank1`.

- **83.2%-99.1% of entry signals fall outside 09:00-15:59 ET**, depending on
  the combo.
- Recorded champion (`band 2.5, stop 0.75, no reversal bar, regime filter`):
  895 entries, 820 of them (91.6%) outside RTH. Backtest: 339 trades,
  PF 3.43. On RTH-only input: 17 trades.
- RTH-only samples are 2-102 trades per combo. Those PFs (5-99) come from
  tiny samples and **are not evidence of edge**.

Findings:
1. The archived `MES_vwap_rank1` gate-v2 verdict (FAIL via `dsr=0.0`) tested
   an **overnight** mean-reversion strategy, not the documented 09:30-anchored
   session VWAP. Its nominal `pf_ci_lower 1.71` / `p_edge 0.857` / `STRONG`
   WFO describe that overnight behaviour.
2. No authorization impact: the verdict is FAIL and archived, and the VWAP
   path is not live.
3. The documented strategy has almost no signals at 1h resolution, because
   the 09:00 ET bar also contains 30 minutes of premarket. A faithful test
   needs sub-hour bars and an explicit 09:30 anchor. The issue already notes
   the 09:xx reset bug on sub-hour data.

## Recommended next steps (human decision; nothing here was executed)

1. Keep production behaviour unchanged until the causal replacements are
   reviewed. PR #749's `opening_range_causal.py` is the existing IB candidate.
2. When patching, re-run `ib_wfo_runner` for both symbols and both modes, and
   rebuild `family_fdr_report.md`. Count the added trials in the campaign
   ledger. Delete the strict-xfail markers in the same PR.
3. Label the archived VWAP verdict "tested overnight behaviour (#752)" rather
   than deleting it. Treat any future 09:30-anchored VWAP as a new hypothesis
   with its own pre-registration.
