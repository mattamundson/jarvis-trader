"""Unit tests for the research-only ThinkScript source-integrity scanner."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCANNER_PATH = (
    Path(__file__).resolve().parents[2]
    / "thinkorswim-scripts"
    / "tools"
    / "thinkscript_integrity_scan.py"
)


def _load_scanner():
    spec = importlib.util.spec_from_file_location("thinkscript_integrity_scan", SCANNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scanner_flags_future_and_chart_global_constructs(tmp_path: Path) -> None:
    scanner = _load_scanner()
    source = tmp_path / "sample.ts"
    source.write_text(
        """
# close[-99] in a comment must not count
plot x = close[-1];
def y = GetTime()[-1];
def z = HighestAll(close);
def q = InertiaAll(close, 7);
def a = ta.atr(14);
def d = 20261224;
def ext = close(\"VIX\");
profile p = TimeProfile();
""",
        encoding="utf-8",
    )

    finding = scanner.scan_file(source)
    assert finding.negative_index_count == 2  # close[-1] + GetTime()[-1]
    assert finding.negative_index_values == [1]
    assert finding.future_calendar_reference_count == 1
    assert finding.highest_all_count == 1
    assert finding.inertia_all_count == 1
    assert finding.profile_primitive_count == 1
    assert finding.hardcoded_date_count == 1
    assert finding.external_symbols == ["VIX"]
    assert finding.pine_style_ta_namespace is True
    assert finding.requires_manual_causal_review is True


def test_scanner_does_not_flag_simple_causal_formula(tmp_path: Path) -> None:
    scanner = _load_scanner()
    source = tmp_path / "causal.ts"
    source.write_text(
        """
def prior = close[1];
def basis = Average(close, 20);
plot signal = close > basis and close > prior;
""",
        encoding="utf-8",
    )

    finding = scanner.scan_file(source)
    assert finding.negative_index_count == 0
    assert finding.future_calendar_reference_count == 0
    assert finding.requires_manual_causal_review is False
