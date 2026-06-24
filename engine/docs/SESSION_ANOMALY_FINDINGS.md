# MES session-anomaly (overnight-drift) — findings

**Date:** 2026-06-24 · **Branch:** `feat/session-anomaly-mes` (standalone, UNPUSHED).
**Track:** a *fresh, non-overlapping* edge track (every prior attempt was trend-direction,
fill-magnet, or spread; a peer session owns the MGC intraday DD-attack). Tests the well-
documented equity-index **overnight drift**: historically most of the index's return has
accrued overnight (RTH close → next RTH open) rather than intraday.

**Data:** `MES_2024-09-22_2026-05-29_5m_cont.csv` — 433 RTH days (~20 months), UTC bars
converted to US/Eastern for the 09:30–16:00 RTH boundary (DST-aware).
**Method:** parameter-free long-overnight and long-intraday legs (nothing to overfit),
net of realistic MES round-trip cost (commission $1.70 + ~1 pt slippage), evaluated with the
canonical honesty helpers (`bootstrap_pf_ci_lower`, `classify_wfo_consistency`) **plus a
mandatory chronological H1/H2 split** — the ES-NQ lesson that a pooled bootstrap passes a
non-stationary, back-loaded edge.

## Result — both legs FAIL the honest gate

| leg | total ret | PF | PF_ci_lower | p_edge | sharpe | maxDD | H1_pf | H2_pf | stationary | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| OVERNIGHT (net) | +4.04% | 1.054 | **1.176** ✓ | 0.619 ✗ | 0.273 | **17.46%** ✗ | **0.96** | 1.20 | **No** | FAIL |
| INTRADAY (net) | +4.49% | 1.053 | 0.946 ✗ | 0.429 ✗ | 0.249 | 12.44% ✗ | 1.07 | 1.03 | Yes | FAIL |

Gate bar: PF_ci_lower ≥ 1.10, p_edge ≥ 0.95, sharpe ≥ 0.10, maxDD ≤ 5%, H1/H2 both PF > 1.

## Interpretation (decision-grade)

1. **The documented overnight premium is absent in recent MES.** Overnight (+4.04%) ≈
   intraday (+4.49%) — return is split roughly evenly across the two sessions, *not* the
   historical "overnight ≫ intraday." The classic anomaly does not hold here.
2. **The naive overnight leg is non-stationary.** Its only positive contribution is in H2
   (PF 1.20, +3.38 bps/day); H1 *loses* (PF 0.96, −1.11 bps/day). The "edge" is a
   second-half regime artifact, exactly what the H1/H2 guard exists to catch. The lone
   metric it passes (PF_ci_lower 1.176) is the pooled-bootstrap mirage the guard overrides.
3. **Unhedged overnight carry has structural gap-risk drawdown** — 17.5% maxDD, far past the
   5% ceiling. Holding the index overnight with no filter eats every gap-down.
4. **Intraday is stationary but too weak** — both halves profitable but PF_ci_lower 0.946
   (< 1.0) and p_edge 0.43; no tradeable edge.

**Verdict: no deployable naive session edge on MES.** Consistent with every prior track —
the honest gate + stationarity guard refute it.

## Calendar / seasonality extension (turn-of-month + day-of-week)

Same data, same honest gate. Close-to-close daily returns, net of cost.

| track | days held | total ret | PF | PF_ci_lower | p_edge | sharpe | maxDD | H1_pf | H2_pf | stationary | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| turn-of-month (long TOM window) | 84 | +2.21% | 1.103 | **1.607** ✓ | 0.619 ✗ | **0.523** | 5.78% ✗ | **0.98** | 1.26 | **No** | FAIL |

Day-of-week descriptive (mean bps/day, net): **Mon +17.8 (PF 1.78), Wed +27.0 (PF 2.24)**
positive; **Thu −19.4 (PF 0.54)** strongly negative; Tue/Fri ~flat. A "long Mon+Wed" rule is
**not** built — selecting the winning days from this table is in-sample selection bias, and (see
below) it would be regime-beta regardless.

Turn-of-month is the *best* candidate found (Sharpe 0.52, PF_ci 1.61, DD near the ceiling) but
fails the same way as overnight: **non-stationary** — H1 PF 0.98 loses, H2 PF 1.26 carries it.

## Meta-finding (the decision-grade conclusion)

**Every MES session/calendar candidate is non-stationary, back-loaded into the second half.**
Overnight (H1 0.96 / H2 1.20), turn-of-month (H1 0.98 / H2 1.26), and the positive weekdays all
concentrate their return in H2 (late-2025 → 2026). In this 20-month sample the "anomalies" are
**indistinguishable from exposure to the recent bull regime** — regime-beta, not alpha. The
chronological H1/H2 guard catches it every time; a pooled bootstrap (which several of these pass:
overnight PF_ci 1.18, TOM PF_ci 1.61) would have green-lit a regime artifact.

**Implication for the edge search:** a stationary edge on this instrument/period likely needs
either (a) a **longer sample spanning multiple regimes** (data-gated — IB/Amo), or (b) a
genuinely **regime-neutral structure** (market-neutral / stationarity-gated relative-value, or
the magnet-fill microstructure singlefinder — the one candidate that already cleared per-window
adequacy). Piling on more simple single-leg MES anomalies will keep producing H2-regime-beta.

## DATA PULL — SPY daily 1993→2026 (Amo-authorized, the decisive test)

The MES non-stationarity could be a too-short-sample artifact (20 months, one regime).
Authorized data pull: **SPY daily, 8,407 days, 1993-01-29 → 2026-06-24** (yfinance,
split/div-adjusted; saved `engine/backtest/cache/SPY_daily.csv`, gitignored). SPY is the
canonical multi-decade vehicle for the night effect and tracks SPX/MES directly. Spans 2000,
2008, 2018, 2020, 2022 — every regime. Run via `... --daily --gross`.

| leg (gross, 33yr) | total ret | PF | PF_ci_lower | p_edge | sharpe | maxDD | H1_pf | H2_pf | stationary |
|---|---|---|---|---|---|---|---|---|---|
| **OVERNIGHT** | +2282% | 1.210 | 1.529 | 0.728 | **0.950** | 32.8% | **1.24** | **1.18** | **YES** |
| INTRADAY | +28% | 1.024 | 1.262 | 0.545 | 0.125 | 68.5% | 0.98 | 1.09 | No |
| **TURN_OF_MONTH** | +209% | 1.213 | 2.088 | 0.584 | **1.072** | 18.4% | **1.23** | **1.20** | **YES** |

**Overnight PF by 5-year era — positive in EVERY regime:** 1990s 1.56/1.64, 2000-04 **1.053**
(dot-com), 2005-09 **1.124** (GFC), 2010-14 1.183, 2015-19 1.216, 2020-24 1.154, 2025+ 1.161.
Never < 1.0. The MES "non-stationarity" was a **short-sample artifact** — the overnight drift is
real and stationary across 33 years. Virtually all of SPY's return is overnight (+2282% vs the
intraday +28%); the intraday leg is the weak, non-stationary one.

### Why they still "FAIL" the gate — and the honest net read

Both real legs fail only on `p_edge ≥ 0.95` (95% of *months* profitable) and `maxDD ≤ 5%` —
thresholds calibrated for hedged intraday-trend WFO, structurally impossible for a **long-beta
harvest** (you cannot hold equity overnight through 2008/2020 at 5% DD; no long wins 95% of
months). They are real edges, not gate-passers in raw long form.

Net-of-cost (the deciding lens):

| | gross Sharpe | net@1bp | net@2bp | net@3bp | trades/yr | verdict |
|---|---|---|---|---|---|---|
| overnight | 0.950 | 0.712 | 0.475 | 0.237 | ~252 | **real but too thin** — cost eats half; sized to 5% DD → ~1.5%/yr gross |
| turn-of-month | 1.072 | — | **0.793** | — | ~48 | **the candidate** — low turnover ⇒ cost-robust; stationary; Sharpe survives |

## Conclusion — first real edge of the arc

**Turn-of-month is the first stationary, cost-surviving, multi-regime anomaly found.** Sharpe
1.07 gross / 0.79 net, both 16-year halves PF ~1.2 (no modern decay), ~48 trades/yr so
transaction cost barely dents it. It carries equity-beta drawdown (18%), so its deployable form
is **beta-sized to the risk budget** (≈0.27x for a 5% DD ceiling) and/or routed through the
promotion gate — not a raw unhedged long. Overnight drift is confirmed real but **killed for
standalone deployment** (per-trade edge ≈ transaction cost). This is a regime-NEUTRAL-by-design
direction (the meta-finding's prescription), now with empirical support.

## Productionization (TOM → candidate) — `validate_tom`

Re-run via `python -m backtest.session_anomaly_backtest --validate-tom`.

- **MES transfer confirmed:** turn-of-month on the actual tradeable (MES, net of real MES cost)
  is Sharpe 0.52, PF 1.10, +3.03 bps/day — positive and consistent with the SPY result (the lower
  Sharpe is the 20-month sample, not a transfer failure).
- **Beta-sizing works:** scaling net TOM by 0.263 brings max-DD from 19% to **5.23%**, so the
  deployable form clears the gate's `mc_95th_dd ≤ 5%` ceiling.
- **Rigorous gate-v2 (canonical `compute_gate_v2`, SPY 33yr yearly windows), beta-sized net form:**
  `pf_ci=1.172 ✓  dsr=1.000 ✓  mc95_dd=0.0457 ✓  wfo=MODERATE`. **FAILs the core path on a single
  criterion — `p_edge 0.618 < 0.95`** — and the ALT path on `fixed_params_min_pf 1.15 < 1.20`.

The `p_edge ≥ 0.95` bar (95% of annual windows profitable) is structurally unmeetable for a
long-beta harvest. Two Tier-3 questions for Amo (a beta-harvest gate variant + a systematic-strategy
promotion path) are written up in `BETA_HARVEST_GATE_PROPOSAL.md`. TOM is now a **tracked
promotion-gate candidate** (`live_promotion_gate.turn_of_month_current_evidence`) — correctly
BLOCKED pending the forward paper-shadow + live-system stability + those two policy decisions, but
it carries the strongest backtest evidence of the arc.

## Forward paper-shadow (DARK, observe-only) — LIVE

`engine/backtest/tom_paper_track.py` (+5 tests) is the honest next gate, built in the
`spread_paper_track` mold: NO orders, NO live DB, an isolated JSONL ledger under the
MAIN-checkout `engine/data/tom_paper_track/` (durable across a worktree prune). Each tick records
realized turn-of-month close-to-close returns (SPY daily via free yfinance — the validated vehicle,
no engine dependency); only TOM days strictly AFTER inception count; idempotent. `--report` grades
the accumulated FORWARD record on the gate-v2 bar vs the backtest prior (SPY Sharpe ~0.79 net).

**Inception established 2026-06-24** (first live tick recorded 0 forward days, as expected). It now
accumulates ~48 TOM days/yr; a gate verdict is meaningful after ~24 forward days (~6 months).

**To go fully durable (Amo):** (1) merge `feat/session-anomaly-mes` so the tracker code lands in the
main checkout; (2) register a daily scheduled task — mirrors `Jarvis-SpreadPaperTrack`:
`schtasks /Create /SC DAILY /TN "Jarvis-TomPaperTrack" /TR "<main>/engine/.venv/Scripts/python.exe -m backtest.tom_paper_track" /ST 17:30 /RL LIMITED`
(observe-only; the ledger/state already live in the main checkout, so the data is durable now).

## The one promising refinement (not yet run)

The naive leg's two killers — 17% DD and H1 losses — are exactly what a **regime filter**
addresses. The literature's tradeable form of overnight drift is *conditional*: hold
overnight only in benign regimes, stand aside in stress (when overnight gap risk and H1-type
losses cluster). JARVIS already has the one transferable asset for this from the options-VRP
work: the **VIX/VIX3M term-structure regime filter** (contango = calm, backwardation =
stress). Applying it to the overnight leg is the natural next experiment — it directly
attacks both the drawdown and the non-stationarity. Requires wiring in the VIX/VIX3M loaders
(they exist on `feat/ts-overlay`); flagged for go-ahead before spending on the integration.

## Files

- `engine/backtest/session_anomaly_backtest.py` — standalone module (decompose → leg returns
  → honest metrics + H1/H2 guard). Reuses the gate helpers; never touches the discovery factory.
- `engine/tests/test_session_anomaly_backtest.py` — 14 tests (synthetic-data decomposition,
  cost, stationarity guard). All green.
