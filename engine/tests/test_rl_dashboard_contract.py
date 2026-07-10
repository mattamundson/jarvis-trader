"""
Regression tests — RL Lab dashboard/backend contract (Item 9, ROI backlog).

Covers two field-shape gaps between the engine's RL endpoints and the
dashboard's TypeScript interfaces (dashboard/app/strategies/page.tsx):

1. GET /strategies/rl/models — RLTrainer.list_models() previously returned
   {run_id, completed, metadata} but the frontend's SavedModel interface
   requires {symbol, path, size_kb, metadata}. Missing `path` caused
   ModelsListPanel and ExecutorStatusPanel's deploy dropdown to call
   basename(undefined) -> TypeError (Deploy Model dropdown crash risk).

2. GET /strategies/rl/executor/status — the router only returned
   {executor_count, executors}. The dashboard's simplified
   RLExecutorStatusCard checks `"deployed" in execResp` before populating
   its state, so with the field missing entirely the card silently stayed
   on execStatus=null forever (always showing "NOT DEPLOYED" even when an
   executor is actually live).

These are pure unit tests against RLTrainer.list_models() and
strategies_router.executor_status() directly — no live engine, no FastAPI
TestClient/app boot required (both modules import standalone).

Run:
    cd engine && .venv/Scripts/python -m pytest tests/test_rl_dashboard_contract.py -v
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from strategies.rl_trainer import RLTrainer

# ---------------------------------------------------------------------------
# GET /strategies/rl/models — symbol / path / size_kb
# ---------------------------------------------------------------------------


class TestListModelsDashboardContract:
    """RLTrainer.list_models() must supply the fields SavedModel needs."""

    def _make_model_files(self, models_dir: Path, stem: str, payload_bytes: bytes, meta: dict | None = None):
        models_dir.mkdir(parents=True, exist_ok=True)
        zip_path = models_dir / f"{stem}.zip"
        zip_path.write_bytes(payload_bytes)
        if meta is not None:
            (models_dir / f"{stem}.json").write_text(json.dumps(meta))
        return zip_path

    def test_list_models_includes_symbol_path_size_kb(self, tmp_path):
        """Each model entry must include symbol, path, size_kb alongside the
        existing run_id/completed/metadata fields (never drop the legacy
        fields — test_integration_rl_endpoints.py::test_rl_models_model_entry_fields
        asserts those are still present on the live engine)."""
        models_dir = tmp_path / "rl_models"
        self._make_model_files(models_dir, "MES_20260710_010101", b"x" * 2048, meta={"foo": "bar"})

        with patch("strategies.rl_trainer.RL_MODELS_DIR", models_dir):
            trainer = RLTrainer(data_manager=None)
            models = trainer.list_models()

        assert len(models) == 1
        entry = models[0]

        # Legacy fields must still be present (existing integration test contract).
        assert entry["run_id"] == "MES_20260710_010101"
        assert entry["completed"] is True
        assert entry["metadata"] == {"foo": "bar"}

        # New fields the dashboard's SavedModel interface requires.
        assert entry["symbol"] == "MES"
        assert entry["path"] == str(models_dir / "MES_20260710_010101")
        assert entry["size_kb"] == pytest.approx(2048 / 1024, abs=0.01)

    def test_list_models_size_kb_reflects_real_file_size_not_a_placeholder(self, tmp_path):
        """size_kb must trace to the actual .zip file size on disk — two
        differently-sized models must report different, correct sizes."""
        models_dir = tmp_path / "rl_models"
        self._make_model_files(models_dir, "MES_small", b"a" * 1024)
        self._make_model_files(models_dir, "MES_big", b"b" * 10240)

        with patch("strategies.rl_trainer.RL_MODELS_DIR", models_dir):
            trainer = RLTrainer(data_manager=None)
            models = {m["run_id"]: m for m in trainer.list_models()}

        assert models["MES_small"]["size_kb"] == pytest.approx(1.0, abs=0.01)
        assert models["MES_big"]["size_kb"] == pytest.approx(10.0, abs=0.01)

    def test_list_models_path_matches_model_path_convention(self, tmp_path):
        """`path` must be the model path WITHOUT the .zip extension — matching
        DeployRequest.model_path / EvaluateRequest.model_path docs elsewhere
        in this module ("Path to saved model (without .zip extension)")."""
        models_dir = tmp_path / "rl_models"
        self._make_model_files(models_dir, "MGC_run1", b"z" * 512)

        with patch("strategies.rl_trainer.RL_MODELS_DIR", models_dir):
            trainer = RLTrainer(data_manager=None)
            entry = trainer.list_models()[0]

        assert not entry["path"].endswith(".zip")
        assert Path(f"{entry['path']}.zip").exists()

    def test_list_models_symbol_derived_from_filename_prefix(self, tmp_path):
        """symbol must be the real underscore-prefix of the filename, matching
        the existing filter logic (model_symbol) already used by ?symbol=."""
        models_dir = tmp_path / "rl_models"
        self._make_model_files(models_dir, "MNQ_walkforward_best", b"c" * 100)

        with patch("strategies.rl_trainer.RL_MODELS_DIR", models_dir):
            trainer = RLTrainer(data_manager=None)
            entry = trainer.list_models()[0]

        assert entry["symbol"] == "MNQ"


# ---------------------------------------------------------------------------
# GET /strategies/rl/executor/status — flattened deployed/last_prediction view
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


class TestExecutorStatusDashboardContract:
    """
    strategies_router.executor_status() must include the flattened
    single-executor fields the dashboard's RLExecutorStatusCard needs:
    deployed, symbol, model_path, last_prediction, last_prediction_time,
    next_fire_time -- in addition to the existing executor_count/executors.
    """

    def test_no_executors_deployed(self):
        import routers.strategies_router as sr

        with patch("strategies.rl_executor.get_executor_status", return_value={}):
            result = _run(sr.executor_status())

        assert result["executor_count"] == 0
        assert result["executors"] == {}
        assert result["deployed"] is False
        assert result["symbol"] is None
        assert result["model_path"] is None
        assert result["last_prediction"] is None
        assert result["last_prediction_time"] is None
        assert result["next_fire_time"] is None

    def test_single_executor_deployed_flattens_its_real_fields(self):
        import routers.strategies_router as sr

        fake_status = {
            "MES": {
                "symbol": "MES",
                "model_path": "data/rl_models/MES_20260710",
                "is_running": True,
                "scheduler_running": True,
                "model_loaded": True,
                "last_action": "BUY",
                "last_prediction_time": "2026-07-10T14:00:00+00:00",
                "bars_executed": 12,
                "paper_position": 1,
                "entry_price": 5123.25,
                "bars_in_trade": 3,
                "last_error": None,
                "next_fire_time": "2026-07-10T15:00:00+00:00",
            }
        }

        with patch("strategies.rl_executor.get_executor_status", return_value=fake_status):
            result = _run(sr.executor_status())

        assert result["executor_count"] == 1
        assert result["executors"] == fake_status
        assert result["deployed"] is True
        assert result["symbol"] == "MES"
        assert result["model_path"] == "data/rl_models/MES_20260710"
        # last_prediction mirrors the executor's real last_action, not a placeholder.
        assert result["last_prediction"] == "BUY"
        assert result["last_prediction_time"] == "2026-07-10T14:00:00+00:00"
        assert result["next_fire_time"] == "2026-07-10T15:00:00+00:00"

    def test_multiple_executors_picks_most_recently_predicted(self):
        """When MES + MGC are both deployed, the flattened view must surface
        whichever executor actually predicted most recently -- a real,
        deterministic, non-fabricated selection -- not an arbitrary/blank one."""
        import routers.strategies_router as sr

        fake_status = {
            "MES": {
                "symbol": "MES",
                "model_path": "data/rl_models/MES_old",
                "last_action": "HOLD",
                "last_prediction_time": "2026-07-10T10:00:00+00:00",
                "next_fire_time": "2026-07-10T15:00:00+00:00",
            },
            "MGC": {
                "symbol": "MGC",
                "model_path": "data/rl_models/MGC_new",
                "last_action": "SELL",
                "last_prediction_time": "2026-07-10T14:00:00+00:00",
                "next_fire_time": "2026-07-10T15:00:00+00:00",
            },
        }

        with patch("strategies.rl_executor.get_executor_status", return_value=fake_status):
            result = _run(sr.executor_status())

        assert result["deployed"] is True
        assert result["symbol"] == "MGC"
        assert result["last_prediction"] == "SELL"
        assert result["last_prediction_time"] == "2026-07-10T14:00:00+00:00"
        # Multi-symbol detail must remain fully available regardless of the
        # single-executor flattening above.
        assert result["executor_count"] == 2
        assert set(result["executors"].keys()) == {"MES", "MGC"}

    def test_executor_with_no_prediction_yet_falls_back_to_registry_order(self):
        """A freshly-deployed executor that hasn't predicted yet (no bars
        elapsed) must still be surfaced as deployed=True rather than being
        treated as absent."""
        import routers.strategies_router as sr

        fake_status = {
            "MES": {
                "symbol": "MES",
                "model_path": "data/rl_models/MES_fresh",
                "last_action": None,
                "last_prediction_time": None,
                "next_fire_time": "2026-07-10T15:00:00+00:00",
            }
        }

        with patch("strategies.rl_executor.get_executor_status", return_value=fake_status):
            result = _run(sr.executor_status())

        assert result["deployed"] is True
        assert result["symbol"] == "MES"
        assert result["last_prediction"] is None
        assert result["last_prediction_time"] is None
        assert result["next_fire_time"] == "2026-07-10T15:00:00+00:00"
