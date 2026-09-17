"""Doc/code agreement for the ALT-path p_edge activation bar.

`engine/CLAUDE.md` states the promotion criterion as:

    p_positive_edge >= 0.6 on a fresh rolling walk-forward run (ALT path)

No runner enforced it until `GATE_P_EDGE_ALT` was introduced (2026-09-17), which is
how `MES_trend_vix_pctile_rank1` could print "PASS via alt" at p_edge = 0.5926.
These tests keep the constant and the documented criterion from drifting apart.
"""

from __future__ import annotations

import re
from pathlib import Path

from backtest._gate_v2_helpers import GATE_P_EDGE, GATE_P_EDGE_ALT

ENGINE_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = ENGINE_ROOT / "CLAUDE.md"

_DOC_CRITERION = re.compile(r"p_positive_edge\s*>=\s*([0-9.]+)")


def test_alt_p_edge_bar_is_the_documented_activation_criterion():
    text = CLAUDE_MD.read_text(encoding="utf-8")
    matches = _DOC_CRITERION.findall(text)
    assert matches, "engine/CLAUDE.md no longer documents a p_positive_edge activation bar"
    documented = {float(m) for m in matches}
    assert GATE_P_EDGE_ALT in documented, (
        f"GATE_P_EDGE_ALT={GATE_P_EDGE_ALT} disagrees with the documented criterion(s) "
        f"{sorted(documented)}; update the constant or the docs together"
    )


def test_alt_bar_is_laxer_than_the_core_bar():
    assert 0.0 < GATE_P_EDGE_ALT < GATE_P_EDGE, (
        "the ALT bar must sit strictly between 0 and the CORE bar"
    )


def test_alt_bar_is_wired_nowhere_yet_is_documented():
    """Guard against a silent partial wiring of the ~65 inline ALT conjunctions.

    Either no runner enforces the bar (the reviewed decision pending in
    docs/research/alt-p-edge-gate-proposal-2026-09-17.md), or all of them do.
    A partial wiring is the failure mode this test exists to catch.
    """
    runners = sorted((ENGINE_ROOT / "backtest").glob("*.py"))
    text_by_path = {p: p.read_text(encoding="utf-8") for p in runners}
    # Exclude the module that DEFINES the constant; it is not a consumer.
    consumers = {
        p: t for p, t in text_by_path.items()
        if "alt_pass" in t
        and "def " in t
        and "GATE_P_EDGE_ALT: float" not in t
        and not p.name.startswith("_gate_v2_helpers")
    }
    enforcing = [p for p, t in consumers.items() if "GATE_P_EDGE_ALT" in t]
    assert len(consumers) > 10, "expected many runners with an ALT conjunction"
    assert not enforcing or len(enforcing) == len(consumers), (
        f"partial wiring of GATE_P_EDGE_ALT: {len(enforcing)} of {len(consumers)} "
        "consumer modules reference it; wire all of them or none"
    )
