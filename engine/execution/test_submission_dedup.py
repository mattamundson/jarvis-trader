"""TDD for the cross-path paper-order submission dedup ledger.

Two autonomous paper paths (auto-approve queue + systematic bridge) submit through
the SAME SafetyLayer.submit_paper_order but with SEPARATE idempotency. With both
live, the same (symbol, action, trading_date) could submit twice -> 2x exposure /
double fill. This ledger is the ONE shared first-wins guard both consult.

Run:  cd engine && .venv/Scripts/python execution/test_submission_dedup.py
  or: cd engine && .venv/Scripts/python -m pytest execution/test_submission_dedup.py
"""

from __future__ import annotations

import datetime as dt
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from execution.submission_dedup import SubmissionDedup  # noqa: E402


def test_fresh_key_not_submitted_then_recorded():
    with tempfile.TemporaryDirectory() as d:
        led = SubmissionDedup(Path(d) / "dd.jsonl")
        k = led.make_key("MES", "BUY", "2026-06-29")
        assert led.already_submitted(k) is False
        assert led.record(k, source="bridge", native_id="MES_vwap_rank1") is True
        assert led.already_submitted(k) is True
    print("[PASS] fresh key -> not submitted; after record -> submitted")


def test_make_key_normalizes_case_and_date_formats():
    k_str = SubmissionDedup.make_key("MES", "BUY", "2026-06-29")
    assert SubmissionDedup.make_key("mes", "buy", "2026-06-29") == k_str, "case-insensitive"
    assert SubmissionDedup.make_key("MES", "BUY", dt.date(2026, 6, 29)) == k_str, "date obj"
    assert (
        SubmissionDedup.make_key("MES", "BUY", dt.datetime(2026, 6, 29, 10, 30)) == k_str
    ), "datetime obj"
    assert (
        SubmissionDedup.make_key("MES", "BUY", "2026-06-29T14:00:00Z") == k_str
    ), "iso datetime str"
    print("[PASS] make_key normalizes symbol/action case + date/datetime/str formats")


def test_record_idempotent():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "dd.jsonl"
        led = SubmissionDedup(path)
        k = led.make_key("MGC", "SELL", "2026-06-29")
        assert led.record(k, source="queue", native_id="42") is True
        assert led.record(k, source="bridge", native_id="x") is False, "second record is a no-op"
        assert led.already_submitted(k) is True
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
        assert len(lines) == 1, f"only one ledger line, got {len(lines)}"
    print("[PASS] record is idempotent (one line, second record returns False)")


def test_distinct_keys_independent():
    with tempfile.TemporaryDirectory() as d:
        led = SubmissionDedup(Path(d) / "dd.jsonl")
        a = led.make_key("MES", "BUY", "2026-06-29")
        led.record(a, source="bridge")
        # different action, different symbol, different date -> all independent
        assert led.already_submitted(led.make_key("MES", "SELL", "2026-06-29")) is False
        assert led.already_submitted(led.make_key("MNQ", "BUY", "2026-06-29")) is False
        assert led.already_submitted(led.make_key("MES", "BUY", "2026-06-30")) is False
    print("[PASS] distinct (symbol/action/date) keys are independent")


def test_persistence_across_instances():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "dd.jsonl"
        k = SubmissionDedup(path).make_key("MES", "BUY", "2026-06-29")
        SubmissionDedup(path).record(k, source="queue", native_id="7")
        # a fresh instance on the same path sees the prior record
        assert SubmissionDedup(path).already_submitted(k) is True
    print("[PASS] ledger persists across instances")


def test_cross_path_first_wins():
    """The scenario the guard exists for: queue submits MES BUY today, then the
    bridge tries the same -> bridge must see it as already submitted and skip."""
    with tempfile.TemporaryDirectory() as d:
        led = SubmissionDedup(Path(d) / "dd.jsonl")
        k = led.make_key("MES", "BUY", "2026-06-29")
        # path A (queue) submits + records
        assert not led.already_submitted(k)
        led.record(k, source="queue", native_id="row-99")
        # path B (bridge), same opportunity, must now skip
        assert led.already_submitted(k) is True, "bridge sees queue's submission"
    print("[PASS] cross-path first-wins: bridge skips what the queue already submitted")


def main():
    tests = [
        test_fresh_key_not_submitted_then_recorded,
        test_make_key_normalizes_case_and_date_formats,
        test_record_idempotent,
        test_distinct_keys_independent,
        test_persistence_across_instances,
        test_cross_path_first_wins,
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
    print(f"ALL {len(tests)} submission_dedup tests PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()
