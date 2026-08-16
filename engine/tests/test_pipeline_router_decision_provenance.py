"""Data-provenance stamping for pipeline_router's insert_decision caller.

PR #286 stamped {last_bar_source, serve_age_s} onto main.py's `_log_decision`
path only. This pins the same stamping on `pipeline_router._log_decision_to_db`
(the /pipeline/run background-task decision-persist path), additive only —
no schema change, no change to existing signal_data fields.

Lightweight: exercises the module function directly (no full main.py import),
matching the style of tests/test_pipeline_cache_and_models.py.
"""

from __future__ import annotations

from routers import pipeline_router as pr_mod


class _FakeDM:
    def __init__(self, source, freshness):
        self._last_bar_source = source
        self._freshness = freshness

    def symbol_freshness(self):
        return self._freshness


class _FakeDB:
    def __init__(self):
        self.inserted: list[dict] = []

    def insert_decision(self, **kwargs):
        self.inserted.append(kwargs)
        return len(self.inserted)


def test_log_decision_to_db_stamps_provenance_when_data_manager_injected(monkeypatch):
    fake_db = _FakeDB()
    fake_dm = _FakeDM("ibkr", {"MES": 5.5})
    monkeypatch.setattr(pr_mod, "_db_manager", fake_db)
    monkeypatch.setattr(pr_mod, "_data_manager", fake_dm)

    caller_signal = {"rsi": 60}
    pr_mod._log_decision_to_db(
        symbol="MES",
        action="buy",
        confidence=0.75,
        source="pipeline",
        summary="test summary",
        reasoning="test reasoning",
        regime="trending",
        signal_data=caller_signal,
        full_pipeline_data=None,
    )

    assert len(fake_db.inserted) == 1
    sig = fake_db.inserted[0]["signal_data"]
    assert sig["data_provenance"] == {"last_bar_source": "ibkr", "serve_age_s": 5.5}
    assert sig["rsi"] == 60  # caller's fields preserved
    # caller's dict must NOT be mutated (copy-merge, not in-place)
    assert "data_provenance" not in caller_signal


def test_log_decision_to_db_survives_when_data_manager_absent(monkeypatch):
    fake_db = _FakeDB()
    monkeypatch.setattr(pr_mod, "_db_manager", fake_db)
    monkeypatch.setattr(pr_mod, "_data_manager", None)

    pr_mod._log_decision_to_db(
        symbol="MNQ",
        action="hold",
        confidence=0.0,
        source="pipeline",
        summary="no signal",
        reasoning="",
        regime=None,
        signal_data=None,
        full_pipeline_data=None,
    )

    assert len(fake_db.inserted) == 1
    sig = fake_db.inserted[0]["signal_data"]
    # No provenance available -> default signal_data used, no crash, no key added
    assert sig == {"source": "pipeline", "summary": "no signal"}
    assert "data_provenance" not in sig
