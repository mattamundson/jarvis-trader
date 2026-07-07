"""QuantStats metrics computation for the /reports/quantstats endpoint.

Uses quantstats scalar functions only — no HTML report generation.
Annualisation assumes 252 trading days (standard for daily returns series).
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Number of trading days per year used for annualisation everywhere in this module.
_PERIODS_PER_YEAR = 252

# Required keys in every response dict — null-filled on empty input.
_REQUIRED_KEYS = (
    "n_trades",
    "start_date",
    "end_date",
    "source",
    "sortino",
    "sharpe",
    "calmar",
    "max_dd",
    "max_dd_duration_days",
    "win_rate",
    "profit_factor",
    "monthly_returns",
    "rolling_sharpe_30d",
    # Extended suite (audit F-13, 2026-06-11) — additive, all nullable
    "ulcer_index",
    "ulcer_perf_index",
    "gain_to_pain",
    "common_sense_ratio",
    "tail_ratio",
    "skew",
    "kurtosis",
    "recovery_factor",
    "cpc_index",
    "r_squared",
    "cagr",
    "exposure",
    "consecutive_losses",
    "outlier_loss_ratio",
    "avg_win",
    "avg_loss",
    "volatility_ann",
    "var_95",
    "cvar_95",
    "kelly_criterion",
    "risk_of_ruin",
)


def _null_shell(
    *, source: str, n_trades: int, start_date: str | None, end_date: str | None
) -> dict:
    """Return the response shape with all metric fields set to null."""
    return {
        "n_trades": n_trades,
        "start_date": start_date,
        "end_date": end_date,
        "source": source,
        "sortino": None,
        "sharpe": None,
        "calmar": None,
        "max_dd": None,
        "max_dd_duration_days": None,
        "win_rate": None,
        "profit_factor": None,
        "monthly_returns": {},
        "rolling_sharpe_30d": [],
        "ulcer_index": None,
        "ulcer_perf_index": None,
        "gain_to_pain": None,
        "common_sense_ratio": None,
        "tail_ratio": None,
        "skew": None,
        "kurtosis": None,
        "recovery_factor": None,
        "cpc_index": None,
        "r_squared": None,
        "cagr": None,
        "exposure": None,
        "consecutive_losses": None,
        "outlier_loss_ratio": None,
        "avg_win": None,
        "avg_loss": None,
        "volatility_ann": None,
        "var_95": None,
        "cvar_95": None,
        "kelly_criterion": None,
        "risk_of_ruin": None,
    }


def _monthly_returns(daily_returns: pd.Series) -> dict[str, float]:
    """Aggregate daily returns into YYYY-MM keyed monthly returns.

    Monthly return = compound product of daily factors minus 1.
    """
    if daily_returns.empty:
        return {}
    monthly = (1 + daily_returns).resample("ME").prod() - 1
    return {dt.strftime("%Y-%m"): round(float(v), 6) for dt, v in monthly.items()}


def _rolling_sharpe_30d(daily_returns: pd.Series) -> list[dict]:
    """30-day rolling annualised Sharpe, one entry per date.

    Returns an empty list when the series is shorter than 30 observations.
    Entries with NaN value (the warmup period) are excluded.
    """
    if daily_returns.empty or len(daily_returns) < 2:
        return []

    try:
        import quantstats as qs

        rs: pd.Series = qs.stats.rolling_sharpe(
            daily_returns,
            rf=0.0,
            rolling_period=30,
            annualize=True,
            periods_per_year=_PERIODS_PER_YEAR,
        )
    except Exception:
        # Fallback: manual rolling Sharpe
        roll_mean = daily_returns.rolling(30).mean()
        roll_std = daily_returns.rolling(30).std()
        rs = (roll_mean / roll_std) * np.sqrt(_PERIODS_PER_YEAR)

    valid = rs.dropna().replace([np.inf, -np.inf], np.nan).dropna()
    return [
        {"date": dt.strftime("%Y-%m-%d"), "value": round(float(v), 6)} for dt, v in valid.items()
    ]


def _load_pnl_series(
    db_path: str,
    run_id: str | None,
    days: int,
) -> tuple[pd.Series, str, int, str, str]:
    """Load a daily returns Series from the database.

    Preference order:
      1. ``pnl_snapshots`` — already daily; uses ``portfolio_equity`` to
         derive returns (equity-based, avoids double-counting).
      2. ``paper_trades`` fallback — aggregates ``pnl`` by exit date.

    Returns
    -------
    (daily_returns, source, n_trades, start_date, end_date)
    start_date / end_date are ISO "YYYY-MM-DD" strings.
    """
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff = cutoff_dt.strftime("%Y-%m-%d")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # --- pnl_snapshots (preferred) ---
        try:
            snap_rows = conn.execute(
                "SELECT date, daily_pnl, portfolio_equity FROM pnl_snapshots "
                "WHERE date >= ? ORDER BY date ASC",
                (cutoff,),
            ).fetchall()
        except sqlite3.OperationalError:
            snap_rows = []

        if snap_rows:
            df = pd.DataFrame([dict(r) for r in snap_rows])
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").set_index("date")

            # Prefer equity-curve returns; fall back to daily_pnl if equity missing/zero.
            if "portfolio_equity" in df.columns and df["portfolio_equity"].gt(0).any():
                equity = df["portfolio_equity"].replace(0, np.nan).ffill()
                returns = equity.pct_change().dropna()
            else:
                # Use daily_pnl as a dollar-return series normalised by a $10k base.
                base = 10_000.0
                returns = (df["daily_pnl"] / base).dropna()

            n_trades = len(returns)
            start = returns.index.min().strftime("%Y-%m-%d") if n_trades else cutoff
            end = returns.index.max().strftime("%Y-%m-%d") if n_trades else cutoff
            return returns, "pnl_snapshots", n_trades, start, end

        # --- paper_trades fallback ---
        try:
            query = (
                "SELECT exit_time, pnl FROM paper_trades "
                "WHERE status = 'closed' AND exit_time >= ? "
            )
            params: tuple = (cutoff,)
            if run_id:
                query += "AND notes LIKE ? "
                params = (cutoff, f"%{run_id}%")
            query += "ORDER BY exit_time ASC"
            trade_rows = conn.execute(query, params).fetchall()
        except sqlite3.OperationalError:
            trade_rows = []

        if not trade_rows:
            # No data at all — return empty Series
            return pd.Series(dtype=float), "paper_trades", 0, cutoff, cutoff

        df = pd.DataFrame([dict(r) for r in trade_rows])
        df["exit_date"] = pd.to_datetime(df["exit_time"]).dt.normalize()

        # Aggregate pnl by day; normalise against $10k base.
        daily_pnl = df.groupby("exit_date")["pnl"].sum()
        base = 10_000.0
        returns = (daily_pnl / base).sort_index()
        n_trades = len(trade_rows)
        start = returns.index.min().strftime("%Y-%m-%d") if n_trades else cutoff
        end = returns.index.max().strftime("%Y-%m-%d") if n_trades else cutoff
        return returns, "paper_trades", n_trades, start, end



def _equity_curve_r_squared(returns: pd.Series) -> float | None:
    """R-squared of the cumulative equity curve against a linear time trend.

    High value = systematic drift (smooth equity curve); low = erratic.
    Manual implementation: qs.stats.r_squared requires a benchmark series,
    which is not what the linear-consistency diagnostic wants.
    """
    try:
        if len(returns) < 3:
            return None
        curve = (1 + returns).cumprod().to_numpy(dtype=float)
        x = np.arange(len(curve), dtype=float)
        corr = np.corrcoef(x, curve)[0, 1]
        if not np.isfinite(corr):
            return None
        return float(corr**2)
    except Exception:
        return None


def compute_quantstats_metrics(
    daily_returns: pd.Series,
    *,
    source: str,
) -> dict:
    """Compute the QuantStats metrics blob from a daily returns Series.

    Parameters
    ----------
    daily_returns:
        Daily return values (fractional, e.g. 0.01 = +1%).
        Index must be a DatetimeIndex.
    source:
        "pnl_snapshots" or "paper_trades" — passed through to the response.

    Returns
    -------
    dict matching the locked JSON response shape.  Every metric field is
    ``null`` when ``daily_returns`` is empty.

    Caveats
    -------
    - Annualisation factor: 252 trading days throughout.
    - ``profit_factor``: QuantStats defines it as gross_profit / |gross_loss|.
      When there are no losing days the gross_loss denominator is 0 and
      profit_factor is returned as ``null`` (rather than ``inf``).
    - ``max_dd_duration_days``: longest single drawdown episode in calendar
      days from the ``drawdown_details`` DataFrame; ``null`` on empty series.
    """
    n_trades = 0  # populated by caller via .update(); set 0 as placeholder
    start_date = None
    end_date = None

    if daily_returns.empty or daily_returns.isna().all():
        return _null_shell(
            source=source, n_trades=n_trades, start_date=start_date, end_date=end_date
        )

    try:
        import quantstats as qs
    except ImportError as exc:
        raise RuntimeError("quantstats is not installed in this venv") from exc

    # Ensure clean float series without NaN/inf
    returns = daily_returns.replace([np.inf, -np.inf], np.nan).dropna()

    if returns.empty:
        return _null_shell(
            source=source, n_trades=n_trades, start_date=start_date, end_date=end_date
        )

    def _safe(fn, *args, **kwargs):
        """Run a qs scalar function; return None on any error or non-finite result."""
        try:
            val = fn(*args, **kwargs)
            if isinstance(val, pd.Series):
                val = val.iloc[-1]
            if val is None or (isinstance(val, float) and not np.isfinite(val)):
                return None
            return float(val)
        except Exception:
            return None

    # Scalar metrics
    sortino = _safe(qs.stats.sortino, returns, rf=0.0, periods=_PERIODS_PER_YEAR, annualize=True)
    sharpe = _safe(qs.stats.sharpe, returns, rf=0.0, periods=_PERIODS_PER_YEAR, annualize=True)
    calmar = _safe(qs.stats.calmar, returns, periods=_PERIODS_PER_YEAR)
    max_dd = _safe(qs.stats.max_drawdown, returns)
    win_rate = _safe(qs.stats.win_rate, returns)

    # profit_factor: guard against inf (no-losing-day case)
    try:
        pf_raw = qs.stats.profit_factor(returns)
        if isinstance(pf_raw, pd.Series):
            pf_raw = pf_raw.iloc[-1]
        profit_factor = float(pf_raw) if (pf_raw is not None and np.isfinite(pf_raw)) else None
    except Exception:
        profit_factor = None

    # Longest drawdown duration in days
    max_dd_duration_days: int | None = None
    try:
        dd_series = qs.stats.to_drawdown_series(returns)
        dd_details = qs.stats.drawdown_details(dd_series)
        if dd_details is not None and not dd_details.empty and "days" in dd_details.columns:
            max_dd_duration_days = int(dd_details["days"].max())
    except Exception:
        max_dd_duration_days = None

    # Extended suite (audit F-13): tail risk, drawdown quality, RL diagnostics,
    # signal quality. All additive + nullable so existing consumers are unaffected
    # (frontend guards must use != null, never !== undefined).
    consecutive_losses = None
    try:
        cl = qs.stats.consecutive_losses(returns)
        if cl is not None and np.isfinite(float(cl)):
            consecutive_losses = int(cl)
    except Exception:
        pass

    extended = {
        "ulcer_index": _safe(qs.stats.ulcer_index, returns),
        "ulcer_perf_index": _safe(qs.stats.ulcer_performance_index, returns, rf=0.0),
        "gain_to_pain": _safe(qs.stats.gain_to_pain_ratio, returns),
        "common_sense_ratio": _safe(qs.stats.common_sense_ratio, returns),
        "tail_ratio": _safe(qs.stats.tail_ratio, returns),
        "skew": _safe(qs.stats.skew, returns),
        "kurtosis": _safe(qs.stats.kurtosis, returns),
        "recovery_factor": _safe(qs.stats.recovery_factor, returns),
        "cpc_index": _safe(qs.stats.cpc_index, returns),
        "r_squared": _equity_curve_r_squared(returns),
        "cagr": _safe(qs.stats.cagr, returns, rf=0.0, periods=_PERIODS_PER_YEAR),
        "exposure": _safe(qs.stats.exposure, returns),
        "consecutive_losses": consecutive_losses,
        "outlier_loss_ratio": _safe(qs.stats.outlier_loss_ratio, returns),
        "avg_win": _safe(qs.stats.avg_win, returns),
        "avg_loss": _safe(qs.stats.avg_loss, returns),
        "volatility_ann": _safe(
            qs.stats.volatility, returns, periods=_PERIODS_PER_YEAR, annualize=True
        ),
        "var_95": _safe(qs.stats.value_at_risk, returns),
        "cvar_95": _safe(qs.stats.expected_shortfall, returns),
        "kelly_criterion": _safe(qs.stats.kelly_criterion, returns),
        "risk_of_ruin": _safe(qs.stats.risk_of_ruin, returns),
    }

    return {
        "n_trades": n_trades,  # caller overwrites
        "start_date": start_date,  # caller overwrites
        "end_date": end_date,  # caller overwrites
        "source": source,
        "sortino": sortino,
        "sharpe": sharpe,
        "calmar": calmar,
        "max_dd": max_dd,
        "max_dd_duration_days": max_dd_duration_days,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "monthly_returns": _monthly_returns(returns),
        "rolling_sharpe_30d": _rolling_sharpe_30d(returns),
        **extended,
    }
