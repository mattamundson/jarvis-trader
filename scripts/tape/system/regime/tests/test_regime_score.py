from pathlib import Path
import json
from regime_score import parse_context, compute_raw_score, raw_to_display, score_today, Inputs

import os as _os  # noqa: E402
# Box layout mirrors /workspace/tape; override with TAPE_ROOT. Defaults to scripts/tape in the repo.
TAPE_ROOT = Path(_os.environ.get("TAPE_ROOT") or Path(__file__).resolve().parents[3])


# Frozen 2026-11-06 00:07 CT pre-NFP snapshot (the read findings.md documents).
CONTEXT = Path(__file__).resolve().parent / "fixtures" / "es-context-20261106-0007.md"


def test_parse_context_has_vix_and_ovn():
    assert CONTEXT.exists()
    inp = parse_context(CONTEXT.read_text(encoding="utf-8"))
    assert inp.vix_prior is not None
    assert inp.ovn_range is not None
    assert inp.session_date == "2026-11-06"
    assert inp.is_nfp == 1


def test_score_nfp_day_elevated():
    inp = Inputs(
        session_date="2026-11-06",
        dow=4,  # Friday
        vix_prior=28.18,
        vix9=32.66,
        vix_chg=11.57,
        ovn_range=94.75,
        avg_range_20=100.0,
        gap_in_range=1,
        gap_prior_range=0.1,
        is_event=1,
        is_nfp=1,
        gex_stale=True,
        gex_net_b=-51.72,
        notes=[],
    )
    raw, fired, caveats = compute_raw_score(inp)
    # event +2, vix_spike -1 (chg>=2), VIX>=25 → 0 pts
    assert any(f["rule"] == "event_day" for f in fired)
    assert any(f["rule"] == "vix_spike" for f in fired)
    assert any("VIX>=25" in c for c in caveats)
    assert raw_to_display(raw) >= 0


def test_score_today_runs():
    out = score_today(CONTEXT)
    assert out["session_date"] == "2026-11-06"
    assert "display_score_0_10" in out
    assert out["Live legal?"] == "NO, size 0"
    assert isinstance(out["fired_rules"], list)


def test_vix_high_no_points():
    inp = Inputs(session_date="x", vix_prior=30.0, notes=[])
    raw, fired, caveats = compute_raw_score(inp)
    assert not any(f["rule"].startswith("vix_") and f["pts"] > 0 and "25" in f["rule"] for f in fired)
    assert any("VIX>=25" in c for c in caveats)
