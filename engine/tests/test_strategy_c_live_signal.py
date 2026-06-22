"""Regression cover for the Strategy C+ weekly signal runner's failure contract.

Incident (2026-06-05): the weekly generation task reported success (exit 0) but
wrote no fresh signal -> the C+ signal silently went 13 days stale. run_live_signal
must therefore guarantee:

  * success  -> writes the signal JSON AND returns a dict WITHOUT an "error" key
  * failure  -> returns {"error": ...}, writes NOTHING, and the __main__ exit code
               is non-zero (so the scheduled task surfaces the failure)

These are pure-logic tests: the heavy StrategyCEngine is faked, so no data,
network, or engine restart is needed.
"""

from __future__ import annotations

import json

import strategy_c.engine as sce
from strategy_c.live_signal import run_live_signal


class _FakeEngineOK:
    def __init__(self, *args, **kwargs):
        pass

    def get_live_signal(self):
        return {
            "generated_at": "2026-06-22T16:05:00",
            "combined_scale": 0.5,
            "holdings": {"SPY": 1.0},
            "layers": {},
        }


class _FakeEngineBoom:
    def __init__(self, *args, **kwargs):
        pass

    def get_live_signal(self):
        raise RuntimeError("data source down")


def _exit_code(signal: dict) -> int:
    """Mirror of live_signal.__main__: exit 0 only when no error key is present."""
    return 0 if "error" not in signal else 1


def test_success_writes_signal_and_exit_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(sce, "StrategyCEngine", _FakeEngineOK)
    out = tmp_path / "strategy_c_plus_live_signal.json"

    result = run_live_signal(save_path=str(out), notify=False)

    assert "error" not in result
    assert out.exists(), "success path must write the signal file"
    assert json.loads(out.read_text())["holdings"] == {"SPY": 1.0}
    assert _exit_code(result) == 0


def test_failure_writes_nothing_and_exit_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(sce, "StrategyCEngine", _FakeEngineBoom)
    out = tmp_path / "strategy_c_plus_live_signal.json"

    result = run_live_signal(save_path=str(out), notify=False)

    assert "error" in result
    # The crux of the 2026-06-05 silent failure: a failed run must NOT leave a
    # stale/empty file behind, and must NOT report success.
    assert not out.exists(), "failure path must not write a signal file"
    assert _exit_code(result) == 1
