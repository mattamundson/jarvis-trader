"""
JARVIS TRADER — RV-filter calibration counter (report-only)
===========================================================
Tracks how many closed live/paper trades have accumulated for the instruments
whose relative-volume (RV) filter is *validated but held pending calibration*,
so the operator can see when there is enough live data to confidently
enable/confirm the filter.

Background (see ``engine/CLAUDE.md``)
------------------------------------
The ``min_rv_annualized=9.0`` filter passed gate-v2 for MGC (CORE, p_edge=1.0)
and MES (ALT) on 2026-05-24, but is **not** flipped on in paper because each
needs **60+ live trades** for calibration/confirmation first. This module does
not enable, disable, or otherwise touch the filter, the paper config, or any
risk parameter — it only **reads closed trades and counts them** against that
documented threshold. Enabling the filter remains a separate, human,
gate-v2 / Tier-3 decision.

Design
------
The core (``calibration_status``) takes an injected ``trade_counter`` callable
so it is pure and unit-testable without a database; ``status_from_db`` is the
thin production adapter over ``get_closed_trades``.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Documented live-trade threshold before the RV filter may be enabled/confirmed.
# Source: engine/CLAUDE.md active-instruments table (2026-05-24 gate-v2 notes).
DEFAULT_MIN_TRADES = 60


@dataclass(frozen=True)
class RVFilterTarget:
    """A validated-but-pending RV filter awaiting live-trade calibration."""

    symbol: str
    min_rv_annualized: float
    min_trades: int
    note: str


# The two instruments with a validated-but-dormant RV filter. Metadata only —
# changing these does not change any trading behaviour.
RV_FILTER_TARGETS: dict[str, RVFilterTarget] = {
    "MGC": RVFilterTarget(
        symbol="MGC",
        min_rv_annualized=9.0,
        min_trades=DEFAULT_MIN_TRADES,
        note="Validated CORE gate-v2 2026-05-24 (p_edge=1.0); NOT enabled — pending calibration.",
    ),
    "MES": RVFilterTarget(
        symbol="MES",
        min_rv_annualized=9.0,
        min_trades=DEFAULT_MIN_TRADES,
        note="Validated ALT gate-v2 2026-05-24; min_rv_annualized in config, env-gated "
        "(MES_MIN_RV_ANNUALIZED) — 60+ live trades for confirmation.",
    ),
}


@dataclass
class RVCalibrationStatus:
    """Progress of one instrument toward its RV-filter calibration threshold."""

    symbol: str
    closed_trades: int
    min_trades: int
    remaining: int
    progress_pct: float
    ready: bool
    min_rv_annualized: float
    note: str

    def as_dict(self) -> dict:
        return asdict(self)


def compute_status(closed_trades: int, target: RVFilterTarget) -> RVCalibrationStatus:
    """Build a calibration status from a closed-trade count and a target."""
    count = max(0, int(closed_trades))
    remaining = max(0, target.min_trades - count)
    progress = 100.0 if target.min_trades <= 0 else min(100.0, count / target.min_trades * 100.0)
    return RVCalibrationStatus(
        symbol=target.symbol,
        closed_trades=count,
        min_trades=target.min_trades,
        remaining=remaining,
        progress_pct=round(progress, 1),
        ready=count >= target.min_trades,
        min_rv_annualized=target.min_rv_annualized,
        note=target.note,
    )


def calibration_status(
    trade_counter: Callable[[str], int],
    targets: Optional[dict[str, RVFilterTarget]] = None,
) -> list[RVCalibrationStatus]:
    """Compute calibration status for every target using an injected counter.

    ``trade_counter(symbol)`` returns the number of closed live/paper trades for
    that symbol. Kept injectable so the logic is testable without a database.
    """
    targets = targets or RV_FILTER_TARGETS
    out: list[RVCalibrationStatus] = []
    for symbol, target in targets.items():
        try:
            count = int(trade_counter(symbol))
        except Exception as exc:  # noqa: BLE001 — a bad count must not abort the report
            logger.warning("[RVCalibration] trade count failed for %s: %s", symbol, exc)
            count = 0
        out.append(compute_status(count, target))
    return out


def status_from_db(
    db,
    targets: Optional[dict[str, RVFilterTarget]] = None,
    *,
    count_cap: int = 1000,
) -> list[RVCalibrationStatus]:
    """Production adapter: count closed trades per symbol via ``get_closed_trades``.

    Read-only. ``count_cap`` bounds the row fetch (thresholds are ~60, so a
    1000-row cap is ample); if a symbol ever exceeds it the count saturates and
    ``ready`` still resolves True.
    """

    def _counter(symbol: str) -> int:
        rows = db.get_closed_trades(symbol=symbol, limit=count_cap)
        return len(rows or [])

    return calibration_status(_counter, targets)


def format_report(statuses: list[RVCalibrationStatus]) -> str:
    """Render a one-line-per-instrument human-readable progress report."""
    if not statuses:
        return "RV-filter calibration: no targets configured."
    lines = ["RV-filter calibration (live-trade progress toward enable threshold):"]
    for s in statuses:
        flag = "READY" if s.ready else f"{s.remaining} to go"
        lines.append(
            f"  {s.symbol}: {s.closed_trades}/{s.min_trades} trades "
            f"({s.progress_pct:.0f}%) — {flag} | RV>={s.min_rv_annualized:g}%"
        )
    return "\n".join(lines)
