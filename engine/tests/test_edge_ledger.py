"""Tests for the unified honest-edge ledger CLI (no DB required)."""

from __future__ import annotations

import json

from tools import edge_ledger


def _synthetic_report() -> dict:
    """A report covering all four honesty cases."""
    return {
        "candidates": [
            {  # graduated, precise attribution -> validated
                "id": "cand-graduated",
                "symbol": "MGC",
                "attribution_level": "candidate_id",
                "precise_attribution": True,
                "graduated": True,
                "survives_family_fdr": True,
                "forward": {"n_oos_windows": 6, "p_edge": 0.83,
                            "pf_ci_lower": 1.42, "binom_p": 0.01,
                            "total_trades": 40, "total_pnl": 1200.0},
            },
            {  # context-only: symbol-level, NOT precise -> never validated
                "id": "cand-context",
                "symbol": "MES",
                "attribution_level": "symbol",
                "precise_attribution": False,
                "graduated": False,
                "survives_family_fdr": False,
                "forward": {"n_oos_windows": 5, "p_edge": 0.9,
                            "pf_ci_lower": 2.1, "binom_p": 0.001,
                            "total_trades": 30, "total_pnl": 900.0},
            },
        ],
        "lineages": [
            {  # graduated pre-registered lineage -> validated
                "lineage": "mgc-trend-rv",
                "pre_registered": True,
                "graduated": True,
                "survives_family_fdr": True,
                "forward": {"n_oos_windows": 5, "p_edge": 0.8,
                            "pf_ci_lower": 1.3, "binom_p": 0.02,
                            "total_trades": 25, "total_pnl": 700.0},
            },
            {  # unregistered with strong stats -> never validated
                "lineage": "unregistered:abcd1234",
                "pre_registered": False,
                "graduated": False,
                "survives_family_fdr": True,
                "forward": {"n_oos_windows": 8, "p_edge": 1.0,
                            "pf_ci_lower": 5.0, "binom_p": 0.0001,
                            "total_trades": 60, "total_pnl": 5000.0},
            },
        ],
        "n_graduated": 1,
        "n_lineages_graduated": 1,
    }


def test_build_ledger_counts_only_validated():
    ledger = edge_ledger.build_ledger(_synthetic_report())
    v = ledger["verdict"]
    assert v["n_graduated_candidates"] == 1
    assert v["n_graduated_lineages"] == 1
    assert v["n_validated_total"] == 2

    by_id = {r["id"]: r for r in ledger["rows"]}
    assert by_id["cand-graduated"]["status"] == "GRADUATED"
    assert by_id["mgc-trend-rv"]["status"] == "GRADUATED"
    # The context-only candidate and unregistered lineage are NOT validated.
    assert by_id["cand-context"]["status"] == "context-only"
    assert by_id["cand-context"]["graduated"] is False
    assert by_id["unregistered:abcd1234"]["status"] == "context-only"
    assert by_id["unregistered:abcd1234"]["graduated"] is False


def test_render_table_contains_ids_and_graduated():
    ledger = edge_ledger.build_ledger(_synthetic_report())
    out = edge_ledger.render_table(ledger)
    for cid in ("cand-graduated", "cand-context", "mgc-trend-rv",
                "unregistered:abcd1234"):
        assert cid in out
    assert "GRADUATED" in out
    # Verdict header reflects the two validated edges.
    assert "= 2" in out


def test_graduated_rows_sort_first():
    ledger = edge_ledger.build_ledger(_synthetic_report())
    statuses = [r["status"] for r in ledger["rows"]]
    # All GRADUATED rows precede any non-graduated row.
    last_grad = max(i for i, s in enumerate(statuses) if s == "GRADUATED")
    first_non_grad = min(i for i, s in enumerate(statuses) if s != "GRADUATED")
    assert last_grad < first_non_grad


def test_json_path_emits_same_verdict(capsys):
    report = _synthetic_report()
    rc = edge_ledger.main(["--json"], load_report=lambda live=False: report)
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"]["n_validated_total"] == 2
    assert payload["verdict"]["n_graduated_candidates"] == 1
    assert payload["verdict"]["n_graduated_lineages"] == 1


def test_degrades_gracefully_when_no_data(capsys):
    rc = edge_ledger.main([], load_report=lambda live=False: None)
    assert rc == 0
    assert "no forward-test data available" in capsys.readouterr().out
