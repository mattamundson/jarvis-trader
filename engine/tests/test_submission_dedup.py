"""
Coverage gap fix (US-103): execution/submission_dedup.py showed 0% coverage in
the engine/risk + engine/execution + engine/portfolio audit despite already
having a full hand-written test suite at
``execution/test_submission_dedup.py`` — that file lives outside ``tests/``
so ``pytest tests/`` never collects it and every line of the module reports
as a coverage miss.

This module is the shared first-wins ledger that prevents the auto-approve
queue and the systematic bridge from double-submitting the same paper-order
opportunity (see the module docstring on ``SubmissionDedup``) — i.e. it is a
double-exposure guard, not incidental plumbing, so leaving it uncollected by
the standard suite is a real gap.

This file re-expresses the same scenarios as pytest-native tests (rather than
importing the manual-runner module, which prints/`sys.exit`s and is meant to
be invoked directly) so they run under the normal ``pytest tests/`` sweep and
show up in ``--cov=execution``. The original file is left untouched as a
standalone manual-run entry point.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from execution.submission_dedup import SubmissionDedup


def test_fresh_key_not_submitted_then_recorded(tmp_path):
    led = SubmissionDedup(tmp_path / "dd.jsonl")
    key = led.make_key("MES", "BUY", "2026-06-29")

    assert led.already_submitted(key) is False
    assert led.record(key, source="bridge", native_id="MES_vwap_rank1") is True
    assert led.already_submitted(key) is True


def test_make_key_normalizes_case_and_date_formats():
    expected = SubmissionDedup.make_key("MES", "BUY", "2026-06-29")

    assert SubmissionDedup.make_key("mes", "buy", "2026-06-29") == expected
    assert SubmissionDedup.make_key("MES", "BUY", dt.date(2026, 6, 29)) == expected
    assert (
        SubmissionDedup.make_key("MES", "BUY", dt.datetime(2026, 6, 29, 10, 30))
        == expected
    )
    assert (
        SubmissionDedup.make_key("MES", "BUY", "2026-06-29T14:00:00Z") == expected
    )


def test_record_is_idempotent(tmp_path):
    path = tmp_path / "dd.jsonl"
    led = SubmissionDedup(path)
    key = led.make_key("MGC", "SELL", "2026-06-29")

    assert led.record(key, source="queue", native_id="42") is True
    # Second attempt at the same key is a no-op — the caller must not double-fill.
    assert led.record(key, source="bridge", native_id="x") is False
    assert led.already_submitted(key) is True

    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1, "record() must never write a duplicate ledger line"


def test_distinct_symbol_action_date_keys_are_independent(tmp_path):
    led = SubmissionDedup(tmp_path / "dd.jsonl")
    key_a = led.make_key("MES", "BUY", "2026-06-29")
    led.record(key_a, source="bridge")

    assert led.already_submitted(led.make_key("MES", "SELL", "2026-06-29")) is False
    assert led.already_submitted(led.make_key("MNQ", "BUY", "2026-06-29")) is False
    assert led.already_submitted(led.make_key("MES", "BUY", "2026-06-30")) is False


def test_ledger_persists_across_instances(tmp_path):
    path = tmp_path / "dd.jsonl"
    key = SubmissionDedup(path).make_key("MES", "BUY", "2026-06-29")
    SubmissionDedup(path).record(key, source="queue", native_id="7")

    # A fresh instance pointed at the same path sees the prior record.
    assert SubmissionDedup(path).already_submitted(key) is True


def test_cross_path_first_wins(tmp_path):
    """The scenario the guard exists for: the queue submits MES BUY today, then
    the bridge tries the same opportunity and must see it as already claimed."""
    led = SubmissionDedup(tmp_path / "dd.jsonl")
    key = led.make_key("MES", "BUY", "2026-06-29")

    assert not led.already_submitted(key)
    led.record(key, source="queue", native_id="row-99")
    assert led.already_submitted(key) is True, "bridge must see the queue's submission"


def test_already_submitted_false_when_ledger_file_absent(tmp_path):
    """No writes yet -> the ledger path doesn't exist; must read as empty, not raise."""
    led = SubmissionDedup(tmp_path / "does-not-exist.jsonl")
    assert led.already_submitted("MES|BUY|2026-06-29") is False


def test_keys_skips_malformed_json_lines(tmp_path):
    """A corrupt/partial line (e.g. a crash mid-write) must not break reads for
    every other, well-formed entry in the ledger."""
    path = tmp_path / "dd.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    good_key = SubmissionDedup.make_key("MGC", "BUY", "2026-06-29")
    path.write_text(
        '{"key": "' + good_key + '", "source": "queue", "native_id": "1"}\n'
        "not valid json\n"
        "\n",  # blank line
        encoding="utf-8",
    )

    led = SubmissionDedup(path)
    assert led.already_submitted(good_key) is True
    assert led.already_submitted("OTHER|SELL|2026-06-29") is False


def test_record_creates_parent_directory(tmp_path):
    """The ledger lives under a gitignored runtime dir that may not exist yet on
    a fresh checkout — record() must create it rather than raise FileNotFoundError."""
    nested = tmp_path / "nested" / "dir" / "dd.jsonl"
    led = SubmissionDedup(nested)

    assert not nested.parent.exists()
    key = led.make_key("MES", "BUY", "2026-06-29")
    assert led.record(key, source="queue") is True
    assert Path(nested).exists()


def test_default_ledger_path_under_engine_data():
    """No explicit path -> falls back to the shared runtime ledger location
    (engine/data/systematic_exec/submission_dedup.jsonl), not cwd or /tmp."""
    led = SubmissionDedup()
    assert led._path.parts[-3:] == ("data", "systematic_exec", "submission_dedup.jsonl")
