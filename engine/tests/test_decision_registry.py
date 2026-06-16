"""Decision-lineage registry loader + honesty guard (P2 scaffold)."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("API_KEY", "test-key")
_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from backtest import decision_registry as dr  # noqa: E402


def test_loads_shipped_scaffold_with_empty_lineages() -> None:
    reg = dr.load_registry()
    assert reg["schema_version"] == 1
    assert reg["lineages"] == []  # nothing registered yet -> all default-material
    assert "graduation_rule" in reg


def test_verify_clean_on_shipped_registry() -> None:
    assert dr.verify_registry(dr.load_registry()) == []


def test_verify_flags_duplicate_config_hash_across_lineages() -> None:
    reg = {
        "allowed_status": ["forward_testing"],
        "lineages": [
            {"id": "a", "status": "forward_testing", "member_config_hashes": ["deadbeef"]},
            {"id": "b", "status": "forward_testing", "member_config_hashes": ["deadbeef"]},
        ],
    }
    problems = dr.verify_registry(reg)
    assert any("deadbeef"[:8] in p for p in problems)


def test_verify_flags_duplicate_lineage_id() -> None:
    reg = {
        "allowed_status": ["forward_testing"],
        "lineages": [
            {"id": "dup", "status": "forward_testing"},
            {"id": "dup", "status": "forward_testing"},
        ],
    }
    assert any("duplicate lineage id" in p for p in dr.verify_registry(reg))


def test_lineage_for_config_hash() -> None:
    reg = {"lineages": [{"id": "llm_core", "member_config_hashes": ["h1", "h2"]}]}
    assert dr.lineage_for_config_hash("h2", registry=reg) == "llm_core"
    assert dr.lineage_for_config_hash("nope", registry=reg) is None


def test_get_active_lineages() -> None:
    reg = {
        "lineages": [
            {"id": "x", "status": "forward_testing"},
            {"id": "y", "status": "paused"},
        ]
    }
    active = dr.get_active_lineages(registry=reg)
    assert [lin["id"] for lin in active] == ["x"]
