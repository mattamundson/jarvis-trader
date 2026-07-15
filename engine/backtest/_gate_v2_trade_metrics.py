"""Trade-level gate-v2 risk metrics (drawdown MC + Deflated Sharpe).

WHY THIS MODULE EXISTS
----------------------
The per-strategy gate-v2 runners (run_mes_trend_rank11.py, run_mgc_trend_rank4.py,
and siblings) historically computed two ALT-lane metrics from **window-level**
aggregates:

    oos_dds     = [r.max_drawdown_pct for r in oos_results]   # one DD per WFO window
    mc_95th_dd  = np.percentile(oos_dds, 95.0)                # percentile across windows
    mean_sharpe = mean([r.sharpe_ratio for r in oos_results]) # mean of per-window Sharpes
    dsr         = deflated_sharpe_ratio(sharpe=mean_sharpe, n_obs=max(all_trades, 30))

Both are mis-specified for sparse strategies:

* **mc_95th_dd window-level** takes ONE drawdown per WFO window and a percentile
  across windows. A drawdown that builds across several trades inside the test set
  is invisible — each window contributes only its own (small) max DD, and empty
  windows contribute 0.0, dragging the percentile down. For MES (16 OOS trades /
  19 windows, ~7 empty) this badly understates tail risk. The codebase already has
  a correct trade-level permutation MC (`monte_carlo.bootstrap_max_dd`) — it just
  was never wired into the gate runners. (`scripts/validate_strategy.py` uses it.)

* **DSR from mean-of-window-Sharpes** feeds the Bailey/Lopez de Prado deflation a
  Sharpe that is the arithmetic mean of per-window Sharpes (a 1-2 trade window
  yields a giant, unstable Sharpe), with `n_obs` floored at 30 and hardcoded
  Gaussian skew/kurt — producing a Phi(z) that rounds to 1.0 and auto-passes. The
  correct path computes the Deflated Sharpe from the actual per-trade return series
  with real skew/kurt (`deflated_sharpe.deflated_sharpe_from_returns`).

This module centralises the CORRECT trade-level computation so every runner shares
one tested implementation, matching `scripts/validate_strategy.py`.

UNITS (critical — a 100x error here mis-certifies live strategies)
------------------------------------------------------------------
* `Trade.pnl` is in USD (dollars).
* `monte_carlo.bootstrap_max_dd(...)["mc_95th"]` returns drawdown on a **0-100
  scale** (`_compute_max_dd` does `abs(dd.min()) * 100`).
* The gate compares `mc_95th_dd` (a **fraction**, e.g. GATE_MC_DD_ALT == 0.04) so
  this module divides the 0-100 MC result by 100 to return a fraction.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from backtest.deflated_sharpe import deflated_sharpe_from_returns
from backtest.monte_carlo import bootstrap_max_dd, bootstrap_win_rate, compute_cvar, compute_var
from backtest.monte_carlo import probability_of_ruin as _mc_probability_of_ruin
from backtest.stationarity_gate import h1_h2_split

#: Drawdown returned when there are too few real trades to simulate a path.
#: 1.0 == 100% == fail-safe (worse than any real gate ceiling).
_DEGENERATE_DD_FRACTION = 1.0
_MC_N_RESAMPLES = 10_000
_MC_SEED = 42


def concat_oos_trade_pnls(oos_results: Sequence) -> list[float]:
    """Flatten the per-trade USD PnLs across every OOS window, in sequence.

    Empty windows (0 trades) contribute nothing — unlike the window-level DD
    metric, which counted them as 0.0 drawdown and diluted the percentile.
    """
    pnls: list[float] = []
    for r in oos_results:
        for t in getattr(r, "trades", []) or []:
            pnls.append(float(t.pnl))
    return pnls


def trade_level_mc_95th_dd(
    oos_results: Sequence,
    initial_capital: float,
    n_resamples: int = _MC_N_RESAMPLES,
    seed: int = _MC_SEED,
) -> float:
    """95th-percentile max drawdown from a permutation MC on the OOS trade list.

    Returns a **fraction** (0.04 == 4%), matching the gate's `mc_95th_dd`
    convention. Fail-safe (1.0) when fewer than 2 real trades exist.
    """
    pnls = concat_oos_trade_pnls(oos_results)
    if len(pnls) < 2:
        return _DEGENERATE_DD_FRACTION
    mc = bootstrap_max_dd(pnls, initial_capital=initial_capital, n_resamples=n_resamples, seed=seed)
    # bootstrap_max_dd reports on a 0-100 scale; the gate wants a fraction.
    return float(mc["mc_95th"]) / 100.0


def trade_level_dsr(
    oos_results: Sequence,
    n_grid_combos: int,
    initial_capital: float,
) -> float:
    """Deflated Sharpe Ratio from the actual per-trade return series.

    Mirrors `scripts/validate_strategy.py`: returns = per-trade PnL / capital,
    real skew/kurt, n_obs = trade count. Fail-safe (0.0) when < 2 trades
    (handled inside `deflated_sharpe_from_returns`).
    """
    pnls = concat_oos_trade_pnls(oos_results)
    returns = (np.asarray(pnls, dtype=float) / initial_capital).tolist()
    result = deflated_sharpe_from_returns(
        returns=returns, n_trials=max(int(n_grid_combos), 1), ann_factor=252.0
    )
    return float(result.get("dsr", 0.0))


def trade_level_stationarity(
    oos_results: Sequence,
    min_trades_per_half: int = 5,
    min_pf: float = 1.0,
) -> dict:
    """H1/H2 chronological PF consistency from the SAME concatenated OOS trade
    series used by the DD/DSR metrics.

    Pooled bootstrap PF-CI is blind to WHEN the edge occurred; this binds on
    stationarity. Returns the `stationarity_gate.h1_h2_split` dict -- consumers
    gate on `["consistent"]`. Fail-safe: an empty/sparse series yields
    consistent=False so an enforcing gate default-denies rather than waving a
    back-loaded edge through. See stationarity_gate for the ES-NQ rationale.
    """
    pnls = concat_oos_trade_pnls(oos_results)
    return h1_h2_split(pnls, min_trades_per_half=min_trades_per_half, min_pf=min_pf)


def trade_level_win_rate_ci_lower(oos_results: Sequence) -> float:
    """95% bootstrap CI lower bound on win rate, from the SAME concatenated OOS
    trade list used by the DD/DSR metrics (no new data path).

    Complements DSR: a strategy carried by a few outlier wins can pass the
    risk-adjusted-return gate while winning unreliably; this binds on win
    reliability. Fail-safe (0.0) when fewer than 2 trades — so an enforcing gate
    default-denies on a degenerate sample rather than waving it through.
    """
    pnls = concat_oos_trade_pnls(oos_results)
    if len(pnls) < 2:
        return 0.0
    return float(bootstrap_win_rate(pnls)["win_rate_ci_95_low"])


# ---------------------------------------------------------------------------
# Report-only bootstrap risk metrics (VaR / CVaR / probability of ruin)
# ---------------------------------------------------------------------------
#
# These three wrappers are REPORT-ONLY diagnostics, not gate-v2 pass/fail
# thresholds (per ml-pitfalls-defense.md policy: new statistical metrics land
# as informational fields first). Do NOT wire these into verdict pass/fail
# logic alongside pf_ci_lower/p_edge/mc_95th_dd/dsr -- they are surfaced
# alongside the verdict for human review only.


def trade_level_var(
    oos_results: Sequence,
    initial_capital: float,
    confidence: float = 0.95,
    n_resamples: int = _MC_N_RESAMPLES,
    seed: int = _MC_SEED,
) -> float:
    """Bootstrap-resampled VaR (USD, negative-for-loss) from the concatenated
    OOS trade list. Report-only -- not a gate threshold. `initial_capital` is
    accepted for signature parity with the sibling trade_level_* wrappers, even
    though `compute_var` itself only needs the raw PnL series. Fail-safe (0.0)
    when fewer than 2 real trades exist.
    """
    pnls = concat_oos_trade_pnls(oos_results)
    if len(pnls) < 2:
        return 0.0
    result = compute_var(pnls, confidence=confidence, n_resamples=n_resamples, seed=seed)
    return float(result["var_pct"])


def trade_level_cvar(
    oos_results: Sequence,
    initial_capital: float,
    confidence: float = 0.95,
    n_resamples: int = _MC_N_RESAMPLES,
    seed: int = _MC_SEED,
) -> float:
    """Bootstrap-resampled CVaR (USD, negative-for-loss) from the concatenated
    OOS trade list. Report-only -- not a gate threshold. `initial_capital` is
    accepted for signature parity with the sibling trade_level_* wrappers, even
    though `compute_cvar` itself only needs the raw PnL series. Fail-safe (0.0)
    when fewer than 2 real trades exist.
    """
    pnls = concat_oos_trade_pnls(oos_results)
    if len(pnls) < 2:
        return 0.0
    result = compute_cvar(pnls, confidence=confidence, n_resamples=n_resamples, seed=seed)
    return float(result["cvar"])


def trade_level_probability_of_ruin(
    oos_results: Sequence,
    initial_capital: float,
    ruin_threshold_pct: float = 0.5,
    n_resamples: int = _MC_N_RESAMPLES,
    seed: int = _MC_SEED,
) -> float:
    """Bootstrap-resampled probability of ruin from the concatenated OOS trade
    list. Report-only -- not a gate threshold. Fail-safe (0.0) when fewer than
    2 real trades exist (too little data to simulate a path -- must not
    silently over-flag as risky).
    """
    pnls = concat_oos_trade_pnls(oos_results)
    if len(pnls) < 2:
        return 0.0
    result = _mc_probability_of_ruin(
        pnls,
        initial_capital=initial_capital,
        ruin_threshold_pct=ruin_threshold_pct,
        n_resamples=n_resamples,
        seed=seed,
    )
    return float(result["probability_of_ruin"])
