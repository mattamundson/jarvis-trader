"""Tests for reproducible research data/context fingerprints."""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.research_fingerprints import (
    ResearchFingerprintError,
    dataframe_fingerprint,
    manifest_fingerprint,
    research_context_fingerprint,
    sha256_file,
)


def test_file_hash_changes_when_content_changes(tmp_path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    first = sha256_file(path)
    path.write_text("a,b\n1,3\n", encoding="utf-8")
    second = sha256_file(path)
    assert first != second


def test_dataframe_fingerprint_is_stable_for_copy_but_order_sensitive() -> None:
    frame = pd.DataFrame({"x": [1, 2, 3], "y": [4.0, 5.0, 6.0]})
    assert dataframe_fingerprint(frame) == dataframe_fingerprint(frame.copy())
    assert dataframe_fingerprint(frame) != dataframe_fingerprint(frame.iloc[::-1])


def test_dataframe_schema_change_changes_fingerprint() -> None:
    frame = pd.DataFrame({"x": [1, 2, 3]})
    renamed = frame.rename(columns={"x": "z"})
    cast = frame.astype({"x": "float64"})
    assert dataframe_fingerprint(frame) != dataframe_fingerprint(renamed)
    assert dataframe_fingerprint(frame) != dataframe_fingerprint(cast)


def test_manifest_fingerprint_is_input_order_invariant(tmp_path) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("alpha", encoding="utf-8")
    b.write_text("beta", encoding="utf-8")
    first = manifest_fingerprint([a, b], root=tmp_path)
    second = manifest_fingerprint([b, a], root=tmp_path)
    assert first == second


def test_manifest_change_changes_fingerprint(tmp_path) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("alpha", encoding="utf-8")
    b.write_text("beta", encoding="utf-8")
    first = manifest_fingerprint([a, b], root=tmp_path)
    b.write_text("gamma", encoding="utf-8")
    second = manifest_fingerprint([a, b], root=tmp_path)
    assert first != second


def test_research_context_commits_to_every_component() -> None:
    kwargs = {
        "data_fingerprint": "data-a",
        "registry_fingerprint": "reg-a",
        "code_commit": "abc123",
        "configuration": {"stop": 0.75, "features": ["stc", "rs"]},
    }
    baseline = research_context_fingerprint(**kwargs)
    for key, replacement in (
        ("data_fingerprint", "data-b"),
        ("registry_fingerprint", "reg-b"),
        ("code_commit", "def456"),
        ("configuration", {"stop": 0.50, "features": ["stc", "rs"]}),
    ):
        changed = dict(kwargs)
        changed[key] = replacement
        assert research_context_fingerprint(**changed) != baseline


def test_fingerprint_inputs_fail_closed_when_missing(tmp_path) -> None:
    with pytest.raises(ResearchFingerprintError, match="not a file"):
        sha256_file(tmp_path / "missing")
    with pytest.raises(ResearchFingerprintError, match="at least one"):
        manifest_fingerprint([])
    with pytest.raises(ResearchFingerprintError, match="code_commit"):
        research_context_fingerprint(
            data_fingerprint="data",
            registry_fingerprint="registry",
            code_commit="",
            configuration={},
        )
