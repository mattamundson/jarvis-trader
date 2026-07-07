"""Tests for scripts/analyze_jarvis_log.py — JARVIS ask-log daily aggregator."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

# Load the script as a module via its absolute path so tests run correctly
# regardless of pytest rootdir (which is engine/ due to pyproject.toml there).
_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "analyze_jarvis_log.py"
_spec = importlib.util.spec_from_file_location("analyze_jarvis_log", _SCRIPT_PATH)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

aggregate = _mod.aggregate
load_records = _mod.load_records
main = _mod.main
render_markdown = _mod.render_markdown
write_daily_file = _mod.write_daily_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    intent: str = "market_analysis",
    elapsed_ms: int = 800,
    sources_count: int = 3,
    actions_count: int = 1,
    target_date: date | None = None,
    hour: int = 10,
) -> dict:
    if target_date is None:
        target_date = date(2026, 5, 19)
    ts = datetime(
        target_date.year, target_date.month, target_date.day, hour, 0, 0, tzinfo=timezone.utc
    )
    return {
        "timestamp": ts.isoformat(),
        "question_hash": "abc123",
        "intent": intent,
        "elapsed_ms": elapsed_ms,
        "sources_count": sources_count,
        "actions_count": actions_count,
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------------------
# test_aggregation_basic
# ---------------------------------------------------------------------------


class TestAggregationBasic:
    """Synthetic JSONL → correct counts and statistics."""

    def test_intent_counts(self):
        target = date(2026, 5, 19)
        records = [
            _make_record("market_analysis", elapsed_ms=500, target_date=target),
            _make_record("market_analysis", elapsed_ms=700, target_date=target),
            _make_record("position_query", elapsed_ms=300, target_date=target),
            _make_record("unknown", elapsed_ms=1200, target_date=target),
            _make_record("refused", elapsed_ms=200, target_date=target),
        ]
        agg = aggregate(records, target)

        assert agg["request_count"] == 5
        assert agg["intent_counts"]["market_analysis"] == 2
        assert agg["intent_counts"]["position_query"] == 1
        assert agg["intent_counts"]["unknown"] == 1
        assert agg["intent_counts"]["refused"] == 1

    def test_unknown_rate(self):
        target = date(2026, 5, 19)
        records = [
            _make_record("unknown", target_date=target),
            _make_record("market_analysis", target_date=target),
            _make_record("market_analysis", target_date=target),
            _make_record("market_analysis", target_date=target),
        ]
        agg = aggregate(records, target)
        assert agg["unknown_rate"] == pytest.approx(0.25, abs=1e-4)

    def test_refused_rate(self):
        target = date(2026, 5, 19)
        records = [
            _make_record("refused", target_date=target),
            _make_record("refused", target_date=target),
            _make_record("market_analysis", target_date=target),
        ]
        agg = aggregate(records, target)
        assert agg["refused_rate"] == pytest.approx(2 / 3, abs=1e-4)

    def test_latency_percentiles(self):
        target = date(2026, 5, 19)
        # 10 records, values 100..1000 in steps of 100
        records = [
            _make_record("market_analysis", elapsed_ms=v * 100, target_date=target)
            for v in range(1, 11)
        ]
        agg = aggregate(records, target)
        # p50 of [100,200,...,1000]: idx = 0.50 * 9 = 4.5 → between idx 4 (500) and 5 (600)
        # 500 + (600-500)*0.5 = 550
        assert agg["p50_ms"] == 550
        # p95 of 10 values: idx = 0.95 * 9 = 8.55 (float ~8.5499...) → lo=8 (900), hi=9 (1000)
        # frac = 8.5499... - 8 = 0.5499... → int(900 + 100 * 0.5499...) = int(954.99...) = 954
        assert agg["p95_ms"] == 954

    def test_zero_unknown_and_refused(self):
        target = date(2026, 5, 19)
        records = [
            _make_record("market_analysis", target_date=target),
            _make_record("position_query", target_date=target),
        ]
        agg = aggregate(records, target)
        assert agg["unknown_rate"] == 0.0
        assert agg["refused_rate"] == 0.0

    def test_filters_other_dates(self, tmp_path):
        """Records from other dates are excluded from the aggregate."""
        target = date(2026, 5, 19)
        other = date(2026, 5, 18)
        records = [
            _make_record("market_analysis", target_date=target),
            _make_record("position_query", target_date=other),
        ]
        log_path = tmp_path / "jarvis_ask.log"
        _write_jsonl(log_path, records)
        loaded = load_records(log_path, target)
        assert len(loaded) == 1
        assert loaded[0]["intent"] == "market_analysis"


# ---------------------------------------------------------------------------
# test_writes_daily_md
# ---------------------------------------------------------------------------


class TestWritesDailyMd:
    """Aggregator writes correct file shape and valid frontmatter."""

    def test_file_created_at_correct_path(self, tmp_path):
        target = date(2026, 5, 19)
        log_path = tmp_path / "jarvis_ask.log"
        output_dir = tmp_path / "wiki" / "jarvis-daily-log"

        records = [
            _make_record("market_analysis", elapsed_ms=600, target_date=target),
            _make_record("position_query", elapsed_ms=400, target_date=target),
            _make_record("unknown", elapsed_ms=1500, target_date=target),
        ]
        _write_jsonl(log_path, records)

        loaded = load_records(log_path, target)
        agg = aggregate(loaded, target)
        content = render_markdown(agg)
        out_path = write_daily_file(content, output_dir, target)

        assert out_path == output_dir / "2026-05-19.md"
        assert out_path.exists()

    def test_frontmatter_fields_present(self, tmp_path):
        target = date(2026, 5, 19)
        records = [
            _make_record("market_analysis", elapsed_ms=800, target_date=target),
            _make_record("unknown", elapsed_ms=1200, target_date=target),
        ]
        agg = aggregate(records, target)
        content = render_markdown(agg)

        assert 'source: "jarvis-ask-log"' in content
        assert 'kind: "daily-aggregate"' in content
        assert f'date: "{target.isoformat()}"' in content
        assert "request_count: 2" in content
        assert "unknown_rate:" in content
        assert "refused_rate:" in content
        assert "p50_ms:" in content
        assert "p95_ms:" in content
        assert "- jarvis-ask" in content
        assert "- self-improving-loop" in content
        assert "- daily-log" in content

    def test_body_has_intent_table_and_summary(self, tmp_path):
        target = date(2026, 5, 19)
        records = [_make_record("market_analysis", target_date=target)]
        agg = aggregate(records, target)
        content = render_markdown(agg)

        assert "## Intent Distribution" in content
        assert "## Summary" in content
        assert "market_analysis" in content

    def test_output_dir_created_if_missing(self, tmp_path):
        target = date(2026, 5, 19)
        deep_dir = tmp_path / "deep" / "nested" / "wiki" / "jarvis-daily-log"
        agg = aggregate([_make_record(target_date=target)], target)
        content = render_markdown(agg)
        out_path = write_daily_file(content, deep_dir, target)
        assert out_path.exists()


# ---------------------------------------------------------------------------
# test_handles_missing_log
# ---------------------------------------------------------------------------


class TestHandlesMissingLog:
    """Log file doesn't exist → graceful exit, no output file."""

    def test_load_returns_empty_for_nonexistent_file(self, tmp_path):
        missing = tmp_path / "nonexistent.log"
        records = load_records(missing, date(2026, 5, 19))
        assert records == []

    def test_main_exits_0_for_missing_log(self, tmp_path):
        log_path = tmp_path / "missing.log"
        output_dir = tmp_path / "out"
        result = main(
            [
                "--date",
                "2026-05-19",
                "--log-file",
                str(log_path),
                "--output-dir",
                str(output_dir),
            ]
        )
        assert result == 0
        assert not output_dir.exists() or not any(output_dir.iterdir())

    def test_no_output_file_written_for_missing_log(self, tmp_path):
        log_path = tmp_path / "missing.log"
        output_dir = tmp_path / "out"
        main(
            [
                "--date",
                "2026-05-19",
                "--log-file",
                str(log_path),
                "--output-dir",
                str(output_dir),
            ]
        )
        expected = output_dir / "2026-05-19.md"
        assert not expected.exists()


# ---------------------------------------------------------------------------
# test_handles_empty_log
# ---------------------------------------------------------------------------


class TestHandlesEmptyLog:
    """Empty log file (0 lines) → graceful exit, no output file."""

    def test_empty_file_returns_no_records(self, tmp_path):
        log_path = tmp_path / "empty.log"
        log_path.write_text("", encoding="utf-8")
        records = load_records(log_path, date(2026, 5, 19))
        assert records == []

    def test_main_exits_0_for_empty_log(self, tmp_path):
        log_path = tmp_path / "empty.log"
        log_path.write_text("", encoding="utf-8")
        output_dir = tmp_path / "out"
        result = main(
            [
                "--date",
                "2026-05-19",
                "--log-file",
                str(log_path),
                "--output-dir",
                str(output_dir),
            ]
        )
        assert result == 0

    def test_no_output_file_for_empty_log(self, tmp_path):
        log_path = tmp_path / "empty.log"
        log_path.write_text("", encoding="utf-8")
        output_dir = tmp_path / "out"
        main(
            [
                "--date",
                "2026-05-19",
                "--log-file",
                str(log_path),
                "--output-dir",
                str(output_dir),
            ]
        )
        expected = output_dir / "2026-05-19.md"
        assert not expected.exists()

    def test_whitespace_only_lines_treated_as_empty(self, tmp_path):
        log_path = tmp_path / "ws.log"
        log_path.write_text("   \n\n  \n", encoding="utf-8")
        records = load_records(log_path, date(2026, 5, 19))
        assert records == []


# ---------------------------------------------------------------------------
# test_idempotent_rerun
# ---------------------------------------------------------------------------


class TestIdempotentRerun:
    """Running the aggregator twice on the same day produces identical output."""

    def test_second_run_overwrites_with_same_content(self, tmp_path):
        target = date(2026, 5, 19)
        log_path = tmp_path / "jarvis_ask.log"
        output_dir = tmp_path / "out"

        records = [
            _make_record("market_analysis", elapsed_ms=600, target_date=target),
            _make_record("position_query", elapsed_ms=450, target_date=target),
            _make_record("unknown", elapsed_ms=2000, target_date=target),
        ]
        _write_jsonl(log_path, records)

        argv = [
            "--date",
            target.isoformat(),
            "--log-file",
            str(log_path),
            "--output-dir",
            str(output_dir),
        ]

        result1 = main(argv)
        out_path = output_dir / f"{target.isoformat()}.md"
        content_after_run1 = out_path.read_text(encoding="utf-8")
        mtime_after_run1 = out_path.stat().st_mtime

        result2 = main(argv)
        content_after_run2 = out_path.read_text(encoding="utf-8")

        assert result1 == 0
        assert result2 == 0
        assert content_after_run1 == content_after_run2

    def test_idempotent_file_count(self, tmp_path):
        """Only one file per date — no duplicates."""
        target = date(2026, 5, 19)
        log_path = tmp_path / "jarvis_ask.log"
        output_dir = tmp_path / "out"
        records = [_make_record(target_date=target)]
        _write_jsonl(log_path, records)

        argv = [
            "--date",
            target.isoformat(),
            "--log-file",
            str(log_path),
            "--output-dir",
            str(output_dir),
        ]
        main(argv)
        main(argv)

        files = list(output_dir.glob("*.md"))
        assert len(files) == 1
