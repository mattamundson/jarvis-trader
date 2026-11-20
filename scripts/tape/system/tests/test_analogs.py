import sys
from pathlib import Path
import os as _os  # noqa: E402
# Box layout mirrors /workspace/tape; override with TAPE_ROOT. Defaults to scripts/tape in the repo.
TAPE_ROOT = Path(_os.environ.get("TAPE_ROOT") or Path(__file__).resolve().parents[2])

ROOT = (TAPE_ROOT / "system")
sys.path.insert(0, str(ROOT))
from analogs import SessionFeat, find_analogs, summarize



def test_analog_distance_prefers_similar_range():
    q = SessionFeat("2026-11-06", 7400, 7320, 80, 0.3, 28.0, 1, None, 7388, None, None, None)
    lib = [
        SessionFeat("2026-01-01", 5000, 4950, 50, 0.3, 28.0, 1, None, 4970, 1.0, 2.0, 3.0),
        SessionFeat("2026-01-02", 7400, 7320, 80, 0.31, 27.5, 1, None, 7380, -1.0, -2.0, 5.0),
        SessionFeat("2026-01-03", 6000, 5900, 100, 0.8, 15.0, 0, None, 5950, 10.0, 20.0, 30.0),
    ]
    top = find_analogs(q, lib, k=2)
    assert top[0][1].session_date == "2026-01-02"
    s = summarize(top)
    assert s["n_analogs"] == 2
    assert s["outcome_1h"]["n"] == 2
