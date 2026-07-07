"""Tier B — guardrail: IB Gateway connect() retry loop must stay wired in main lifespan.

Addresses regression in IBKR_EXECUTION_REGRESSION_REPORT_2026-05-07.md where a
single connect() call left safety_layer._ib_gateway=None permanently after a
transient IB Gateway hiccup. Commit b0c3ea5 added a 3-attempt retry loop with
30s backoff. This test prevents accidental revert during refactors.
"""

from __future__ import annotations

from pathlib import Path


def test_main_py_has_ib_connect_retry_loop() -> None:
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    text = main_py.read_text(encoding="utf-8", errors="replace")
    assert "for _attempt in range(3)" in text, "retry loop removed"
    assert "await asyncio.sleep(30)" in text, "30s backoff removed"
    assert "after 3 attempts" in text, "warning message removed"
    assert "ib_paper_connector.connect()" in text, "connect call moved or renamed"
