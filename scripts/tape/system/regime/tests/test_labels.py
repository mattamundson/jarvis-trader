"""Label definition unit tests."""
from labels import LabelParams, label_session, close_position, VARIANTS


def test_close_position():
    assert close_position(100, 200, 100) == 0.0
    assert close_position(100, 200, 200) == 1.0
    assert abs(close_position(100, 200, 150) - 0.5) < 1e-9
    assert close_position(100, 100, 100) is None


def test_trend_outer_wide():
    # close at high, range 120 vs avg 80 → 1.5x wide + outer
    lab = label_session(
        rth_low=100, rth_high=220, rth_close=215,
        avg_range_20=80, ib_low=150, ib_high=180,
    )
    assert lab == "trend"


def test_balance_mid_narrow():
    lab = label_session(
        rth_low=100, rth_high=140, rth_close=120,
        avg_range_20=80, ib_low=105, ib_high=135,
    )
    assert lab == "balance"


def test_ib_breakout_onesided():
    # IB 20 pts; extend 25 above, 5 below → trend via breakout
    lab = label_session(
        rth_low=95, rth_high=145, rth_close=120,  # mid close would be balance-ish
        avg_range_20=80, ib_low=100, ib_high=120,
    )
    assert lab == "trend"


def test_variants_exist():
    assert len(VARIANTS) >= 3
    assert VARIANTS[0].name == "primary"
