"""Guard: paper_runner JSON state writes are atomic (temp + os.replace).

entry_eval persists the crossover-bar dedup that prevents re-entering the same
1h bar on the next 5-minute poll. A torn (partial) write makes _load_entry_eval
fall back to {} — wiping the dedup and re-enabling a DOUBLE ENTRY. The standalone
Jarvis-PaperCollect task and the in-process engine can both write it, so torn
writes were reachable. These tests pin atomic round-trips and no leftover temp.
"""

from __future__ import annotations

from pathlib import Path

from backtest import paper_runner


def test_atomic_write_json_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_runner, "_RESULTS_DIR", tmp_path)

    paper_runner._save_entry_eval({"MES": "2026-06-05T14:00:00"})
    assert paper_runner._load_entry_eval() == {"MES": "2026-06-05T14:00:00"}

    # No leftover temp file beside the real one.
    assert not (tmp_path / "entry_eval.json.tmp").exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_overwrite_keeps_valid_json(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_runner, "_RESULTS_DIR", tmp_path)

    paper_runner._save_entry_eval({"MES": "old"})
    paper_runner._save_entry_eval({"MES": "new", "MGC": "x"})  # overwrite

    assert paper_runner._load_entry_eval() == {"MES": "new", "MGC": "x"}


def test_data_error_state_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_runner, "_RESULTS_DIR", tmp_path)

    paper_runner._save_data_error_state({"MNQ": 3})
    assert paper_runner._load_data_error_state() == {"MNQ": 3}
    assert list(tmp_path.glob("*.tmp")) == []


def test_corrupt_existing_file_still_recovers_to_empty(tmp_path, monkeypatch):
    # A pre-existing corrupt file must not raise — the loader degrades to {}.
    monkeypatch.setattr(paper_runner, "_RESULTS_DIR", tmp_path)
    p: Path = paper_runner._entry_eval_path()
    p.write_text("{ this is not json", encoding="utf-8")
    assert paper_runner._load_entry_eval() == {}
    # And a subsequent atomic save repairs it.
    paper_runner._save_entry_eval({"MES": "ok"})
    assert paper_runner._load_entry_eval() == {"MES": "ok"}
