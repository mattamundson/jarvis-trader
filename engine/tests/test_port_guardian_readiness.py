"""
Tests for the port_guardian readiness gate (P0.1).

The guardian launches uvicorn in-process and blocks, so pm2 only ever sees the
guardian PID alive — if uvicorn hangs in startup or never binds 8010, pm2 still
reports the app "online" while nothing serves. These cover the two new units that
close that gap: a readiness watchdog that detects a server that never comes up, and
a structured restart-event recorder so a restart's cause is no longer invisible.
"""

import json
from contextlib import contextmanager

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
