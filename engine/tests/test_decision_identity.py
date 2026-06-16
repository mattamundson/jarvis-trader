"""Decision-identity fingerprint + per-symbol lineage resolution (P1/P2).

The fingerprint must be deterministic (a property of the running config, so the
fill-mirror can recompute it per trade), per-symbol in its lineage, default-
material (unknown config_hash -> its own singleton lineage), and FAIL-OPEN (never
raise into a trading decision).
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("API_KEY", "test-key")

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from agents import decision_identity as di  # noqa: E402


def test_fingerprint_is_deterministic() -> None:
    a = di.compute_config_fingerprint()
    b = di.compute_config_fingerprint()
    assert a["config_hash"] == b["config_hash"]
    assert len(a["config_hash"]) == 64  # full sha256 hex
    assert "snapshot" in a and a["snapshot"]["pipeline_version"] == di.PIPELINE_VERSION


def test_snapshot_carries_identity_fields() -> None:
    snap = di.compute_config_fingerprint()["snapshot"]
    assert "git_sha" in snap
    assert "active_analysts" in snap and isinstance(snap["active_analysts"], list)
    assert "gates" in snap and "autonomous_threshold" in snap["gates"]


def test_current_identity_is_per_symbol() -> None:
    mes = di.current_decision_identity("MES")
    mgc = di.current_decision_identity("MGC")
    assert mes["symbol"] == "MES"
    assert mes["lineage"].endswith("::MES")
    assert mgc["lineage"].endswith("::MGC")
    # Same config, different symbol -> same config_hash, different lineage.
    assert mes["config_hash"] == mgc["config_hash"]
    assert mes["lineage"] != mgc["lineage"]
    assert mes["pipeline_version"] == di.PIPELINE_VERSION


def test_resolve_lineage_default_material_singleton() -> None:
    # Empty registry -> unregistered singleton, per-symbol.
    lin = di.resolve_lineage("abcdef0123456789", "MGC", registry={"lineages": []})
    assert lin == "unregistered:abcdef01::MGC"


def test_resolve_lineage_registered() -> None:
    reg = {
        "lineages": [
            {"id": "llm_core_v2", "member_config_hashes": ["abcdef0123456789"]}
        ]
    }
    assert di.resolve_lineage("abcdef0123456789", "MES", registry=reg) == "llm_core_v2::MES"
    # A different hash stays default-material.
    assert di.resolve_lineage("ffffffff", "MES", registry=reg) == "unregistered:ffffffff::MES"


def test_current_identity_fail_open(monkeypatch) -> None:
    def _boom() -> dict:
        raise RuntimeError("fingerprint exploded")

    monkeypatch.setattr(di, "compute_config_fingerprint", _boom)
    out = di.current_decision_identity("MNQ")
    # Degraded but still attributable to a coarse identity -- never raises.
    assert out["pipeline_version"] == di.PIPELINE_VERSION
    assert out["symbol"] == "MNQ"
    assert out["lineage"].endswith("::MNQ")
