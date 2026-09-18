"""Tests for `_gate_v2_helpers.campaign_trial_count`.

The defect this addresses: runners pass their own grid size as `n_trials`, so recorded DSR is
deflated against 1-64 trials while the real campaign count is in the hundreds. DSR is a cliff and
the ALT floor is 0.30 (measured on the current candidate: 0.977 @4 → 0.2885 @200 → 0.0505 @500), so
every recorded DSR understates deflation.

The dedupe test is the load-bearing one: the 2026-09-17 audit found the same artifact filed under up
to four names, so a naive sum of recorded grid sizes double-counts and would OVERSTATE the campaign
— which would deflate DSR *more* than the evidence supports. Both directions of error matter.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("API_KEY", "local-research-sandbox-dummy-not-a-credential")

from backtest._gate_v2_helpers import campaign_trial_count


def _write(root, name: str, payload: dict):
    p = root / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _fixture(root):
    """5 artifacts: one MES dup pair, one distinct MES, one MGC, one MES with no grid recorded."""
    a = _write(root, "mes_a.json", {"symbol": "MES", "wfo_config": {"n_combos": 10}})
    # Byte-identical copy under another name -> must count once.
    (root / "mes_a_dup.json").write_bytes(a.read_bytes())
    _write(root, "mes_c.json", {"symbol": "MES", "wfo_config": {"n_combos": 5}})
    _write(root, "mgc.json", {"symbol": "MGC", "wfo_config": {"n_combos": 7}})
    _write(root, "mes_nogrid.json", {"symbol": "MES"})


def test_dedupes_identical_artifacts(tmp_path):
    _fixture(tmp_path)
    r = campaign_trial_count("MES", verdict_root=tmp_path)
    # 10 (once, not twice) + 5
    assert r["n_trials_lower_bound"] == 15
    assert r["n_distinct_artifacts_counted"] == 2
    # all four MES files matched, including the one with no grid recorded
    assert r["n_files_matching_symbol"] == 4
    assert r["n_files_scanned"] == 5


def test_excludes_other_symbols(tmp_path):
    _fixture(tmp_path)
    assert campaign_trial_count("MGC", verdict_root=tmp_path)["n_trials_lower_bound"] == 7
    assert campaign_trial_count("NOPE", verdict_root=tmp_path)["n_trials_lower_bound"] == 0


def test_missing_root_returns_zero_without_raising(tmp_path):
    r = campaign_trial_count("MES", verdict_root=tmp_path / "does_not_exist")
    assert r["n_trials_lower_bound"] == 0
    assert r["n_files_scanned"] == 0


def test_reports_its_basis_and_caveat(tmp_path):
    r = campaign_trial_count("MES", verdict_root=tmp_path)
    # A number without its basis is how the original error survived; both must be present.
    assert "grid-combo" in r["basis"]
    assert "lower bound" in r["caveat"]


def test_deflation_report_shows_both_bases(tmp_path):
    """The report must carry BOTH counts, or new verdicts become incomparable with old ones."""
    from backtest._gate_v2_helpers import deflation_report

    _fixture(tmp_path)
    d = deflation_report("MES", n_grid_combos=4, verdict_root=tmp_path)
    assert d["n_trials_grid"] == 4
    assert d["n_trials_campaign"] == 15
    assert d["enforcement"].startswith("report-only")
    assert "grid-combo" in d["campaign_basis"]
    assert "lower bound" in d["campaign_caveat"]


def test_deflation_report_on_real_store_orders_the_bases():
    """Against the real artifact store, the campaign count must exceed the runner grid count.

    This is the whole point: the live vix_pctile verdict deflates against 4 while the MES campaign
    is in the hundreds. If this ever inverts, the derivation is wrong.
    """
    from backtest._gate_v2_helpers import deflation_report

    d = deflation_report("MES", n_grid_combos=4)
    if d["n_distinct_artifacts_counted"] == 0:
        import pytest as _pytest
        _pytest.skip("verdict store not present in this checkout")
    assert d["n_trials_campaign"] > d["n_trials_grid"]


def test_naive_sum_would_overstate(tmp_path):
    """Guard against the failure mode the dedupe prevents."""
    _fixture(tmp_path)
    naive = 10 + 10 + 5  # counting the duplicate as a separate run
    assert campaign_trial_count("MES", verdict_root=tmp_path)["n_trials_lower_bound"] < naive
