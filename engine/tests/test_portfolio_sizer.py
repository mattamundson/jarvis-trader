"""P2.3: correlation-aware portfolio sizing (pure module, inert until wired).

Today position_sizer.calculate_position_size sizes each instrument independently
(Kelly + drawdown), so two correlated longs (e.g. MES + MGC in a risk-on regime)
silently stack aggregate exposure. This module adds the missing portfolio view:

  portfolio_risk(...)            — combined risk accounting for correlation:
                                   uncorrelated => quadrature, correlated => linear,
                                   hedged (rho=-1, equal) => ~0.
  correlation_scale_factor(...)  — how much to trim a NEW position so the combined
                                   correlated risk stays at/under a ceiling. Falls
                                   out as "size MES down when MGC is already hot".

Pure functions, exhaustively testable, no I/O. Wiring into the live sizing path
and a backtest validation are deliberately OUT of scope here (Amo-gated).
"""

import math

from risk.portfolio_sizer import (
    correlation_scale_factor,
    correlation_trim_contracts,
    portfolio_risk,
)


# --------------------------------------------------------------------------- #
# portfolio_risk — combined risk with correlation
# --------------------------------------------------------------------------- #
def test_empty_book_has_zero_risk():
    assert portfolio_risk({}, {}) == 0.0


def test_single_position_risk_is_its_own():
    assert portfolio_risk({"MES": 100.0}, {}) == 100.0


def test_uncorrelated_positions_add_in_quadrature():
    # rho=0 => sqrt(100^2 + 100^2)
    r = portfolio_risk({"MES": 100.0, "MGC": 100.0}, {("MES", "MGC"): 0.0})
    assert math.isclose(r, math.hypot(100.0, 100.0), rel_tol=1e-9)


def test_perfectly_correlated_positions_add_linearly():
    # rho=1 => 100 + 100
    r = portfolio_risk({"MES": 100.0, "MGC": 100.0}, {("MES", "MGC"): 1.0})
    assert math.isclose(r, 200.0, rel_tol=1e-9)


def test_perfect_hedge_cancels_to_zero():
    # rho=-1, equal size => fully hedged
    r = portfolio_risk({"MES": 100.0, "MGC": 100.0}, {("MES", "MGC"): -1.0})
    assert math.isclose(r, 0.0, abs_tol=1e-9)


def test_partial_correlation_between_quadrature_and_linear():
    # rho=0.5 => sqrt(100^2 + 100^2 + 2*0.5*100*100) = sqrt(30000)
    r = portfolio_risk({"MES": 100.0, "MGC": 100.0}, {("MES", "MGC"): 0.5})
    assert math.isclose(r, math.sqrt(30000.0), rel_tol=1e-9)


def test_correlation_lookup_is_order_independent():
    a = portfolio_risk({"MES": 100.0, "MGC": 80.0}, {("MES", "MGC"): 0.4})
    b = portfolio_risk({"MES": 100.0, "MGC": 80.0}, {("MGC", "MES"): 0.4})
    assert math.isclose(a, b, rel_tol=1e-9)


# --------------------------------------------------------------------------- #
# correlation_scale_factor — trim the NEW position to fit the ceiling
# --------------------------------------------------------------------------- #
def test_new_position_within_ceiling_is_not_trimmed():
    f = correlation_scale_factor("MES", 100.0, {}, {}, max_portfolio_risk=200.0)
    assert f == 1.0


def test_new_position_alone_over_ceiling_is_trimmed_proportionally():
    # No existing book: 300 * f = 200 => f = 2/3
    f = correlation_scale_factor("MES", 300.0, {}, {}, max_portfolio_risk=200.0)
    assert math.isclose(f, 200.0 / 300.0, rel_tol=1e-9)


def test_correlated_new_position_trimmed_to_zero_when_book_full():
    # MGC already fills the 200 ceiling; MES perfectly correlated => no room.
    f = correlation_scale_factor(
        "MES", 100.0, {"MGC": 200.0}, {("MES", "MGC"): 1.0}, max_portfolio_risk=200.0
    )
    assert math.isclose(f, 0.0, abs_tol=1e-9)


def test_correlated_new_position_partial_trim():
    # MGC=150, ceiling=200, rho=1 (linear): 150 + 100f = 200 => f = 0.5
    f = correlation_scale_factor(
        "MES", 100.0, {"MGC": 150.0}, {("MES", "MGC"): 1.0}, max_portfolio_risk=200.0
    )
    assert math.isclose(f, 0.5, rel_tol=1e-9)


def test_hedging_new_position_is_not_trimmed():
    # MGC=200 at ceiling, MES anti-correlated => combined risk falls, keep full size.
    f = correlation_scale_factor(
        "MES", 100.0, {"MGC": 200.0}, {("MES", "MGC"): -1.0}, max_portfolio_risk=200.0
    )
    assert f == 1.0


def test_uncorrelated_new_position_partial_trim_quadrature():
    # MGC=180, ceiling=200, rho=0: sqrt(180^2 + (100f)^2) = 200 => f^2 = 0.76
    f = correlation_scale_factor(
        "MES", 100.0, {"MGC": 180.0}, {("MES", "MGC"): 0.0}, max_portfolio_risk=200.0
    )
    assert math.isclose(f, math.sqrt(0.76), rel_tol=1e-9)


def test_factor_always_in_unit_interval():
    f = correlation_scale_factor(
        "MES", 100.0, {"MGC": 500.0}, {("MES", "MGC"): 1.0}, max_portfolio_risk=200.0
    )
    assert 0.0 <= f <= 1.0


def test_zero_new_risk_is_noop():
    f = correlation_scale_factor("MES", 0.0, {"MGC": 100.0}, {}, max_portfolio_risk=200.0)
    assert f == 1.0


def test_nonpositive_ceiling_blocks_new_position():
    f = correlation_scale_factor("MES", 100.0, {}, {}, max_portfolio_risk=0.0)
    assert f == 0.0


def test_missing_correlation_uses_conservative_default():
    # No correlation supplied for the pair; default_corr biases toward caution
    # (treats unknown pairs as positively correlated => more trimming, never less).
    f_unknown = correlation_scale_factor(
        "MES", 100.0, {"MGC": 150.0}, {}, max_portfolio_risk=200.0, default_corr=1.0
    )
    assert math.isclose(f_unknown, 0.5, rel_tol=1e-9)


# --------------------------------------------------------------------------- #
# correlation_trim_contracts — factor -> integer micro-contract count
# --------------------------------------------------------------------------- #
def test_trim_noop_when_book_empty():
    n, f, _ = correlation_trim_contracts(
        "MES",
        contracts=2,
        new_risk=100.0,
        open_book_risks={},
        correlations={},
        max_portfolio_risk=200.0,
    )
    assert n == 2 and f == 1.0


def test_trim_noop_when_zero_contracts():
    n, _f, _ = correlation_trim_contracts(
        "MES",
        contracts=0,
        new_risk=100.0,
        open_book_risks={"MGC": 100.0},
        correlations={},
        max_portfolio_risk=200.0,
    )
    assert n == 0


def test_trim_unchanged_when_room_available():
    # Uncorrelated, plenty of headroom -> factor 1.0 -> no change.
    n, f, _ = correlation_trim_contracts(
        "MES",
        contracts=2,
        new_risk=50.0,
        open_book_risks={"MGC": 50.0},
        correlations={("MES", "MGC"): 0.0},
        max_portfolio_risk=500.0,
    )
    assert n == 2 and f == 1.0


def test_trim_scales_down_but_keeps_at_least_one_above_block_threshold():
    # factor ~0.5 (>= block_threshold) -> round(2*0.5)=1, never below 1.
    n, f, _ = correlation_trim_contracts(
        "MES",
        contracts=2,
        new_risk=100.0,
        open_book_risks={"MGC": 150.0},
        correlations={("MES", "MGC"): 1.0},
        max_portfolio_risk=200.0,
        block_threshold=0.4,
    )
    assert n == 1 and math.isclose(f, 0.5, rel_tol=1e-9)


def test_trim_blocks_to_zero_below_block_threshold():
    # Book full + perfectly correlated -> factor 0.0 < block_threshold -> block.
    n, f, _ = correlation_trim_contracts(
        "MES",
        contracts=2,
        new_risk=100.0,
        open_book_risks={"MGC": 200.0},
        correlations={("MES", "MGC"): 1.0},
        max_portfolio_risk=200.0,
        block_threshold=0.4,
    )
    assert n == 0 and f == 0.0


def test_trim_keeps_single_contract_on_mild_pressure():
    # 1 contract, factor 0.7 (>= threshold) -> max(1, round(0.7)) = 1, kept.
    n, _f, _ = correlation_trim_contracts(
        "MES",
        contracts=1,
        new_risk=60.0,
        open_book_risks={"MGC": 160.0},
        correlations={("MES", "MGC"): 1.0},
        max_portfolio_risk=200.0,
        block_threshold=0.4,
    )
    assert n == 1


def test_trim_never_increases_contracts():
    n, _f, _ = correlation_trim_contracts(
        "MES",
        contracts=2,
        new_risk=10.0,
        open_book_risks={"MGC": 10.0},
        correlations={("MES", "MGC"): -1.0},
        max_portfolio_risk=1000.0,
    )
    assert n <= 2
