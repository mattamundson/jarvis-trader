"""Halted instruments must never render as actionable in ANY dashboard app.

WHY: ``dashboard/`` was split into ``dashboard/apps/{trading-desk,research-lab,
ops-console}``, each carrying its own copy of the shared App Router pages. Those
copies were forked from an older root revision, so safety/honesty fixes that had
already landed in ``dashboard/app/`` silently reverted inside the sub-apps.

The concrete regression this guards: ``apps/research-lab/app/watchlist/page.tsx``
lost the ``DO_NOT_TRADE_SYMBOLS`` gate entirely, so MCL/MNQ/M2K rendered plain
BUY/SELL badges and MNQ's instrument card read ``"RESEARCH"`` instead of
``"DO NOT TRADE"`` -- the same inverted-status defect D2-02 fixed at the root a
month earlier.

The engine is the real authority (``SafetyLayer.check_order`` hard-blocks orders
for these symbols regardless of what any UI says), but a green BUY badge on a
halted instrument is a status-honesty defect in a trading UI, and this repo has
now shipped that same defect three separate times.

This lives in the engine suite rather than ``dashboard/tests/`` deliberately: it
asserts against ``backtest.signals.DO_NOT_TRADE_SYMBOLS`` itself, so there is no
hand-copied symbol fixture to drift. ``dashboard/tests/symbol-status-halt-parity
.node.test.ts`` covers the TS-internal half of the same invariant.
"""
import re
from pathlib import Path

import pytest

from backtest.signals import DO_NOT_TRADE_SYMBOLS

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = REPO_ROOT / "dashboard"
APPS_DIR = DASHBOARD / "apps"

# The only status string an INSTRUMENT_SPECS entry for a halted symbol may carry.
HALTED_STATUS = "DO NOT TRADE"

# An INSTRUMENT_SPECS-style entry: symbol -> exchange -> status within one object
# literal. The ``exchange:`` anchor is what makes this specific to the live
# instrument-reference cards ("this is the instrument and what it is cleared to
# do right now"). It deliberately does NOT match historical backtest-result rows
# (e.g. BACKTEST_RANKS in app/performance/page.tsx), whose ``status`` records the
# verdict of a past WFO run and must not be retro-edited to today's truth -- that
# page's separate present-tense honesty problem is tracked on its own.
_SPEC_RE = re.compile(
    r'symbol:\s*"([A-Z0-9]+)"[\s\S]{0,300}?exchange:\s*"[^"]*"[\s\S]{0,300}?status:\s*"([^"]+)"'
)
_HALTED_LIST_RE = re.compile(r"HALTED_SYMBOLS\s*=\s*\[([^\]]*)\]")


pytestmark = pytest.mark.skipif(
    not DASHBOARD.is_dir(), reason="dashboard/ not present in this checkout"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _subdirs(path: Path) -> list[Path]:
    return sorted(p for p in path.iterdir() if p.is_dir()) if path.is_dir() else []


def _duplicated_pages() -> list[tuple[str, Path, Path]]:
    """(label, sub_app_page, root_page) for every route both trees define."""
    pairs: list[tuple[str, Path, Path]] = []
    for app in _subdirs(APPS_DIR):
        for route in _subdirs(app / "app"):
            sub_page = route / "page.tsx"
            root_page = DASHBOARD / "app" / route.name / "page.tsx"
            if sub_page.is_file() and root_page.is_file():
                pairs.append((f"apps/{app.name}/app/{route.name}", sub_page, root_page))
    return pairs


def _all_pages() -> list[tuple[str, Path]]:
    """(label, page.tsx) for every App Router page, root and sub-app alike."""
    pages = [
        (f"app/{route.name}", route / "page.tsx")
        for route in _subdirs(DASHBOARD / "app")
        if (route / "page.tsx").is_file()
    ]
    pages += [(label, page) for label, page, _ in _duplicated_pages()]
    return pages


def test_sub_app_pages_keep_the_halt_gate_their_root_counterpart_has():
    pairs = _duplicated_pages()
    # Guard the guard: an empty set would make this test vacuously green if the
    # sub-app layout is ever restructured away.
    assert pairs, "expected at least one duplicated apps/*/app/<route>/page.tsx"

    regressions = [
        f"{label}/page.tsx dropped the DO_NOT_TRADE_SYMBOLS gate that "
        f"app/{root_page.parent.name}/page.tsx still has"
        for label, sub_page, root_page in pairs
        if "DO_NOT_TRADE_SYMBOLS" in _read(root_page)
        and "DO_NOT_TRADE_SYMBOLS" not in _read(sub_page)
    ]
    assert regressions == []


def test_no_dashboard_page_labels_a_halted_instrument_as_tradeable():
    violations = []
    for label, page in _all_pages():
        for symbol, status in _SPEC_RE.findall(_read(page)):
            if symbol in DO_NOT_TRADE_SYMBOLS and status != HALTED_STATUS:
                violations.append(
                    f'{label}/page.tsx: {symbol} has status "{status}", '
                    f'expected "{HALTED_STATUS}"'
                )
    assert violations == []


def test_research_lab_watchlist_gates_both_render_paths():
    """Lock the two call sites that previously rendered a plain BUY/SELL badge.

    The scan widget branches on ``isHalted``; the signal table threads ``halted``
    into ``SignalBadge``. Losing either one is what put a directional badge on a
    halted instrument, so a presence check on the constant alone is not enough.
    """
    source = _read(APPS_DIR / "research-lab" / "app" / "watchlist" / "page.tsx")
    assert "const isHalted = DO_NOT_TRADE_SYMBOLS.has(" in source
    assert "halted={DO_NOT_TRADE_SYMBOLS.has(" in source


def test_every_halted_symbols_list_matches_the_engine_blocklist():
    """Each TS copy of HALTED_SYMBOLS mirrors the engine set exactly."""
    sources = sorted(DASHBOARD.glob("lib/approvedSymbols.ts")) + sorted(
        APPS_DIR.glob("*/lib/approvedSymbols.ts")
    )
    assert sources, "expected at least one lib/approvedSymbols.ts"

    mismatches = []
    for src in sources:
        match = _HALTED_LIST_RE.search(_read(src))
        rel = src.relative_to(REPO_ROOT).as_posix()
        if match is None:
            mismatches.append(f"{rel}: no HALTED_SYMBOLS literal found")
            continue
        listed = set(re.findall(r'"([^"]+)"', match.group(1)))
        if listed != set(DO_NOT_TRADE_SYMBOLS):
            mismatches.append(
                f"{rel}: HALTED_SYMBOLS={sorted(listed)} != "
                f"engine DO_NOT_TRADE_SYMBOLS={sorted(DO_NOT_TRADE_SYMBOLS)}"
            )
    assert mismatches == []
