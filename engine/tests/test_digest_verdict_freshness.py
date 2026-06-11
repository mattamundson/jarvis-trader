"""I9: gate-v2 verdict freshness monitor in the daily digest.

Pure assessor + file reader tested with synthetic verdict files.
"""

import json
from datetime import datetime, timedelta, timezone

try:
    from engine.discord.digest_generator import (
        _assess_verdict_freshness,
        _verdict_freshness,
    )
except ImportError:  # pragma: no cover
    from discord.digest_generator import (
        _assess_verdict_freshness,
        _verdict_freshness,
    )

NOW = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)


def _rec(symbol, days_old, verdict="PASS"):
    return {
        "symbol": symbol,
        "created_at": NOW - timedelta(days=days_old),
        "verdict": verdict,
    }


class TestAssessVerdictFreshness:
    def test_fresh_actives_no_alert(self):
        r = _assess_verdict_freshness(
            [_rec("MES", 0.5), _rec("MGC", 2.0)], NOW, ["MES", "MGC"]
        )
        assert r["alert"] is False
        assert r["symbols"]["MES"]["age_days"] == 0.5
        assert r["symbols"]["MGC"]["active"] is True

    def test_stale_active_alerts(self):
        r = _assess_verdict_freshness(
            [_rec("MES", 0.5), _rec("MGC", 9.0)], NOW, ["MES", "MGC"]
        )
        assert r["alert"] is True
        assert r["stale_active"] == ["MGC"]

    def test_newest_per_symbol_wins(self):
        r = _assess_verdict_freshness(
            [_rec("MES", 30.0), _rec("MES", 1.0), _rec("MES", 12.0)],
            NOW,
            ["MES"],
        )
        assert r["alert"] is False
        assert r["symbols"]["MES"]["age_days"] == 1.0
        assert r["symbols"]["MES"]["files"] == 3

    def test_missing_active_alerts(self):
        r = _assess_verdict_freshness([_rec("MES", 1.0)], NOW, ["MES", "MGC"])
        assert r["alert"] is True
        assert r["missing_active"] == ["MGC"]

    def test_stale_inactive_does_not_alert(self):
        r = _assess_verdict_freshness(
            [_rec("MES", 1.0), _rec("MCL", 40.0)], NOW, ["MES"]
        )
        assert r["alert"] is False
        assert r["symbols"]["MCL"]["active"] is False


class TestVerdictFreshnessReader:
    def _write(self, dirpath, name, symbol, days_old, verdict="PASS"):
        # Relative to REAL now: the reader computes age against datetime.now().
        body = {
            "symbol": symbol,
            "verdict": verdict,
            "created_at": (
                datetime.now(timezone.utc) - timedelta(days=days_old)
            ).isoformat(),
        }
        (dirpath / name).write_text(json.dumps(body), encoding="utf-8")

    def test_reads_synthetic_files(self, tmp_path):
        self._write(tmp_path, "MES_trend_rank1.json", "MES", 1.0)
        self._write(tmp_path, "MGC_trend_rank4.json", "MGC", 10.0)
        r = _verdict_freshness(verdict_dir=tmp_path, active_symbols=["MES", "MGC"])
        assert r["stale_active"] == ["MGC"]
        assert r["alert"] is True
        assert r["symbols"]["MES"]["latest_verdict"] == "PASS"

    def test_archive_subdir_ignored(self, tmp_path):
        self._write(tmp_path, "MES_trend_rank1.json", "MES", 1.0)
        archive = tmp_path / "archive"
        archive.mkdir()
        self._write(archive, "MES_old.json", "MES", 0.1)  # would mask staleness
        r = _verdict_freshness(verdict_dir=tmp_path, active_symbols=["MES"])
        assert r["symbols"]["MES"]["files"] == 1
        assert 0.9 <= r["symbols"]["MES"]["age_days"] <= 1.1

    def test_malformed_file_skipped(self, tmp_path):
        (tmp_path / "garbage.json").write_text("{not json", encoding="utf-8")
        self._write(tmp_path, "MES_trend_rank1.json", "MES", 1.0)
        r = _verdict_freshness(verdict_dir=tmp_path, active_symbols=["MES"])
        assert r["alert"] is False
        assert list(r["symbols"]) == ["MES"]

    def test_missing_dir_alerts_on_missing_actives(self, tmp_path):
        r = _verdict_freshness(
            verdict_dir=tmp_path / "nope", active_symbols=["MES", "MGC"]
        )
        assert r["missing_active"] == ["MES", "MGC"]
        assert r["alert"] is True
