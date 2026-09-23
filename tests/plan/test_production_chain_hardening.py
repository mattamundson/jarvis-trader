from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_production_chain_hardening_validator_passes() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/validate_production_chain_hardening.py"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout
    assert "paper-only authority" in proc.stdout


def test_production_chain_hardening_preserves_capital_boundary() -> None:
    data = json.loads((ROOT / "docs/plans/production_chain_hardening_v1.json").read_text())
    assert data["capital_authority"] == "paper_only"
    assert data["live_capital_authorized"] is False
    assert data["canary_authorized"] is False
    assert data["agent_boundaries"]["may_not_submit_broker_orders"] is True


def test_source_excerpt_gaps_are_explicitly_accounted_for() -> None:
    data = json.loads((ROOT / "docs/plans/production_chain_hardening_v1.json").read_text())
    assert data["declared_program_phases"] == data["captured_phase_rows"] + data["missing_phase_rows"]
    assert data["declared_starting_queue"] == data["captured_starting_queue_rows"] + data["missing_starting_queue_rows"]
    assert data["missing_phase_rows"] == 5
    assert data["missing_starting_queue_rows"] == 2
