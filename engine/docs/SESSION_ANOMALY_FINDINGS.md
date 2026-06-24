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
