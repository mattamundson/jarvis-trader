import pytest
from engine.research.event_markets.schema import (
    EventMarketReplayRecord,
    infer_resolution_value,
    replay_hash,
)


def _raw(**overrides):
    base = {
        "venue": "polymarket",
        "market_id": "m-1",
        "market_slug_or_ticker": "btc-updown-15m-example",
        "outcome_token_or_side": "yes",
        "event_ts_utc": "2026-09-14T22:00:30-05:00",
        "raw_artifact_sha256": "a" * 64,
        "source_repo_or_api": "mattamundson/polybot",
        "source_commit_or_api_version": "f298140",
        "raw_price": 0.51,
        "normalized_probability": 0.51,
        "quantity": 10,
        "bid": 0.50,
        "ask": 0.52,
        "mid": 0.51,
        "spread": 0.02,
        "resolution_status": "unresolved",
        "venue_payload": {"token_id": "token-yes"},
    }
    base.update(overrides)
    return base


def test_polymarket_record_normalizes_utc_and_keeps_payload_isolated():
    record = EventMarketReplayRecord.from_raw(_raw())
    assert record.event_ts_utc == "2026-09-15T03:00:30Z"
    assert record.venue_payload == {"token_id": "token-yes"}
    assert record.resolution_value is None


def test_nanosecond_timestamp_and_kalshi_payload_are_supported():
    record = EventMarketReplayRecord.from_raw(
        _raw(
            venue="kalshi",
            market_slug_or_ticker="KXBTC-EXAMPLE",
            event_ts_utc=1_757_992_430_000_000_000,
            venue_payload={"ticker": "KXBTC-EXAMPLE"},
        )
    )
    assert record.event_ts_utc.endswith("Z")
    assert record.venue_payload["ticker"] == "KXBTC-EXAMPLE"


def test_probability_and_bid_ask_sanity_fail_closed():
    with pytest.raises(ValueError, match="normalized_probability"):
        EventMarketReplayRecord.from_raw(_raw(normalized_probability=1.01))
    with pytest.raises(ValueError, match="bid must not exceed ask"):
        EventMarketReplayRecord.from_raw(_raw(bid=0.60, ask=0.59))


def test_resolution_inference_does_not_fabricate_unresolved_outcomes():
    assert infer_resolution_value({"result": ""}) is None
    assert infer_resolution_value({"result": "yes"}) == 1.0
    resolved = EventMarketReplayRecord.from_raw(_raw(resolution_status="resolved", result="no"))
    assert resolved.resolution_value == 0.0
    with pytest.raises(ValueError, match="resolved records require"):
        EventMarketReplayRecord.from_raw(_raw(resolution_status="resolved"))


def test_replay_hash_is_deterministic_independent_of_input_order():
    a = EventMarketReplayRecord.from_raw(_raw(market_id="a", event_ts_utc="2026-01-01T00:00:02Z"))
    b = EventMarketReplayRecord.from_raw(_raw(market_id="b", event_ts_utc="2026-01-01T00:00:01Z"))
    assert replay_hash([a, b], adapter_version="test.v1") == replay_hash([b, a], adapter_version="test.v1")
    assert replay_hash([a, b], adapter_version="test.v1") != replay_hash([a, b], adapter_version="test.v2")
