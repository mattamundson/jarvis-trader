"""I4: scheduled-task health rollup in the daily digest.

Tests the pure parser (_assess_task_health) and the file reader (_task_health)
against real check-task-health.ps1 report shapes.
"""

try:
    from engine.discord.digest_generator import _assess_task_health, _task_health
except ImportError:  # pragma: no cover
    from discord.digest_generator import _assess_task_health, _task_health

HEALTHY_REPORT = """=== Scheduled Task Health  2026-06-11T08:30:01-05:00 ===
Scanned 42 task(s) across prefixes: Jarvis-, JARVIS-, Hermes-, DP600-
Failing (enabled): 0   Failing (disabled, informational): 1

All enabled tasks healthy (0x0 / running / armed).

--- DISABLED tasks with a stale failure result (informational) ---
  Jarvis-DiscordAutoImport         0x1        last=2026-06-03 09:00
"""

FAILING_REPORT = """=== Scheduled Task Health  2026-06-11T08:30:01-05:00 ===
Scanned 42 task(s) across prefixes: Jarvis-, JARVIS-, Hermes-, DP600-
Failing (enabled): 2   Failing (disabled, informational): 1

--- ENABLED tasks with a failure result ---
  Jarvis-FinanceSync               0x1        last=2026-06-10 07:00 next=2026-06-11 07:00  state=Ready
  Jarvis-PM2RestartWatch-15min     0x2        last=2026-06-10 22:45 next=2026-06-10 23:00  state=Ready

--- DISABLED tasks with a stale failure result (informational) ---
  Jarvis-DiscordAutoImport         0x1        last=2026-06-03 09:00
"""


class TestAssessTaskHealth:
    def test_healthy_report_no_alert(self):
        r = _assess_task_health(HEALTHY_REPORT, age_hours=2.0)
        assert r["alert"] is False
        assert r["scanned"] == 42
        assert r["failing_enabled"] == 0
        assert r["failing_disabled"] == 1
        assert r["failing_tasks"] == []
        assert r["stale"] is False

    def test_failing_report_alerts_with_names_and_codes(self):
        r = _assess_task_health(FAILING_REPORT, age_hours=2.0)
        assert r["alert"] is True
        assert r["failing_enabled"] == 2
        names = {t["name"]: t["result"] for t in r["failing_tasks"]}
        assert names == {
            "Jarvis-FinanceSync": "0x1",
            "Jarvis-PM2RestartWatch-15min": "0x2",
        }

    def test_disabled_section_not_counted_as_failing_tasks(self):
        r = _assess_task_health(FAILING_REPORT, age_hours=2.0)
        assert all(t["name"] != "Jarvis-DiscordAutoImport" for t in r["failing_tasks"])

    def test_stale_report_alerts_even_when_healthy(self):
        r = _assess_task_health(HEALTHY_REPORT, age_hours=30.0)
        assert r["stale"] is True
        assert r["alert"] is True

    def test_malformed_text_is_graceful(self):
        r = _assess_task_health("garbage that matches nothing", age_hours=1.0)
        assert r["alert"] is False
        assert r["scanned"] is None
        assert r["failing_enabled"] is None
        assert r["failing_tasks"] == []


class TestTaskHealthReader:
    def test_reads_and_parses_file(self, tmp_path):
        p = tmp_path / "task-health-latest.txt"
        p.write_text(FAILING_REPORT, encoding="utf-8")
        r = _task_health(report_path=p)
        assert r["present"] is True
        assert r["alert"] is True
        assert r["failing_enabled"] == 2
        assert r["stale"] is False  # freshly written

    def test_missing_file_is_quiet(self, tmp_path):
        r = _task_health(report_path=tmp_path / "nope.txt")
        assert r["present"] is False
        assert r["alert"] is False
        assert r["failing_tasks"] == []
