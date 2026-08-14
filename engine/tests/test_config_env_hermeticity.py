"""
JARVIS TRADER — Config env-loading hermeticity (MR-6.1)

config.py's _validate_required_env_vars() used to call
load_dotenv(dotenv_path=".env", override=True) unconditionally at module
import time. Since tests run with cwd=engine/, ".env" resolved to the LIVE
engine/.env — override=True meant every real secret in that file (including
ones tests/conftest.py never stubs, e.g. MOONSHOT_API_KEY,
JARVIS_DECISION_PRIMARY, GOOGLE_API_KEY) landed in os.environ during pytest
runs. llm/client.py reads those keys straight from os.environ, so a test
that constructed a real client could make a live, billed network call
instead of exercising the mocked/unconfigured path it was asserting on
(observed ~$0.007 real spend). The fix: skip the .env load entirely when
TESTING=1 (the sentinel tests/conftest.py sets before config is imported).

These tests use a synthetic temp .env (never the real engine/.env) so they
are deterministic and don't depend on what secrets happen to be on this
machine.
"""

import importlib
import os

import pytest


@pytest.fixture
def isolated_dotenv(tmp_path, monkeypatch):
    """A throwaway cwd containing a synthetic .env with canary secrets.

    load_dotenv(dotenv_path=".env") resolves relative to cwd, so chdir'ing
    here means _validate_required_env_vars() reads THIS file, never the
    real engine/.env.
    """
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text(
        "MR61_CANARY_VAR=should-not-leak-under-testing\n"
        "MOONSHOT_API_KEY=sk-fake-canary-do-not-leak\n"
        "JARVIS_DECISION_PRIMARY=kimi-canary\n"
        "API_KEY=canary-key\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    for var in ("MR61_CANARY_VAR", "MOONSHOT_API_KEY", "JARVIS_DECISION_PRIMARY", "API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return dotenv_file


def _reload_config():
    """Re-import config fresh so module-level _validate_required_env_vars() reruns."""
    import config

    return importlib.reload(config)


def test_testing_mode_does_not_load_dotenv_at_all(isolated_dotenv, monkeypatch):
    """Under TESTING=1, the synthetic .env's vars never reach os.environ."""
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("API_KEY", "conftest-stub-key")  # conftest always sets this

    _reload_config()

    assert "MR61_CANARY_VAR" not in os.environ
    assert "MOONSHOT_API_KEY" not in os.environ
    assert "JARVIS_DECISION_PRIMARY" not in os.environ
    # The var conftest DID stub is left exactly as conftest set it — not
    # overwritten by the synthetic .env's API_KEY=canary-key.
    assert os.environ["API_KEY"] == "conftest-stub-key"


def test_non_testing_mode_still_loads_dotenv(isolated_dotenv, monkeypatch):
    """Outside pytest (TESTING unset), .env loading behaves as before —
    this proves the fix is scoped to tests, not a behavior change for the
    real engine process."""
    monkeypatch.delenv("TESTING", raising=False)

    _reload_config()

    assert os.environ["MR61_CANARY_VAR"] == "should-not-leak-under-testing"
    assert os.environ["MOONSHOT_API_KEY"] == "sk-fake-canary-do-not-leak"
    assert os.environ["JARVIS_DECISION_PRIMARY"] == "kimi-canary"


def test_llm_client_sees_no_provider_keys_when_testing_and_dotenv_has_them(
    isolated_dotenv, monkeypatch
):
    """End-to-end: with TESTING=1 and a .env that DOES define provider
    keys, llm/client.py's os.getenv reads for those keys come back empty —
    the exact condition that keeps a decision-tier client from routing to
    a real, billed provider call during a test."""
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("API_KEY", "conftest-stub-key")

    _reload_config()

    assert os.getenv("MOONSHOT_API_KEY", "") == ""
    assert os.getenv("JARVIS_DECISION_PRIMARY", "") == ""
