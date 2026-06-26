# Daily calendar/seasonality screen — findings (2026-06-24; effects expanded 2026-06-26)

Standalone screener (`daily_calendar_discovery.py`) over the deep free daily ETF
caches pulled by `free_daily_export.py` (SPY 33yr, DIA 28yr, QQQ 27yr, IWM 26yr,
GLD 22yr; + cross-asset TLT 24yr, SLV 20yr, EEM 23yr, XLU 28yr, HYG 19yr, LQD 24yr,
EFA 25yr). **12 symbols × 18 effects = 216** parameter-free long-on-selected-days
strategies, each graded net @ 2bps on the honest bar: bootstrap PF-CI, p_edge,
**deflated Sharpe penalized for 18 trials**, max-DD, chronological H1/H2 stationarity,
and the canonical `compute_gate_v2` verdict.

> **2026-06-26 update:** family grew 13 → 17 → **18** effects (added `santa_claus`,
> `post_holiday`, `last_day_of_month`, `opex_week`, then **`pre_fomc`**) AND the symbol
> set grew 5 → 12 (added cross-asset TLT/SLV/EEM, then the duration/credit/intl family
> XLU/HYG/LQD/EFA to TEST the month-end mechanism). Net: **33 durable candidates, 10
> gate-v2 PASSes.** The cross-asset breadth didn't just add passers — it LOCALIZED each
> effect to its economic mechanism (see § "Cross-asset" and headline 3). **Every prior
> passer survived re-deflation to 18 trials** — adding the 18th effect (raising the
> multiple-testing penalty) knocked out none of the 9 standing PASSes.

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

## Headline 3: each effect localizes to its economic mechanism (the 9 gate-v2 PASSes)

The 12-symbol cross-asset board makes the mechanism unambiguous — the effects are not
generic "be long on these days," they fire where their economic driver lives:

| effect | gate-v2 PASS on | mechanism | dies / negative on |
|---|---|---|---|
| **pre_holiday** | SPY, GLD, **HYG** | risk-on holiday drift | bonds (TLT neg) |
| **santa_claus** | SPY, DIA, EEM, **EFA**, **HYG** | year-end risk-on (broadest) | bonds (TLT neg) |
| **last_day_of_month** | **LQD** | month-end DURATION/RATES demand | every equity (negative) |

- **`last_day_of_month` is a pure rates/duration effect.** It gate-PASSES on LQD (IG credit,
  Sharpe 2.95, H1/H2 3.31/1.45, DD 3.5%) and is a strong candidate on TLT (Treasuries) and XLU
  (utilities = bond proxy) — yet it is **negative on every equity** (SPY −0.96, IWM −1.16, DIA
  −1.83). The sign-separation between the duration complex (+) and equities (−) is the documented
  month-end index-duration-extension buy, cleanly isolated. This is the strongest *new structural*
  finding of the whole calendar track.
- **Holiday/year-end effects are risk-on** — they pass across equity (SPY/DIA), EM (EEM), developed
  intl (EFA), gold (GLD), and high-yield credit (HYG, which trades like equity), and go negative in
  Treasuries. HYG pre_holiday is especially clean (DD only 2.7%, H1/H2 1.43/3.29).

10 gate-v2 PASSes total; 33 durable candidates across the 216 cells.

## Headline 4: pre-FOMC drift is REAL but DECAYING — passes only on low-DD Treasuries (2026-06-26)

The Lucca-Moench pre-FOMC announcement drift (NY Fed Staff Report 512: equities earn an
outsized premium in the ~24h before scheduled FOMC decisions) is the strongest *documented*
equity anomaly tested here — and the screen tells the honest story of its **post-publication
decay**. The mask flags the single trading day before each of the **271 scheduled FOMC
announcements 1994-2027** (last day of each scheduled meeting; emergency/intermeeting cuts
and the cancelled 2020 March meeting excluded — the drift is an ANTICIPATED-announcement
effect). Dates sourced from the Fed's own calendars + per-year historical pages, not memory.

| sym | effect | n | PF-CI | dsr(×18) | Sharpe | DD% | H1/H2 PF | gate-v2 |
|---|---|---|---|---|---|---|---|---|
| TLT | pre_fomc | 191 | 2.46 | 1.00 | 2.50 | 3.8 | 1.93/1.26 | **PASS (ALT)** |
| SPY | pre_fomc | 259 | 2.49 | 1.00 | 1.46 | 12.4 | 1.68/**1.04** | FAIL (DD) |
| DIA | pre_fomc | 227 | 2.45 | 1.00 | 1.58 | 11.1 | 1.41/1.48 | FAIL (DD) |
| QQQ | pre_fomc | 218 | 2.55 | 0.98 | 1.25 | 15.8 | 1.22/1.37 | FAIL (DD) |

- **The decay is the headline.** SPY's H1→H2 profit factor collapses **1.68 → 1.04** — the
  pre-FOMC equity drift was strong pre-~2011 and has faded to near-nothing since, exactly the
  "anomaly decays after it's published" pattern (Lucca-Moench published 2015). The screen
  surfaces SPY/DIA/QQQ as durable candidates (full-sample PF-CI > 2.4) but the gate correctly
  **FAILS** them on the ~12-16% drawdown of the equity pre-FOMC day-subset.
- **Only TLT (20y Treasuries) PASSES the gate (ALT path)** — bonds' pre-FOMC bid is lower-DD
  (3.8%) and **less decayed** (H2 PF 1.26 vs SPY's 1.04): Treasuries rally into a binary rate
  decision (rate-anticipation + event hedging), and that duration bid has held up better than
  the equity risk-premium compression. **Caveat: it is a NARROW pass** — DD 3.8% sits just
  under the 4.0% ALT ceiling (`GATE_MC_DD_ALT`); a slightly tighter ceiling flips it to FAIL.
- **Best forward-shadow cadence of the whole calendar family** — fires ~8×/yr, so a forward
  record accrues an order of magnitude faster than once-a-year santa_claus. That makes
  `pre_fomc` the highest-value forward slot for *watching the decay continue* out-of-sample.

## Cross-asset (2026-06-26) — TLT / SLV / EEM / XLU / HYG / LQD / EFA separate real seasonals from equity quirks

Pulling 3 economically-distinct instruments (TLT 20y Treasuries, SLV silver, EEM emerging
markets) tested whether the effects are US-equity artifacts or genuine cross-asset seasonals:

- **santa_claus generalizes hardest** — adds a **gate-v2 PASS on EEM** (dsr 1.00, Sharpe 3.88,
  H1/H2 2.40/1.55) on top of SPY+DIA, plus a strong SLV candidate. Equity + EM + metals breadth
  = a real cross-asset year-end seasonal, not a single-market fluke.
- **pre_holiday generalizes** — EEM (PF-CI 2.91, dsr 1.00) and SLV are strong candidates atop
  the SPY+GLD PASS. Holds across equity / EM / metals.
- **NEW bond-specific effect — TLT `last_day_of_month`** (n=288, PF-CI 2.81, dsr 1.00, Sharpe
  3.20, H1/H2 2.12/1.37). The month-end effect that is *negative* in equities is *strongly
  positive* in 20y Treasuries — the documented month-end index-duration-extension buy. The
  cross-asset SIGN FLIP validates the economic mechanism (it is duration demand, not beta).
- **Precious-metals holiday symmetry** — GLD and SLV BOTH show pre- and post-holiday candidacy
  (dsr 1.00); equities are pre-only, bonds negative. Metals' holiday effect spans the break.
- **TLT otherwise diverges from equities** — pre_holiday/santa_claus are NEGATIVE for bonds
  (flight-to-safety vs risk-on calendar structure differ), confirming the effects are not just
  generic beta on a day-subset.

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
- **pre_fomc** (day before each scheduled FOMC announcement; headline 4) — real but
  DECAYING; 4 equity/bond candidates, 1 gate-PASS (TLT). The SPY H1/H2 1.68→1.04 split is
  the cleanest decay signature in the whole family — a textbook published-anomaly fade.

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
3. **pre_fomc is the best forward-shadow cadence in the family** (~8 obs/yr). Forward-watch
   TLT pre_fomc (the gate-PASS) + SPY pre_fomc (the decayed-equity reference) to test whether
   the decay continues out-of-sample — wired into `calendar_paper_track.py` 2026-06-26.
4. Fold the calendar family into the discovery factory once the session-anomaly +
   discovery-factory branches converge (currently kept standalone to avoid peer collision).
