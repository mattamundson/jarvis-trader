import json
import sys
from pathlib import Path

import os as _os  # noqa: E402
# Box layout mirrors /workspace/tape; override with TAPE_ROOT. Defaults to scripts/tape in the repo.
TAPE_ROOT = Path(_os.environ.get("TAPE_ROOT") or Path(__file__).resolve().parents[2])

ROOT = (TAPE_ROOT / "system")
sys.path.insert(0, str(ROOT))


def test_event_calendar_has_nfp_tomorrow():
    cal = json.loads((ROOT / "data" / "event_calendar.json").read_text(encoding="utf-8"))
    nfp = [e for e in cal["events"] if e["name"] == "NFP" and e["date"] == "2026-11-06"]
    assert nfp and nfp[0]["time_ct"] == "07:30"


def test_event_stats_marks_sample_size():
    # lightweight: distributions always include n
    from event_stats import _distro
    d = _distro([{"delta": 1.0, "range": 5.0}, {"delta": -2.0, "range": 8.0}])
    assert d["n"] == 2
    assert "median_delta" in d
