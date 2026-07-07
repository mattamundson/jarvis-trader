"""
US-008 — Lock the resolutions of the two previously-open TODOs at
session_manager.py:232 and recipe_loader.py:90 so that if either claim
("wired into X") regresses, CI fails instead of silently drifting back
toward stale-TODO state.

Resolutions:
  * session_manager: wired via agent_gateway.GatewaySessionStore (messaging
    channel scope, not per-pipeline scope as the original TODO imagined).
  * recipe_loader: wired via pipeline.run_pipeline's active_recipe_name kwarg
    which overrides entry_max_vix / min_confluence / size_mult.
"""

import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.session_manager import SessionManager  # noqa: E402
from services.agent_gateway import GatewaySessionStore  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# session_manager.py — close_session works, gateway uses SessionManager
# ─────────────────────────────────────────────────────────────────────────────


class TestSessionManagerResolution:
    def test_close_session_updates_timestamp_idempotently(self, tmp_path):
        """Regression: close_session must be safe to call repeatedly."""
        db_path = tmp_path / "test.db"
        mgr = SessionManager(db_path)
        sid = mgr.create_session("test_close")
        mgr.close_session(sid)
        mgr.close_session(sid)  # idempotent — no exception

    def test_close_session_noop_on_missing_id(self, tmp_path):
        """Closing a non-existent session should not raise."""
        db_path = tmp_path / "test.db"
        mgr = SessionManager(db_path)
        mgr.close_session(999999)  # no exception

    def test_gateway_session_store_uses_session_manager(self, tmp_path):
        """
        GatewaySessionStore composes SessionManager — this is the wiring point
        the TODO at session_manager.py:232 pointed to. If someone later
        removes SessionManager from the gateway, this test fails and forces
        a re-evaluation of where session lifecycle lives.
        """
        db_path = tmp_path / "gw.db"
        store = GatewaySessionStore(db_path)
        assert isinstance(store._session_manager, SessionManager)


# ─────────────────────────────────────────────────────────────────────────────
# recipe_loader.py — pipeline signature accepts active_recipe_name
# ─────────────────────────────────────────────────────────────────────────────


class TestRecipeLoaderResolution:
    def test_pipeline_run_accepts_active_recipe_name_kwarg(self):
        """
        The TODO at recipe_loader.py:90 asked for an optional active_recipe_name
        kwarg on the pipeline entry. Assert its existence directly on the
        signature so renaming/removing it trips this test.
        """
        from agents.pipeline import TradingPipeline

        sig = inspect.signature(TradingPipeline.analyze_and_decide)
        assert "active_recipe_name" in sig.parameters
        param = sig.parameters["active_recipe_name"]
        # Default must be None to preserve legacy behavior.
        assert param.default is None

    def test_recipe_loader_import_used_in_pipeline(self):
        """If RecipeLoader import is removed from pipeline, this fails."""
        from agents import pipeline as pipeline_mod

        src = inspect.getsource(pipeline_mod)
        assert "RecipeLoader" in src
        assert "active_recipe" in src
