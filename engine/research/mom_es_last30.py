"""MOM: ES prior-settle-to-14:30 return versus the 14:30-15:00 return.

This is the unadjusted calendar-front test. It is not the roll-adjusted
room wording and it is not the VWAP/CVD tile. It does not download bars.

Minute bars are labeled by the America/Chicago minute they open.
The signal is the close of the 14:29 bar, the last bar closed at 14:30:00.
The fill is the open of the 14:30 bar. The exit is the close of the bar
timestamped 15:00, used as the settlement mark. The 14:59 close is not the exit.
"""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CHICAGO = ZoneInfo("America/Chicago")
HOLDOUT_START = date(2021, 1, 1)
POINT_VALUE = 5.0
ROUND_TRIP_COST = 3.72
ROLL_RULE = (
    "ES.c.0 calendar front month, original outright prints, "
    "drop a session whose instrument_id changes between the prior 15:00 CT "
    "settlement and the 14:29 CT close"
)

_ACTIVE_MODE: str | None = None


class ModeConflict(RuntimeError):
    """Replication and holdout must not run in one process."""


class ReplicationWindowError(RuntimeError):
    """Replication mode was given a timestamp on or after 2021-01-01."""


class HoldoutClosed(RuntimeError):
    """Holdout mode has no sentinel from a replication run."""


@dataclass(frozen=True)
class Bar:
    ts: datetime
    instrument_id: str
    open: float
    close: float


@dataclass(frozen=True)
class KeptSession:
    trade_date: date
    instrument_id: str
    signal_return: float
    forward_return: float
    direction: int
    net_pnl: float | None


@dataclass(frozen=True)
class MomRow:
    slope: float | None
    net_mean: float | None
    newey_west_t: float | None
    trade_count: int
    best_five_share: float | None
    verdict: str


def cost_identity() -> str:
    """Fees 1.22 plus two ticks 2.50. The sum is the frozen round trip."""
    fees = 2.0 * (0.25 + 0.35 + 0.01)
    slippage = 2.0 * (0.25 * POINT_VALUE)
    total = fees + slippage
    if abs(total - ROUND_TRIP_COST) > 1e-9:
        raise RuntimeError(f"cost identity drifted: {total}")
    return f"fees={fees:.2f} slippage={slippage:.2f} round_trip={ROUND_TRIP_COST:.2f}"


def chicago(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        raise ValueError("bar timestamp must be timezone-aware")
    return ts.astimezone(CHICAGO)


def _clock(ts: datetime) -> tuple[date, int, int]:
    local = chicago(ts)
    return local.date(), local.hour, local.minute


def assert_replication_window(bars: list[Bar]) -> None:
    for bar in bars:
        if _clock(bar.ts)[0] >= HOLDOUT_START:
            raise ReplicationWindowError(
                f"replication refuses {chicago(bar.ts).isoformat()}"
            )


def ols_slope_newey_west_t(
    x: list[float], y: list[float], lags: int
) -> tuple[float, float]:
    """Slope and Bartlett HAC t for y = a + b x.

    The meat of the sandwich is the sum of score outer products, not the
    average. Lag weight is 1 - lag / (lags + 1).
    """
    n = len(x)
    if n != len(y) or n < 3:
        raise ValueError("need at least 3 paired observations")
    if lags < 0 or lags >= n:
        raise ValueError("lags must be in 0..n-1")
    sum_x = math.fsum(x)
    sum_y = math.fsum(y)
    sum_xx = math.fsum(v * v for v in x)
    sum_xy = math.fsum(a * b for a, b in zip(x, y, strict=True))
    det = n * sum_xx - sum_x * sum_x
    if det == 0.0:
        raise ValueError("singular design")
    intercept = (sum_xx * sum_y - sum_x * sum_xy) / det
    slope = (-sum_x * sum_y + n * sum_xy) / det
    resid = [y[i] - intercept - slope * x[i] for i in range(n)]
    scores = [(resid[i], resid[i] * x[i]) for i in range(n)]

    def outer(left: tuple[float, float], right: tuple[float, float]) -> tuple[tuple[float, float], tuple[float, float]]:
        return (
            (left[0] * right[0], left[0] * right[1]),
            (left[1] * right[0], left[1] * right[1]),
        )

    def add(left, right):
        return (
            (left[0][0] + right[0][0], left[0][1] + right[0][1]),
            (left[1][0] + right[1][0], left[1][1] + right[1][1]),
        )

    def scale(matrix, factor: float):
        return (
            (matrix[0][0] * factor, matrix[0][1] * factor),
            (matrix[1][0] * factor, matrix[1][1] * factor),
        )

    meat = ((0.0, 0.0), (0.0, 0.0))
    for score in scores:
        meat = add(meat, outer(score, score))
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1.0)
        cross = ((0.0, 0.0), (0.0, 0.0))
        for i in range(lag, n):
            cross = add(cross, outer(scores[i], scores[i - lag]))
        symmetric = add(cross, ((cross[0][0], cross[1][0]), (cross[0][1], cross[1][1])))
        meat = add(meat, scale(symmetric, weight))
    inv = (
        (sum_xx / det, -sum_x / det),
        (-sum_x / det, n / det),
    )

    def matmul(left, right):
        return (
            (
                left[0][0] * right[0][0] + left[0][1] * right[1][0],
                left[0][0] * right[0][1] + left[0][1] * right[1][1],
            ),
            (
                left[1][0] * right[0][0] + left[1][1] * right[1][0],
                left[1][0] * right[0][1] + left[1][1] * right[1][1],
            ),
        )

    variance = matmul(matmul(inv, meat), inv)[1][1]
    if variance <= 0.0:
        raise ValueError("non-positive slope variance")
    return slope, slope / math.sqrt(variance)


def automatic_lags(n: int) -> int:
    """Newey-West rule of thumb, at least 1 when the sample can bear it."""
    if n < 3:
        return 0
    guessed = int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))
    return max(1, min(guessed, n - 2))


def _index_bars(bars: list[Bar]) -> dict[tuple[date, int, int], Bar]:
    indexed: dict[tuple[date, int, int], Bar] = {}
    for bar in bars:
        key = _clock(bar.ts)
        if key in indexed:
            raise ValueError(f"duplicate bar {key}")
        indexed[key] = bar
    return indexed


def _prior_settlement(
    indexed: dict[tuple[date, int, int], Bar], trade_date: date
) -> Bar | None:
    candidates = [
        bar
        for (day, hour, minute), bar in indexed.items()
        if day < trade_date and hour == 15 and minute == 0
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda bar: _clock(bar.ts)[0])


def build_sessions(bars: list[Bar]) -> tuple[list[KeptSession], int]:
    """Return kept sessions and the number dropped for a contract change."""
    indexed = _index_bars(bars)
    trade_dates = sorted({day for (day, hour, minute) in indexed if hour == 14 and minute == 29})
    kept: list[KeptSession] = []
    dropped = 0
    for trade_date in trade_dates:
        signal_bar = indexed.get((trade_date, 14, 29))
        fill_bar = indexed.get((trade_date, 14, 30))
        settle_bar = indexed.get((trade_date, 15, 0))
        prior = _prior_settlement(indexed, trade_date)
        if signal_bar is None or fill_bar is None or settle_bar is None or prior is None:
            continue
        if prior.instrument_id != signal_bar.instrument_id:
            dropped += 1
            continue
        if (
            fill_bar.instrument_id != signal_bar.instrument_id
            or settle_bar.instrument_id != signal_bar.instrument_id
        ):
            dropped += 1
            continue
        if prior.close == 0.0 or fill_bar.open == 0.0:
            continue
        signal_return = (signal_bar.close - prior.close) / prior.close
        forward_return = (settle_bar.close - fill_bar.open) / fill_bar.open
        if signal_bar.close == prior.close:
            direction = 0
            net = None
        else:
            direction = 1 if signal_bar.close > prior.close else -1
            gross = direction * (settle_bar.close - fill_bar.open) * POINT_VALUE
            net = gross - ROUND_TRIP_COST
        kept.append(
            KeptSession(
                trade_date=trade_date,
                instrument_id=signal_bar.instrument_id,
                signal_return=signal_return,
                forward_return=forward_return,
                direction=direction,
                net_pnl=net,
            )
        )
    return kept, dropped


def best_five_share(pnls: list[float]) -> float | None:
    if not pnls:
        return None
    total = math.fsum(pnls)
    if total == 0.0:
        return None
    best = sorted(pnls, reverse=True)[:5]
    return math.fsum(best) / total


def summarize(sessions: list[KeptSession], lags: int | None = None) -> MomRow:
    traded = [session.net_pnl for session in sessions if session.net_pnl is not None]
    net_mean = math.fsum(traded) / len(traded) if traded else None
    share = best_five_share(traded)
    slope: float | None = None
    t_stat: float | None = None
    if len(sessions) >= 3:
        use_lags = automatic_lags(len(sessions)) if lags is None else lags
        try:
            slope, t_stat = ols_slope_newey_west_t(
                [session.signal_return for session in sessions],
                [session.forward_return for session in sessions],
                use_lags,
            )
        except ValueError:
            slope, t_stat = None, None
    if slope is None or t_stat is None or net_mean is None:
        verdict = "inconclusive"
    elif t_stat >= 3.0 and net_mean > 0.0:
        verdict = "pass"
    else:
        verdict = "reject"
    return MomRow(
        slope=slope,
        net_mean=net_mean,
        newey_west_t=t_stat,
        trade_count=len(traded),
        best_five_share=share,
        verdict=verdict,
    )


def format_report(row: MomRow, mode: str) -> str:
    def num(value: float | None) -> str:
        return "na" if value is None else f"{value:.6f}"

    lines = [
        cost_identity(),
        (
            f"slope={num(row.slope)} net_mean={num(row.net_mean)} "
            f"newey_west_t={num(row.newey_west_t)} trades={row.trade_count} "
            f"best_five_share={num(row.best_five_share)}"
        ),
        row.verdict,
    ]
    if mode == "holdout" and row.verdict != "pass":
        lines.append("stop, no GEX purchase, no live trading")
    return "\n".join(lines)


def script_git_hash(script_path: Path | None = None) -> str:
    path = (script_path or Path(__file__)).resolve()
    completed = subprocess.run(
        ["git", "hash-object", str(path)],
        check=True,
        capture_output=True,
        text=True,
        cwd=path.parent,
    )
    return completed.stdout.strip()


def write_sentinel(path: Path, script_hash: str | None = None) -> None:
    payload = {
        "script_git_hash": script_hash if script_hash is not None else script_git_hash(),
        "roll_rule": ROLL_RULE,
        "round_trip_cost": ROUND_TRIP_COST,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_sentinel(path: Path) -> None:
    if not path.is_file():
        raise HoldoutClosed(f"missing sentinel {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected_hash = script_git_hash()
    if payload.get("script_git_hash") != expected_hash:
        raise HoldoutClosed("sentinel script hash does not match this file")
    if payload.get("roll_rule") != ROLL_RULE:
        raise HoldoutClosed("sentinel roll rule does not match")
    cost = payload.get("round_trip_cost")
    if not isinstance(cost, (int, float)) or abs(float(cost) - ROUND_TRIP_COST) > 1e-9:
        raise HoldoutClosed("sentinel round trip is not 3.72")


def execute(bars: list[Bar], mode: str, sentinel_path: Path) -> str:
    """Run one mode. A second mode in this process raises ModeConflict."""
    global _ACTIVE_MODE
    if mode not in {"replication", "holdout"}:
        raise ValueError(f"unknown mode {mode}")
    if _ACTIVE_MODE is not None:
        raise ModeConflict(f"{_ACTIVE_MODE} already ran in this process")
    _ACTIVE_MODE = mode
    if mode == "replication":
        assert_replication_window(bars)
        text = format_report(summarize(build_sessions(bars)[0]), mode)
        write_sentinel(sentinel_path)
        return text
    read_sentinel(sentinel_path)
    return format_report(summarize(build_sessions(bars)[0]), mode)
