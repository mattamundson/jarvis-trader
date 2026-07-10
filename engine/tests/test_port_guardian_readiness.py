"""
Tests for the port_guardian readiness gate (P0.1) and adaptive readiness deadline
(P0.7).

The guardian launches uvicorn in-process and blocks, so pm2 only ever sees the
guardian PID alive — if uvicorn hangs in startup or never binds 8010, pm2 still
reports the app "online" while nothing serves. These cover the units that close
that gap: a readiness watchdog that detects a server that never comes up, a
structured restart-event recorder so a restart's cause is no longer invisible,
and (P0.7) an adaptive READINESS_DEADLINE that sizes itself off p95 of recorded
boot durations instead of a fixed 360s, so a genuinely slow-but-healthy box
under contention isn't killed by too tight a fixed ceiling, and a fast box
isn't left "starting" for minutes longer than it needs.
"""

import json
from contextlib import contextmanager

import pytest

from scripts import port_guardian


class TestReadinessWatchdog:
    def test_returns_true_once_server_becomes_ready(self):
        # is_ready flips True on the 3rd probe; watchdog should stop and report ready.
        calls = {"n": 0}

        def is_ready():
            calls["n"] += 1
            return calls["n"] >= 3

        clock = {"t": 0.0}

        ready = port_guardian._readiness_watchdog(
            deadline_s=600,
            poll_interval_s=5,
            is_ready_fn=is_ready,
            now_fn=lambda: clock["t"],
            sleep_fn=lambda s: clock.__setitem__("t", clock["t"] + s),
        )

        assert ready is True
        assert calls["n"] == 3  # stopped probing as soon as ready

    def test_returns_false_when_server_never_ready_before_deadline(self):
        clock = {"t": 0.0}

        ready = port_guardian._readiness_watchdog(
            deadline_s=30,
            poll_interval_s=5,
            is_ready_fn=lambda: False,
            now_fn=lambda: clock["t"],
            sleep_fn=lambda s: clock.__setitem__("t", clock["t"] + s),
        )

        assert ready is False


class TestWslRelayDetection:
    def test_detects_wslrelay_by_name(self):
        assert port_guardian._is_wsl_relay("wslrelay") is True
        assert port_guardian._is_wsl_relay("wslrelay.exe") is True
        assert port_guardian._is_wsl_relay("WSLRelay") is True  # case-insensitive

    def test_ignores_non_relay_holders(self):
        for name in ("python", "python3.12", "uvicorn", "unknown", "", None):
            assert port_guardian._is_wsl_relay(name) is False


class TestRestartEventRecord:
    def test_appends_structured_jsonl_record(self, tmp_path):
        log = tmp_path / "restarts.jsonl"

        port_guardian._record_restart_event(
            reason="health-timeout",
            details={"port": 8010, "deadline_s": 360},
            log_path=log,
        )

        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["reason"] == "health-timeout"
        assert rec["details"]["port"] == 8010
        assert isinstance(rec["pid"], int)
        assert rec["ts"]  # an ISO timestamp string is present

    def test_appends_without_clobbering_prior_records(self, tmp_path):
        log = tmp_path / "restarts.jsonl"
        port_guardian._record_restart_event("orphan-kill", {"pid": 111}, log)
        port_guardian._record_restart_event("health-timeout", {"port": 8010}, log)

        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["reason"] == "orphan-kill"
        assert json.loads(lines[1])["reason"] == "health-timeout"

    def test_records_enriched_diagnostic_details(self, tmp_path):
        # The watchdog now records whether the port was bound at timeout, so a
        # latency cascade (port_bound=True) is distinguishable from a hard startup
        # failure (port_bound=False). Prove the recorder round-trips that shape.
        log = tmp_path / "restarts.jsonl"
        port_guardian._record_restart_event(
            "health-timeout",
            {
                "port": 8010,
                "deadline_s": 360,
                "probe_timeout_s": port_guardian.READINESS_PROBE_TIMEOUT,
                "port_bound": True,
                "holder_pids": [4242],
            },
            log,
        )
        rec = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
        assert rec["details"]["port_bound"] is True
        assert rec["details"]["holder_pids"] == [4242]
        assert rec["details"]["probe_timeout_s"] == port_guardian.READINESS_PROBE_TIMEOUT


class TestBootDurationRecording:
    def test_record_and_load_round_trip(self, tmp_path):
        log = tmp_path / "boot_times.jsonl"
        port_guardian._record_boot_duration(42.3, log)
        port_guardian._record_boot_duration(58.9, log)

        durations = port_guardian._load_boot_durations(log)

        assert durations == [42.3, 58.9]

    def test_load_missing_file_returns_empty(self, tmp_path):
        assert port_guardian._load_boot_durations(tmp_path / "nope.jsonl") == []

    def test_load_skips_malformed_lines_without_raising(self, tmp_path):
        log = tmp_path / "boot_times.jsonl"
        log.write_text(
            '{"ts": "x", "duration_s": 12.0}\n'
            "not json at all\n"
            '{"ts": "x"}\n'  # missing duration_s
            '{"ts": "x", "duration_s": 30.5}\n',
            encoding="utf-8",
        )

        assert port_guardian._load_boot_durations(log) == [12.0, 30.5]

    def test_load_respects_max_records_keeping_most_recent(self, tmp_path):
        log = tmp_path / "boot_times.jsonl"
        for i in range(10):
            port_guardian._record_boot_duration(float(i), log)

        durations = port_guardian._load_boot_durations(log, max_records=3)

        assert durations == [7.0, 8.0, 9.0]


class TestPercentile:
    def test_p95_of_evenly_spaced_values(self):
        values = [float(i) for i in range(1, 101)]  # 1..100
        assert port_guardian._percentile(values, 95) == pytest.approx(95.05, abs=0.5)

    def test_single_value_returns_itself(self):
        assert port_guardian._percentile([42.0], 95) == 42.0

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            port_guardian._percentile([], 95)


class TestComputeAdaptiveDeadline:
    def test_returns_fallback_when_insufficient_samples(self):
        durations = [100.0, 110.0]  # below default min_samples=5
        deadline = port_guardian._compute_adaptive_deadline(durations)
        assert deadline == port_guardian.READINESS_DEADLINE_DEFAULT

    def test_computes_p95_times_multiplier_once_enough_samples(self):
        # 10 identical 100s boots -> p95 == 100 -> deadline == 100 * 1.5 == 150
        durations = [100.0] * 10
        deadline = port_guardian._compute_adaptive_deadline(durations)
        assert deadline == pytest.approx(150.0)

    def test_floors_a_pathologically_low_computed_deadline(self):
        # Very fast boots (5s each) would compute 5 * 1.5 == 7.5s, which is far
        # below any sane readiness window -- the floor must win.
        durations = [5.0] * 10
        deadline = port_guardian._compute_adaptive_deadline(durations)
        assert deadline == port_guardian.READINESS_DEADLINE_FLOOR

    def test_slow_boot_history_raises_deadline_above_fixed_default(self):
        # Sustained 300s boots under contention -> p95*1.5 == 450s, above the old
        # fixed 360s default -- this is the exact regression the story targets:
        # a fixed 360s deadline would keep killing a healthy-but-slow boot.
        durations = [300.0] * 20
        deadline = port_guardian._compute_adaptive_deadline(durations)
        assert deadline == pytest.approx(450.0)
        assert deadline > port_guardian.READINESS_DEADLINE_DEFAULT

    def test_custom_min_samples_and_multiplier_are_honored(self):
        durations = [200.0, 200.0]
        deadline = port_guardian._compute_adaptive_deadline(
            durations, min_samples=2, multiplier=2.0, floor_s=0.0, fallback_s=999.0
        )
        assert deadline == pytest.approx(400.0)


class TestResolveReadinessDeadline:
    def test_env_override_always_wins_over_history(self, tmp_path):
        log = tmp_path / "boot_times.jsonl"
        for _ in range(10):
            port_guardian._record_boot_duration(300.0, log)  # would compute 450 adaptively

        deadline = port_guardian._resolve_readiness_deadline("42", boot_log_path=log)

        assert deadline == 42.0

    def test_invalid_env_override_falls_through_to_adaptive(self, tmp_path):
        log = tmp_path / "boot_times.jsonl"
        for _ in range(10):
            port_guardian._record_boot_duration(300.0, log)

        deadline = port_guardian._resolve_readiness_deadline("not-a-number", boot_log_path=log)

        assert deadline == pytest.approx(450.0)

    def test_no_override_and_no_history_returns_fixed_default(self, tmp_path):
        log = tmp_path / "nope.jsonl"

        deadline = port_guardian._resolve_readiness_deadline(None, boot_log_path=log)

        assert deadline == port_guardian.READINESS_DEADLINE_DEFAULT

    def test_no_override_with_history_adapts(self, tmp_path):
        log = tmp_path / "boot_times.jsonl"
        for _ in range(10):
            port_guardian._record_boot_duration(120.0, log)

        deadline = port_guardian._resolve_readiness_deadline(None, boot_log_path=log)

        assert deadline == pytest.approx(180.0)


class TestConfirmReadinessAndRecordBoot:
    def test_records_boot_duration_on_success(self):
        calls = {"n": 0}

        def is_ready():
            calls["n"] += 1
            return calls["n"] >= 3

        clock = {"t": 0.0}
        recorded = []

        ready, elapsed = port_guardian._confirm_readiness_and_record_boot(
            deadline_s=600,
            poll_interval_s=5,
            is_ready_fn=is_ready,
            now_fn=lambda: clock["t"],
            sleep_fn=lambda s: clock.__setitem__("t", clock["t"] + s),
            record_fn=lambda duration: recorded.append(duration),
        )

        assert ready is True
        assert elapsed == pytest.approx(10.0)  # 2 sleeps of 5s before the 3rd (ready) probe
        assert recorded == [pytest.approx(10.0)]

    def test_does_not_record_on_timeout(self):
        clock = {"t": 0.0}
        recorded = []

        ready, elapsed = port_guardian._confirm_readiness_and_record_boot(
            deadline_s=20,
            poll_interval_s=5,
            is_ready_fn=lambda: False,
            now_fn=lambda: clock["t"],
            sleep_fn=lambda s: clock.__setitem__("t", clock["t"] + s),
            record_fn=lambda duration: recorded.append(duration),
        )

        assert ready is False
        assert recorded == []


class TestProbeTimeout:
    def test_is_healthy_uses_generous_configured_timeout(self, monkeypatch):
        # A too-tight 2s probe mis-reads a transient /health spike on a serving
        # engine as dead and force-restarts it. _is_healthy must pass the generous
        # READINESS_PROBE_TIMEOUT so a brief spike is absorbed, not escalated.
        captured = {}

        @contextmanager
        def _fake_urlopen(url, timeout=None):
            captured["url"] = url
            captured["timeout"] = timeout

            class _Resp:
                status = 200

            yield _Resp()

        monkeypatch.setattr(port_guardian.urllib.request, "urlopen", _fake_urlopen)

        assert port_guardian._is_healthy(8010) is True
        assert captured["timeout"] == port_guardian.READINESS_PROBE_TIMEOUT
        assert captured["timeout"] >= 5, "probe timeout must absorb multi-second spikes"

    def test_is_healthy_false_on_probe_error(self, monkeypatch):
        def _boom(url, timeout=None):
            raise port_guardian.urllib.error.URLError("refused")

        monkeypatch.setattr(port_guardian.urllib.request, "urlopen", _boom)
        assert port_guardian._is_healthy(8010) is False
