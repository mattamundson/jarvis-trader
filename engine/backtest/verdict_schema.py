"""Typed schema for gate v2 verdict JSON files.

Verdict files are written by the runner scripts (run_*.py) and read by
compare_verdicts.py, mgc_wfo_journal.py, and the verdict_lifecycle module.
This Pydantic v2 model provides schema validation at load time so malformed
or schema-drifted verdicts surface as errors rather than silent KeyErrors
or NoneType failures later in the pipeline.

Usage::

    from backtest.verdict_schema import VerdictSchema, load_verdict_validated

    schema = load_verdict_validated(Path("data/gate_v2_verdicts/MES_trend_rank11.json"))
    print(schema.verdict, schema.passed_via)
    print(schema.gate_v2_metrics.pf_ci_lower)

The schema uses ``extra="allow"`` at every level so older verdict files with
extra fields or newer files with added fields are accepted without error.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GateV2Metrics(BaseModel):
    """Quantitative metrics produced by the gate v2 evaluation."""

    model_config = ConfigDict(extra="allow")

    pf_ci_lower: float | None = None
    p_edge: float | None = None
    mc_95th_dd: float | None = None
    mc_95th_dd_pct: float | None = None
    dsr: float | None = None
    wfo_consistency: str | None = None
    fixed_params_min_pf: float | None = None
    fixed_params_mean_pf: float | None = None
    fixed_params_max_pf: float | None = None
    n_combos_with_trades: int | None = None
    combo_results: list[dict[str, Any]] = Field(default_factory=list)
    cost_survives_through: str | None = None
    cost_tier_results: dict[str, dict[str, Any]] | None = None
    # Breakeven-slippage stress (Monte Carlo `run_slippage_stress` /
    # `slippage_stress_from_pnls`) — report-only, does not affect PASS/FAIL.
    # Optional with a None default so verdict files written before this field
    # existed still validate (backward-compatible schema addition).
    breakeven_extra_ticks: float | None = None
    slippage_stress_verdict: str | None = None


class GateV2Detail(BaseModel):
    """Verdict + reasons block nested under the ``gate_v2`` key."""

    model_config = ConfigDict(extra="allow")

    verdict: str = "FAIL"
    passed_via: str | None = None
    core_verdict: str = "FAIL"
    alt_verdict: str = "FAIL"
    n_core_passed: int = 0
    n_core_criteria: int = 4
    n_alt_passed: int = 0
    n_alt_criteria: int = 5
    reasons: list[str] = Field(default_factory=list)
    core_reasons: list[str] = Field(default_factory=list)
    alt_reasons: list[str] = Field(default_factory=list)


class VerdictSchema(BaseModel):
    """Top-level schema for a gate v2 verdict JSON file."""

    model_config = ConfigDict(extra="allow")

    symbol: str
    family: str
    rank: int | None = None
    verdict: str = "FAIL"
    passed_via: str | None = None
    core_verdict: str = "FAIL"
    alt_verdict: str = "FAIL"
    n_core_passed: int | None = None
    n_alt_passed: int | None = None
    created_at: str | None = None
    champion_params: dict[str, Any] | None = None
    gate_v2_metrics: GateV2Metrics | None = None
    gate_v2: GateV2Detail | None = None
    aux_freshness: dict[str, str | None] | None = None


def _sanitize_json(text: str) -> str:
    """Replace bare Python Infinity/NaN tokens that are not valid JSON."""
    text = re.sub(r":\s*Infinity\b", ": null", text)
    text = re.sub(r":\s*-Infinity\b", ": null", text)
    text = re.sub(r":\s*NaN\b", ": null", text)
    return text


def load_verdict_validated(path: Path) -> VerdictSchema:
    """Load and validate a verdict JSON file, returning a ``VerdictSchema``.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
        json.JSONDecodeError: if the file is not valid JSON after sanitization.
        pydantic.ValidationError: if the file fails schema validation (e.g.,
            ``symbol`` is missing or a numeric field contains a string).

    Unlike ``compare_verdicts._load()``, this function provides typed access
    and validates required fields rather than silently returning a raw dict.
    """
    text = path.read_text(encoding="utf-8")
    text = _sanitize_json(text)
    data = json.loads(text)
    return VerdictSchema.model_validate(data)
