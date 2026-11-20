import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
import os as _os  # noqa: E402
# Box layout mirrors /workspace/tape; override with TAPE_ROOT. Defaults to scripts/tape in the repo.
TAPE_ROOT = Path(_os.environ.get("TAPE_ROOT") or Path(__file__).resolve().parents[2])
from zoneinfo import ZoneInfo

ROOT = (TAPE_ROOT / "system")
sys.path.insert(0, str(ROOT))
from grade_calls import grade_one, hit_rate_report
from lib.prices import Bar


CT = ZoneInfo("America/Chicago")


def _synth_bars(start, n=90, start_px=7390.0, step=0.25):
    bars = []
    px = start_px
    for i in range(n):
        ts = start + timedelta(minutes=i)
        o = px
        c = px + step
        bars.append(Bar(ts=ts, o=o, h=max(o, c) + 0.5, l=min(o, c) - 0.5, c=c, v=10))
        px = c
    return bars


def test_bullish_hit_on_up_move():
    start = datetime(2026, 11, 5, 21, 0, tzinfo=CT)
    bars = _synth_bars(start, step=0.5)
    call = {
        "id": "t1",
        "ts_ct": "2026-11-05 21:00",
        "bias": "bullish",
        "lean_pct": {"up": 55, "down": 45},
        "named_levels": {},
        "triggers": [{"side": "long", "level": 7400, "confirm": "5m_close"}],
        "invalidation": {"level": 7380, "rule": "x"},
        "data_freshness": {"gamma_stale": True, "missing": []},
        "setup_type": "test",
        "price_at_call": 7390.0,
    }
    g = grade_one(call, bars, bars, prior_range={"date": "2026-11-04", "high": 7800, "low": 7600, "close": 7700})
    assert g["grades"]["plus_30m"]["hit"] == "HIT"
    assert g["grades"]["plus_30m"]["mfe_pts"] >= 0


def test_bearish_miss_on_up_move():
    start = datetime(2026, 11, 5, 21, 0, tzinfo=CT)
    bars = _synth_bars(start, step=0.5)
    call = {
        "id": "t2",
        "ts_ct": "2026-11-05 21:00",
        "bias": "bearish",
        "lean_pct": {"up": 40, "down": 60},
        "named_levels": {},
        "triggers": [],
        "invalidation": {"level": 7400, "rule": "x"},
        "data_freshness": {"gamma_stale": True, "missing": []},
        "setup_type": "test",
        "price_at_call": 7390.0,
    }
    g = grade_one(call, bars, bars, prior_range=None)
    assert g["grades"]["plus_30m"]["hit"] == "MISS"


def test_hit_rate_buckets():
    graded = [
        {"hour_of_night": "21", "setup_type": "a", "grades": {"plus_30m": {"status": "GRADED", "hit": "HIT"}}},
        {"hour_of_night": "21", "setup_type": "a", "grades": {"plus_30m": {"status": "GRADED", "hit": "MISS"}}},
        {"hour_of_night": "22", "setup_type": "b", "grades": {"plus_30m": {"status": "GRADED", "hit": "HIT"}}},
    ]
    r = hit_rate_report(graded, "plus_30m")
    assert r["overall"]["n"] == 3
    assert r["overall"]["hits"] == 2
    assert r["by_hour_of_night_ct"]["21"]["n"] == 2
