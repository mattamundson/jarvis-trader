"""Tests for backtest.verdict_schema — typed Pydantic model for verdict JSON.

Covers:
- Happy-path parsing of real MCL/MGC verdict files from data/gate_v2_verdicts/
- Validation error on missing required ``symbol`` field
- _sanitize_json strips bare Infinity/NaN tokens
- load_verdict_validated raises FileNotFoundError on missing paths
- VerdictSchema re-exported from compare_verdicts for backward compat
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backtest.verdict_schema import (
    NON_VERDICT_ARTIFACTS as _KNOWN_NON_VERDICT_ARTIFACTS,
)
from backtest.verdict_schema import (
    VerdictSchema,
    _sanitize_json,
    load_verdict_validated,
)

_VERDICTS_DIR = Path(__file__).parent.parent / "data" / "gate_v2_verdicts"

# The non-verdict classification is imported (not redefined) so this CI gate and
# the runtime authorization path in backtest.gate_v2_policy cannot drift apart:
# one list, one source of truth (see `NON_VERDICT_ARTIFACTS` in verdict_schema).


# ---------------------------------------------------------------------------
# Minimal valid dict helpers
# ---------------------------------------------------------------------------


def _minimal(symbol: str = "MES", family: str = "trend") -> dict:
    return {"symbol": symbol, "family": family, "verdict": "FAIL"}


def _with_metrics(base: dict, **kwargs) -> dict:
    base = dict(base)
    base.setdefault("gate_v2_metrics", {})
    base["gate_v2_metrics"].update(kwargs)
    return base


# ---------------------------------------------------------------------------
# VerdictSchema validation
# ---------------------------------------------------------------------------


def test_minimal_verdict_parses() -> None:
    schema = VerdictSchema.model_validate(_minimal())
    assert schema.symbol == "MES"
    assert schema.family == "trend"
    assert schema.verdict == "FAIL"


def test_verdict_schema_missing_symbol_raises() -> None:
    with pytest.raises(ValidationError):
        VerdictSchema.model_validate({"family": "trend"})


def test_verdict_schema_missing_family_raises() -> None:
    with pytest.raises(ValidationError):
        VerdictSchema.model_validate({"symbol": "MES"})


def test_verdict_schema_extra_fields_allowed() -> None:
    data = _minimal()
    data["totally_unknown_field"] = "some value"
    schema = VerdictSchema.model_validate(data)
    assert schema.symbol == "MES"


def test_verdict_schema_gate_v2_metrics_parsed() -> None:
    data = _with_metrics(
        _minimal(),
        pf_ci_lower=2.1,
        p_edge=0.95,
        dsr=1.2,
        mc_95th_dd_pct=1.5,
        wfo_consistency="MODERATE",
    )
    schema = VerdictSchema.model_validate(data)
    assert schema.gate_v2_metrics is not None
    assert schema.gate_v2_metrics.pf_ci_lower == pytest.approx(2.1)
    assert schema.gate_v2_metrics.p_edge == pytest.approx(0.95)
    assert schema.gate_v2_metrics.wfo_consistency == "MODERATE"


def test_verdict_schema_champion_params_preserved() -> None:
    data = _minimal()
    data["champion_params"] = {"fast": 20, "slow": 50, "atr_trail_mult": 2.0}
    schema = VerdictSchema.model_validate(data)
    assert schema.champion_params is not None
    assert schema.champion_params["fast"] == 20


def test_verdict_schema_gate_v2_detail_parsed() -> None:
    data = _minimal(symbol="MGC")
    data["gate_v2"] = {
        "verdict": "PASS",
        "passed_via": "alt",
        "core_verdict": "FAIL",
        "alt_verdict": "PASS",
        "reasons": ["reason A", "reason B"],
    }
    schema = VerdictSchema.model_validate(data)
    assert schema.gate_v2 is not None
    assert schema.gate_v2.verdict == "PASS"
    assert schema.gate_v2.passed_via == "alt"
    assert len(schema.gate_v2.reasons) == 2


def test_verdict_schema_null_passed_via_allowed() -> None:
    data = _minimal()
    data["passed_via"] = None
    schema = VerdictSchema.model_validate(data)
    assert schema.passed_via is None


# ---------------------------------------------------------------------------
# _sanitize_json
# ---------------------------------------------------------------------------


def test_sanitize_json_replaces_bare_infinity() -> None:
    raw = '{"pf": Infinity, "dd": -Infinity, "ok": 1.0}'
    sanitized = _sanitize_json(raw)
    result = json.loads(sanitized)
    assert result["pf"] is None
    assert result["dd"] is None
    assert result["ok"] == pytest.approx(1.0)


def test_sanitize_json_replaces_nan() -> None:
    raw = '{"val": NaN}'
    sanitized = _sanitize_json(raw)
    result = json.loads(sanitized)
    assert result["val"] is None


def test_sanitize_json_passes_valid_json_unchanged() -> None:
    raw = '{"symbol": "MES", "verdict": "PASS", "pf": 1.5}'
    sanitized = _sanitize_json(raw)
    assert json.loads(sanitized) == {"symbol": "MES", "verdict": "PASS", "pf": 1.5}


# ---------------------------------------------------------------------------
# load_verdict_validated
# ---------------------------------------------------------------------------


def test_load_verdict_validated_file_not_found_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_verdict_validated(Path("__nonexistent_verdict__.json"))


def test_load_verdict_validated_invalid_json_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("NOT JSON {{{ }", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_verdict_validated(bad)


def test_load_verdict_validated_missing_symbol_raises(tmp_path: Path) -> None:
    v = tmp_path / "no_symbol.json"
    v.write_text(json.dumps({"family": "trend"}), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_verdict_validated(v)


def test_load_verdict_validated_roundtrip(tmp_path: Path) -> None:
    data = _with_metrics(
        _minimal(symbol="MGC", family="trend"),
        pf_ci_lower=2.6,
        p_edge=0.68,
        dsr=1.0,
        wfo_consistency="MODERATE",
    )
    data["champion_params"] = {"fast": 50, "slow": 120}
    data["verdict"] = "PASS"
    data["passed_via"] = "alt"

    path = tmp_path / "MGC_trend_rank4.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    schema = load_verdict_validated(path)
    assert schema.symbol == "MGC"
    assert schema.verdict == "PASS"
    assert schema.passed_via == "alt"
    assert schema.gate_v2_metrics is not None
    assert schema.gate_v2_metrics.pf_ci_lower == pytest.approx(2.6)


def test_load_verdict_handles_bare_infinity_in_file(tmp_path: Path) -> None:
    raw = '{"symbol": "MCL", "family": "meanrev", "verdict": "FAIL", "pf": Infinity}'
    path = tmp_path / "infinity.json"
    path.write_text(raw, encoding="utf-8")
    schema = load_verdict_validated(path)
    assert schema.symbol == "MCL"


# ---------------------------------------------------------------------------
# Real verdict files (conditional — skip if data dir not present)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _VERDICTS_DIR.exists(),
    reason="data/gate_v2_verdicts/ not present in this environment",
)
def test_real_verdict_files_validate() -> None:
    failures: list[str] = []
    validated: list[str] = []
    classified_non_verdicts: list[str] = []
    for path in sorted(_VERDICTS_DIR.glob("*.json")):
        if path.name in _KNOWN_NON_VERDICT_ARTIFACTS:
            raw = json.loads(_sanitize_json(path.read_text(encoding="utf-8")))
            assert any(
                key in raw for key in ("scope", "safety_boundary", "statistical_use_boundary")
            ), f"{path.name}: classified non-verdict artifact lacks evidence/provenance marker"
            classified_non_verdicts.append(path.name)
            continue

        try:
            schema = load_verdict_validated(path)
            assert schema.symbol, f"{path.name}: empty symbol"
            assert schema.family, f"{path.name}: empty family"
            validated.append(path.name)
        except Exception as exc:
            failures.append(f"{path.name}: {exc}")

    if not validated:
        pytest.skip("No verdict-shaped JSON files present; classified known evidence artifacts only")
    assert classified_non_verdicts == sorted(classified_non_verdicts)
    assert not failures, "Some real verdict files failed validation:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# Re-export from compare_verdicts (backward-compat check)
# ---------------------------------------------------------------------------


def test_verdict_schema_re_exported_from_compare_verdicts() -> None:
    from backtest.compare_verdicts import VerdictSchema as CVS  # noqa: F401

    assert CVS is VerdictSchema


def test_load_verdict_validated_re_exported_from_compare_verdicts() -> None:
    from backtest.compare_verdicts import load_verdict_validated as cv_fn

    assert cv_fn is load_verdict_validated
