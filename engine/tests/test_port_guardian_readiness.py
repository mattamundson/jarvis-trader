"""
Tests for the port_guardian readiness gate (P0.1), exit-path observability
(T2-16, 2026-07-09), and adaptive readiness deadline (P0.7, 2026-07-09).

The guardian launches uvicorn in-process and blocks, so pm2 only ever sees the
guardian PID alive — if uvicorn hangs in startup or never binds 8010, pm2 still
reports the app "online" while nothing serves. These cover the units that close
that gap: a readiness watchdog that detects a server that never comes up, a
structured restart-event recorder so a restart's cause is no longer invisible,
and (P0.7) an adaptive READINESS_DEADLINE that sizes itself off p95 of recorded
boot durations instead of a fixed 360s, so a genuinely slow-but-healthy box
under contention isn't killed by too tight a fixed ceiling, and a fast box
isn't left "starting" for minutes longer than it needs.

T2-16 audit finding: the guardian had a confirmed 28-minute episode where uvicorn
accepted TCP connections but never answered a single HTTP request, then exited with
NO log entry explaining why. Root cause: the startup readiness watchdog only checks
once (thread returns after the server first comes up) and several of main()'s exit
branches never called the restart-event recorder at all. The classes below
(TestLivenessMonitor, TestTerminationLogger, TestMainExitPathLogging) simulate each
previously-silent exit path — including the "accepts TCP, never responds" case via
TestLivenessMonitor — and assert a structured log entry is now written for each one.
"""

import json
import sys
import types
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


class TestPortHoldersTimeout:
    def test_netstat_call_has_a_timeout(self, monkeypatch):
        # A stalled netstat.exe under heavy machine contention must not hang
        # main() forever before the readiness watchdog thread ever starts.
        captured = {}

        def _fake_check_output(cmd, **kwargs):
            captured.update(kwargs)
            return ""

        monkeypatch.setattr(port_guardian.subprocess, "check_output", _fake_check_output)
        port_guardian._port_holders(8010)
        assert captured.get("timeout"), "netstat subprocess call must set a timeout"

    def test_returns_empty_list_on_timeout_instead_of_hanging(self, monkeypatch):
        def _boom(cmd, **kwargs):
            raise port_guardian.subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout"))

        monkeypatch.setattr(port_guardian.subprocess, "check_output", _boom)
        assert port_guardian._port_holders(8010) == []


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


class TestLivenessMonitor:
    """The headline T2-16 fix: a server that passes startup readiness and later
    stops answering /health (accepts TCP, never responds) must be logged the
    moment the hang is DETECTED — not only at exit, since a hard kill can't be
    intercepted by any code in the dying process."""

    @staticmethod
    def _clock():
        clock = {"t": 0.0}
        return clock, (lambda: clock["t"]), (lambda s: clock.__setitem__("t", clock["t"] + s))

    def test_no_log_while_consistently_healthy(self):
        events = []
        clock, now_fn, sleep_fn = self._clock()

        port_guardian._liveness_monitor(
            poll_interval_s=15,
            hang_failures=3,
            is_healthy_fn=lambda: True,
            record_fn=lambda reason, details: events.append((reason, details)),
            sleep_fn=sleep_fn,
            now_fn=now_fn,
            max_iterations=10,
        )

        assert events == []

    def test_transient_blip_below_threshold_does_not_log(self):
        # One failed probe then recovery — never reaches hang_failures=3, so this
        # must NOT be logged (avoids noise from a single momentary spike, same
        # rationale as the generous READINESS_PROBE_TIMEOUT on _is_healthy).
        sequence = iter([True, False, True, True, True])
        events = []
        clock, now_fn, sleep_fn = self._clock()

        port_guardian._liveness_monitor(
            poll_interval_s=15,
            hang_failures=3,
            is_healthy_fn=lambda: next(sequence),
            record_fn=lambda reason, details: events.append((reason, details)),
            sleep_fn=sleep_fn,
            now_fn=now_fn,
            max_iterations=5,
        )

        assert events == []

    def test_logs_hang_detected_once_after_consecutive_failures(self):
        # True, True, then fails from here on — this is the reported incident
        # shape: healthy at startup, then accepts-but-never-responds indefinitely.
        sequence = iter([True, True, False, False, False, False, False])
        events = []
        clock, now_fn, sleep_fn = self._clock()

        port_guardian._liveness_monitor(
            poll_interval_s=15,
            hang_failures=3,
            is_healthy_fn=lambda: next(sequence),
            record_fn=lambda reason, details: events.append((reason, details)),
            sleep_fn=sleep_fn,
            now_fn=now_fn,
            max_iterations=7,
        )

        hang_events = [e for e in events if e[0] == "liveness-hang-detected"]
        assert len(hang_events) == 1, "must log exactly once per hang episode, not every poll"
        reason, details = hang_events[0]
        assert details["consecutive_failures"] == 3
        assert details["poll_interval_s"] == 15
        assert details["hang_duration_s"] >= 0

    def test_logs_recovered_after_a_detected_hang(self):
        sequence = iter([True, False, False, False, False, True, True])
        events = []
        clock, now_fn, sleep_fn = self._clock()

        port_guardian._liveness_monitor(
            poll_interval_s=15,
            hang_failures=3,
            is_healthy_fn=lambda: next(sequence),
            record_fn=lambda reason, details: events.append((reason, details)),
            sleep_fn=sleep_fn,
            now_fn=now_fn,
            max_iterations=7,
        )

        reasons = [e[0] for e in events]
        assert reasons == ["liveness-hang-detected", "liveness-recovered"]
        recovered_details = events[1][1]
        assert recovered_details["hang_duration_s"] is not None
        assert recovered_details["consecutive_failures_observed"] == 4

    def test_never_forces_exit(self):
        # Purely observational: even a permanent hang must not raise/exit —
        # only the caller (main()'s watchdog thread) decides what, if anything,
        # happens next. This pins "don't change restart behavior/timing."
        events = []
        clock, now_fn, sleep_fn = self._clock()

        port_guardian._liveness_monitor(
            poll_interval_s=15,
            hang_failures=3,
            is_healthy_fn=lambda: False,
            record_fn=lambda reason, details: events.append((reason, details)),
            sleep_fn=sleep_fn,
            now_fn=now_fn,
            max_iterations=20,
        )

        # Ran to completion (20 iterations) without raising; logged once, not repeatedly.
        assert [e[0] for e in events] == ["liveness-hang-detected"]


class TestTerminationLogger:
    """Best-effort SIGTERM/SIGINT logging for the softer external-kill paths
    (PM2 stop, `taskkill` without `/F`). Cannot cover a hard TerminateProcess/
    SIGKILL — nothing runs in a process killed that way — which is why
    TestLivenessMonitor above logs during the hang rather than only at exit."""

    def test_handler_logs_structured_event_and_exits_with_signal_code(self, monkeypatch, tmp_path):
        log = tmp_path / "restarts.jsonl"
        monkeypatch.setattr(port_guardian, "RESTART_LOG", log)

        registered = {}

        def _fake_signal(sig, handler):
            registered[sig] = handler

        monkeypatch.setattr(port_guardian.signal, "signal", _fake_signal)

        port_guardian._install_termination_logger()

        assert port_guardian.signal.SIGTERM in registered
        handler = registered[port_guardian.signal.SIGTERM]

        with pytest.raises(SystemExit) as exc_info:
            handler(int(port_guardian.signal.SIGTERM), None)

        assert exc_info.value.code == 128 + int(port_guardian.signal.SIGTERM)
        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["reason"] == "signal-terminated"
        assert rec["details"]["signal_name"] == "SIGTERM"

    def test_installer_never_raises_if_signal_registration_fails(self, monkeypatch):
        def _boom(sig, handler):
            raise ValueError("not main thread")

        monkeypatch.setattr(port_guardian.signal, "signal", _boom)
        # Must not raise — observability wiring must never break the guardian.
        port_guardian._install_termination_logger()


class TestMainExitPathLogging:
    """Drives main() through each previously-silent exit branch and asserts a
    structured record now lands in RESTART_LOG for every one of them."""

    def _read_records(self, log_path):
        if not log_path.exists():
            return []
        return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]

    def _patch_common(self, monkeypatch, tmp_path):
        log = tmp_path / "restarts.jsonl"
        monkeypatch.setattr(port_guardian, "RESTART_LOG", log)
        monkeypatch.setattr(port_guardian, "_check_venv_python", lambda: None)
        monkeypatch.setattr(port_guardian, "_install_termination_logger", lambda: None)
        return log

    def test_wrong_python_is_logged(self, monkeypatch, tmp_path):
        log = tmp_path / "restarts.jsonl"
        monkeypatch.setattr(port_guardian, "RESTART_LOG", log)
        monkeypatch.setattr(port_guardian.sys, "executable", r"C:\WindowsApps\python.exe")

        with pytest.raises(SystemExit) as exc_info:
            port_guardian._check_venv_python()

        assert exc_info.value.code == 4
        records = self._read_records(log)
        assert len(records) == 1
        assert records[0]["reason"] == "wrong-python"

    def test_unidentified_port_holder_is_logged(self, monkeypatch, tmp_path):
        log = self._patch_common(monkeypatch, tmp_path)
        monkeypatch.setattr(port_guardian, "_port_holders", lambda port: [4242])
        monkeypatch.setattr(port_guardian, "_process_name", lambda pid: "chrome")

        result = port_guardian.main()

        assert result == 1
        records = self._read_records(log)
        assert any(r["reason"] == "unidentified-port-holder" for r in records)

    def test_unkillable_healthy_orphan_is_logged(self, monkeypatch, tmp_path):
        log = self._patch_common(monkeypatch, tmp_path)
        monkeypatch.setattr(port_guardian, "_port_holders", lambda port: [111])
        monkeypatch.setattr(port_guardian, "_process_name", lambda pid: "python")
        monkeypatch.setattr(port_guardian, "_kill_pid", lambda pid: False)
        monkeypatch.setattr(port_guardian, "_is_healthy", lambda port: True)
        # This branch sleeps HEALTHY_ORPHAN_BACKOFF (30s) — neutralize for the test.
        monkeypatch.setattr(port_guardian.time, "sleep", lambda s: None)

        result = port_guardian.main()

        assert result == 3
        records = self._read_records(log)
        assert any(r["reason"] == "unkillable-healthy-orphan" for r in records)

    def test_unkillable_unhealthy_orphan_is_logged(self, monkeypatch, tmp_path):
        log = self._patch_common(monkeypatch, tmp_path)
        monkeypatch.setattr(port_guardian, "_port_holders", lambda port: [111])
        monkeypatch.setattr(port_guardian, "_process_name", lambda pid: "python")
        monkeypatch.setattr(port_guardian, "_kill_pid", lambda pid: False)
        monkeypatch.setattr(port_guardian, "_is_healthy", lambda port: False)

        result = port_guardian.main()

        assert result == 2
        records = self._read_records(log)
        assert any(r["reason"] == "unkillable-unhealthy-orphan" for r in records)

    def test_port_still_bound_after_kill_is_logged(self, monkeypatch, tmp_path):
        log = self._patch_common(monkeypatch, tmp_path)
        monkeypatch.setattr(port_guardian, "_port_holders", lambda port: [111])
        monkeypatch.setattr(port_guardian, "_process_name", lambda pid: "python")
        monkeypatch.setattr(port_guardian, "_kill_pid", lambda pid: True)
        monkeypatch.setattr(port_guardian, "_wait_port_free", lambda *a, **k: False)

        result = port_guardian.main()

        assert result == 2
        records = self._read_records(log)
        assert any(r["reason"] == "port-still-bound-after-kill" for r in records)

    def test_uvicorn_crash_is_logged_and_reraised(self, monkeypatch, tmp_path):
        log = self._patch_common(monkeypatch, tmp_path)
        monkeypatch.setattr(port_guardian, "_port_holders", lambda port: [])
        monkeypatch.setattr(port_guardian, "_start_readiness_watchdog", lambda: None)
        monkeypatch.setattr(port_guardian.os, "chdir", lambda path: None)

        fake_uvicorn = types.ModuleType("uvicorn")

        def _boom_run(*a, **k):
            raise RuntimeError("simulated uvicorn crash")

        fake_uvicorn.run = _boom_run
        monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

        with pytest.raises(RuntimeError, match="simulated uvicorn crash"):
            port_guardian.main()

        records = self._read_records(log)
        crash_records = [r for r in records if r["reason"] == "uvicorn-crashed"]
        assert len(crash_records) == 1
        assert crash_records[0]["details"]["error_type"] == "RuntimeError"

    def test_normal_shutdown_is_logged(self, monkeypatch, tmp_path):
        log = self._patch_common(monkeypatch, tmp_path)
        monkeypatch.setattr(port_guardian, "_port_holders", lambda port: [])
        monkeypatch.setattr(port_guardian, "_start_readiness_watchdog", lambda: None)
        monkeypatch.setattr(port_guardian.os, "chdir", lambda path: None)

        fake_uvicorn = types.ModuleType("uvicorn")
        fake_uvicorn.run = lambda *a, **k: None  # returns normally — graceful shutdown
        monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

        result = port_guardian.main()

        assert result == 0
        records = self._read_records(log)
        assert any(r["reason"] == "normal-shutdown" for r in records)
