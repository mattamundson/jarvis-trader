"""Tier B — guardrail: ConsecutiveLossTracker must stay wired in main lifespan."""

from __future__ import annotations

from pathlib import Path


def test_main_py_wires_loss_tracker_into_safety_layer() -> None:
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    text = main_py.read_text(encoding="utf-8", errors="replace")
    assert "ConsecutiveLossTracker" in text
    assert "loss_tracker = ConsecutiveLossTracker" in text
    assert "SafetyLayer" in text
    assert "loss_tracker" in text and "safety_layer" in text
