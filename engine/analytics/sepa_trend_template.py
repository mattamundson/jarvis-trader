"""
JARVIS TRADER — SEPA trend template (Minervini)
================================================
Classifier implementing Mark Minervini's Stage 2 Uptrend Template from
*Trade Like a Stock Market Wizard* (McGraw-Hill, 2013). Produces a score
in ``[0.0, 1.0]`` representing the fraction of the 8 criteria currently
satisfied, plus a per-criterion breakdown so the debate stage can cite
specific failures in its reasoning.

Pattern source
--------------
Adapted from himself65/finance-skills ``sepa-strategy`` skill
(github.com/himself65/finance-skills, MIT). The original skill targets
equities; this port adapts the criteria for futures by:

  * Making the relative-strength criterion (IBD RS ≥ 70) optional and
    computed against a supplied benchmark series rather than the S&P 500.
  * Keeping the 50/150/200 SMA structure unchanged — trend alignment is
    timeframe-agnostic and works the same on continuous futures contracts.
  * Returning a dataclass with explicit pass/fail flags per criterion
    instead of the original boolean-list so callers (``debate.py``,
    ``regime_classifier``) can surface *which* criteria failed.

Criteria (exact Minervini wording in docstring of each helper)
--------------------------------------------------------------
  1. Price > 150-day SMA AND Price > 200-day SMA
  2. 150-day SMA > 200-day SMA
  3. 200-day SMA trending up for at least 1 month (~20 bars)
  4. 50-day SMA > 150-day SMA AND 50-day SMA > 200-day SMA
  5. Price > 50-day SMA
  6. Price ≥ 30% above 52-week low
  7. Price within 25% of 52-week high
  8. Relative strength ≥ 70 vs. benchmark (optional; skipped if None)

Score
-----
``score = criteria_passed / criteria_checked`` (counts only criteria that
had enough data to evaluate — so a 6-month series that can't compute the
200-SMA yields a score over the 6 criteria it *can* check).

Usage
-----
    from analytics.sepa_trend_template import evaluate_sepa

    result = evaluate_sepa(close_series, high_series, low_series)
    if result.score >= 0.75:
        # Stage 2 uptrend — bull bias, lean into trend-following debate
    elif result.score <= 0.25:
        # Not in uptrend — consider range or reversal playbook

License
-------
Source skill is MIT. Pattern (not code) ported. Attribution here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class SEPAResult:
    """Per-criterion outcome of a SEPA trend-template evaluation.

    ``score`` is ``passed / evaluated`` over criteria that had sufficient
    data. A criterion set to ``None`` (rather than True/False) means the
    series was too short to evaluate it — it does not count toward the
    score denominator.
    """

    c1_price_above_long_smas: Optional[bool] = None
    c2_sma150_above_sma200: Optional[bool] = None
    c3_sma200_uptrending: Optional[bool] = None
    c4_sma50_above_long_smas: Optional[bool] = None
    c5_price_above_sma50: Optional[bool] = None
    c6_above_52wk_low_by_pct: Optional[bool] = None
    c7_within_52wk_high_pct: Optional[bool] = None
    c8_relative_strength_ge_70: Optional[bool] = None

    score: float = 0.0
    evaluated_count: int = 0
    passed_count: int = 0
    reasons_failed: list[str] = field(default_factory=list)
    reasons_skipped: list[str] = field(default_factory=list)

    def is_stage_2_uptrend(self, threshold: float = 0.75) -> bool:
        """Convenience: True iff ``score >= threshold`` (default 0.75)."""
        return self.score >= threshold


# ---------------------------------------------------------------------------
# Core evaluator
# ---------------------------------------------------------------------------


def _last_valid(series: pd.Series) -> Optional[float]:
    if series is None or series.empty:
        return None
    last = series.dropna()
    if last.empty:
        return None
    return float(last.iloc[-1])


def evaluate_sepa(
    close: pd.Series,
    high: Optional[pd.Series] = None,
    low: Optional[pd.Series] = None,
    benchmark_close: Optional[pd.Series] = None,
    *,
    sma_fast: int = 50,
    sma_mid: int = 150,
    sma_slow: int = 200,
    uptrend_lookback: int = 20,
    above_low_pct: float = 0.30,
    within_high_pct: float = 0.25,
    rs_threshold: float = 70.0,
) -> SEPAResult:
    """Evaluate Minervini's 8-criterion Stage 2 uptrend template.

    Args:
        close: Close-price series (chronological, no gaps required — the
            rolling ops tolerate gaps, but length must be at least
            ``sma_slow`` bars for all criteria to be evaluated).
        high: High-price series, used for the 52-week high criterion.
            If None, the 52-week high is computed from ``close`` instead.
        low: Low-price series, used for the 52-week low criterion.
            If None, falls back to ``close``.
        benchmark_close: Series of the same length as ``close`` for a
            benchmark (e.g. SPY for equities, CL1/NQ1 continuous contract
            for futures). If None, criterion 8 is skipped.
        sma_fast, sma_mid, sma_slow: Moving-average periods. Defaults
            match Minervini's 50/150/200 specification.
        uptrend_lookback: Bars over which the slow SMA must be rising for
            criterion 3. Default 20 (~1 month of daily bars).
        above_low_pct: Minimum fraction above 52-week low for criterion 6.
        within_high_pct: Maximum fraction below 52-week high for criterion 7.
        rs_threshold: IBD-style relative-strength percentile for criterion 8.

    Returns:
        A ``SEPAResult`` with per-criterion True/False/None and a summary
        score. Criteria with insufficient data are flagged in
        ``reasons_skipped``; failed criteria are flagged in
        ``reasons_failed`` with a short description.
    """
    if close is None or len(close) == 0:
        return SEPAResult(score=0.0, reasons_skipped=["close series is empty"])

    high = high if high is not None else close
    low = low if low is not None else close

    result = SEPAResult()

    sma_50 = close.rolling(sma_fast).mean()
    sma_150 = close.rolling(sma_mid).mean()
    sma_200 = close.rolling(sma_slow).mean()

    price = _last_valid(close)
    ma50 = _last_valid(sma_50)
    ma150 = _last_valid(sma_150)
    ma200 = _last_valid(sma_200)

    # C1 — price above both long SMAs
    if price is None or ma150 is None or ma200 is None:
        result.reasons_skipped.append(f"c1 needs {sma_mid}/{sma_slow} bars")
    else:
        result.c1_price_above_long_smas = price > ma150 and price > ma200
        if not result.c1_price_above_long_smas:
            result.reasons_failed.append(
                f"c1: price {price:.2f} not above both SMA{sma_mid} {ma150:.2f} and SMA{sma_slow} {ma200:.2f}"
            )

    # C2 — 150 SMA above 200 SMA
    if ma150 is None or ma200 is None:
        result.reasons_skipped.append(f"c2 needs {sma_slow} bars")
    else:
        result.c2_sma150_above_sma200 = ma150 > ma200
        if not result.c2_sma150_above_sma200:
            result.reasons_failed.append(
                f"c2: SMA{sma_mid} {ma150:.2f} not above SMA{sma_slow} {ma200:.2f}"
            )

    # C3 — 200 SMA rising over the uptrend lookback
    if len(sma_200.dropna()) < uptrend_lookback + 1:
        result.reasons_skipped.append(f"c3 needs {sma_slow + uptrend_lookback} bars")
    else:
        tail = sma_200.dropna().iloc[-(uptrend_lookback + 1):]
        result.c3_sma200_uptrending = float(tail.iloc[-1]) > float(tail.iloc[0])
        if not result.c3_sma200_uptrending:
            result.reasons_failed.append(
                f"c3: SMA{sma_slow} not rising over {uptrend_lookback} bars"
            )

    # C4 — 50 SMA above both long SMAs
    if ma50 is None or ma150 is None or ma200 is None:
        result.reasons_skipped.append(f"c4 needs {sma_slow} bars")
    else:
        result.c4_sma50_above_long_smas = ma50 > ma150 and ma50 > ma200
        if not result.c4_sma50_above_long_smas:
            result.reasons_failed.append(
                f"c4: SMA{sma_fast} {ma50:.2f} not above both SMA{sma_mid} {ma150:.2f} and SMA{sma_slow} {ma200:.2f}"
            )

    # C5 — price above 50 SMA
    if price is None or ma50 is None:
        result.reasons_skipped.append(f"c5 needs {sma_fast} bars")
    else:
        result.c5_price_above_sma50 = price > ma50
        if not result.c5_price_above_sma50:
            result.reasons_failed.append(
                f"c5: price {price:.2f} not above SMA{sma_fast} {ma50:.2f}"
            )

    # C6 — price at least above_low_pct above 52-week low
    # 52 trading weeks ≈ 252 bars on daily; we use whatever we have.
    window_52w = min(252, len(close))
    if window_52w < 20:
        result.reasons_skipped.append("c6 needs at least 20 bars of history")
    else:
        low_tail = low.iloc[-window_52w:].dropna()
        if low_tail.empty or price is None:
            result.reasons_skipped.append("c6 low series empty")
        else:
            low_52w = float(low_tail.min())
            if low_52w <= 0:
                result.reasons_skipped.append("c6 non-positive low")
            else:
                pct_above = (price - low_52w) / low_52w
                result.c6_above_52wk_low_by_pct = pct_above >= above_low_pct
                if not result.c6_above_52wk_low_by_pct:
                    result.reasons_failed.append(
                        f"c6: only {pct_above:.1%} above 52wk low {low_52w:.2f} (need {above_low_pct:.0%})"
                    )

    # C7 — price within within_high_pct of 52-week high
    if window_52w < 20:
        result.reasons_skipped.append("c7 needs at least 20 bars of history")
    else:
        high_tail = high.iloc[-window_52w:].dropna()
        if high_tail.empty or price is None:
            result.reasons_skipped.append("c7 high series empty")
        else:
            high_52w = float(high_tail.max())
            if high_52w <= 0:
                result.reasons_skipped.append("c7 non-positive high")
            else:
                pct_below = (high_52w - price) / high_52w
                result.c7_within_52wk_high_pct = pct_below <= within_high_pct
                if not result.c7_within_52wk_high_pct:
                    result.reasons_failed.append(
                        f"c7: {pct_below:.1%} below 52wk high {high_52w:.2f} (need ≤ {within_high_pct:.0%})"
                    )

    # C8 — relative strength vs benchmark (optional)
    if benchmark_close is None:
        result.reasons_skipped.append("c8 no benchmark supplied")
    else:
        rs = _relative_strength_percentile(close, benchmark_close)
        if rs is None:
            result.reasons_skipped.append("c8 insufficient benchmark history")
        else:
            result.c8_relative_strength_ge_70 = rs >= rs_threshold
            if not result.c8_relative_strength_ge_70:
                result.reasons_failed.append(
                    f"c8: relative strength {rs:.1f} below {rs_threshold:.0f}"
                )

    # Score
    evaluated = [
        v
        for v in (
            result.c1_price_above_long_smas,
            result.c2_sma150_above_sma200,
            result.c3_sma200_uptrending,
            result.c4_sma50_above_long_smas,
            result.c5_price_above_sma50,
            result.c6_above_52wk_low_by_pct,
            result.c7_within_52wk_high_pct,
            result.c8_relative_strength_ge_70,
        )
        if v is not None
    ]
    result.evaluated_count = len(evaluated)
    result.passed_count = sum(1 for v in evaluated if v)
    result.score = (
        result.passed_count / result.evaluated_count
        if result.evaluated_count > 0
        else 0.0
    )
    return result


# ---------------------------------------------------------------------------
# Relative strength helper
# ---------------------------------------------------------------------------


def _relative_strength_percentile(
    close: pd.Series,
    benchmark: pd.Series,
    lookback: int = 252,
) -> Optional[float]:
    """Approximate IBD-style RS percentile in [0, 100].

    IBD's RS uses a weighted 3/6/9/12-month return composite. We compute
    a simplified version: the last-year total return of ``close`` ranked
    against the return of ``benchmark`` using the ratio of their
    cumulative returns scaled to [0, 100] via a monotonic mapping:

        rs_ratio = (1 + close_return) / (1 + benchmark_return)
        percentile = 100 * clip(rs_ratio - threshold_low, 0, threshold_range)
                                / threshold_range

    where the ``threshold_low/range`` are calibrated so that outperforming
    the benchmark by 20% maps to ~80, matching IBD's broadly recognized
    "strong RS" zone. This is intentionally coarse — it is a *regime*
    signal, not an exact IBD replica.
    """
    close_tail = close.dropna().iloc[-lookback:] if len(close) >= 20 else pd.Series(dtype=float)
    bench_tail = (
        benchmark.dropna().iloc[-lookback:] if len(benchmark) >= 20 else pd.Series(dtype=float)
    )
    if close_tail.empty or bench_tail.empty:
        return None
    if float(close_tail.iloc[0]) <= 0 or float(bench_tail.iloc[0]) <= 0:
        return None

    close_ret = float(close_tail.iloc[-1]) / float(close_tail.iloc[0]) - 1.0
    bench_ret = float(bench_tail.iloc[-1]) / float(bench_tail.iloc[0]) - 1.0
    rs_ratio = (1.0 + close_ret) / (1.0 + bench_ret)

    # Calibrate: rs_ratio of 1.0 -> 50; 1.20 -> 80; 0.80 -> 20; clipped to [0, 100].
    threshold_low = 0.80
    threshold_range = 0.40  # [0.80, 1.20]
    clipped = np.clip(rs_ratio - threshold_low, 0.0, threshold_range)
    return float(clipped / threshold_range * 100.0)
