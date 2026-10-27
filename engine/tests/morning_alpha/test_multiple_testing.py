import math
import random

from morning_alpha.research.multiple_testing import (
    VariantReturnSeries,
    cscv_pbo,
    reality_check,
    romano_wolf_stepdown,
    spa_style_test,
)


def _series():
    rng = random.Random(7)
    n = 80
    stable = tuple(0.08 + rng.gauss(0, 0.05) for _ in range(n))
    noise1 = tuple(rng.gauss(0, 0.08) for _ in range(n))
    noise2 = tuple(rng.gauss(-0.03, 0.08) for _ in range(n))
    return (
        VariantReturnSeries(variant_id='stable', returns=stable),
        VariantReturnSeries(variant_id='noise1', returns=noise1),
        VariantReturnSeries(variant_id='noise2', returns=noise2),
    )


def test_cscv_pbo_is_bounded_and_stable_signal_has_low_overfit_probability():
    result = cscv_pbo(_series(), partitions=8)
    assert 0 <= result.pbo <= 1
    assert result.split_count > 0
    assert result.pbo < 0.5
    assert all(math.isfinite(x) for x in result.oos_logits)


def test_cscv_detects_unstable_variant_selection_as_higher_pbo():
    # Each variant dominates a different temporal block, encouraging IS winners to fail OOS.
    unstable = (
        VariantReturnSeries(variant_id='a', returns=tuple([0.4]*20 + [-0.3]*20 + [0.4]*20 + [-0.3]*20)),
        VariantReturnSeries(variant_id='b', returns=tuple([-0.3]*20 + [0.4]*20 + [-0.3]*20 + [0.4]*20)),
        VariantReturnSeries(variant_id='c', returns=tuple([0.05]*80)),
    )
    assert cscv_pbo(unstable, partitions=8).pbo >= cscv_pbo(_series(), partitions=8).pbo


def test_reality_check_detects_strong_best_variant_against_zero_benchmark():
    result = reality_check(_series(), n_bootstrap=1000, block_length=5, seed=4)
    assert result.best_variant_id == 'stable'
    assert result.p_value < 0.05
    assert result.method == 'white_reality_check_style_block_bootstrap'


def test_spa_style_is_not_more_penalized_by_obviously_bad_alternative():
    base = _series()
    bad = VariantReturnSeries(variant_id='awful', returns=tuple([-0.8] * 80))
    rc = reality_check(base + (bad,), n_bootstrap=800, block_length=5, seed=9)
    spa = spa_style_test(base + (bad,), n_bootstrap=800, block_length=5, seed=9)
    assert spa.best_variant_id == 'stable'
    assert 0 <= spa.p_value <= 1
    assert spa.active_variant_count < len(base) + 1
    assert spa.p_value <= rc.p_value + 0.10


def test_romano_wolf_adjusted_pvalues_are_not_smaller_than_raw_and_are_bounded():
    result = romano_wolf_stepdown(_series(), n_bootstrap=800, block_length=5, seed=11)
    assert set(result.adjusted_p_values) == {'stable','noise1','noise2'}
    for key, adjusted in result.adjusted_p_values.items():
        assert 0 <= result.raw_p_values[key] <= adjusted <= 1
    assert result.adjusted_p_values['stable'] < result.adjusted_p_values['noise2']
