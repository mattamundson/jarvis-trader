"""Backtest-rigor guardrails — statistical sanity checks for paper/backtest metrics.

Five pure, independently-testable functions that catch the most common ways a
backtest or paper-trading metric lies. Each is a diagnostic (report-only) by
default: it returns a structured verdict a caller can log, surface in a
dashboard, or wire into a gate — this module does not itself block anything,
and nothing in ``engine/agents/`` or ``engine/backtest/signals.py`` imports
it. See ``docs/repo-integrations/`` bookmark-dossier research (top "do now"
backtest-rigor items, 2026-07-09) for the provenance of this list.

1. ``sharpe_implausibility_gate`` — flags a reported Sharpe that is too good
   to be real. Even top quant funds rarely sustain out-of-sample Sharpe > 2-3;
   a backtest/paper Sharpe > 5-8 is a near-certain lookahead-bias or
   overfitting artifact, not a durable edge.
2. ``mc_permutation_gate`` — thin adapter over the EXISTING, already-tested
   ``backtest.monte_carlo.run_monte_carlo`` (trade-order permutation). Does
   NOT reimplement the shuffle: it builds the minimal ``BacktestResult``/
   ``Trade`` wrapper that function needs from a raw P&L sequence and
   interprets the result as a pass/fail gate. See that module's docstring
   for the underlying algorithm (Masters 2020 permutation methodology).
3. ``ljung_box_independence_check`` — the permutation test above (and
   ``analytics/permutation_test.permute_and_score``) both assume the trade
   P&L series is i.i.d. Trend-following series often have real
   autocorrelation, which violates that assumption. This runs a Ljung-Box
   test (Ljung & Box 1978) so a caller can attach the right caveat to a
   permutation p-value instead of trusting it blindly.
4. ``adf_stationarity_check`` — Augmented Dickey-Fuller test (Dickey & Fuller
   1979; augmented form: Said & Dickey 1984) for whether a price/return
   series is stationary before combining it with the live SMA/ATR system.
5. ``diebold_mariano_test`` — Diebold & Mariano (1995, JBES) test with the
   Harvey-Leybourne-Newbold (1997) small-sample correction, for whether a
   candidate signal's return/forecast series has a significantly different
   edge than a baseline series before ever considering a swap-in.

Dependency note: ``statsmodels`` is added to ``engine/requirements*.txt`` for
items 3 and 4 (Ljung-Box, ADF). It was not previously a dependency; scipy
alone does not implement either test, and hand-rolling ADF's MacKinnon
critical-value tables is exactly the kind of reinvention that is more likely
to introduce a subtle bug than importing the standard, actively-maintained
library implementation. Imports are deferred inside the functions that need
it (repo convention for heavy optional dependencies — see
``.claude/rules/coding-style.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

# ---------------------------------------------------------------------------
# 1. Sharpe-implausibility reject gate
# ---------------------------------------------------------------------------

#: Sharpe above which a reported metric is flagged as implausible. Even 4+ is
#: rare for a real out-of-sample strategy; this default sits just above that.
SHARPE_IMPLAUSIBILITY_THRESHOLD: float = 5.0

#: Sharpe above which the flag is upgraded from "implausible" to "near-certain
#: artifact" — top systematic funds (Renaissance Medallion is the famous
#: outlier, not the norm) report annualized Sharpe in the low single digits.
SHARPE_EXTREME_THRESHOLD: float = 8.0

#: Below this trade count, a high Sharpe carries extra suspicion — the
#: standard error of a Sharpe estimate shrinks slowly with sample size, so a
#: thin sample overstates confidence in any point estimate (Bailey & Lopez de
#: Prado's Deflated Sharpe Ratio formalizes this; this gate is a cheap
#: pre-check, not a replacement for ``backtest.deflated_sharpe``).
SHARPE_SMALL_SAMPLE_TRADES: int = 30


def sharpe_implausibility_gate(
    sharpe: float,
    n_trades: int | None = None,
    period_days: float | None = None,
    threshold: float = SHARPE_IMPLAUSIBILITY_THRESHOLD,
    extreme_threshold: float = SHARPE_EXTREME_THRESHOLD,
) -> dict[str, Any]:
    """Flag a Sharpe ratio that is too high to plausibly be a real edge.

    Pure function: does not fetch or compute a Sharpe, just judges one. This
    is intentionally the cheapest, fastest check in the module — a strategy
    reporting Sharpe > ~5-8 should be treated as near-certain lookahead bias
    or overfitting before anyone spends a permutation test or a DSR run on it.

    Args:
        sharpe: the reported (annualized) Sharpe ratio.
        n_trades: trade count backing the Sharpe, if known. Used only to add
            a small-sample caveat to the explanation; does not change
            ``flagged``.
        period_days: sample period in days, if known. Same role as
            ``n_trades`` — informational only.
        threshold: Sharpe above which ``flagged`` is True. Default 5.0.
        extreme_threshold: Sharpe above which ``severity`` is upgraded to
            ``"extreme"``. Default 8.0.

    Returns:
        dict with ``flagged`` (bool), ``severity`` (``"normal"`` /
        ``"implausible"`` / ``"extreme"``), ``sharpe``, ``threshold``, and a
        human-readable ``explanation``.
    """
    flagged = bool(sharpe > threshold)
    if sharpe >= extreme_threshold:
        severity = "extreme"
    elif flagged:
        severity = "implausible"
    else:
        severity = "normal"

    reasons: list[str] = []
    if flagged:
        reasons.append(
            f"Sharpe {sharpe:.2f} exceeds the implausibility threshold ({threshold:.1f}). "
            "Real out-of-sample strategies rarely sustain Sharpe above 2-3 annualized; "
            "values in this range are far more consistent with lookahead bias, "
            "survivorship, or curve-fitting than with a durable edge."
        )
    if sharpe >= extreme_threshold:
        reasons.append(
            f"Sharpe {sharpe:.2f} is above the extreme threshold ({extreme_threshold:.1f}) — "
            "treat this metric as almost certainly an artifact, not a validated edge."
        )
    if n_trades is not None and n_trades < SHARPE_SMALL_SAMPLE_TRADES and flagged:
        reasons.append(
            f"n_trades={n_trades} is below the small-sample threshold "
            f"({SHARPE_SMALL_SAMPLE_TRADES}) — a high Sharpe on this few trades has a wide "
            "standard error; cross-check with backtest.deflated_sharpe (DSR) and "
            "mc_permutation_gate before trusting it."
        )
    if not flagged:
        reasons.append(f"Sharpe {sharpe:.2f} is within the plausible range (<= {threshold:.1f}).")

    return {
        "test": "sharpe_implausibility",
        "sharpe": float(sharpe),
        "threshold": float(threshold),
        "extreme_threshold": float(extreme_threshold),
        "n_trades": n_trades,
        "period_days": period_days,
        "flagged": flagged,
        "severity": severity,
        "explanation": " ".join(reasons),
    }


# ---------------------------------------------------------------------------
# 2. Monte Carlo trade-order permutation gate
# ---------------------------------------------------------------------------

#: Default reordering iterations. Matches the module-level default already
#: used by ``backtest.monte_carlo.run_monte_carlo``.
MC_PERMUTATION_ITERS: int = 1000

#: Percentile band the original stat should sit in to be judged "consistent
#: with reordering" (i.e., not a sequencing-luck outlier). Symmetric 5/95.
MC_PERMUTATION_BAND: tuple[float, float] = (5.0, 95.0)


@dataclass
class _SyntheticTrade:
    """Minimal duck-typed stand-in for ``backtest.trade_manager.Trade``.

    ``run_monte_carlo`` only reads ``trade.pnl`` off each element of
    ``result.trades`` — see ``backtest/monte_carlo.py``:
    ``pnls = np.array([t.pnl for t in result.trades], dtype=np.float64)``.
    Building a real ``Trade`` dataclass would require populating unused
    fields (entry/exit dates, prices, direction) purely to satisfy its
    constructor; this lighter stand-in is more honest about what is actually
    consumed and avoids importing ``backtest.trade_manager`` for a field that
    is never read.
    """

    pnl: float


@dataclass
class _SyntheticResult:
    """Minimal duck-typed stand-in for ``backtest.trade_manager.BacktestResult``.

    Only ``.trades`` is read by ``run_monte_carlo``.
    """

    trades: list[_SyntheticTrade]


def mc_permutation_gate(
    pnls: Sequence[float],
    n_iters: int = MC_PERMUTATION_ITERS,
    initial_capital: float = 10_000.0,
    symbol: str = "MES",
    seed: int = 42,
    band: tuple[float, float] = MC_PERMUTATION_BAND,
) -> dict[str, Any]:
    """Does the strategy's edge survive random reordering of its own trades?

    Shuffles the realized trade P&L sequence ``n_iters`` times (via the
    existing, tested ``backtest.monte_carlo.run_monte_carlo``) and reports
    where the REAL equity curve's Sharpe and max-drawdown sit within the
    distribution generated by every other possible ordering of the exact
    same trades.

    Note on ``final_capital`` / total return: with no slippage randomization
    (the default), the sum of a fixed trade list is invariant to order, so
    ``final_capital`` is identical across every permutation and uninformative
    here — the order-sensitive signal is in the annualized Sharpe (computed
    from per-step equity-relative returns) and max drawdown (a genuinely
    path-dependent statistic). This gate reports both.

    Args:
        pnls: per-trade P&L values (USD), in the ORIGINAL realized order.
        n_iters: number of reorderings.
        initial_capital: starting capital used to build the equity curve.
        symbol: instrument symbol (tick-value lookup only used if slippage
            is added upstream; unused here since slippage defaults to 0).
        seed: RNG seed for reproducibility.
        band: (low_pct, high_pct) — the original stat is judged "consistent
            with reordering" if it falls inside this percentile band of the
            permuted distribution. Falling outside (either direction) means
            the specific realized sequence looks unusually lucky or unusually
            unlucky relative to a random reordering of its own trades — worth
            a second look either way.

    Returns:
        dict with ``real_sharpe``, ``real_max_dd_pct``, their percentile rank
        within the permuted distribution, ``consistent_with_reordering``
        (bool), and ``explanation``. With fewer than 2 trades the test is
        undefined and returns a fail-closed verdict (too little evidence is
        no evidence).
    """
    from backtest.monte_carlo import run_monte_carlo

    pnl_list = [float(p) for p in pnls]
    n = len(pnl_list)
    if n < 2:
        return {
            "test": "mc_trade_order_permutation",
            "n_trades": n,
            "real_sharpe": None,
            "real_max_dd_pct": None,
            "sharpe_percentile": None,
            "max_dd_percentile": None,
            "consistent_with_reordering": False,
            "flagged": True,
            "explanation": f"Only {n} trade(s) supplied — need >= 2 to permute. Fail-closed.",
        }

    result = _SyntheticResult(trades=[_SyntheticTrade(pnl=p) for p in pnl_list])
    mc = run_monte_carlo(
        result,  # type: ignore[arg-type]  # duck-typed: run_monte_carlo only reads .trades[i].pnl
        n_simulations=n_iters,
        initial_capital=initial_capital,
        symbol=symbol,
        seed=seed,
    )

    real_sharpe = mc["original"]["sharpe_ratio"]
    real_dd = mc["original"]["max_drawdown_pct"]
    dist_sharpe = mc["distribution"]["sharpe_ratio"]
    dist_dd = mc["distribution"]["max_drawdown_pct"]

    # Percentile rank of the real stat within its own permuted null. Uses the
    # same percentile keys run_monte_carlo already computed (p5/p25/median/
    # p75/p95) rather than re-deriving the full distribution, so this stays
    # a thin interpretive layer, not a second simulation.
    def _rank_against_percentiles(value: float, dist: dict[str, float]) -> float:
        pts = [(5.0, dist["p5"]), (25.0, dist["p25"]), (50.0, dist["median"]),
               (75.0, dist["p75"]), (95.0, dist["p95"])]
        if value <= pts[0][1]:
            return 5.0
        if value >= pts[-1][1]:
            return 95.0
        for (p_lo, v_lo), (p_hi, v_hi) in zip(pts, pts[1:], strict=False):
            if v_lo <= value <= v_hi:
                if v_hi == v_lo:
                    return p_lo
                frac = (value - v_lo) / (v_hi - v_lo)
                return p_lo + frac * (p_hi - p_lo)
        return 50.0

    sharpe_pct = _rank_against_percentiles(real_sharpe, dist_sharpe)
    # Lower drawdown is "better"; rank it the same way but note that a very
    # LOW percentile here (original drawdown far below the reordering
    # distribution) is what "unusually lucky sequencing" looks like.
    dd_pct = _rank_against_percentiles(real_dd, dist_dd)

    low, high = band
    sharpe_in_band = low <= sharpe_pct <= high
    dd_in_band = low <= dd_pct <= high
    consistent = bool(sharpe_in_band and dd_in_band)

    reasons: list[str] = []
    if not sharpe_in_band:
        reasons.append(
            f"real Sharpe ({real_sharpe:.3f}) sits at the {sharpe_pct:.0f}th percentile of "
            f"the reordering null (outside [{low:.0f}, {high:.0f}]) — the realized trade "
            "sequence produced an unusually favorable or unfavorable Sharpe compared to "
            "other orderings of the exact same trades."
        )
    if not dd_in_band:
        reasons.append(
            f"real max drawdown ({real_dd:.2f}%) sits at the {dd_pct:.0f}th percentile of "
            f"the reordering null (outside [{low:.0f}, {high:.0f}])."
        )
    if consistent:
        reasons.append(
            "Real Sharpe and max drawdown both sit within the typical reordering range — "
            "no evidence the backtest's specific trade sequencing is doing unusual work."
        )

    return {
        "test": "mc_trade_order_permutation",
        "n_trades": n,
        "n_iters": n_iters,
        "real_sharpe": round(float(real_sharpe), 4),
        "real_max_dd_pct": round(float(real_dd), 4),
        "sharpe_percentile": round(sharpe_pct, 1),
        "max_dd_percentile": round(dd_pct, 1),
        "band": band,
        "consistent_with_reordering": consistent,
        "flagged": not consistent,
        "monte_carlo_verdict": mc["verdict"],
        "explanation": " ".join(reasons),
    }


# ---------------------------------------------------------------------------
# 3. Ljung-Box independence pre-check
# ---------------------------------------------------------------------------

#: Default number of lags for the Ljung-Box test. 10 is a common default for
#: daily-ish trade sequences; callers with a strong seasonality prior should
#: override.
LJUNG_BOX_DEFAULT_LAGS: int = 10

#: Significance level: reject "no autocorrelation" (H0) below this p-value.
LJUNG_BOX_ALPHA: float = 0.05


def ljung_box_independence_check(
    returns: Sequence[float],
    lags: int = LJUNG_BOX_DEFAULT_LAGS,
    alpha: float = LJUNG_BOX_ALPHA,
) -> dict[str, Any]:
    """Ljung-Box test for autocorrelation in a trade-return series.

    ``mc_permutation_gate`` (and ``analytics.permutation_test.permute_and_score``)
    build their null by reordering/sign-flipping trades independently — an
    i.i.d. assumption. Trend-following strategies in particular often have
    real serial correlation in trade outcomes (a winning trade increases the
    odds the next one, in the same regime, also wins). This test does not
    change the permutation p-value; it tells the caller whether that
    p-value needs an autocorrelation caveat attached.

    Citation: Ljung, G. M. and Box, G. E. P. (1978), "On a Measure of Lack of
    Fit in Time Series Models," Biometrika 65(2), 297-303.

    Args:
        returns: the trade-return (or P&L) series in chronological order.
        lags: number of lags to test jointly (Ljung-Box is a joint test over
            lags 1..``lags``).
        alpha: significance level. p_value < alpha => reject H0 (series is
            autocorrelated); p_value >= alpha => fail to reject (consistent
            with independence, which is what a permutation test needs).

    Returns:
        dict with ``lb_statistic``, ``p_value``, ``independent`` (bool — True
        means the i.i.d. assumption is NOT contradicted by this test),
        ``lags``, and ``explanation``. Requires >= ``lags + 2`` observations;
        with fewer, returns ``independent=None`` (undetermined, not a pass).
    """
    series = np.asarray(list(returns), dtype=np.float64)
    n = len(series)
    min_n = lags + 2
    if n < min_n:
        return {
            "test": "ljung_box_independence",
            "n": n,
            "lags": lags,
            "lb_statistic": None,
            "p_value": None,
            "independent": None,
            "alpha": alpha,
            "explanation": (
                f"Only {n} observations supplied, need >= {min_n} for {lags} lags. "
                "Result undetermined — do not treat as a pass."
            ),
        }

    from statsmodels.stats.diagnostic import acorr_ljungbox

    result = acorr_ljungbox(series, lags=[lags], return_df=True)
    lb_stat = float(result["lb_stat"].iloc[0])
    p_value = float(result["lb_pvalue"].iloc[0])
    independent = bool(p_value >= alpha)

    if independent:
        explanation = (
            f"p={p_value:.4f} >= alpha={alpha}: fail to reject the no-autocorrelation null "
            f"over {lags} lags. Consistent with the i.i.d. assumption a permutation test needs "
            "(does not prove independence, only fails to contradict it)."
        )
    else:
        explanation = (
            f"p={p_value:.4f} < alpha={alpha}: reject the no-autocorrelation null over "
            f"{lags} lags — this return series shows real serial correlation. Any permutation "
            "test p-value computed on it needs an explicit autocorrelation caveat; consider "
            "a block-permutation (backtest.bar_permute.get_block_permutation) or a "
            "moving-block bootstrap (backtest.monte_carlo.bootstrap_pf) instead of the plain "
            "i.i.d. shuffle."
        )

    return {
        "test": "ljung_box_independence",
        "n": n,
        "lags": lags,
        "lb_statistic": round(lb_stat, 4),
        "p_value": round(p_value, 6),
        "independent": independent,
        "alpha": alpha,
        "explanation": explanation,
    }


# ---------------------------------------------------------------------------
# 4. ADF stationarity pre-check
# ---------------------------------------------------------------------------

ADF_ALPHA: float = 0.05


def adf_stationarity_check(
    series: Sequence[float],
    alpha: float = ADF_ALPHA,
    regression: str = "c",
) -> dict[str, Any]:
    """Augmented Dickey-Fuller stationarity test for a price/return series.

    Before combining a new candidate signal with the live SMA/ATR system (or
    feeding a raw price level into any statistic that assumes stationarity —
    a rolling correlation, a z-score, a regression), check the series isn't
    a random walk / unit-root process silently violating that assumption.

    Citations: Dickey, D. A. and Fuller, W. A. (1979), "Distribution of the
    Estimators for Autoregressive Time Series with a Unit Root," JASA 74;
    augmented form (accounts for higher-order serial correlation): Said, S.
    E. and Dickey, D. A. (1984), "Testing for Unit Roots in
    Autoregressive-Moving Average Models of Unknown Order," Biometrika 71.

    Args:
        series: the price/return series to test.
        alpha: significance level. p_value < alpha => reject the unit-root
            null => series is stationary.
        regression: statsmodels ``adfuller`` regression spec — ``"c"``
            (constant, default; appropriate for a return/spread series that
            fluctuates around a nonzero mean), ``"ct"`` (constant + trend),
            or ``"n"`` (no constant, for a series already centered at 0).

    Returns:
        dict with ``adf_statistic``, ``p_value``, ``stationary`` (bool),
        ``critical_values`` (1%/5%/10%), ``used_lag``, ``nobs``, and
        ``explanation``. Requires >= 20 observations (ADF's own practical
        minimum for the lag-selection step to be meaningful); with fewer,
        returns ``stationary=None``.
    """
    values = np.asarray(list(series), dtype=np.float64)
    n = len(values)
    if n < 20:
        return {
            "test": "adf_stationarity",
            "n": n,
            "adf_statistic": None,
            "p_value": None,
            "stationary": None,
            "critical_values": None,
            "used_lag": None,
            "alpha": alpha,
            "explanation": f"Only {n} observations supplied, need >= 20. Result undetermined.",
        }

    from statsmodels.tsa.stattools import adfuller

    adf_stat, p_value, used_lag, nobs, crit_values, _icbest = adfuller(
        values, regression=regression, autolag="AIC"
    )
    stationary = bool(p_value < alpha)

    if stationary:
        explanation = (
            f"p={p_value:.4f} < alpha={alpha}: reject the unit-root null. Series is "
            "stationary — safe to combine with statistics that assume a stable mean/variance "
            "(rolling z-scores, mean-reversion signals, correlation with the SMA/ATR system)."
        )
    else:
        explanation = (
            f"p={p_value:.4f} >= alpha={alpha}: fail to reject the unit-root null. Series "
            "behaves like a random walk (non-stationary) — do not feed it directly into a "
            "mean-reversion signal or a rolling correlation without differencing/detrending "
            "first, or the result will silently violate the stationarity assumption."
        )

    return {
        "test": "adf_stationarity",
        "n": n,
        "regression": regression,
        "adf_statistic": round(float(adf_stat), 4),
        "p_value": round(float(p_value), 6),
        "stationary": stationary,
        "critical_values": {k: round(float(v), 4) for k, v in crit_values.items()},
        "used_lag": int(used_lag),
        "nobs": int(nobs),
        "alpha": alpha,
        "explanation": explanation,
    }


# ---------------------------------------------------------------------------
# 5. Diebold-Mariano forecast/edge comparison test
# ---------------------------------------------------------------------------

DM_ALPHA: float = 0.05


def diebold_mariano_test(
    candidate_returns: Sequence[float],
    baseline_returns: Sequence[float],
    h: int = 1,
    alpha: float = DM_ALPHA,
    power: int = 1,
) -> dict[str, Any]:
    """Diebold-Mariano test: is a candidate signal's edge different from a baseline's?

    Tests whether two aligned return/forecast-error series have significantly
    different average loss, using the Harvey-Leybourne-Newbold (1997)
    small-sample t-correction and a Newey-West-style HAC variance estimate
    for the loss differential (accounts for serial correlation up to
    ``h - 1`` lags, matching the forecast horizon).

    Loss is defined as ``-return`` (so lower loss = higher return) unless
    ``power=2``, which uses squared negative return — closer to a classic
    forecast-error DM test and more sensitive to large adverse moves. Both
    series must be pre-aligned (same trades/bars, same order) before calling.

    Citations: Diebold, F.X. and Mariano, R.S. (1995), "Comparing Predictive
    Accuracy," Journal of Business & Economic Statistics 13(3), 253-263.
    Small-sample correction: Harvey, D., Leybourne, S., and Newbold, P.
    (1997), "Testing the Equality of Prediction Mean Squared Errors,"
    International Journal of Forecasting 13(2), 281-291.

    Args:
        candidate_returns: candidate signal's aligned return series.
        baseline_returns: baseline (e.g. live SMA/ATR) strategy's aligned
            return series. Must be the same length as ``candidate_returns``.
        h: forecast horizon in steps; controls how many autocorrelation lags
            (``h - 1``) are included in the HAC variance estimate.
        alpha: significance level for the two-sided test.
        power: 1 for a mean-return-differential loss (``-return``), 2 for a
            squared loss (``-return**2`` — penalizes large adverse moves
            more; closer to the classic forecast-MSE formulation).

    Returns:
        dict with ``dm_statistic``, ``p_value``, ``significant`` (bool),
        ``better`` (``"candidate"`` / ``"baseline"`` / ``"tie"`` — which
        series had the lower mean loss when ``significant`` is True, else
        ``"tie"``), and ``explanation``. Requires >= 10 aligned observations;
        with fewer, or mismatched lengths, returns a fail-closed verdict.
    """
    cand = np.asarray(list(candidate_returns), dtype=np.float64)
    base = np.asarray(list(baseline_returns), dtype=np.float64)

    if len(cand) != len(base):
        return {
            "test": "diebold_mariano",
            "n": None,
            "dm_statistic": None,
            "p_value": None,
            "significant": False,
            "better": "tie",
            "explanation": (
                f"Series length mismatch (candidate={len(cand)}, baseline={len(base)}) — "
                "both must be pre-aligned to the same trades/bars. Fail-closed."
            ),
        }

    T = len(cand)
    if T < 10:
        return {
            "test": "diebold_mariano",
            "n": T,
            "dm_statistic": None,
            "p_value": None,
            "significant": False,
            "better": "tie",
            "explanation": f"Only {T} aligned observations supplied, need >= 10. Fail-closed.",
        }

    if power == 2:
        loss_cand = -(cand**2)  # squared-magnitude penalty on negative returns
        loss_base = -(base**2)
    else:
        loss_cand = -cand
        loss_base = -base

    d = loss_cand - loss_base  # loss differential; d < 0 on average => candidate has lower loss
    d_mean = float(d.mean())

    # Newey-West-style HAC variance of the mean, with (h - 1) lags.
    gamma0 = float(np.var(d, ddof=0))
    var_d = gamma0
    for lag in range(1, h):
        if lag >= T:
            break
        cov = float(np.cov(d[lag:], d[:-lag], ddof=0)[0, 1])
        var_d += 2.0 * (1.0 - lag / h) * cov
    var_d = max(var_d, 1e-12) / T  # variance of the SAMPLE MEAN; floor avoids div-by-zero

    dm_raw = d_mean / float(np.sqrt(var_d))

    # Harvey-Leybourne-Newbold small-sample correction.
    hln_factor = float(np.sqrt((T + 1 - 2 * h + h * (h - 1) / T) / T))
    dm_stat = dm_raw * hln_factor

    from scipy import stats as sp_stats

    p_value = float(2.0 * (1.0 - sp_stats.t.cdf(abs(dm_stat), df=T - 1)))
    significant = bool(p_value < alpha)

    if not significant:
        better = "tie"
        explanation = (
            f"p={p_value:.4f} >= alpha={alpha}: cannot reject equal predictive/edge accuracy. "
            "No statistical basis to prefer the candidate over the baseline (or vice versa) — "
            "do not swap in the candidate on this evidence alone."
        )
    elif d_mean < 0:
        better = "candidate"
        explanation = (
            f"p={p_value:.4f} < alpha={alpha}: candidate has significantly LOWER mean loss "
            "(higher edge) than the baseline over this aligned sample."
        )
    else:
        better = "baseline"
        explanation = (
            f"p={p_value:.4f} < alpha={alpha}: baseline has significantly LOWER mean loss "
            "(higher edge) than the candidate over this aligned sample — do not swap in the "
            "candidate."
        )

    return {
        "test": "diebold_mariano",
        "n": T,
        "h": h,
        "power": power,
        "dm_statistic": round(dm_stat, 4),
        "p_value": round(p_value, 6),
        "significant": significant,
        "better": better,
        "alpha": alpha,
        "explanation": explanation,
    }
