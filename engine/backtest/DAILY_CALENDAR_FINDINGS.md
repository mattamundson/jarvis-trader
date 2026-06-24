# Daily calendar/seasonality screen — findings (2026-06-24)

Standalone screener (`daily_calendar_discovery.py`) over the deep free daily ETF
caches pulled by `free_daily_export.py` (SPY 33yr, DIA 28yr, QQQ 27yr, IWM 26yr,
GLD 22yr). 5 symbols × 13 calendar effects = 65 parameter-free long-on-selected-days
strategies, each graded net @ 2bps on the honest bar: bootstrap PF-CI, p_edge,
**deflated Sharpe penalized for 13 trials**, max-DD, chronological H1/H2 stationarity,
and the canonical `compute_gate_v2` verdict.

Candidacy ranks on DURABLE metrics (stationary + PF-CI≥1.10 + dsr≥0.10), NOT p_edge —
the turn-of-month lesson: `p_edge≥0.95` is structurally impossible for a long-beta
harvest. All candidates are BLOCKED from promotion; this is a research leaderboard.

## Headline: the PRE-HOLIDAY effect is the standout

The day-before-market-holiday drift (Ariel/Lakonishok-Smidt) is the strongest,
most robust signal — it clears the 13-trial-penalized bar on **all five** ETFs,
is stationary in both halves, and is low-drawdown:

| sym | effect | n | PF-CI | dsr(×13) | Sharpe | DD% | H1/H2 PF | gate-v2 |
|---|---|---|---|---|---|---|---|---|
| QQQ | pre_holiday | 251 | 2.73 | 1.00 | 1.29 | 16.3 | 1.24/1.37 | FAIL (p_edge) |
| IWM | pre_holiday | 241 | 2.62 | 1.00 | 1.54 | 11.5 | 1.05/1.86 | FAIL (p_edge) |
| GLD | pre_holiday | 201 | 2.43 | 1.00 | 2.77 | 6.1 | 1.56/1.67 | **PASS (ALT)** |
| SPY | pre_holiday | 302 | 2.55 | 0.94 | 1.32 | 7.8 | 1.17/1.44 | **PASS (ALT)** |
| DIA | pre_holiday | 261 | 2.47 | 0.97 | 1.20 | 8.1 | 1.23/1.27 | FAIL (p_edge) |

SPY and GLD pre_holiday pass the FULL canonical gate-v2 via the ALT path — a
stronger result than turn-of-month, which only ALT-failed on `fixed_params_min_pf`.
~9–11 trades/yr (matches the ~9 US market holidays), so cost-robust.

## Other durable candidates (stationary + survive the penalty)

- **GLD january** (n=444, PF-CI 1.37, dsr 1.00, H1/H2 1.41/1.56) — gold's January seasonal.
- **QQQ turn_of_quarter** (n=437, PF-CI 2.16, dsr 0.51) — quarter-turn rebalancing drift.

9 durable candidates total across the 65 cells.

## Caveats / honest reads

- **Turn-of-month under the screen penalty:** SPY TOM (n=1604) is stationary (H1/H2
  1.17/1.13, PF-CI 2.01) but its deflated Sharpe collapses to ~0 once penalized for
  13 trials — expected and correct. Its dedicated single-hypothesis validation
  (`validate_tom`, n_trials=1, beta-sized) is the promotion-relevant grade; this screen
  deliberately over-penalizes to surface only the most robust effects. NOT a regression.
- **Weekday effects** (mon/tue/wed/...) are profitable gross but die on the penalty +
  high drawdown (35–60%) — they're just beta exposure on a subset of days, not edge.
- **September** is the only consistently negative effect across symbols (PF<1) — the
  documented worst-month seasonal, correctly surfaced with a sub-1 PF.
- These are IN-SAMPLE over the full history; the honest next gate is a FORWARD shadow
  (like TOM's `tom_paper_track`), not promotion. Pre-holiday is the prime forward-track
  candidate.

## Next

1. Forward-shadow the pre-holiday effect (mirror `tom_paper_track`, observe-only).
2. Fold the calendar family into the discovery factory once the session-anomaly +
   discovery-factory branches converge (currently kept standalone to avoid peer collision).
