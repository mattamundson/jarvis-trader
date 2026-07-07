"""
analytics.regime_detector — P3-15 persistent-regime alert.

Monitors two conditions that signal an abnormal macro regime where the
MES 1h mean-rev and trend edges may be compromised:

    C1 (PERSISTENT_OVERSOLD): MES daily RSI(14) < RSI_OVERSOLD_THRESHOLD
       for >= RSI_STREAK_DAYS consecutive calendar days.
       Signal: prolonged sell-off. Mean-rev LONG setups face deteriorating
       fundamentals; trend LONG signals may be trapping buyers.

    C2 (HIGH_VIX): VIX > VIX_ALERT_THRESHOLD for >= VIX_STREAK_DAYS
       consecutive trading days.
       Signal: fear spike. ATR expands, fills worsen, edge degrades.

Usage (standalone):
    from analytics.regime_detector import check_regime_alerts
    alerts = check_regime_alerts()
    print(alerts)

Usage (from engine/ directory):
    .venv/Scripts/python -c "
    from analytics.regime_detector import check_regime_alerts
    print(check_regime_alerts())
    "

FastAPI integration: GET /safety/regime-alert
    Returns the RegimeAlertReport as JSON.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

RSI_OVERSOLD_THRESHOLD: float = 30.0  # daily RSI below this triggers C1
RSI_STREAK_DAYS: int = 5  # consecutive days required for alert

VIX_ALERT_THRESHOLD: float = 25.0  # VIX above this triggers C2
VIX_STREAK_DAYS: int = 3  # consecutive trading days required

RSI_PERIOD: int = 14  # Wilder RSI period on daily bars
RSI_LOOKBACK_DAYS: int = 60  # days of daily bars to load

# ---------------------------------------------------------------------------
# Data paths
# ---------------------------------------------------------------------------

_ENGINE_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _ENGINE_ROOT / "backtest" / "cache"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class RegimeAlert:
    condition: str  # "PERSISTENT_OVERSOLD" | "HIGH_VIX"
    active: bool
    description: str
    current_value: Optional[float] = None
    threshold: Optional[float] = None
    streak_days: Optional[int] = None
    required_streak: Optional[int] = None


@dataclass
class RegimeAlertReport:
    timestamp: str
    any_alert: bool
    alerts: list[RegimeAlert] = field(default_factory=list)
    mes_daily_rsi: Optional[float] = None
    mes_rsi_streak: Optional[int] = None  # consecutive days RSI < threshold
    vix_current: Optional[float] = None
    vix_streak: Optional[int] = None  # consecutive days VIX > threshold
    mes_data_source: str = "none"
    vix_data_source: str = "none"
    error: Optional[str] = None

    def __str__(self) -> str:
        lines = [f"RegimeAlertReport @ {self.timestamp}"]
        lines.append(f"  any_alert: {self.any_alert}")
        for a in self.alerts:
            status = "ACTIVE" if a.active else "clear"
            lines.append(
                f"  [{status:6s}] {a.condition}: {a.description} "
                f"(value={a.current_value}, streak={a.streak_days}/{a.required_streak}d)"
            )
        lines.append(
            f"  MES daily RSI: {self.mes_daily_rsi} "
            f"(streak < {RSI_OVERSOLD_THRESHOLD}: {self.mes_rsi_streak}d) "
            f"[src: {self.mes_data_source}]"
        )
        lines.append(
            f"  VIX: {self.vix_current} "
            f"(streak > {VIX_ALERT_THRESHOLD}: {self.vix_streak}d) "
            f"[src: {self.vix_data_source}]"
        )
        if self.error:
            lines.append(f"  ERROR: {self.error}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["alerts"] = [asdict(a) for a in self.alerts]
        return d


# ---------------------------------------------------------------------------
# RSI helper
# ---------------------------------------------------------------------------


def _wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.mask(avg_loss == 0.0, 100.0)
    return rsi


# ---------------------------------------------------------------------------
# MES daily RSI
# ---------------------------------------------------------------------------


def _load_mes_daily_rsi() -> tuple[Optional[float], Optional[int], str]:
    """Return (latest_rsi, streak_count, source_description).

    streak_count = consecutive trailing days where daily RSI < RSI_OVERSOLD_THRESHOLD.
    Returns (None, None, 'error') on any failure.
    """
    try:
        from backtest._gate_v2_helpers import _find_latest_cache

        data_file = _find_latest_cache(_CACHE_DIR, "MES", "_1d.csv")
    except FileNotFoundError:
        logger.warning("regime_detector: no MES daily cache found in %s", _CACHE_DIR)
        return None, None, "no_cache"
    except Exception as exc:
        logger.warning("regime_detector: cache lookup error: %s", exc)
        return None, None, "error"

    try:
        df = pd.read_csv(data_file)
        df.columns = [c.lower() for c in df.columns]
        ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
        df[ts_col] = pd.to_datetime(df[ts_col])
        df = df.set_index(ts_col).sort_index()
        close = df["close"].tail(RSI_LOOKBACK_DAYS)
    except Exception as exc:
        logger.warning("regime_detector: failed to load %s: %s", data_file.name, exc)
        return None, None, "error"

    if len(close) < RSI_PERIOD + 1:
        return None, None, "insufficient_data"

    rsi = _wilder_rsi(close, period=RSI_PERIOD).dropna()
    if rsi.empty:
        return None, None, "rsi_empty"

    latest_rsi = float(rsi.iloc[-1])

    # Count consecutive trailing days below threshold
    streak = 0
    for val in reversed(rsi.values):
        if val < RSI_OVERSOLD_THRESHOLD:
            streak += 1
        else:
            break

    return latest_rsi, streak, data_file.name


# ---------------------------------------------------------------------------
# VIX sustained check
# ---------------------------------------------------------------------------


def _load_vix_streak() -> tuple[Optional[float], Optional[int], str]:
    """Return (current_vix, streak_count, source_description).

    streak_count = consecutive trading days where VIX > VIX_ALERT_THRESHOLD.
    Returns (None, None, 'error') on failure.
    """
    # Primary: use VIXOverlay (live / cached)
    try:
        from analytics.vix_overlay import VIXOverlay

        overlay = VIXOverlay()
        state = overlay.get_state()
        current_vix = state.vix_value
        source = state.source
    except Exception as exc:
        logger.warning("regime_detector: VIXOverlay failed: %s", exc)
        return None, None, "error"

    # For the streak, check VIX closing values from SPY daily (as proxy)
    # or fall back to a single-day check if no historical VIX data is available.
    streak = 1 if current_vix > VIX_ALERT_THRESHOLD else 0

    # Attempt to extend streak count using daily SPY cache (VIX proxy not available
    # directly, but SPY daily ATR / realized vol gives directional confirmation).
    # Best-effort: if the SPY 1d cache exists, look at ATR-based vol as a second
    # sanity check. If not available, streak = single-day reading only.
    try:
        from backtest._gate_v2_helpers import _find_latest_cache

        spy_file = _find_latest_cache(_CACHE_DIR, "SPY", "_1d.csv")
        spy_df = pd.read_csv(spy_file)
        spy_df.columns = [c.lower() for c in spy_df.columns]
        ts_col = "timestamp" if "timestamp" in spy_df.columns else "datetime"
        spy_df[ts_col] = pd.to_datetime(spy_df[ts_col])
        spy_df = spy_df.set_index(ts_col).sort_index().tail(20)
        # Daily realized vol as VIX proxy (annualized close-to-close, %)
        log_ret = np.log(spy_df["close"] / spy_df["close"].shift(1))
        rv = log_ret.rolling(5, min_periods=3).std() * np.sqrt(252) * 100.0
        rv = rv.dropna()
        # Map realized vol to approximate VIX regime:
        # rv > 25% → VIX likely > 25 (rough rule; not exact but directional)
        above = rv > VIX_ALERT_THRESHOLD
        if len(above) > 0:
            streak = 0
            for val in reversed(above.values):
                if val:
                    streak += 1
                else:
                    break
            # Incorporate the live VIX reading for the current day
            if current_vix > VIX_ALERT_THRESHOLD:
                streak = max(streak, 1)
            source = f"{source}+spy_rv"
    except Exception:
        # Best-effort — single-day VIX streak only
        pass

    return current_vix, streak, source


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------


def check_regime_alerts() -> RegimeAlertReport:
    """Run both regime alert checks and return a unified report."""
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    report = RegimeAlertReport(timestamp=now_iso, any_alert=False)

    # C1: MES persistent oversold
    try:
        mes_rsi, rsi_streak, mes_src = _load_mes_daily_rsi()
        report.mes_daily_rsi = round(mes_rsi, 2) if mes_rsi is not None else None
        report.mes_rsi_streak = rsi_streak
        report.mes_data_source = mes_src

        c1_active = (
            mes_rsi is not None
            and rsi_streak is not None
            and mes_rsi < RSI_OVERSOLD_THRESHOLD
            and rsi_streak >= RSI_STREAK_DAYS
        )
        c1_desc = (
            f"MES daily RSI {mes_rsi:.1f} < {RSI_OVERSOLD_THRESHOLD} "
            f"for {rsi_streak}d ({RSI_STREAK_DAYS}d required)"
            if mes_rsi is not None
            else "MES daily data unavailable"
        )
        report.alerts.append(
            RegimeAlert(
                condition="PERSISTENT_OVERSOLD",
                active=c1_active,
                description=c1_desc,
                current_value=report.mes_daily_rsi,
                threshold=RSI_OVERSOLD_THRESHOLD,
                streak_days=rsi_streak,
                required_streak=RSI_STREAK_DAYS,
            )
        )
    except Exception as exc:
        logger.error("regime_detector C1 error: %s", exc)
        report.error = str(exc)

    # C2: high VIX sustained
    try:
        vix_val, vix_streak, vix_src = _load_vix_streak()
        report.vix_current = round(vix_val, 2) if vix_val is not None else None
        report.vix_streak = vix_streak
        report.vix_data_source = vix_src

        c2_active = (
            vix_val is not None
            and vix_streak is not None
            and vix_val > VIX_ALERT_THRESHOLD
            and vix_streak >= VIX_STREAK_DAYS
        )
        c2_desc = (
            f"VIX {vix_val:.1f} > {VIX_ALERT_THRESHOLD} "
            f"for {vix_streak}d ({VIX_STREAK_DAYS}d required)"
            if vix_val is not None
            else "VIX data unavailable"
        )
        report.alerts.append(
            RegimeAlert(
                condition="HIGH_VIX",
                active=c2_active,
                description=c2_desc,
                current_value=report.vix_current,
                threshold=VIX_ALERT_THRESHOLD,
                streak_days=vix_streak,
                required_streak=VIX_STREAK_DAYS,
            )
        )
    except Exception as exc:
        logger.error("regime_detector C2 error: %s", exc)
        if not report.error:
            report.error = str(exc)

    report.any_alert = any(a.active for a in report.alerts)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    engine_root = Path(__file__).resolve().parent.parent
    if str(engine_root) not in sys.path:
        sys.path.insert(0, str(engine_root))
    logging.basicConfig(level=logging.WARNING)
    result = check_regime_alerts()
    print(result)
    sys.exit(0 if not result.any_alert else 1)
