import sys
from pathlib import Path
import os as _os  # noqa: E402
# Box layout mirrors /workspace/tape; override with TAPE_ROOT. Defaults to scripts/tape in the repo.
TAPE_ROOT = Path(_os.environ.get("TAPE_ROOT") or Path(__file__).resolve().parents[2])

ROOT = (TAPE_ROOT / "system")
sys.path.insert(0, str(ROOT))
from checklist import build, render



def test_checklist_lists_missing_or_stale():
    h = build()
    assert "asof_ct" in h
    assert isinstance(h["missing"], list)
    # gamma from state is hours old tonight → should flag stale
    text = render(h)
    assert "PRE-READ CHECKLIST" in text
    assert "Live legal? NO, size 0" in text
