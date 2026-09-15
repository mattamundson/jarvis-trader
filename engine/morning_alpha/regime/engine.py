from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from morning_alpha.models import MarketRegime


class RegimeInputs(BaseModel):
    """Point-in-time inputs used to classify broad U.S. equity regime."""

    model_config = ConfigDict(frozen=True)

    as_of: datetime
    spy_close: float = Field(gt=0)
    spy_ema8: float = Field(gt=0)
    spy_ema21: float = Field(gt=0)
    spy_ema34: float = Field(gt=0)
    qqq_close: float = Field(gt=0)
    qqq_ema8: float = Field(gt=0)
    qqq_ema21: float = Field(gt=0)
    qqq_ema34: float = Field(gt=0)
    iwm_return_20d: float
    spy_return_20d: float
    vix: float = Field(ge=0)
    breadth_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    ten_year_yield_change_5d: float | None = None
    crude_return_5d: float | None = None
    scheduled_event_risk: bool = False

    @model_validator(mode="after")
    def validate_timestamp(self) -> "RegimeInputs":
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return self


def _trend(close: float, ema8: float, ema21: float, ema34: float) -> str:
    if close >= ema8 >= ema21 >= ema34:
        return "TRENDING_BULL"
    if close <= ema8 <= ema21 <= ema34:
        return "TRENDING_BEAR"
    return "MIXED"


def _vix_bucket(vix: float) -> str:
    if vix < 15:
        return "LOW"
    if vix < 20:
        return "NORMAL"
    if vix < 30:
        return "ELEVATED"
    return "CRISIS"


def _direction(value: float | None, *, threshold: float = 0.0) -> str | None:
    if value is None:
        return None
    if value > threshold:
        return "RISING"
    if value < -threshold:
        return "FALLING"
    return "FLAT"


class MarketRegimeEngine:
    """Deterministic, research-versioned broad-market context classifier."""

    version = "market_regime@0.1.0-research"

    def evaluate(self, inputs: RegimeInputs) -> MarketRegime:
        spy_trend = _trend(inputs.spy_close, inputs.spy_ema8, inputs.spy_ema21, inputs.spy_ema34)
        qqq_trend = _trend(inputs.qqq_close, inputs.qqq_ema8, inputs.qqq_ema21, inputs.qqq_ema34)
        vix_bucket = _vix_bucket(inputs.vix)
        breadth = inputs.breadth_score

        if inputs.scheduled_event_risk:
            risk_state = "EVENT_RISK"
        elif vix_bucket == "CRISIS":
            risk_state = "VOLATILE"
        elif breadth is not None and breadth <= -0.35:
            risk_state = "RISK_OFF"
        elif spy_trend == "TRENDING_BULL" and qqq_trend == "TRENDING_BULL" and (
            breadth is None or breadth >= 0
        ):
            risk_state = "TRENDING_BULL"
        elif spy_trend == "TRENDING_BEAR" and qqq_trend == "TRENDING_BEAR":
            risk_state = "TRENDING_BEAR"
        else:
            risk_state = "NEUTRAL"

        return MarketRegime(
            as_of=inputs.as_of,
            spy_trend=spy_trend,
            qqq_trend=qqq_trend,
            iwm_relative_strength=inputs.iwm_return_20d - inputs.spy_return_20d,
            vix_bucket=vix_bucket,
            breadth_score=breadth,
            ten_year_yield_trend=_direction(inputs.ten_year_yield_change_5d, threshold=0.01),
            crude_trend=_direction(inputs.crude_return_5d, threshold=0.005),
            scheduled_event_risk=inputs.scheduled_event_risk,
            risk_state=risk_state,
        )
