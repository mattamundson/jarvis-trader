from datetime import UTC, datetime, timedelta
from pathlib import Path
import json

import pytest

from morning_alpha.cli import main
from morning_alpha.research.campaign import (
    ResearchCampaignSpec,
    inspect_research_files,
    require_research_ready,
)


def _manifest(**overrides):
    now = datetime(2026, 9, 15, tzinfo=UTC)
    data = {
        "manifest_version": "1.0.0",
        "generated_at": now.isoformat(),
        "providers": ["fixture"],
        "daily_symbol_count": 800,
        "intraday_symbol_count": 250,
        "earliest_daily_timestamp": (now - timedelta(days=365 * 10)).isoformat(),
        "latest_daily_timestamp": now.isoformat(),
        "earliest_intraday_timestamp": (now - timedelta(days=365 * 8)).isoformat(),
        "latest_intraday_timestamp": now.isoformat(),
        "point_in_time_universe": True,
        "delisted_symbols": True,
        "corporate_actions": True,
        "sector_history": True,
        "earnings_events": True,
        "macro_context": True,
        "source_lineage": True,
        "premarket_bars": True,
    }
    data.update(overrides)
    return data


def _dataset(tmp_path: Path, manifest: dict | None = None) -> Path:
    root = tmp_path / "research"
    bars = root / "bars"
    bars.mkdir(parents=True)
    (bars / "SPY.parquet").write_bytes(b"fixture")
    if manifest is not None:
        (root / "research_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_parquet_files_alone_are_only_file_stage_ready(tmp_path: Path):
    report = inspect_research_files(_dataset(tmp_path))
    assert report.file_stage_ready is True
    assert report.ready is False
    assert "MANIFEST_MISSING" in report.reasons


def test_complete_manifest_marks_campaign_ready(tmp_path: Path):
    report = inspect_research_files(_dataset(tmp_path, _manifest()))
    assert report.ready is True
    assert report.manifest_present is True
    assert report.daily_symbol_count == 800
    assert report.intraday_symbol_count == 250
    assert report.providers == ("fixture",)
    assert report.reasons == ()


def test_manifest_fails_closed_on_survivorship_and_lineage_gaps(tmp_path: Path):
    report = inspect_research_files(
        _dataset(
            tmp_path,
            _manifest(delisted_symbols=False, source_lineage=False),
        )
    )
    assert report.ready is False
    assert "DELISTED_SYMBOLS_MISSING" in report.reasons
    assert "SOURCE_LINEAGE_MISSING" in report.reasons
    with pytest.raises(RuntimeError, match="research data not ready"):
        require_research_ready(report)


def test_manifest_enforces_pre_registered_coverage_thresholds(tmp_path: Path):
    report = inspect_research_files(
        _dataset(
            tmp_path,
            _manifest(daily_symbol_count=499, intraday_symbol_count=99),
        )
    )
    assert report.ready is False
    assert "DAILY_SYMBOL_COVERAGE_LOW" in report.reasons
    assert "INTRADAY_SYMBOL_COVERAGE_LOW" in report.reasons


def test_manifest_enforces_history_span(tmp_path: Path):
    now = datetime(2026, 9, 15, tzinfo=UTC)
    report = inspect_research_files(
        _dataset(
            tmp_path,
            _manifest(earliest_daily_timestamp=(now - timedelta(days=365 * 2)).isoformat()),
        )
    )
    assert report.ready is False
    assert "DAILY_HISTORY_SPAN_TOO_SHORT" in report.reasons


def test_cli_research_data_check_returns_two_when_not_ready(tmp_path: Path, capsys):
    root = _dataset(tmp_path)
    rc = main(["research-data-check", "--data-root", str(root), "--json"])
    out = capsys.readouterr().out
    assert rc == 2
    payload = json.loads(out)
    assert payload["ready"] is False
    assert "MANIFEST_MISSING" in payload["reasons"]


def test_cli_research_data_check_returns_zero_when_ready(tmp_path: Path, capsys):
    root = _dataset(tmp_path, _manifest())
    rc = main(["research-data-check", "--data-root", str(root), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ready"] is True


def test_cli_campaign_plan_is_machine_readable(capsys):
    rc = main(["research-campaign-plan", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["campaign_id"] == "morning_alpha_v1"
    assert payload["min_daily_symbols"] == 500
    assert payload["min_intraday_symbols"] == 100
    assert payload["min_history_years"] == 8
    assert payload["strategies"][0]["strategy_id"] == "relative_strength_breakout"
