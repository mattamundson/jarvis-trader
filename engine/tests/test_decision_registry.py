"""Decision-lineage registry loader + honesty guard (P2 scaffold)."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("API_KEY", "test-key")
_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from backtest import decision_registry as dr  # noqa: E402


def test_loads_shipped_scaffold_registers_dark_lineages() -> None:
    # R1/T6: the spread + calendar dark tracks are now pre-registered (empty forward
    # windows). ES-NQ stays intentionally UNregistered (context-only, preserves live).
    # preholiday_spy_v1 added 2026-06-25 (free-daily calendar standout forward track).
    reg = dr.load_registry()
    assert reg["schema_version"] == 1
    assert "graduation_rule" in reg
    ids = {lin["id"] for lin in reg["lineages"]}
    assert ids == {"mes_m2k_spread_v1", "tom_spy_v1", "preholiday_spy_v1"}
    assert "es_nq_spread_v1" not in ids  # honesty: unregistered, never graduates


def test_shipped_registry_dark_lineages_have_correct_types() -> None:
    reg = dr.load_registry()
    by_id = {lin["id"]: lin for lin in reg["lineages"]}
    assert by_id["mes_m2k_spread_v1"]["strategy_type"] == "spread"
    assert by_id["mes_m2k_spread_v1"]["legs"] == ["MES", "M2K"]
    assert by_id["tom_spy_v1"]["strategy_type"] == "calendar"
    assert by_id["tom_spy_v1"]["rule"] == "turn_of_month"
    assert by_id["preholiday_spy_v1"]["strategy_type"] == "calendar"
    assert by_id["preholiday_spy_v1"]["rule"] == "pre_holiday"


def test_shipped_unregistered_es_nq_spread_is_never_pre_registered() -> None:
    # The live ES-NQ track is cleanly stamped but intentionally absent from the
    # registry -> context-only, can never graduate (R1/T6 honesty guarantee).
    reg = dr.load_registry()
    assert dr.is_pre_registered("es_nq_spread_v1::ES_NQ_SPREAD", registry=reg) is False
    assert dr.is_pre_registered("mes_m2k_spread_v1::MES_M2K_SPREAD", registry=reg) is True


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


# ── strategy_type schema (R1/T1) ────────────────────────────────────────────────


def test_verify_accepts_llm_without_new_fields() -> None:
    # Backward-compat: a lineage with no strategy_type is treated as llm and needs
    # none of the new fields.
    reg = {
        "allowed_status": ["forward_testing"],
        "lineages": [{"id": "llm_core", "status": "forward_testing"}],
    }
    assert dr.verify_registry(reg) == []


def test_verify_rejects_unknown_strategy_type() -> None:
    reg = {
        "allowed_status": ["forward_testing"],
        "lineages": [{"id": "x", "status": "forward_testing", "strategy_type": "bogus"}],
    }
    assert any("strategy_type" in p for p in dr.verify_registry(reg))


def test_verify_requires_inception_for_non_llm() -> None:
    # Any non-llm class MUST carry an inception date (machine-checkable pre-registration).
    for st in ("mechanical", "spread", "calendar"):
        reg = {
            "allowed_status": ["forward_testing"],
            "lineages": [
                {
                    "id": "x",
                    "status": "forward_testing",
                    "strategy_type": st,
                    # deliberately no inception
                    "legs": ["A", "B"],
                    "composite_symbol": "A_B",
                    "rule": "r",
                    "vehicle": "V",
                }
            ],
        }
        assert any("inception" in p for p in dr.verify_registry(reg)), st


def test_verify_spread_requires_legs_and_composite_symbol() -> None:
    reg = {
        "allowed_status": ["forward_testing"],
        "lineages": [
            {
                "id": "sp",
                "status": "forward_testing",
                "strategy_type": "spread",
                "inception": "2026-06-24",
                # missing legs + composite_symbol
            }
        ],
    }
    problems = dr.verify_registry(reg)
    assert any("legs" in p for p in problems)
    assert any("composite_symbol" in p for p in problems)


def test_verify_calendar_requires_rule_and_vehicle() -> None:
    reg = {
        "allowed_status": ["forward_testing"],
        "lineages": [
            {
                "id": "cal",
                "status": "forward_testing",
                "strategy_type": "calendar",
                "inception": "2026-06-24",
                # missing rule + vehicle
            }
        ],
    }
    problems = dr.verify_registry(reg)
    assert any("rule" in p for p in problems)
    assert any("vehicle" in p for p in problems)


def test_verify_accepts_well_formed_spread_and_calendar() -> None:
    reg = {
        "allowed_status": ["forward_testing"],
        "lineages": [
            {
                "id": "sp",
                "status": "forward_testing",
                "strategy_type": "spread",
                "inception": "2026-06-24",
                "legs": ["MES", "M2K"],
                "composite_symbol": "MES_M2K_SPREAD",
            },
            {
                "id": "cal",
                "status": "forward_testing",
                "strategy_type": "calendar",
                "inception": "2026-06-24",
                "rule": "turn_of_month",
                "vehicle": "SPY",
            },
        ],
    }
    assert dr.verify_registry(reg) == []


# ── membership-aware honesty guard (R1/T1) ──────────────────────────────────────


def test_is_pre_registered_prefix_only_without_registry() -> None:
    # Backward-compat: no registry -> prefix-only check, unchanged.
    assert dr.is_pre_registered("anything::MES") is True
    assert dr.is_pre_registered("unregistered:deadbeef::MES") is False


def test_is_pre_registered_requires_membership_when_registry_given() -> None:
    reg = {"lineages": [{"id": "mes_m2k_spread_v1", "status": "forward_testing"}]}
    # Registered stem -> pre-registered.
    assert dr.is_pre_registered("mes_m2k_spread_v1::MES_M2K_SPREAD", registry=reg) is True
    # Clean-looking but NOT in the registry -> context-only (this is what keeps
    # es_nq_spread_v1 from graduating while it is intentionally unregistered).
    assert dr.is_pre_registered("es_nq_spread_v1::ES_NQ_SPREAD", registry=reg) is False
    # unregistered prefix is never pre-registered regardless.
    assert dr.is_pre_registered("unregistered:abc::MES", registry=reg) is False
