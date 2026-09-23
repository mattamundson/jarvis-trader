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

import os

import pytest


@pytest.fixture
def isolated_dotenv(tmp_path):
    """A throwaway cwd containing a synthetic .env with canary secrets.

    load_dotenv(dotenv_path=".env") resolves relative to cwd, so chdir'ing
    here means _validate_required_env_vars() reads THIS file, never the
    real engine/.env.

    Deliberately does NOT use monkeypatch for the chdir/env changes: a
    monkeypatch.setenv/delenv call made while os.environ is mid-isolation
    here registers its OWN teardown, and that teardown was observed to run
    AFTER this fixture's own `finally` block (fixture teardown order across
    independently-requested fixtures isn't simply reverse signature order),
    silently deleting API_KEY again right before the next test's setup ran
    and crashing its TradingConfig() construction. One writer (this
    fixture), manually snapshotting and restoring the full os.environ + cwd
    and refreshing config's settings in `finally`, removes the race
    entirely — see _reload_config() for why it refreshes fields in place
    rather than replacing the module.
    """
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text(
        "MR61_CANARY_VAR=should-not-leak-under-testing\n"
        "MOONSHOT_API_KEY=sk-fake-canary-do-not-leak\n"
        "JARVIS_DECISION_PRIMARY=kimi-canary\n"
        "API_KEY=canary-key\n",
        encoding="utf-8",
    )
    orig_cwd = os.getcwd()
    orig_env = dict(os.environ)
    try:
        os.chdir(tmp_path)
        for var in ("MR61_CANARY_VAR", "MOONSHOT_API_KEY", "JARVIS_DECISION_PRIMARY", "API_KEY"):
            os.environ.pop(var, None)
        yield dotenv_file
    finally:
        os.chdir(orig_cwd)
        os.environ.clear()
        os.environ.update(orig_env)
        _reload_config()


def _reload_config():
    """Rerun _validate_required_env_vars() and refresh config.settings' field
    values for the current environment.

    Deliberately does NOT use importlib.reload(config): that replaces
    config.settings with a brand-new TradingConfig instance, but every
    module that already did `from config import settings` before this runs
    (middleware/auth.py, routers/phase3_readiness_router.py, and others)
    holds a direct reference to the OLD object, not to `config`'s current
    attribute — reload silently desyncs them from whatever a test sets up
    afterward (observed: test_phase3_readiness_position_cap.py's
    _patch_setting(settings, "MAX_SINGLE_ORDER_VALUE", ...) had zero effect
    on the router under test, which kept reading its own stale pre-reload
    object). Updating the existing singleton's fields in place keeps every
    already-captured reference correct instead.
    """
    import config

    fresh = config.TradingConfig()
    for field_name in type(fresh).model_fields:
        object.__setattr__(config.settings, field_name, getattr(fresh, field_name))
    config._validate_required_env_vars()
    return config


def test_testing_mode_does_not_load_dotenv_at_all(isolated_dotenv):
    """Under TESTING=1, the synthetic .env's vars never reach os.environ.

    Sets env vars directly (not via monkeypatch): isolated_dotenv's own
    finally block already snapshots/restores the full os.environ, and a
    second, competing monkeypatch finalizer here was observed to run AFTER
    that restore completes (fixture teardown order isn't simply reverse
    signature order across independent fixtures) — deleting API_KEY again
    right before the next test's setup ran, which crashed the next test's
    TradingConfig() construction. One writer, deterministic order.
    """
    os.environ["TESTING"] = "1"
    os.environ["API_KEY"] = "conftest-stub-key"  # conftest always sets this

    _reload_config()

    assert "MR61_CANARY_VAR" not in os.environ
    assert "MOONSHOT_API_KEY" not in os.environ
    assert "JARVIS_DECISION_PRIMARY" not in os.environ
    # The var conftest DID stub is left exactly as conftest set it — not
    # overwritten by the synthetic .env's API_KEY=canary-key.
    assert os.environ["API_KEY"] == "conftest-stub-key"


def test_non_testing_mode_still_loads_dotenv(isolated_dotenv):
    """Outside pytest (TESTING unset), .env loading behaves as before —
    this proves the fix is scoped to tests, not a behavior change for the
    real engine process."""
    os.environ.pop("TESTING", None)

    _reload_config()

    assert os.environ["MR61_CANARY_VAR"] == "should-not-leak-under-testing"
    assert os.environ["MOONSHOT_API_KEY"] == "sk-fake-canary-do-not-leak"
    assert os.environ["JARVIS_DECISION_PRIMARY"] == "kimi-canary"


def test_llm_client_sees_no_provider_keys_when_testing_and_dotenv_has_them(
    isolated_dotenv,
):
    """End-to-end: with TESTING=1 and a .env that DOES define provider
    keys, llm/client.py's os.getenv reads for those keys come back empty —
    the exact condition that keeps a decision-tier client from routing to
    a real, billed provider call during a test."""
    os.environ["TESTING"] = "1"
    os.environ["API_KEY"] = "conftest-stub-key"

    _reload_config()

    assert os.getenv("MOONSHOT_API_KEY", "") == ""
    assert os.getenv("JARVIS_DECISION_PRIMARY", "") == ""
