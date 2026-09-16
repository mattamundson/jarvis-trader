from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from statistics import fmean
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from morning_alpha.models import InstrumentSnapshot, MarketBar
from morning_alpha.setups.base import SetupContext


NEW_YORK = ZoneInfo("America/New_York")


def _require_aware(ts: datetime, name: str) -> None:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _completed_daily_bars(bars: list[MarketBar], decision_timestamp: datetime) -> list[MarketBar]:
    _require_aware(decision_timestamp, "decision_timestamp")
    decision_date = decision_timestamp.astimezone(NEW_YORK).date()
    completed = [
        bar
        for bar in bars
        if bar.timestamp.astimezone(NEW_YORK).date() < decision_date
        and bar.timestamp < decision_timestamp
    ]
    return sorted(completed, key=lambda bar: bar.timestamp)


class FeatureInputLineage(BaseModel):
    model_config = ConfigDict(frozen=True)

    stock_endpoint: datetime
    spy_endpoint: datetime
    sector_endpoint: datetime
    latest_source_timestamp: datetime
    data_manifest_hash: str = Field(pattern=r"^.{64}$")

    @model_validator(mode="after")
    def validate_timestamps(self) -> "FeatureInputLineage":
        for name in ("stock_endpoint", "spy_endpoint", "sector_endpoint", "latest_source_timestamp"):
            _require_aware(getattr(self, name), name)
        return self


class HistoricalFeatureSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    stable_security_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    sector: str
    sector_etf: str
    decision_timestamp: datetime
    data_manifest_hash: str = Field(pattern=r"^.{64}$")
    price_as_of: float = Field(gt=0)
    previous_close: float = Field(gt=0)
    returns_20d: float
    spy_return_20d: float
    sector_return_20d: float
    sma20: float = Field(gt=0)
    sma50: float = Field(gt=0)
    atr14: float = Field(gt=0)
    prior_high: float = Field(gt=0)
    prior_low: float = Field(gt=0)
    high_252d: float = Field(gt=0)
    avg_daily_shares_20d: float = Field(ge=0)
    avg_dollar_volume_20d: float = Field(ge=0)
    source: str
    ingested_at: datetime
    lineage: FeatureInputLineage
    latest_source_timestamp: datetime
    feature_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_lineage_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_snapshot(self) -> "HistoricalFeatureSnapshot":
        _require_aware(self.decision_timestamp, "decision_timestamp")
        _require_aware(self.ingested_at, "ingested_at")
        _require_aware(self.latest_source_timestamp, "latest_source_timestamp")
        if self.latest_source_timestamp >= self.decision_timestamp:
            raise ValueError("TEMPORAL_LEAKAGE: feature source reaches decision timestamp or later")
        return self

    def to_instrument_snapshot(self) -> InstrumentSnapshot:
        return InstrumentSnapshot(
            symbol=self.symbol,
            as_of=self.decision_timestamp,
            price=self.price_as_of,
            previous_close=self.previous_close,
            avg_daily_shares_20d=self.avg_daily_shares_20d,
            avg_dollar_volume_20d=self.avg_dollar_volume_20d,
            high_52w=self.high_252d,
            sector=self.sector,
            source=self.source,
            ingested_at=self.ingested_at,
        )

    def to_setup_context(self) -> SetupContext:
        fields = SetupContext.model_fields
        payload: dict[str, object] = {
            "spy_return_20d": self.spy_return_20d,
            "sector_return_20d": self.sector_return_20d,
            "sma20": self.sma20,
            "sma50": self.sma50,
            "atr14": self.atr14,
            "prior_high": self.prior_high,
            "prior_low": self.prior_low,
            "high_252d": self.high_252d,
        }
        if "as_of" in fields:
            payload["as_of"] = self.decision_timestamp
        if "return_20d" in fields:
            payload["return_20d"] = self.returns_20d
        elif "returns_20d" in fields:
            payload["returns_20d"] = self.returns_20d
        else:  # pragma: no cover - guarded by detector contract tests
            raise RuntimeError("SetupContext lacks a 20-day return field")
        return SetupContext(**payload)


class HistoricalFeatureBuilder:
    def build(
        self,
        *,
        stable_security_id: str,
        symbol: str,
        sector: str,
        sector_etf: str,
        decision_timestamp: datetime,
        data_manifest_hash: str,
        stock_bars: list[MarketBar],
        spy_bars: list[MarketBar],
        sector_bars: list[MarketBar],
    ) -> HistoricalFeatureSnapshot:
        _require_aware(decision_timestamp, "decision_timestamp")
        stock = _completed_daily_bars(stock_bars, decision_timestamp)
        spy = _completed_daily_bars(spy_bars, decision_timestamp)
        sector_rows = _completed_daily_bars(sector_bars, decision_timestamp)

        if len(stock) < 252:
            raise ValueError("INSUFFICIENT_HISTORY: stock requires 252 completed sessions")
        if len(spy) < 21 or len(sector_rows) < 21:
            raise ValueError("INSUFFICIENT_HISTORY: benchmark requires 21 completed sessions")

        stock = stock[-252:]
        stock_endpoint = stock[-1].timestamp
        spy_endpoint = spy[-1].timestamp
        sector_endpoint = sector_rows[-1].timestamp
        endpoint_dates = {
            stock_endpoint.astimezone(NEW_YORK).date(),
            spy_endpoint.astimezone(NEW_YORK).date(),
            sector_endpoint.astimezone(NEW_YORK).date(),
        }
        if len(endpoint_dates) != 1:
            raise ValueError("BENCHMARK_ALIGNMENT_FAILED: stock/SPY/sector endpoints differ")

        spy = spy[-21:]
        sector_rows = sector_rows[-21:]
        last20 = stock[-20:]
        closes = [bar.close for bar in stock]
        returns_20d = stock[-1].close / stock[-21].close - 1.0
        spy_return_20d = spy[-1].close / spy[-21].close - 1.0
        sector_return_20d = sector_rows[-1].close / sector_rows[-21].close - 1.0
        sma20 = fmean(closes[-20:])
        sma50 = fmean(closes[-50:])

        true_ranges: list[float] = []
        for previous, current in zip(stock[-15:-1], stock[-14:]):
            true_ranges.append(
                max(
                    current.high - current.low,
                    abs(current.high - previous.close),
                    abs(current.low - previous.close),
                )
            )
        atr14 = fmean(true_ranges)
        prior = stock[-1]
        high_252d = max(bar.high for bar in stock)
        avg_daily_shares_20d = fmean(bar.volume for bar in last20)
        avg_dollar_volume_20d = fmean(bar.volume * bar.close for bar in last20)
        latest_source_timestamp = max(stock_endpoint, spy_endpoint, sector_endpoint)
        lineage = FeatureInputLineage(
            stock_endpoint=stock_endpoint,
            spy_endpoint=spy_endpoint,
            sector_endpoint=sector_endpoint,
            latest_source_timestamp=latest_source_timestamp,
            data_manifest_hash=data_manifest_hash,
        )
        source_lineage_hash = _canonical_hash(lineage.model_dump(mode="json"))
        values_payload = {
            "stable_security_id": stable_security_id,
            "symbol": symbol,
            "sector": sector,
            "sector_etf": sector_etf,
            "decision_timestamp": decision_timestamp.isoformat(),
            "data_manifest_hash": data_manifest_hash,
            "price_as_of": prior.close,
            "previous_close": prior.close,
            "returns_20d": returns_20d,
            "spy_return_20d": spy_return_20d,
            "sector_return_20d": sector_return_20d,
            "sma20": sma20,
            "sma50": sma50,
            "atr14": atr14,
            "prior_high": prior.high,
            "prior_low": prior.low,
            "high_252d": high_252d,
            "avg_daily_shares_20d": avg_daily_shares_20d,
            "avg_dollar_volume_20d": avg_dollar_volume_20d,
            "source_lineage_hash": source_lineage_hash,
        }
        feature_hash = _canonical_hash(values_payload)
        return HistoricalFeatureSnapshot(
            stable_security_id=stable_security_id,
            symbol=symbol,
            sector=sector,
            sector_etf=sector_etf,
            decision_timestamp=decision_timestamp,
            data_manifest_hash=data_manifest_hash,
            price_as_of=prior.close,
            previous_close=prior.close,
            returns_20d=returns_20d,
            spy_return_20d=spy_return_20d,
            sector_return_20d=sector_return_20d,
            sma20=sma20,
            sma50=sma50,
            atr14=atr14,
            prior_high=prior.high,
            prior_low=prior.low,
            high_252d=high_252d,
            avg_daily_shares_20d=avg_daily_shares_20d,
            avg_dollar_volume_20d=avg_dollar_volume_20d,
            source=prior.source,
            ingested_at=max(bar.ingested_at for bar in stock),
            lineage=lineage,
            latest_source_timestamp=latest_source_timestamp,
            feature_hash=feature_hash,
            source_lineage_hash=source_lineage_hash,
        )
