from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Iterable
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from morning_alpha.models import MarketBar, Session

_EASTERN = ZoneInfo("America/New_York")


class ForwardHorizon(StrEnum):
    MIN_30 = "30m"
    MIN_60 = "60m"
    EOD = "eod"
    DAY_1 = "1d"
    DAY_2 = "2d"
    DAY_3 = "3d"
    DAY_5 = "5d"
    DAY_10 = "10d"
    DAY_20 = "20d"


class ForwardReturnObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1)
    horizon: ForwardHorizon
    decision_time: datetime
    entry_price: float = Field(gt=0)
    end_timestamp: datetime | None = None
    end_price: float | None = Field(default=None, gt=0)
    simple_return: float | None = None
    available: bool
    reason: str | None = None

    @model_validator(mode="after")
    def validate_times(self) -> "ForwardReturnObservation":
        if self.decision_time.tzinfo is None or self.decision_time.utcoffset() is None:
            raise ValueError("decision_time must be timezone-aware")
        if self.end_timestamp is not None and (
            self.end_timestamp.tzinfo is None or self.end_timestamp.utcoffset() is None
        ):
            raise ValueError("end_timestamp must be timezone-aware")
        return self


_MINUTE_HORIZONS = {
    ForwardHorizon.MIN_30: timedelta(minutes=30),
    ForwardHorizon.MIN_60: timedelta(minutes=60),
}
_DAY_HORIZONS = {
    ForwardHorizon.DAY_1: 1,
    ForwardHorizon.DAY_2: 2,
    ForwardHorizon.DAY_3: 3,
    ForwardHorizon.DAY_5: 5,
    ForwardHorizon.DAY_10: 10,
    ForwardHorizon.DAY_20: 20,
}


def _trade_date(ts: datetime):
    return ts.astimezone(_EASTERN).date()


class ForwardReturnEngine:
    def _endpoint(
        self,
        decision_time: datetime,
        bars: list[MarketBar],
        horizon: ForwardHorizon,
    ) -> MarketBar | None:
        if horizon in _MINUTE_HORIZONS:
            boundary = decision_time + _MINUTE_HORIZONS[horizon]
            eligible = [bar for bar in bars if decision_time < bar.timestamp <= boundary]
            return eligible[-1] if eligible else None

        decision_date = _trade_date(decision_time)
        if horizon is ForwardHorizon.EOD:
            eligible = [bar for bar in bars if _trade_date(bar.timestamp) == decision_date]
            return eligible[-1] if eligible else None

        days_forward = _DAY_HORIZONS[horizon]
        future_dates = sorted(
            {_trade_date(bar.timestamp) for bar in bars if _trade_date(bar.timestamp) > decision_date}
        )
        if len(future_dates) < days_forward:
            return None
        target_date = future_dates[days_forward - 1]
        eligible = [bar for bar in bars if _trade_date(bar.timestamp) == target_date]
        return eligible[-1] if eligible else None

    def measure(
        self,
        symbol: str,
        decision_time: datetime,
        entry_price: float,
        bars: Iterable[MarketBar],
        horizons: tuple[ForwardHorizon, ...],
    ) -> tuple[ForwardReturnObservation, ...]:
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            raise ValueError("decision_time must be timezone-aware")
        if entry_price <= 0:
            raise ValueError("entry_price must be positive")

        eligible_bars = sorted(
            (
                bar
                for bar in bars
                if bar.symbol == symbol
                and bar.timestamp > decision_time
                and bar.session is Session.RTH
            ),
            key=lambda bar: bar.timestamp,
        )

        observations: list[ForwardReturnObservation] = []
        for horizon in horizons:
            endpoint = self._endpoint(decision_time, eligible_bars, horizon)
            if endpoint is None:
                observations.append(
                    ForwardReturnObservation(
                        symbol=symbol,
                        horizon=horizon,
                        decision_time=decision_time,
                        entry_price=entry_price,
                        available=False,
                        reason="NO_ELIGIBLE_ENDPOINT",
                    )
                )
                continue
            observations.append(
                ForwardReturnObservation(
                    symbol=symbol,
                    horizon=horizon,
                    decision_time=decision_time,
                    entry_price=entry_price,
                    end_timestamp=endpoint.timestamp,
                    end_price=endpoint.close,
                    simple_return=(endpoint.close / entry_price) - 1.0,
                    available=True,
                )
            )
        return tuple(observations)
