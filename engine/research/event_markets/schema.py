"""Offline event-market replay record schema helpers.

The helpers in this module are intentionally inert. They normalize fixture/replay
records for research evidence and deterministic tests only; they do not call any
network, broker, order router, runtime config, or trading surface.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

_ALLOWED_VENUES = {"polymarket", "kalshi"}
_ALLOWED_SIDES = {"yes", "no", "up", "down"}
_ALLOWED_RESOLUTION_STATUS = {"resolved", "unresolved", "ambiguous"}


def _parse_utc_timestamp(value: str | int | float | datetime) -> str:
    """Return an ISO-8601 UTC timestamp with second precision.

    Accepts timezone-aware/naive datetimes, ISO strings, epoch seconds,
    milliseconds, microseconds, or nanoseconds. Naive timestamps are treated as
    UTC because replay artifacts must not depend on local machine timezone.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 1_000_000_000_000_000_000:  # ns
            numeric /= 1_000_000_000
        elif numeric > 1_000_000_000_000_000:  # us
            numeric /= 1_000_000
        elif numeric > 1_000_000_000_000:  # ms
            numeric /= 1_000
        dt = datetime.fromtimestamp(numeric, tz=timezone.utc)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("event timestamp is empty")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    else:
        raise TypeError(f"unsupported timestamp type: {type(value).__name__}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _probability(value: float | int | None, *, field_name: str) -> float | None:
    if value is None:
        return None
    result = float(value)
    if result < 0.0 or result > 1.0:
        raise ValueError(f"{field_name} must be inside [0, 1], got {result}")
    return result


def _positive(value: float | int, *, field_name: str) -> float:
    result = float(value)
    if result < 0.0:
        raise ValueError(f"{field_name} must be non-negative, got {result}")
    return result


def infer_resolution_value(raw: Mapping[str, Any]) -> float | None:
    """Infer binary resolution value when source fields are explicit.

    Unresolved or ambiguous records return ``None`` rather than fabricating an
    outcome. Accepted resolved values are 0.0, 0.5, or 1.0.
    """
    if "resolution_value" in raw and raw["resolution_value"] is not None:
        value = float(raw["resolution_value"])
        if value not in {0.0, 0.5, 1.0}:
            raise ValueError("resolution_value must be 0.0, 0.5, 1.0, or null")
        return value
    result = str(raw.get("result", "")).strip().lower()
    if result in {"yes", "win", "winner", "true", "1"}:
        return 1.0
    if result in {"no", "loss", "loser", "false", "0"}:
        return 0.0
    if result in {"50_50", "tie", "draw", "0.5"}:
        return 0.5
    return None


@dataclass(frozen=True)
class EventMarketReplayRecord:
    """Normalized event-market replay record for research evidence."""

    venue: str
    market_id: str
    market_slug_or_ticker: str
    outcome_token_or_side: str
    event_ts_utc: str
    raw_artifact_sha256: str
    source_repo_or_api: str
    source_commit_or_api_version: str
    raw_price: float
    normalized_probability: float
    quantity: float
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    spread: float | None = None
    resolution_status: str = "unresolved"
    resolution_value: float | None = None
    venue_payload: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> "EventMarketReplayRecord":
        venue = str(raw["venue"]).strip().lower()
        if venue not in _ALLOWED_VENUES:
            raise ValueError(f"unsupported venue: {venue}")
        side = str(raw["outcome_token_or_side"]).strip().lower()
        if side not in _ALLOWED_SIDES and not str(raw["outcome_token_or_side"]).strip():
            raise ValueError("outcome_token_or_side is required")
        status = str(raw.get("resolution_status", "unresolved")).strip().lower()
        if status not in _ALLOWED_RESOLUTION_STATUS:
            raise ValueError(f"unsupported resolution_status: {status}")
        payload = raw.get("venue_payload") or {}
        if not isinstance(payload, Mapping):
            raise ValueError("venue_payload must be an object")
        if venue == "polymarket" and "token_id" not in payload:
            raise ValueError("polymarket venue_payload requires token_id")
        if venue == "kalshi" and "ticker" not in payload:
            raise ValueError("kalshi venue_payload requires ticker")
        bid = _probability(raw.get("bid"), field_name="bid")
        ask = _probability(raw.get("ask"), field_name="ask")
        if bid is not None and ask is not None and bid > ask:
            raise ValueError("bid must not exceed ask")
        mid = _probability(raw.get("mid"), field_name="mid")
        spread = raw.get("spread")
        spread_value = None if spread is None else _positive(spread, field_name="spread")
        resolution_value = infer_resolution_value(raw)
        if status == "resolved" and resolution_value is None:
            raise ValueError("resolved records require explicit resolution_value/result")
        if status != "resolved" and resolution_value is not None:
            raise ValueError("unresolved/ambiguous records must not carry resolved outcome")
        return cls(
            venue=venue,
            market_id=str(raw["market_id"]).strip(),
            market_slug_or_ticker=str(raw["market_slug_or_ticker"]).strip(),
            outcome_token_or_side=str(raw["outcome_token_or_side"]).strip(),
            event_ts_utc=_parse_utc_timestamp(raw["event_ts_utc"]),
            raw_artifact_sha256=str(raw["raw_artifact_sha256"]).strip().lower(),
            source_repo_or_api=str(raw["source_repo_or_api"]).strip(),
            source_commit_or_api_version=str(raw["source_commit_or_api_version"]).strip(),
            raw_price=_probability(raw["raw_price"], field_name="raw_price"),
            normalized_probability=_probability(raw["normalized_probability"], field_name="normalized_probability"),
            quantity=_positive(raw["quantity"], field_name="quantity"),
            bid=bid,
            ask=ask,
            mid=mid,
            spread=spread_value,
            resolution_status=status,
            resolution_value=resolution_value,
            venue_payload=dict(payload),
        )

    def to_canonical_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {key: data[key] for key in sorted(data)}


def replay_hash(records: list[EventMarketReplayRecord], *, adapter_version: str) -> str:
    """Return a deterministic hash for a normalized replay record set."""
    ordered = sorted((record.to_canonical_dict() for record in records), key=lambda r: (r["event_ts_utc"], r["venue"], r["market_id"], r["outcome_token_or_side"]))
    payload = {
        "adapter_version": adapter_version,
        "normalized_schema_version": "event-market-replay-record.v1",
        "records": ordered,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
