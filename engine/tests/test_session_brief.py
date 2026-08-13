"""
Tests for the Phase 5 proactive advisor brief (analytics.session_brief).

Covers the invariants the mission cares about:
  * reasoning is assembled ONLY from existing fields (never fabricated),
  * a reasoning-less snapshot yields an honest gap statement + reasoning_available=False,
  * staleness is computed from completed_at against a fixed `now`,
  * the brief caps at max_actions and dedupes by symbol,
  * empty input yields an honest empty brief (degraded, with a note).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from analytics.session_brief import (
    DEFAULT_STALE_AFTER_S,
    build_action,
    build_session_brief,
)

NOW = datetime(2026, 7, 2, 18, 0, 0, tzinfo=timezone.utc)


def _fresh_iso(seconds_ago: float) -> str:
    return (NOW - timedelta(seconds=seconds_ago)).isoformat()


def _full_snapshot(symbol: str = "MES", action: str = "buy", seconds_ago: float = 30.0) -> dict:
    return {
        "symbol": symbol,
        "final_action": action,
        "boosted_confidence": 0.72,
        "completed_at": _fresh_iso(seconds_ago),
        "trade_decision": {"action": action, "reasoning": "Momentum breakout above IB high."},
        "risk_decision": {"reasoning": "Stop 12 ticks below entry; 0.4% account risk."},
        "fund_decision": {"reasoning": "Conviction supports a single micro contract."},
        "debate_result": {
            "bull_weakest_point": "Volume thinning into the move.",
            "bear_weakest_point": "No macro catalyst against the trend.",
        },
        "analyst_reports": {"technical": {"reasoning": "RSI 61, trend up."}},
        "errors": [],
    }


def test_build_action_assembles_only_existing_reasoning():
    action = build_action(_full_snapshot(), now=NOW)
    assert action is not None
    assert action["symbol"] == "MES"
    assert action["action"] == "buy"
    assert action["confidence"] == 0.72
    assert action["reasoning_available"] is True
    # Every fragment must be a verbatim existing field — nothing invented.
    assert "Momentum breakout above IB high." in action["why"]
    assert "Stop 12 ticks below entry" in action["why"]
    assert "Conviction supports a single micro contract." in action["why"]
    assert "Volume thinning into the move." in action["why"]
    assert "RSI 61, trend up." in action["why"]
    assert set(action["reasoning_sources"]) == {
        "Trade",
        "Risk",
        "Fund",
        "Bull-case weakness",
        "Bear-case weakness",
        "Technical",
    }
    assert action["staleness"]["is_stale"] is False
    assert action["data_degraded"] is False


def test_missing_reasoning_is_flagged_not_fabricated():
    snap = {
        "symbol": "MGC",
        "final_action": "sell",
        "boosted_confidence": 0.55,
        "completed_at": _fresh_iso(10.0),
        # No trade/risk/fund/debate/technical reasoning at all.
    }
    action = build_action(snap, now=NOW)
    assert action is not None
    assert action["reasoning_available"] is False
    assert action["reasoning_sources"] == []
    assert "No reasoning captured" in action["why"]
    assert "Not fabricating" in action["why"]
    # A reasoning-less decision is honestly degraded.
    assert action["data_degraded"] is True


def test_staleness_downgrades_old_decision():
    snap = _full_snapshot(seconds_ago=DEFAULT_STALE_AFTER_S + 60.0)
    action = build_action(snap, now=NOW)
    assert action["staleness"]["is_stale"] is True
    assert action["staleness"]["age_seconds"] > DEFAULT_STALE_AFTER_S
    assert action["data_degraded"] is True


def test_unknown_age_is_degraded():
    snap = _full_snapshot()
    snap.pop("completed_at")
    action = build_action(snap, now=NOW)
    assert action["staleness"]["unknown_age"] is True
    assert action["staleness"]["age_seconds"] is None
    assert action["data_degraded"] is True


def test_build_action_rejects_non_dict():
    assert build_action(None, now=NOW) is None
    assert build_action("not a snapshot", now=NOW) is None


def test_brief_caps_and_dedupes_and_ranks():
    snapshots = [
        _full_snapshot(symbol="MES", action="buy", seconds_ago=30.0),  # newest MES
        _full_snapshot(symbol="MES", action="sell", seconds_ago=200.0),  # dupe symbol -> dropped
        _full_snapshot(symbol="MGC", action="hold", seconds_ago=20.0),  # inert -> ranked last
        _full_snapshot(symbol="QQQ", action="buy", seconds_ago=40.0),
        _full_snapshot(symbol="AAPL", action="buy", seconds_ago=50.0),
    ]
    brief = build_session_brief(snapshots, now=NOW, max_actions=3)
    assert brief["count"] == 3
    symbols = [a["symbol"] for a in brief["actions"]]
    assert symbols.count("MES") == 1  # deduped
    # Actionable (non-hold) come before the hold, so MGC (hold) is excluded by the cap.
    assert "MGC" not in symbols
    assert all(a["action"] != "hold" for a in brief["actions"])


def test_empty_brief_is_honest():
    brief = build_session_brief([], now=NOW)
    assert brief["actions"] == []
    assert brief["count"] == 0
    assert brief["degraded"] is True
    assert brief["note"] and "No recent pipeline snapshots" in brief["note"]


def test_brief_generated_at_is_deterministic_with_now():
    brief = build_session_brief([_full_snapshot()], now=NOW)
    assert brief["generated_at"] == NOW.isoformat()


def test_cross_signals_absent_is_unchanged():
    """Default (no cross_signals arg) must not add the new key -- backward compat."""
    brief = build_session_brief([_full_snapshot()], now=NOW)
    assert "cross_signal_advisories" not in brief


def test_cross_signals_available():
    cross_signals = {
        "available": True,
        "signals": [{"symbol": "ZC", "signal": "buy", "prob_up": 0.61}],
        "error": None,
        "fetched_at": "2026-07-09T12:00:00+00:00",
    }
    brief = build_session_brief([_full_snapshot()], now=NOW, cross_signals=cross_signals)

    advisories = brief["cross_signal_advisories"]
    assert advisories["source"] == "amo-arbitrage"
    assert advisories["available"] is True
    assert advisories["signals"] == cross_signals["signals"]
    assert advisories["note"] is None


def test_cross_signals_unavailable_is_honest_not_fabricated():
    cross_signals = {
        "available": False,
        "signals": [],
        "error": "connection refused",
        "fetched_at": "2026-07-09T12:00:00+00:00",
    }
    brief = build_session_brief([_full_snapshot()], now=NOW, cross_signals=cross_signals)

    advisories = brief["cross_signal_advisories"]
    assert advisories["available"] is False
    assert "signals" not in advisories
    assert advisories["note"] is not None
    assert "not fabricating" in advisories["note"].lower()
