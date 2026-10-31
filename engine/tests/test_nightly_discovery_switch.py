"""The nightly LLM discovery loop must be off unless explicitly enabled."""

from __future__ import annotations

from pathlib import Path

from flags.registry import FLAG_DEFINITIONS

ENGINE = Path(__file__).resolve().parents[1]


def test_flag_defined_and_defaults_off():
    flag = {f["name"]: f for f in FLAG_DEFINITIONS}["ENABLE_NIGHTLY_DISCOVERY"]
    assert flag["default"] is False
    assert flag["requires_restart"] is True


def test_scheduler_registration_is_behind_the_flag():
    src = (ENGINE / "main.py").read_text(encoding="utf-8")
    gate = src.index('is_enabled("ENABLE_NIGHTLY_DISCOVERY")')
    job = src.index('id="nightly_discovery"')
    assert gate < job, "nightly_discovery add_job must sit behind the flag check"
