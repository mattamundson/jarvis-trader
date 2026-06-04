"""Regression: analysis.discord_correlation must not resolve the DB at import.

An eager ``DB_PATH = _find_db()`` at module top raised FileNotFoundError during
pytest *collection* in CI (no jarvis_trader.db present in the runner), which
failed the entire engine test suite at conftest import. Resolution is now lazy
(``_db_path()``), so importing the module — and the conftest chain that
transitively imports it — succeeds without a DB.
"""
import subprocess
import sys
from pathlib import Path

import pytest

_ENGINE_DIR = Path(__file__).resolve().parent.parent


def test_import_does_not_resolve_db():
    """A fresh interpreter must import the module without resolving the DB.

    Mirrors the CI condition: if import eagerly resolved the DB, the cache would
    be populated (or, with no DB present, import would raise outright).
    """
    code = (
        "import analysis.discord_correlation as dc;"
        "assert dc._DB_PATH_CACHE is None, 'DB resolved at import';"
        "print('LAZY_OK')"
    )
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_ENGINE_DIR),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "LAZY_OK" in r.stdout


def test_db_path_is_cached(monkeypatch):
    import analysis.discord_correlation as dc

    calls = {"n": 0}

    def fake_find():
        calls["n"] += 1
        return Path("/tmp/fake_jarvis.db")

    monkeypatch.setattr(dc, "_DB_PATH_CACHE", None)
    monkeypatch.setattr(dc, "_find_db", fake_find)
    p1 = dc._db_path()
    p2 = dc._db_path()
    assert p1 == p2 == Path("/tmp/fake_jarvis.db")
    assert calls["n"] == 1  # resolved once, then cached


def test_db_path_raises_only_when_called(monkeypatch):
    import analysis.discord_correlation as dc

    def boom():
        raise FileNotFoundError("no db")

    monkeypatch.setattr(dc, "_DB_PATH_CACHE", None)
    monkeypatch.setattr(dc, "_find_db", boom)
    # Import already succeeded (this test is running); the error must surface
    # only when the path is actually needed.
    with pytest.raises(FileNotFoundError):
        dc._db_path()


def test_default_output_filename(monkeypatch):
    import analysis.discord_correlation as dc

    monkeypatch.setattr(dc, "_DB_PATH_CACHE", None)
    monkeypatch.setattr(dc, "_find_db", lambda: Path("/data/jarvis_trader.db"))
    assert dc._default_output() == Path("/data/discord_correlation_study.csv")
