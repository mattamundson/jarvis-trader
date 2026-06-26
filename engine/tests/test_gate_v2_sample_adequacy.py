"""Unit + integration tests — gate-v2 sample-adequacy floor (Initiative 2B, shadow).

Covers the four units that carry the 2B logic:
  * _gate_v2_helpers.MIN_OOS_TRADES_TOTAL + sample_adequacy_enforced() env switch
  * gate_v2_policy: INSUFFICIENT_SAMPLE is a readable, default-deny verdict
  * compare_verdicts._is_rating_drop: PASS -> INSUFFICIENT_SAMPLE is a degradation
  * run_mes_trend_rank11._compute_gate_v2: shadow (records, doesn't flip) vs
    enforce (flips to INSUFFICIENT_SAMPLE only when <30 OOS trades AND env set)

Fixture-free (try/finally) so it runs identically under pytest or standalone:
    engine/.venv/Scripts/python.exe -m pytest engine/tests/test_gate_v2_sample_adequacy.py -q
    engine/.venv/Scripts/python.exe engine/tests/test_gate_v2_sample_adequacy.py
"""

import os
import pathlib
import sys
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace

_ENGINE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ENGINE))
os.environ.setdefault("API_KEY", "test-key")

import backtest._gate_v2_helpers as gh  # noqa: E402
import backtest._gate_v2_trade_metrics as tlm  # noqa: E402
import backtest.compare_verdicts as cv  # noqa: E402
import backtest.gate_v2_policy as pol  # noqa: E402
import backtest.run_mes_trend_rank11 as mes  # noqa: E402

_ENFORCE_ENV = "GATE_V2_ENFORCE_SAMPLE_ADEQUACY"


# --- helpers ------------------------------------------------------------------
def _set_env(val):
    if val is None:
        os.environ.pop(_ENFORCE_ENV, None)
    else:
        os.environ[_ENFORCE_ENV] = val


def _oos(total_trades, pf=1.5, dd=2.0):
    return SimpleNamespace(total_trades=total_trades, profit_factor=pf, max_drawdown_pct=dd)


def _verdict_doc(symbol, verdict, created_at=None):
    return {
        "symbol": symbol,
        "family": "trend",
        "rank": 11,
        "verdict": verdict,
        "passed_via": "alt" if verdict == "PASS" else None,
        "core_verdict": "FAIL",
        "alt_verdict": "PASS" if verdict == "PASS" else "FAIL",
        "n_core_passed": 0,
        "n_alt_passed": 5 if verdict == "PASS" else 0,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "aux_freshness": {},
        "gate_v2": {},
        "gate_v2_metrics": {},
    }


# --- _gate_v2_helpers env switch ---------------------------------------------
def test_min_oos_trades_total_is_30():
    assert gh.MIN_OOS_TRADES_TOTAL == 30


def test_enforce_default_off():
    try:
        _set_env(None)
        assert gh.sample_adequacy_enforced() is False
    finally:
        _set_env(None)


def test_enforce_truthy_values():
    try:
        for v in ("1", "true", "TRUE", "yes", "on"):
            _set_env(v)
            assert gh.sample_adequacy_enforced() is True, v
        for v in ("0", "", "false", "no"):
            _set_env(v)
            assert gh.sample_adequacy_enforced() is False, v
    finally:
        _set_env(None)


# --- gate_v2_policy readability + default-deny --------------------------------
def test_insufficient_sample_is_valid_verdict():
    assert "INSUFFICIENT_SAMPLE" in pol._VALID_VERDICTS
    # readable: from_dict must not raise on the new verdict string
    snap = pol.VerdictSnapshot.from_dict(_verdict_doc("MES", "INSUFFICIENT_SAMPLE"))
    assert snap.verdict == "INSUFFICIENT_SAMPLE"


def test_insufficient_sample_denies_authorization():
    d = pathlib.Path(tempfile.mkdtemp(prefix="gv2sa_"))
    (d / "MES_trend_rank11.json").write_text(
        __import__("json").dumps(_verdict_doc("MES", "INSUFFICIENT_SAMPLE")), encoding="utf-8"
    )
    # readable AND default-deny (only PASS authorizes)
    assert pol.get_last_verdict("MES", verdicts_dir=d) is not None
    assert pol.is_ungate_eligible("MES", verdicts_dir=d) is False


def test_pass_still_authorizes():
    d = pathlib.Path(tempfile.mkdtemp(prefix="gv2sa_"))
    (d / "MES_trend_rank11.json").write_text(
        __import__("json").dumps(_verdict_doc("MES", "PASS")), encoding="utf-8"
    )
    assert pol.is_ungate_eligible("MES", verdicts_dir=d) is True


# --- compare_verdicts rating-drop --------------------------------------------
def test_rating_drop_pass_to_insufficient_sample():
    diff = {"old_verdict": "PASS", "new_verdict": "INSUFFICIENT_SAMPLE"}
    assert cv._is_rating_drop(diff) is True


def test_no_rating_drop_pass_to_pass():
    diff = {
        "old_verdict": "PASS",
        "new_verdict": "PASS",
        "old_passed_via": "alt",
        "new_passed_via": "alt",
        "metric_deltas": {},
    }
    assert cv._is_rating_drop(diff) is False


# --- integration: real _compute_gate_v2 shadow vs enforce ---------------------
def _call_gate(oos_results):
    """Run the real _compute_gate_v2 with trade-level metrics stubbed to passing
    values so we isolate the sample-adequacy branch from per-trade data needs."""
    orig_dsr, orig_dd = tlm.trade_level_dsr, tlm.trade_level_mc_95th_dd
    tlm.trade_level_dsr = lambda *a, **k: 1.0
    tlm.trade_level_mc_95th_dd = lambda *a, **k: 0.01
    try:
        return mes._compute_gate_v2(
            oos_results,
            n_grid_combos=3,
            fixed_params_metrics={
                "fixed_params_min_pf": 2.0,
                "fixed_params_mean_pf": 2.0,
                "fixed_params_max_pf": 2.0,
            },
            cost_sweep_metrics={"cost_survives_through": "catastrophic"},
        )
    finally:
        tlm.trade_level_dsr, tlm.trade_level_mc_95th_dd = orig_dsr, orig_dd


def test_shadow_records_but_does_not_flip():
    # 8 windows x 2 = 16 OOS trades (<30). Shadow mode (env off): verdict is
    # decided on the metrics (here PASS via alt), NOT flipped; the floor's
    # inputs are recorded for visibility.
    try:
        _set_env(None)
        g = _call_gate([_oos(2) for _ in range(8)])
        assert g["total_oos_trades"] == 16
        assert g["sample_adequate"] is False
        assert g["min_oos_trades_total"] == 30
        assert g["verdict"] != "INSUFFICIENT_SAMPLE"  # shadow does not flip
    finally:
        _set_env(None)


def test_enforce_flips_thin_sample():
    try:
        _set_env("1")
        g = _call_gate([_oos(2) for _ in range(8)])  # 16 < 30
        assert g["verdict"] == "INSUFFICIENT_SAMPLE"
        assert g["passed_via"] is None
        assert g["sample_adequate"] is False
    finally:
        _set_env(None)


def test_enforce_passes_adequate_sample():
    try:
        _set_env("1")
        g = _call_gate([_oos(2) for _ in range(20)])  # 40 >= 30
        assert g["sample_adequate"] is True
        assert g["verdict"] != "INSUFFICIENT_SAMPLE"
    finally:
        _set_env(None)


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"PASS {fn.__name__}")
        except Exception:  # noqa: BLE001
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
