"""Tests for engine/generation/edge_ledger.py.

Covers:
  - module import / public API smoke test
  - normalize_family parsing (base + conditioning)
  - _num coercion (inf/nan/bool safety)
  - alt_path_failures logic on synthetic metrics
  - primary_block priority ordering
  - row_from_verdict parsing on a synthetic verdict file
  - ranked_ledger ordering invariant (PASS before FAIL, dsr desc within PASS)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Ensure engine/ root is on sys.path so `generation` package resolves.
# ---------------------------------------------------------------------------
_engine_root = Path(__file__).resolve().parents[1]
if str(_engine_root) not in sys.path:
    sys.path.insert(0, str(_engine_root))


# ---------------------------------------------------------------------------
# Smoke: import and public API surface
# ---------------------------------------------------------------------------


def test_import():
    import generation.edge_ledger as el  # noqa: F401


def test_public_api():
    import generation.edge_ledger as el

    expected = {
        "normalize_family",
        "alt_path_failures",
        "primary_block",
        "row_from_verdict",
        "build",
        "load_rows",
        "ranked_ledger",
    }
    actual = {x for x in dir(el) if not x.startswith("_")}
    assert expected <= actual, f"Missing public symbols: {expected - actual}"


# ---------------------------------------------------------------------------
# normalize_family
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected_base, expected_cond",
    [
        ("trend", "trend", "none"),
        ("trend_adx_filter", "trend", "adx_filter"),
        ("trend_rv_filter", "trend", "rv_filter"),
        ("trend_adx_rv_filter", "trend", "adx_filter+rv_filter"),
        ("trend_vix", "trend", "vix_filter"),
        ("meanrev", "mean_reversion", "none"),
        ("mean_reversion", "mean_reversion", "none"),
        ("donchian", "donchian", "none"),
        (None, "?", "none"),
        ("", "?", "none"),
    ],
)
def test_normalize_family(raw, expected_base, expected_cond):
    from generation.edge_ledger import normalize_family

    base, cond = normalize_family(raw)
    assert base == expected_base, f"base mismatch for {raw!r}: {base!r} != {expected_base!r}"
    assert cond == expected_cond, f"cond mismatch for {raw!r}: {cond!r} != {expected_cond!r}"


# ---------------------------------------------------------------------------
# _num
# ---------------------------------------------------------------------------


def test_num_coercions():
    from generation.edge_ledger import _num

    assert _num(1.5) == 1.5
    assert _num(0) == 0.0
    assert _num(-3) == -3.0
    assert _num(float("inf")) is None
    assert _num(float("-inf")) is None
    assert _num(float("nan")) is None
    assert _num(True) is None  # bool is NOT a valid metric
    assert _num(False) is None
    assert _num("1.5") is None
    assert _num(None) is None


# ---------------------------------------------------------------------------
# alt_path_failures
# ---------------------------------------------------------------------------

_GOOD_METRICS = {
    "pf_ci_lower": 1.5,
    "dsr": 0.4,
    "wfo_consistency": "STRONG",
    "fixed_params_min_pf": 1.3,
    "cost_survives_through": "realistic",
    "mc_95th_dd_pct": 3.0,
}


def test_alt_path_all_pass():
    from generation.edge_ledger import alt_path_failures

    assert alt_path_failures(_GOOD_METRICS) == []


@pytest.mark.parametrize(
    "mutate_key, mutate_val, expected_fail_token",
    [
        ("pf_ci_lower", 0.9, "pf_ci<1.10"),
        ("dsr", 0.1, "dsr<0.30"),
        ("wfo_consistency", "WEAK", "wfo_weak"),
        ("fixed_params_min_pf", 1.0, "fixed_pf<1.20"),
        ("cost_survives_through", "none", "cost_death"),
        ("mc_95th_dd_pct", 5.0, "mc_dd>4%"),
    ],
)
def test_alt_path_single_failure(mutate_key, mutate_val, expected_fail_token):
    from generation.edge_ledger import alt_path_failures

    m = dict(_GOOD_METRICS)
    m[mutate_key] = mutate_val
    fails = alt_path_failures(m)
    assert expected_fail_token in fails, f"{expected_fail_token!r} not in {fails}"


# ---------------------------------------------------------------------------
# primary_block priority
# ---------------------------------------------------------------------------


def test_primary_block_ordering():
    from generation.edge_ledger import primary_block

    # wfo_weak takes priority over everything
    assert primary_block(["pf_ci<1.10", "wfo_weak", "dsr<0.30"]) == "wfo_weak"
    # cost_death beats dsr
    assert primary_block(["dsr<0.30", "cost_death"]) == "cost_death"
    # empty = None
    assert primary_block([]) is None


# ---------------------------------------------------------------------------
# row_from_verdict (synthetic file)
# ---------------------------------------------------------------------------

_SYNTHETIC_VERDICT = {
    "symbol": "MES",
    "family": "trend_adx_filter",
    "rank": 99,
    "verdict": "PASS",
    "passed_via": "alt",
    "core_verdict": "FAIL",
    "alt_verdict": "PASS",
    "created_at": "2026-01-01T00:00:00+00:00",
    "champion_params": {"fast": 50, "slow": 200},
    "wfo_config": {
        "train_months": 6,
        "test_months": 3,
        "step_months": 3,
        "n_oos_windows": 7,
        "grid_combos": 27,
        "total_oos_trades": 30,
    },
    "gate_v2_metrics": {
        "pf_ci_lower": 1.4,
        "p_edge": 0.97,
        "mc_95th_dd_pct": 2.0,
        "dsr": 0.55,
        "wfo_consistency": "MODERATE",
        "fixed_params_min_pf": 1.25,
        "cost_survives_through": "catastrophic",
    },
}


def test_row_from_verdict_pass():
    from generation.edge_ledger import row_from_verdict

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(_SYNTHETIC_VERDICT, f)
        fpath = Path(f.name)

    try:
        row = row_from_verdict(fpath, is_archived=False)
    finally:
        fpath.unlink(missing_ok=True)

    assert row is not None
    assert row["symbol"] == "MES"
    assert row["base_family"] == "trend"
    assert row["conditioning"] == "adx_filter"
    assert row["verdict"] == "PASS"
    assert row["alt_failures"] == []  # PASS rows never get alt_failures computed
    assert row["metrics"]["pf_ci_lower"] == pytest.approx(1.4)
    assert row["metrics"]["dsr"] == pytest.approx(0.55)


def test_row_from_verdict_fail_flags_blocks():
    from generation.edge_ledger import row_from_verdict

    verdict = dict(_SYNTHETIC_VERDICT)
    verdict["verdict"] = "FAIL"
    verdict["gate_v2_metrics"] = {
        "pf_ci_lower": 0.8,
        "dsr": 0.05,
        "wfo_consistency": "WEAK",
        "fixed_params_min_pf": 0.9,
        "cost_survives_through": "none",
        "mc_95th_dd_pct": 6.0,
    }

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(verdict, f)
        fpath = Path(f.name)

    try:
        row = row_from_verdict(fpath, is_archived=False)
    finally:
        fpath.unlink(missing_ok=True)

    assert row is not None
    assert row["verdict"] == "FAIL"
    assert "wfo_weak" in row["alt_failures"]
    assert row["primary_block"] == "wfo_weak"


def test_row_from_verdict_corrupt_returns_none(tmp_path):
    from generation.edge_ledger import row_from_verdict

    bad = tmp_path / "bad.json"
    bad.write_text("not-json{{{{")
    row = row_from_verdict(bad, is_archived=False)
    assert row is None


# ---------------------------------------------------------------------------
# ranked_ledger ordering invariant
# ---------------------------------------------------------------------------


def test_ranked_ledger_ordering(tmp_path, monkeypatch):
    """PASS rows come before FAIL rows; within PASS, highest dsr first."""
    from generation import edge_ledger as el

    # Build synthetic ledger rows
    rows_data = [
        {
            "source_file": "A.json",
            "is_archived": False,
            "symbol": "MES",
            "base_family": "trend",
            "conditioning": "none",
            "family_raw": "trend",
            "rank": 1,
            "verdict": "FAIL",
            "passed_via": None,
            "core_verdict": "FAIL",
            "alt_verdict": "FAIL",
            "created_at": "2026-01-01T00:00:00+00:00",
            "champion_params": {},
            "design": {},
            "metrics": {
                "pf_ci_lower": 0.8,
                "dsr": 0.0,
                "mc_95th_dd_pct": 5.0,
                "wfo_consistency": "WEAK",
                "fixed_params_min_pf": None,
                "cost_survives_through": "none",
                "p_edge": 0.4,
            },
            "alt_failures": ["wfo_weak", "dsr<0.30", "pf_ci<1.10"],
            "primary_block": "wfo_weak",
        },
        {
            "source_file": "B.json",
            "is_archived": False,
            "symbol": "MGC",
            "base_family": "trend",
            "conditioning": "rv_filter",
            "family_raw": "trend_rv_filter",
            "rank": 1,
            "verdict": "PASS",
            "passed_via": "core",
            "core_verdict": "PASS",
            "alt_verdict": "PASS",
            "created_at": "2026-01-02T00:00:00+00:00",
            "champion_params": {},
            "design": {},
            "metrics": {
                "pf_ci_lower": 3.18,
                "dsr": 1.0,
                "mc_95th_dd_pct": 0.65,
                "wfo_consistency": "STRONG",
                "fixed_params_min_pf": 1.42,
                "cost_survives_through": "catastrophic",
                "p_edge": 1.0,
            },
            "alt_failures": [],
            "primary_block": None,
        },
        {
            "source_file": "C.json",
            "is_archived": False,
            "symbol": "MES",
            "base_family": "trend",
            "conditioning": "adx_filter",
            "family_raw": "trend_adx_filter",
            "rank": 1,
            "verdict": "PASS",
            "passed_via": "alt",
            "core_verdict": "FAIL",
            "alt_verdict": "PASS",
            "created_at": "2026-01-03T00:00:00+00:00",
            "champion_params": {},
            "design": {},
            "metrics": {
                "pf_ci_lower": 1.5,
                "dsr": 0.6,
                "mc_95th_dd_pct": 2.0,
                "wfo_consistency": "MODERATE",
                "fixed_params_min_pf": 1.3,
                "cost_survives_through": "realistic",
                "p_edge": 0.9,
            },
            "alt_failures": [],
            "primary_block": None,
        },
    ]

    ledger_file = tmp_path / "edge_ledger.jsonl"
    with ledger_file.open("w", encoding="utf-8") as fh:
        for r in rows_data:
            fh.write(json.dumps(r) + "\n")

    # Patch LEDGER_PATH to point at our temp file
    monkeypatch.setattr(el, "LEDGER_PATH", ledger_file)

    ranked = el.ranked_ledger()

    # PASS rows first
    verdicts = [r["verdict"] for r in ranked]
    first_fail = next((i for i, v in enumerate(verdicts) if v == "FAIL"), len(verdicts))
    last_pass = max((i for i, v in enumerate(verdicts) if v == "PASS"), default=-1)
    assert last_pass < first_fail, "All PASS rows must precede FAIL rows"

    # Within PASS rows, higher dsr first
    pass_rows = [r for r in ranked if r["verdict"] == "PASS"]
    dsrs = [r["metrics"]["dsr"] for r in pass_rows]
    assert dsrs == sorted(dsrs, reverse=True), f"PASS rows not sorted by dsr desc: {dsrs}"
