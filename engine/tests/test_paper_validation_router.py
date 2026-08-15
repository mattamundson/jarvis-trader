"""
Regression tests for routers.paper_validation_router._compute_rolling_wfe.

Prior behavior: IN_SAMPLE_PF.get(symbol, 1.0) silently defaulted any symbol
missing a reference to in_sample_pf=1.0, which the `<= 1.0` guard then always
forced to wfe=0.0. IN_SAMPLE_PF only ever had MCL/MNQ entries; the 2026-05-24
instrument switch made MES/MGC the active paper pair without updating this
dict, so /paper/validation/wfe silently reported wfe=0.0 ("actively
overfit") for the real active instruments instead of the honest
"insufficient_data" (no in-sample reference exists to compare against).
"""

from routers.paper_validation_router import IN_SAMPLE_PF, _compute_rolling_wfe


def _trade(pnl: float) -> dict:
    return {"pnl": pnl, "exit_time": "2026-06-01T12:00:00Z"}


def test_symbol_without_in_sample_reference_is_insufficient_data_not_zero():
    """A symbol absent from IN_SAMPLE_PF (e.g. MES/MGC) must not fabricate wfe=0.0."""
    assert "MES" not in IN_SAMPLE_PF
    assert "MGC" not in IN_SAMPLE_PF

    trades = [_trade(100.0) for _ in range(6)] + [_trade(-40.0) for _ in range(4)]
    wfe, pf, status = _compute_rolling_wfe(trades, "MES", min_trades=5)

    assert status == "insufficient_data"
    assert wfe is None
    # current_pf is still a real, directly-observed number (not gated by
    # the missing in-sample reference) -- only the WFE ratio is undefined.
    assert pf > 0


def test_symbol_with_in_sample_reference_computes_real_wfe():
    """A symbol present in IN_SAMPLE_PF (e.g. MCL) still gets a real WFE."""
    assert IN_SAMPLE_PF["MCL"] == 5.3

    # 10 trades, gross_profit=1000, gross_loss=200 -> current_pf = 5.0
    trades = [_trade(100.0) for _ in range(10)] + [_trade(-200.0)]
    wfe, pf, status = _compute_rolling_wfe(trades, "MCL", min_trades=5)

    assert status == "ok"
    assert pf == 5.0
    # wfe = (5.0 - 1.0) / (5.3 - 1.0) = 4.0 / 4.3
    assert wfe is not None
    assert abs(wfe - (4.0 / 4.3)) < 1e-9


def test_below_min_trades_is_insufficient_data_regardless_of_symbol():
    wfe, pf, status = _compute_rolling_wfe([_trade(100.0)], "MCL", min_trades=5)
    assert status == "insufficient_data"
    assert wfe is None
    assert pf == 0.0
