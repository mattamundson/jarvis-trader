from morning_alpha.cli import main
from morning_alpha.research.attribution import EdgeAttributionEngine
from morning_alpha.research.campaign import DataReadinessReport
from morning_alpha.research.relative_strength_sprint import RelativeStrengthSprintReport, SprintStatus
from morning_alpha.reporting.edge_research_report import EDGE_RESEARCH_SECTION_ORDER, render_edge_research_report


def report(status=SprintStatus.INSUFFICIENT_DATA):
    return RelativeStrengthSprintReport(
        strategy_key="relative_strength_breakout@1.0.0",
        status=status,
        control_counts={
            "random_universe": 1,
            "random_same_sector": 1,
            "next_open": 1,
            "spy": 1,
            "sector_etf": 1,
        },
        control_symbols={
            "random_universe": "BBB",
            "random_same_sector": "CCC",
            "next_open": "AAA",
            "spy": "SPY",
            "sector_etf": "XLK",
        },
        forward_returns={
            "strategy": 0.12,
            "random_universe": 0.03,
            "random_same_sector": 0.04,
            "next_open": 0.08,
            "spy": 0.02,
            "sector_etf": 0.05,
        },
        attribution=EdgeAttributionEngine().attribute(0.12, 0.08, 0.05, 0.02),
        trial_ids=("a" * 64,),
        reasons=("FULL_VALIDATION_STAGES_PENDING",),
    )


def test_report_contains_required_sections_in_order():
    text = render_edge_research_report(report())
    offsets = [text.index(section) for section in EDGE_RESEARCH_SECTION_ORDER]
    assert offsets == sorted(offsets)
    assert "relative_strength_breakout@1.0.0" in text
    assert "INSUFFICIENT_DATA" in text


def test_report_exposes_selection_and_timing_attribution_without_pass_claim():
    text = render_edge_research_report(report())
    assert "selection_increment" in text
    assert "timing_increment" in text
    assert "GATE V2\nPending full validation stage." in text
    assert "CONCLUSION\nINSUFFICIENT_DATA" in text
    assert "CONCLUSION\nPASS" not in text


def test_cli_blocks_before_handler_when_research_data_is_not_ready(tmp_path, capsys):
    called = []
    rc = main(
        ["research-relative-strength", "--data-root", str(tmp_path / "missing")],
        relative_strength_handler=lambda root: called.append(root) or report(),
    )
    out = capsys.readouterr().out
    assert rc == 2
    assert called == []
    assert "BLOCKED" in out


def test_cli_insufficient_data_report_returns_exit_2(monkeypatch, tmp_path, capsys):
    ready = DataReadinessReport(
        ready=True,
        file_stage_ready=True,
        manifest_present=True,
        root=str(tmp_path),
        file_count=1,
        symbols=("AAA",),
        providers=("fixture",),
        daily_symbol_count=500,
        intraday_symbol_count=100,
        reasons=(),
    )
    monkeypatch.setattr("morning_alpha.cli.inspect_research_files", lambda _root: ready)

    rc = main(
        ["research-relative-strength", "--data-root", str(tmp_path)],
        relative_strength_handler=lambda _root: report(),
    )
    out = capsys.readouterr().out
    assert rc == 2
    assert "CONCLUSION\nINSUFFICIENT_DATA" in out
