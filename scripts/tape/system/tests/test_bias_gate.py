import sys
from datetime import datetime
from pathlib import Path
import os as _os  # noqa: E402
# Box layout mirrors /workspace/tape; override with TAPE_ROOT. Defaults to scripts/tape in the repo.
TAPE_ROOT = Path(_os.environ.get("TAPE_ROOT") or Path(__file__).resolve().parents[2])
from zoneinfo import ZoneInfo

ROOT = (TAPE_ROOT / "system")
sys.path.insert(0, str(ROOT))
from bias_gate import evaluate
from lib.prices import Bar


CT = ZoneInfo("America/Chicago")


def _bars_flat(close=7388.0):
    # 5m bars covering a closed 15m ending 22:00
    out = []
    base = datetime(2026, 11, 5, 21, 45, tzinfo=CT)
    for i in range(6):
        ts = base.replace(minute=45) if i == 0 else datetime(2026, 11, 5, 21 + (45 + 5 * i) // 60,
                                                             (45 + 5 * i) % 60, tzinfo=CT)
        # simpler: explicit list
    explicit = [
        datetime(2026, 11, 5, 21, 45, tzinfo=CT),
        datetime(2026, 11, 5, 21, 50, tzinfo=CT),
        datetime(2026, 11, 5, 21, 55, tzinfo=CT),  # 15m 21:45-22:00 closes 7388
        datetime(2026, 11, 5, 22, 0, tzinfo=CT),
        datetime(2026, 11, 5, 22, 5, tzinfo=CT),
        datetime(2026, 11, 5, 22, 10, tzinfo=CT),
    ]
    return [Bar(ts=t, o=close, h=close + 1, l=close - 1, c=close, v=100) for t in explicit]


def test_blocks_bearish_without_15m_close_beyond_level():
    state = {"bias": "neutral", "named_levels": {"break_up": 7392.0, "break_down": 7383.0}}
    bars = _bars_flat(7388.0)  # above break_down
    asof = datetime(2026, 11, 5, 22, 5, tzinfo=CT)
    r = evaluate(state, "bearish", asof, bars_5m=bars)
    assert r["changed"] is False
    assert r["allowed_bias"] == "neutral"
    assert "keep prior" in r["reason"] or "break_down" in r["reason"]


def test_allows_bearish_on_15m_close_through_break_down():
    state = {"bias": "neutral", "named_levels": {"break_up": 7392.0, "break_down": 7383.0}}
    # 15m close at 22:00 = 7380 <= 7383
    closes = {
        datetime(2026, 11, 5, 21, 45, tzinfo=CT): 7385.0,
        datetime(2026, 11, 5, 21, 50, tzinfo=CT): 7382.0,
        datetime(2026, 11, 5, 21, 55, tzinfo=CT): 7380.0,
        datetime(2026, 11, 5, 22, 0, tzinfo=CT): 7380.0,
        datetime(2026, 11, 5, 22, 5, tzinfo=CT): 7379.0,
    }
    bars = [Bar(ts=t, o=c, h=c + 1, l=c - 1, c=c, v=10) for t, c in closes.items()]
    asof = datetime(2026, 11, 5, 22, 5, tzinfo=CT)
    r = evaluate(state, "bearish", asof, bars_5m=bars)
    assert r["changed"] is True
    assert r["allowed_bias"] == "bearish"


def test_neutral_always_allowed():
    state = {"bias": "bullish", "named_levels": {"break_up": 7392.0, "break_down": 7383.0}}
    bars = _bars_flat(7390.0)
    asof = datetime(2026, 11, 5, 22, 5, tzinfo=CT)
    r = evaluate(state, "neutral", asof, bars_5m=bars)
    assert r["allowed_bias"] == "neutral"
    assert r["changed"] is True
