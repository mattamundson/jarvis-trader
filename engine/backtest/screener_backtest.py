"""
JARVIS TRADER — Pine Screener forward-return backtest
=====================================================
Validates whether the GreenStar2-style screener filters
(``analytics/screener_filters.py``) actually select better-performing names, by
measuring the forward return of bars that pass the filter versus bars that are
rejected.

Method
------
For every symbol and every spaced decision bar ``i`` with enough history and
enough room ahead:

  1. Compute the screener metrics from ``df.iloc[: i + 1]`` only (point-in-time;
     never reads bars after ``i``).
  2. Apply :func:`analytics.screener_filters.passes` to bucket the decision as
     *pass* or *reject*.
  3. Record the forward return ``close[i + horizon] / close[i] - 1`` as the
     evaluation label.

The forward return is a label only — it is never fed back into the decision (see
``.claude/rules/testing.md`` "Time travel is cheating"). The harness reports the
mean forward return and hit-rate for each bucket and their difference (*edge*).
A positive edge means the filter preferentially selected names that went on to
outperform over the test window.

This is a screening-quality diagnostic, not a tradable strategy backtest: it has
no position sizing, costs, or stops. A positive edge is necessary-but-not-
sufficient evidence; promote a configuration only after the usual gate-v2 /
MCPT discipline on an actual entry rule built from it.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Optional

import pandas as pd

from analytics.screener_filters import (
    ScreenerFilters,
    compute_metrics,
    passes,
)

logger = logging.getLogger(__name__)

# Minervini's 200-SMA + 1-month uptrend needs ~210 daily bars before any metric
# is fully evaluable; default decision bars start past that warmup.
DEFAULT_MIN_HISTORY = 210
DEFAULT_HORIZON = 5
DEFAULT_STEP = 5


def forward_return(close: pd.Series, idx: int, horizon: int) -> float:
    """Return ``close[idx + horizon] / close[idx] - 1``, or NaN if out of range."""
    if idx < 0 or idx + horizon >= len(close):
        return float("nan")
    base = float(close.iloc[idx])
    future = float(close.iloc[idx + horizon])
    if base <= 0:
        return float("nan")
    return future / base - 1.0


@dataclass
class BucketStats:
    """Forward-return statistics for one bucket (pass or reject)."""

    n: int = 0
    mean_fwd_return: float = float("nan")
    median_fwd_return: float = float("nan")
    hit_rate: float = float("nan")  # fraction with strictly positive forward return

    @classmethod
    def from_returns(cls, returns: list[float]) -> "BucketStats":
        s = pd.Series([r for r in returns if pd.notna(r)], dtype=float)
        if len(s) == 0:
            return cls()
        return cls(
            n=int(len(s)),
            mean_fwd_return=float(s.mean()),
            median_fwd_return=float(s.median()),
            hit_rate=float((s > 0).mean()),
        )


@dataclass
class ScreenerBacktestResult:
    """Aggregate outcome of a screener forward-return backtest."""

    horizon: int
    step: int
    symbols: list[str] = field(default_factory=list)
    n_decisions: int = 0
    passed: BucketStats = field(default_factory=BucketStats)
    rejected: BucketStats = field(default_factory=BucketStats)

    @property
    def edge(self) -> float:
        """Mean forward-return advantage of passing bars over rejected bars."""
        if pd.isna(self.passed.mean_fwd_return) or pd.isna(self.rejected.mean_fwd_return):
            return float("nan")
        return self.passed.mean_fwd_return - self.rejected.mean_fwd_return

    def as_dict(self) -> dict:
        d = asdict(self)
        d["edge"] = self.edge
        return d


def run_screener_backtest(
    bars_by_symbol: dict[str, pd.DataFrame],
    filters: Optional[ScreenerFilters] = None,
    *,
    horizon: int = DEFAULT_HORIZON,
    step: int = DEFAULT_STEP,
    min_history: int = DEFAULT_MIN_HISTORY,
) -> ScreenerBacktestResult:
    """Backtest the screener filters across a panel of OHLCV frames.

    Args:
        bars_by_symbol: ``{symbol: ohlcv_frame}``. Each frame needs lowercase
            ``open/high/low/close/volume`` columns in chronological order.
        filters: thresholds to evaluate; defaults to :class:`ScreenerFilters`.
        horizon: bars ahead used for the forward-return label.
        step: spacing between decision bars (reduces autocorrelation / runtime).
        min_history: first decision bar index (warmup for the slow SMAs).

    Returns:
        A :class:`ScreenerBacktestResult` with pass/reject bucket stats and edge.
    """
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    if step < 1:
        raise ValueError("step must be >= 1")

    filters = filters or ScreenerFilters()
    pass_returns: list[float] = []
    reject_returns: list[float] = []
    n_decisions = 0
    used_symbols: list[str] = []

    for symbol, df in bars_by_symbol.items():
        if df is None or len(df) <= min_history + horizon:
            continue
        close = df["close"]
        last_decision = len(df) - horizon - 1
        used_symbols.append(symbol)
        for i in range(min_history, last_decision + 1, step):
            window = df.iloc[: i + 1]
            metrics = compute_metrics(window, symbol=symbol)
            verdict = passes(metrics, filters)
            fwd = forward_return(close, i, horizon)
            if pd.isna(fwd):
                continue
            n_decisions += 1
            (pass_returns if verdict.passed else reject_returns).append(fwd)

    return ScreenerBacktestResult(
        horizon=horizon,
        step=step,
        symbols=used_symbols,
        n_decisions=n_decisions,
        passed=BucketStats.from_returns(pass_returns),
        rejected=BucketStats.from_returns(reject_returns),
    )


def _fetch_daily(symbol: str, period: str) -> "pd.DataFrame | None":  # pragma: no cover — network
    """yfinance daily-bar fetch for the CLI runner (lazy import)."""
    import yfinance as yf

    raw = yf.download(symbol, period=period, interval="1d", auto_adjust=True, progress=False)
    if raw is None or len(raw) == 0:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw = raw.rename(columns=str.lower)
    cols = ["open", "high", "low", "close", "volume"]
    if not all(c in raw.columns for c in cols):
        return None
    return raw[cols].dropna()


def main() -> None:  # pragma: no cover — thin CLI
    """CLI: backtest the screener over a list of symbols via yfinance.

    Example:
        python -m backtest.screener_backtest AAPL MSFT NVDA --horizon 5 --period 3y
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Pine Screener forward-return backtest")
    parser.add_argument("symbols", nargs="+", help="Ticker symbols to screen")
    parser.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    parser.add_argument("--step", type=int, default=DEFAULT_STEP)
    parser.add_argument("--period", default="3y", help="yfinance history period")
    args = parser.parse_args()

    bars = {s: _fetch_daily(s, args.period) for s in args.symbols}
    bars = {s: df for s, df in bars.items() if df is not None}
    result = run_screener_backtest(bars, horizon=args.horizon, step=args.step)
    print(json.dumps(result.as_dict(), indent=2, default=str))


if __name__ == "__main__":  # pragma: no cover
    main()
