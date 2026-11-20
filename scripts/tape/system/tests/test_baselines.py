import sys
from datetime import datetime, timedelta
from pathlib import Path
import os as _os  # noqa: E402
# Box layout mirrors /workspace/tape; override with TAPE_ROOT. Defaults to scripts/tape in the repo.
TAPE_ROOT = Path(_os.environ.get("TAPE_ROOT") or Path(__file__).resolve().parents[2])
from zoneinfo import ZoneInfo

ROOT = (TAPE_ROOT / "system")
sys.path.insert(0, str(ROOT))
from grade_calls import grade_one
from lib.prices import Bar


CT = ZoneInfo("America/Chicago")


def test_prior_range_baseline_fields_present():
    start = datetime(2026, 11, 5, 21, 0, tzinfo=CT)
    bars = []
    px = 7380.0
    for i in range(40):
        ts = start + timedelta(minutes=i)
        bars.append(Bar(ts=ts, o=px, h=px + 1, l=px - 1, c=px + 0.25, v=1))
        px += 0.25
    call = {
        "id": "b1",
        "ts_ct": "2026-11-05 21:00",
        "bias": "bullish",
        "lean_pct": {"up": 55, "down": 45},
        "named_levels": {},
        "triggers": [],
        "invalidation": {"level": 7300, "rule": "x"},
        "data_freshness": {"gamma_stale": True, "missing": []},
        "setup_type": "test",
        "price_at_call": 7380.0,
    }
    # prior range far above current → baseline should miss (price outside)
    prior = {"date": "2026-11-04", "high": 7746.0, "low": 7679.0, "close": 7734.0}
    g = grade_one(call, bars, bars, prior_range=prior)
    psr = g["grades"]["plus_30m"]["prior_session_range"]
    assert psr["inside_prior_range"] is False
    assert g["grades"]["plus_30m"]["edge_vs_prior_range"] in {
        "beat_prior_range_baseline", "lost_to_prior_range_baseline", "tied_both_hit", "both_miss"
    }
    assert "beat_no_change_baseline" in g["grades"]["plus_30m"]
