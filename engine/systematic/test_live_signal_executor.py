"""TDD for the systematic signal -> paper-order bridge.

The bridge is the "validated -> tradeable" last mile. Because it touches the
order path, every test asserts a SAFETY property: default-off, deployed-only,
live-mode-refused, kill-switch-refused, idempotent (own + cross-path), and
faithful pass-through of the SafetyLayer verdict. No real broker is involved --
submit_paper_order is mocked.

Run:  cd engine && .venv/Scripts/python systematic/test_live_signal_executor.py
  or: cd engine && .venv/Scripts/python -m pytest systematic/test_live_signal_executor.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, ".")

from execution.submission_dedup import SubmissionDedup  # noqa: E402
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


def _mock_safety(approved=True, reason="dry-run", order_id=None, routed=False, killed=False):
    s = AsyncMock()
    s.submit_paper_order = AsyncMock(
        return_value={
            "approved": approved,
            "reason": reason,
            "order_id": order_id,
            "routed_to_ib": routed,
        }
    )
    s.is_killed = MagicMock(return_value=killed)
    return s


def _make(safety, d, *, deployed=True, auto_execute=True, live=False, dedup=None):
    """Build an executor with test-safe defaults (paper mode, kill switch off)."""
    return LiveSignalExecutor(
        safety,
        registry=_registry(deployed),
        ledger_path=Path(d) / "exec.jsonl",
        auto_execute=auto_execute,
        dedup=dedup if dedup is not None else SubmissionDedup(Path(d) / "dedup.jsonl"),
        live_trading_check=lambda: live,
    )


def test_disabled_by_default_submits_nothing():
    safety = _mock_safety()
    with tempfile.TemporaryDirectory() as d:
        ex = _make(safety, d, auto_execute=False)
        out = asyncio.run(ex.execute_signal(_signal(), "MES_vwap_rank1"))
    assert out["executed"] is False and out["gate"] == "auto_execute_disabled", out
    safety.submit_paper_order.assert_not_awaited()
    print("[PASS] master switch off -> submits nothing")


def test_kill_switch_property_blocks_submission():
    """Regression (safety review D1): ``SafetyLayer.is_killed`` is a @property,
    NOT a method. The previous ``_is_killed`` did ``callable(getattr(...))`` which
    is False for a property's bool value, so the kill check was inert. A MagicMock
    (callable) masked it -- so here we use a REAL property accessor and assert the
    bridge refuses to submit when the kill switch is active."""

    class _KilledSafety:
        @property
        def is_killed(self) -> bool:
            return True

        async def submit_paper_order(self, *a, **k):  # pragma: no cover - must not run
            raise AssertionError("submit_paper_order must not be called when killed")

    with tempfile.TemporaryDirectory() as d:
        ex = _make(_KilledSafety(), d)
        out = asyncio.run(ex.execute_signal(_signal(), "MES_vwap_rank1"))
    assert out["executed"] is False and out["gate"] == "kill_switch", out
    print("[PASS] kill switch (real @property) -> bridge refuses, no submit")


def test_blocks_non_deployed_candidate():
    safety = _mock_safety()
    with tempfile.TemporaryDirectory() as d:
        ex = _make(safety, d, deployed=False)
        out = asyncio.run(ex.execute_signal(_signal(), "MES_vwap_rank1"))
    assert out["executed"] is False and out["gate"] == "candidate_not_deployed", out
    safety.submit_paper_order.assert_not_awaited()
    print("[PASS] non-deployed candidate blocked even when enabled")


def test_refuses_live_mode():
    safety = _mock_safety()
    with tempfile.TemporaryDirectory() as d:
        ex = _make(safety, d, live=True)  # system in LIVE mode
        out = asyncio.run(ex.execute_signal(_signal(), "MES_vwap_rank1"))
    assert out["executed"] is False and out["gate"] == "live_mode_refused", out
    safety.submit_paper_order.assert_not_awaited()
    print("[PASS] refuses to submit when LIVE_TRADING_ENABLED is True")


def test_refuses_when_kill_switch_active():
    safety = _mock_safety(killed=True)
    with tempfile.TemporaryDirectory() as d:
        ex = _make(safety, d)
        out = asyncio.run(ex.execute_signal(_signal(), "MES_vwap_rank1"))
    assert out["executed"] is False and out["gate"] == "kill_switch", out
    safety.submit_paper_order.assert_not_awaited()
    print("[PASS] refuses to submit when kill switch is active")


def test_executes_deployed_candidate_dry_run():
    safety = _mock_safety(approved=True, reason="dry-run", order_id=None, routed=False)
    with tempfile.TemporaryDirectory() as d:
        ledger = Path(d) / "exec.jsonl"
        ex = _make(safety, d)
        out = asyncio.run(ex.execute_signal(_signal(side="long"), "MES_vwap_rank1"))
        assert out["executed"] is True and out["approved"] is True, out
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
        ex = _make(safety, d)
        sig = _signal(date="2026-06-26")
        first = asyncio.run(ex.execute_signal(sig, "MES_vwap_rank1"))
        second = asyncio.run(ex.execute_signal(sig, "MES_vwap_rank1"))
    assert first["executed"] is True, first
    assert second["executed"] is False and second["gate"] in (
        "duplicate",
        "cross_path_duplicate",
    ), second
    safety.submit_paper_order.assert_awaited_once()  # exactly once across both
    print("[PASS] idempotent: identical signal never double-submits")


def test_cross_path_duplicate_blocks_when_queue_already_submitted():
    """The shared-dedup scenario: the auto-approve queue already recorded a MES
    BUY for today; the bridge must skip the same opportunity."""
    safety = _mock_safety()
    with tempfile.TemporaryDirectory() as d:
        shared = SubmissionDedup(Path(d) / "dedup.jsonl")
        # simulate the queue path having already submitted MES BUY today
        shared.record(
            shared.make_key("MES", "BUY", "2026-06-26"), source="queue", native_id="row-1"
        )
        ex = _make(safety, d, dedup=shared)
        out = asyncio.run(
            ex.execute_signal(_signal(side="long", date="2026-06-26"), "MES_vwap_rank1")
        )
    assert out["executed"] is False and out["gate"] == "cross_path_duplicate", out
    safety.submit_paper_order.assert_not_awaited()
    print("[PASS] cross-path dedup: bridge skips what the queue already submitted")


def test_short_maps_to_sell():
    safety = _mock_safety()
    with tempfile.TemporaryDirectory() as d:
        ex = _make(safety, d)
        asyncio.run(ex.execute_signal(_signal(side="short"), "MES_vwap_rank1"))
    assert safety.submit_paper_order.await_args.kwargs["action"] == "SELL"
    print("[PASS] short side -> SELL action")


def test_safety_rejection_passed_through_and_recorded():
    safety = _mock_safety(approved=False, reason="Kill switch active")
    with tempfile.TemporaryDirectory() as d:
        ledger = Path(d) / "exec.jsonl"
        shared = SubmissionDedup(Path(d) / "dedup.jsonl")
        ex = _make(safety, d, dedup=shared)
        out = asyncio.run(ex.execute_signal(_signal(), "MES_vwap_rank1"))
        assert out["executed"] is True and out["approved"] is False, out
        assert "Kill switch" in out["reason"], out
        recs = [json.loads(x) for x in ledger.read_text().splitlines() if x.strip()]
        assert len(recs) == 1 and recs[0]["approved"] is False, recs
        # a REJECTED submit must NOT claim the shared cross-path slot
        assert shared.already_submitted(shared.make_key("MES", "BUY", "2026-06-26")) is False
    print("[PASS] safety rejection passed through, recorded, does NOT claim shared slot")


def test_unrouted_submit_does_not_claim_shared_slot():
    """approved=True but routed_to_ib=False (broker call raised) placed nothing at
    IB, so it must not block the queue path via the cross-path dedup ledger."""
    safety = _mock_safety(approved=True, reason="IB order failed", routed=False)
    with tempfile.TemporaryDirectory() as d:
        shared = SubmissionDedup(Path(d) / "dedup.jsonl")
        ex = _make(safety, d, dedup=shared)
        out = asyncio.run(ex.execute_signal(_signal(), "MES_vwap_rank1"))
        assert out["approved"] is True and out["routed_to_ib"] is False, out
        assert shared.already_submitted(shared.make_key("MES", "BUY", "2026-06-26")) is False
    print("[PASS] unrouted submit does NOT claim shared slot")


def test_routed_submit_claims_shared_slot():
    safety = _mock_safety(approved=True, reason="ok", order_id="101", routed=True)
    with tempfile.TemporaryDirectory() as d:
        shared = SubmissionDedup(Path(d) / "dedup.jsonl")
        ex = _make(safety, d, dedup=shared)
        asyncio.run(ex.execute_signal(_signal(), "MES_vwap_rank1"))
        assert shared.already_submitted(shared.make_key("MES", "BUY", "2026-06-26")) is True
    print("[PASS] routed submit claims shared slot")


def main():
    tests = [
        test_disabled_by_default_submits_nothing,
        test_blocks_non_deployed_candidate,
        test_refuses_live_mode,
        test_refuses_when_kill_switch_active,
        test_executes_deployed_candidate_dry_run,
        test_idempotent_no_double_submit,
        test_cross_path_duplicate_blocks_when_queue_already_submitted,
        test_short_maps_to_sell,
        test_safety_rejection_passed_through_and_recorded,
        test_unrouted_submit_does_not_claim_shared_slot,
        test_routed_submit_claims_shared_slot,
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
