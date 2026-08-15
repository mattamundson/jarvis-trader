"""The GT-08 100x-drawdown-understatement bug must not exist in any dashboard copy.

WHY: ``fmtPct`` once carried an "already in percent form" branch::

    if (Math.abs(val) > 2) return `${val.toFixed(1)}%`;

``GET /portfolio/paper/account/{id}/stats`` always returns ``max_dd`` as a true
fraction of running peak and never pre-multiplies by 100, so that branch silently
divided any real drawdown with ``|val| > 2`` by 100 -- a ``-2.0032`` max_dd
(-200.32%) rendered as ``-2.0%``. GT-08 (#570) removed it and moved the helpers
into ``dashboard/lib/parallelPaperFormat.ts``.

Splitting ``dashboard/`` into ``dashboard/apps/*`` then re-introduced the bug:
``apps/trading-desk/app/parallel-paper/page.tsx`` was forked from a pre-GT-08
revision and carried its own inlined copy of the old, buggy ``fmtPct``. A
trading dashboard understating drawdown by 100x is the exact "confidently wrong
number" failure this repo cares most about, so it gets a mechanical guard rather
than another round of "we fixed it at the root".
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = REPO_ROOT / "dashboard"
ROOT_FORMAT_LIB = DASHBOARD / "lib" / "parallelPaperFormat.ts"

# The removed percent-passthrough branch, tolerant of whitespace/quoting style.
_GT08_BUG_RE = re.compile(r"Math\.abs\(val\)\s*>\s*2\s*\)\s*return")


pytestmark = pytest.mark.skipif(
    not DASHBOARD.is_dir(), reason="dashboard/ not present in this checkout"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _code_only(source: str) -> str:
    """Drop whole-line comments so prose *describing* the old branch is not a hit.

    Both format libs and the node unit test quote the removed branch verbatim in
    a header comment; matching those would make the guard permanently red.
    """
    return "\n".join(
        line
        for line in source.splitlines()
        if not line.lstrip().startswith(("//", "*", "/*"))
    )


def _dashboard_sources() -> list[Path]:
    """Every hand-written dashboard .ts/.tsx, excluding dependencies and build output."""
    skip = {"node_modules", ".next", "dist", "build"}
    return [
        p
        for p in DASHBOARD.rglob("*.ts*")
        if p.suffix in {".ts", ".tsx"} and not skip & set(p.parts)
    ]


def test_no_dashboard_copy_reintroduces_the_gt08_percent_passthrough():
    offenders = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in _dashboard_sources()
        if _GT08_BUG_RE.search(_code_only(_read(p)))
    ]
    assert offenders == [], (
        "these files carry the pre-GT-08 fmtPct percent-passthrough branch, which "
        "understates any drawdown fraction with |val| > 2 by 100x"
    )


def test_every_parallel_paper_format_copy_matches_the_root_lib():
    """Sub-app copies of the format helpers stay byte-identical to the root lib.

    Line endings are normalised: the sub-app tree is LF, the root tree is CRLF.
    """
    assert ROOT_FORMAT_LIB.is_file(), f"missing {ROOT_FORMAT_LIB}"
    expected = _read(ROOT_FORMAT_LIB).replace("\r\n", "\n")

    copies = sorted((DASHBOARD / "apps").glob("*/lib/parallelPaperFormat.ts"))
    assert copies, "expected at least one apps/*/lib/parallelPaperFormat.ts"

    drifted = [
        c.relative_to(REPO_ROOT).as_posix()
        for c in copies
        if _read(c).replace("\r\n", "\n") != expected
    ]
    assert drifted == []


def test_root_fmt_pct_always_scales_by_one_hundred():
    """Lock the corrected shape of the helper the sub-apps are compared against.

    Without this, a regression at the root would silently propagate to every
    copy via the parity test above and still be "green".
    """
    source = _read(ROOT_FORMAT_LIB)
    assert _GT08_BUG_RE.search(_code_only(source)) is None
    assert "(val * 100).toFixed(1)" in source
