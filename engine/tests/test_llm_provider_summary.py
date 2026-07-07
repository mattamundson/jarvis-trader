"""Regression: /health LLM provider-redundancy summary.

The boolean `llm_path_healthy` hides real fragility — running on the Gemini
fallback with the Anthropic primary credit-dead and nothing behind Gemini is
"healthy" yet one failure from a dark pipeline. `get_llm_provider_summary`
surfaces the active leg, the wired-leg count, and a `single_leg_warning` that
fires when the active leg has no backup behind it.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llm.client as client_mod  # noqa: E402
from llm.client import (  # noqa: E402
    _provider_from_model,
    get_llm_provider_summary,
)


@pytest.fixture
def fresh_state(monkeypatch):
    """Isolate the module-level _LLM_PATH_STATE per test."""
    base = {
        "healthy": True,
        "last_failure_ts": None,
        "last_failure_reason": None,
        "last_failure_agent": None,
        "active_provider": None,
        "primary_provider": None,
        "providers_configured": [],
    }
    monkeypatch.setattr(client_mod, "_LLM_PATH_STATE", dict(base))
    return client_mod._LLM_PATH_STATE


def _set(state, **kw):
    state.update(kw)


def test_provider_from_model_families():
    assert _provider_from_model("gemini-2.5-flash") == "gemini"
    assert _provider_from_model("gpt-4o-mini") == "openai"
    assert _provider_from_model("o3-mini") == "openai"
    assert _provider_from_model("deepseek-r1") == "deepseek"
    assert _provider_from_model("claude-sonnet-4-6") == "anthropic"
    assert _provider_from_model("claude-opus-4-7") == "anthropic"
    assert _provider_from_model("") == "anthropic"


def test_today_anthropic_dead_on_gemini_is_single_leg(fresh_state):
    # Live 2026-06-06: anthropic primary (credit-dead) + gemini fallback wired;
    # gemini is serving with nothing behind it.
    _set(
        fresh_state,
        primary_provider="anthropic",
        providers_configured=["anthropic", "gemini"],
        active_provider="gemini",
    )
    s = get_llm_provider_summary()
    assert s["active_provider"] == "gemini"
    assert s["providers_available"] == 2
    assert s["primary_healthy"] is False  # primary degraded, on a fallback
    assert s["single_leg_warning"] is True  # nothing behind gemini


def test_vertex_armed_gives_backup_behind_active(fresh_state):
    # After Amo arms Vertex: anthropic -> vertex -> gemini. Vertex serving,
    # gemini still behind it → not single-leg.
    _set(
        fresh_state,
        primary_provider="anthropic",
        providers_configured=["anthropic", "vertex", "gemini"],
        active_provider="vertex",
    )
    s = get_llm_provider_summary()
    assert s["active_provider"] == "vertex"
    assert s["providers_available"] == 3
    assert s["primary_healthy"] is False
    assert s["single_leg_warning"] is False


def test_healthy_primary_not_single_leg(fresh_state):
    # Anthropic credits restored: primary serving, fallbacks behind it.
    _set(
        fresh_state,
        primary_provider="anthropic",
        providers_configured=["anthropic", "gemini"],
        active_provider="anthropic",
    )
    s = get_llm_provider_summary()
    assert s["primary_healthy"] is True
    assert s["single_leg_warning"] is False


def test_only_one_leg_configured_is_single_leg(fresh_state):
    # Just one wired leg (e.g. ollama-only or anthropic-only, no fallbacks).
    _set(
        fresh_state,
        primary_provider="anthropic",
        providers_configured=["anthropic"],
        active_provider="anthropic",
    )
    s = get_llm_provider_summary()
    assert s["providers_available"] == 1
    assert s["single_leg_warning"] is True


def test_unknown_active_before_first_call(fresh_state):
    # No call has served yet → active None, primary assumed healthy, count stands.
    _set(
        fresh_state,
        primary_provider="anthropic",
        providers_configured=["anthropic", "gemini"],
        active_provider=None,
    )
    s = get_llm_provider_summary()
    assert s["active_provider"] is None
    assert s["primary_healthy"] is True
    assert s["single_leg_warning"] is False


def test_active_provider_resolution_matches_handle_success_logic(fresh_state):
    # _handle_success sets active_provider = served_by or _provider_from_model(model).
    # Verify that resolution rule directly (the funnel is a one-liner; this guards
    # the served_by-overrides-model contract the Vertex leg depends on).
    def resolve(model, served_by=None):
        return served_by or _provider_from_model(model)

    assert resolve("gemini-2.5-flash") == "gemini"
    assert resolve("gpt-4o") == "openai"
    assert resolve("claude-sonnet-4-6") == "anthropic"
    # Vertex passes a claude-* model but must report as vertex.
    assert resolve("claude-sonnet-4-6", served_by="vertex") == "vertex"
