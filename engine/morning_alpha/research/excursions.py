from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Iterable
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from morning_alpha.models import MarketBar, Session, TradePlan

_EASTERN = ZoneInfo("America/New_York")


class ExcursionHorizon(StrEnum):
    MIN_30 = "30m"
    MIN_60 = "60m"
    EOD = "eod"
    DAY_1 = "1d"
    DAY_2 = "2d"
    DAY_3 = "3d"
    DAY_5 = "5d"


class ExcursionObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    horizon: ExcursionHorizon
    available: bool
    end_timestamp: datetime | None = None
    mfe_r: float | None = None
    mae_r: float | None = None
    reason: str | None = None


class ExcursionCurve(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    entry_timestamp: datetime
    observations: tuple[ExcursionObservation, ...]


_MINUTE_HORIZONS = {
    ExcursionHorizon.MIN_30: timedelta(minutes=30),
    ExcursionHorizon.MIN_60: timedelta(minutes=60),
}
_DAY_HORIZONS = {
    ExcursionHorizon.DAY_1: 1,
    ExcursionHorizon.DAY_2: 2,
    ExcursionHorizon.DAY_3: 3,
    ExcursionHorizon.DAY_5: 5,
}


def _trade_date(ts: datetime):
    return ts.astimezone(_EASTERN).date()


class ExcursionEngine:
    def _window(
        self,
        entry_timestamp: datetime,
        bars: list[MarketBar],
        horizon: ExcursionHorizon,
    ) -> list[MarketBar]:
        if horizon in _MINUTE_HORIZONS:
            boundary = entry_timestamp + _MINUTE_HORIZONS[horizon]
            return [bar for bar in bars if entry_timestamp < bar.timestamp <= boundary]

        entry_date = _trade_date(entry_timestamp)
        if horizon is ExcursionHorizon.EOD:
            return [bar for bar in bars if _trade_date(bar.timestamp) == entry_date]

        days_forward = _DAY_HORIZONS[horizon]
        future_dates = sorted(
            {_trade_date(bar.timestamp) for bar in bars if _trade_date(bar.timestamp) > entry_date}
        )
        if len(future_dates) < days_forward:
            return []
        target_date = future_dates[days_forward - 1]
        return [bar for bar in bars if _trade_date(bar.timestamp) <= target_date]

    def measure(
        self,
        plan: TradePlan,
        entry_timestamp: datetime,
        bars: Iterable[MarketBar],
        horizons: tuple[ExcursionHorizon, ...],
    ) -> ExcursionCurve:
        if entry_timestamp.tzinfo is None or entry_timestamp.utcoffset() is None:
            raise ValueError("entry_timestamp must be timezone-aware")

        eligible = sorted(
            (
                bar
                for bar in bars
                if bar.symbol == plan.symbol
                and bar.timestamp > entry_timestamp
                and bar.session is Session.RTH
            ),
            key=lambda row: row.timestamp,
        )

        observations: list[ExcursionObservation] = []
        for horizon in horizons:
            window = self._window(entry_timestamp, eligible, horizon)
            if not window:
                observations.append(
                    ExcursionObservation(
                        horizon=horizon,
                        available=False,
                        reason="NO_ELIGIBLE_BARS",
                    )
                )
                continue

            high = max(bar.high for bar in window)
            low = min(bar.low for bar in window)
            if plan.side == "long":
                mfe_r = (high - plan.entry) / plan.risk_per_share
                mae_r = (low - plan.entry) / plan.risk_per_share
            else:
                mfe_r = (plan.entry - low) / plan.risk_per_share
                mae_r = (plan.entry - high) / plan.risk_per_share

            observations.append(
                ExcursionObservation(
                    horizon=horizon,
                    available=True,
                    end_timestamp=window[-1].timestamp,
                    mfe_r=mfe_r,
                    mae_r=mae_r,
                )
            )

        return ExcursionCurve(
            symbol=plan.symbol,
            entry_timestamp=entry_timestamp,
            observations=tuple(observations),
        )
