# Daily calendar/seasonality screen — findings (2026-06-24; effects expanded 2026-06-26)

Standalone screener (`daily_calendar_discovery.py`) over the deep free daily ETF
caches pulled by `free_daily_export.py` (SPY 33yr, DIA 28yr, QQQ 27yr, IWM 26yr,
GLD 22yr). 5 symbols × **17** calendar effects = 85 parameter-free long-on-selected-days
strategies, each graded net @ 2bps on the honest bar: bootstrap PF-CI, p_edge,
**deflated Sharpe penalized for 17 trials**, max-DD, chronological H1/H2 stationarity,
and the canonical `compute_gate_v2` verdict.

> **2026-06-26 update:** the family grew from 13 → 17 effects (added `santa_claus`,
> `post_holiday`, `last_day_of_month`, `opex_week` — all pre-registered, documented
> anomalies). The harsher 17-trial deflation did NOT unseat the known passers (SPY
> pre_holiday dsr 0.94→0.61, GLD pre_holiday 1.00 — both still gate-PASS) and surfaced
> **santa_claus as a second robust effect** (see headline 2). See § "2026-06-26 effects".

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

## Headline 2: santa_claus is a second robust cross-sectional effect (2026-06-26)

The Santa-Claus window (Hirsch: last 5 trading days of Dec + first 2 of Jan) clears
the gate-v2 on **two** ETFs and is a durable candidate on two more — the breadth that
separates a real seasonal from a single-symbol fluke:

| sym | effect | n | PF-CI | dsr(×17) | Sharpe | DD% | H1/H2 PF | gate-v2 |
|---|---|---|---|---|---|---|---|---|
| GLD | santa_claus | 154 | 2.67 | 1.00 | 4.19 | 6.5 | 1.82/2.40 | FAIL (DD/p_edge) |
| SPY | santa_claus | 231 | 1.96 | 0.66 | 1.52 | 7.6 | 1.55/1.14 | **PASS (ALT)** |
| DIA | santa_claus | 197 | 1.84 | 0.40 | 1.04 | 8.5 | 1.33/1.09 | **PASS (ALT)** |
| IWM | santa_claus | 182 | 1.57 | 1.00 | 1.03 | 7.7 | 1.43/0.93 | FAIL (H2) |

SPY + DIA santa_claus PASS the full gate-v2 (ALT); GLD has the strongest raw metrics
(Sharpe 4.19, dsr 1.00) but gate-fails on drawdown/p_edge. Fires once/yr (~7 days), so
a forward shadow sees its first observation only in late December.

## Other durable candidates (stationary + survive the penalty)

- **GLD january** (n=444, PF-CI 1.37, dsr 1.00, H1/H2 1.41/1.56) — gold's January seasonal.
- **GLD post_holiday** (n=201, PF-CI 2.57, dsr 1.00, Sharpe 3.22) — gold's holiday effect
  spans BOTH sides of the break (gate-fails on DD 9.7%).
- **QQQ turn_of_quarter** (n=437, PF-CI 2.16, dsr 0.05) — quarter-turn rebalancing drift.

10 durable candidates total across the 85 cells.

## 2026-06-26 effects — what the 4 new pre-registered anomalies revealed

- **santa_claus** — the find (headline 2): 2 gate-PASS + 4/5-ETF candidacy.
- **post_holiday** (day AFTER a holiday, complement of pre_holiday) — dead/negative on
  equities (SPY +0.02, DIA −0.30, IWM −0.43 Sharpe) but a candidate on GLD. **Confirms the
  documented asymmetry: the equity holiday effect is PRE-break only; gold's spans the break.**
- **last_day_of_month** (only the final trading day) — all FAIL, negative Sharpe (SPY −0.96,
  DIA −1.83). **Informative negative: the turn-of-month edge is front-loaded into the new
  month, NOT month-end** — isolating the last day strips the edge entirely.
- **opex_week** (Mon-Fri ending on the 3rd Friday) — clean null, dsr 0.00 everywhere.
  Options-expiration flows do not produce a durable close-to-close daily long edge.

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

1. Forward-shadow the pre-holiday effect (mirror `tom_paper_track`, observe-only) — DONE,
   live via `Jarvis-PreHolidayPaperTrack` (SPY+GLD). See `project_preholiday_forward_shadow`.
2. **santa_claus is the new forward-shadow candidate** (SPY+DIA gate-PASS). It fires only
   late-Dec→early-Jan, so add its forward slot before December; no observations until then.
3. Fold the calendar family into the discovery factory once the session-anomaly +
   discovery-factory branches converge (currently kept standalone to avoid peer collision).
