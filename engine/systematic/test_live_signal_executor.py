"""TDD for the systematic signal -> paper-order bridge.

The bridge is the "validated -> tradeable" last mile. Because it touches the
order path, every test asserts a SAFETY property: default-off, deployed-only,
idempotent, and faithful pass-through of the SafetyLayer verdict. No real
broker is involved -- submit_paper_order is mocked.

Run:  cd engine && .venv/Scripts/python backtest/../systematic/test_live_signal_executor.py
  or: cd engine && .venv/Scripts/python -m pytest systematic/test_live_signal_executor.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, ".")

from systematic.live_signal_executor import LiveSignalExecutor  # noqa: E402


def _registry(deployed: bool):
    """Minimal registry: one MES candidate, deployed_live toggled."""
    return {
        "schema_version": 1,
        "allowed_status": ["forward_testing", "graduated", "deployed_live", "retired"],
        "graduation_rule": {"min_forward_oos_windows": 1},
        "candidates": [
            {
                "id": "MES_vwap_rank1",
                "symbol": "MES",
                "family": "vwap_reversion",
                "status": "deployed_live" if deployed else "forward_testing",
                "hypothesis": "x",
                "params": {"a": 1},
                "deployed_live": deployed,
            }
        ],
    }


def _signal(side="long", date="2026-06-26"):
    return {
        "symbol": "MES",
        "side": side,
        "entry_price": 5800.0,
        "stop": 5785.0,
        "quantity": 1,
        "signal_date": date,
    }


def _mock_safety(approved=True, reason="dry-run", order_id=None, routed=False):
    s = AsyncMock()
    s.submit_paper_order = AsyncMock(
        return_value={
            "approved": approved,
            "reason": reason,
            "order_id": order_id,
            "routed_to_ib": routed,
        }
    )
    return s


def test_disabled_by_default_submits_nothing():
    safety = _mock_safety()
    with tempfile.TemporaryDirectory() as d:
        ex = LiveSignalExecutor(
            safety,
            registry=_registry(True),
            ledger_path=Path(d) / "exec.jsonl",
            auto_execute=False,
        )
        out = asyncio.run(ex.execute_signal(_signal(), "MES_vwap_rank1"))
    assert out["executed"] is False, out
    assert out["gate"] == "auto_execute_disabled", out
    safety.submit_paper_order.assert_not_awaited()
    print("[PASS] master switch off -> submits nothing")


def test_blocks_non_deployed_candidate():
    safety = _mock_safety()
    with tempfile.TemporaryDirectory() as d:
        ex = LiveSignalExecutor(
            safety,
            registry=_registry(False),  # NOT deployed
            ledger_path=Path(d) / "exec.jsonl",
            auto_execute=True,
        )
        out = asyncio.run(ex.execute_signal(_signal(), "MES_vwap_rank1"))
    assert out["executed"] is False, out
    assert out["gate"] == "candidate_not_deployed", out
    safety.submit_paper_order.assert_not_awaited()
    print("[PASS] non-deployed candidate blocked even when enabled")


def test_executes_deployed_candidate_dry_run():
    safety = _mock_safety(approved=True, reason="dry-run", order_id=None, routed=False)
    with tempfile.TemporaryDirectory() as d:
        ledger = Path(d) / "exec.jsonl"
        ex = LiveSignalExecutor(
            safety,
            registry=_registry(True),
            ledger_path=ledger,
            auto_execute=True,
        )
        out = asyncio.run(ex.execute_signal(_signal(side="long"), "MES_vwap_rank1"))
        assert out["executed"] is True, out
        assert out["approved"] is True, out
        safety.submit_paper_order.assert_awaited_once()
        kwargs = safety.submit_paper_order.await_args.kwargs
        assert kwargs["symbol"] == "MES" and kwargs["action"] == "BUY", kwargs
        assert kwargs["quantity"] == 1 and kwargs["price"] == 5800.0, kwargs
        assert kwargs["stop_price"] == 5785.0, kwargs
        recs = [json.loads(x) for x in ledger.read_text().splitlines() if x.strip()]
        assert len(recs) == 1 and recs[0]["candidate_id"] == "MES_vwap_rank1", recs
    print("[PASS] deployed candidate executes via submit_paper_order + ledgered")


def test_idempotent_no_double_submit():
    safety = _mock_safety()
    with tempfile.TemporaryDirectory() as d:
        ledger = Path(d) / "exec.jsonl"
        ex = LiveSignalExecutor(
            safety,
            registry=_registry(True),
            ledger_path=ledger,
            auto_execute=True,
        )
        sig = _signal(date="2026-06-26")
        first = asyncio.run(ex.execute_signal(sig, "MES_vwap_rank1"))
        second = asyncio.run(ex.execute_signal(sig, "MES_vwap_rank1"))
    assert first["executed"] is True, first
    assert second["executed"] is False and second["gate"] == "duplicate", second
    safety.submit_paper_order.assert_awaited_once()  # exactly once across both
    print("[PASS] idempotent: identical signal never double-submits")


def test_short_maps_to_sell():
    safety = _mock_safety()
    with tempfile.TemporaryDirectory() as d:
        ex = LiveSignalExecutor(
            safety,
            registry=_registry(True),
            ledger_path=Path(d) / "exec.jsonl",
            auto_execute=True,
        )
        asyncio.run(ex.execute_signal(_signal(side="short"), "MES_vwap_rank1"))
    assert safety.submit_paper_order.await_args.kwargs["action"] == "SELL"
    print("[PASS] short side -> SELL action")


def test_safety_rejection_passed_through_and_recorded():
    safety = _mock_safety(approved=False, reason="Kill switch active")
    with tempfile.TemporaryDirectory() as d:
        ledger = Path(d) / "exec.jsonl"
        ex = LiveSignalExecutor(
            safety,
            registry=_registry(True),
            ledger_path=ledger,
            auto_execute=True,
        )
        out = asyncio.run(ex.execute_signal(_signal(), "MES_vwap_rank1"))
        assert out["executed"] is True and out["approved"] is False, out
        assert "Kill switch" in out["reason"], out
        recs = [json.loads(x) for x in ledger.read_text().splitlines() if x.strip()]
        assert len(recs) == 1 and recs[0]["approved"] is False, recs
    print("[PASS] safety rejection faithfully passed through + recorded")


def main():
    tests = [
        test_disabled_by_default_submits_nothing,
        test_blocks_non_deployed_candidate,
        test_executes_deployed_candidate_dry_run,
        test_idempotent_no_double_submit,
        test_short_maps_to_sell,
        test_safety_rejection_passed_through_and_recorded,
    ]
    failures = []
    for t in tests:
        try:
            t()
        except Exception as exc:
            print(f"[FAIL] {t.__name__}: {exc}")
            failures.append(t.__name__)
    print(f"\n{'=' * 60}")
    if failures:
        print(f"FAILED {len(failures)}/{len(tests)}: {', '.join(failures)}")
        sys.exit(1)
    print(f"ALL {len(tests)} live_signal_executor tests PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()
