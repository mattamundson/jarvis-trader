import math,random
from morning_alpha.research.multiple_testing import VariantReturnSeries,cscv_pbo,reality_check,romano_wolf_stepdown,spa_style_test

def _series():
    rng=random.Random(7); n=80
    return (VariantReturnSeries(variant_id="stable",returns=tuple(.08+rng.gauss(0,.05) for _ in range(n))),VariantReturnSeries(variant_id="noise1",returns=tuple(rng.gauss(0,.08) for _ in range(n))),VariantReturnSeries(variant_id="noise2",returns=tuple(rng.gauss(-.03,.08) for _ in range(n))))

def test_cscv_pbo_bounded_and_stable_low():
    r=cscv_pbo(_series(),partitions=8); assert 0<=r.pbo<=1 and r.split_count>0 and r.pbo<.5 and all(math.isfinite(x) for x in r.oos_logits)

def test_cscv_unstable_selection_higher_pbo():
    unstable=(VariantReturnSeries(variant_id="a",returns=tuple([.4]*20+[-.3]*20+[.4]*20+[-.3]*20)),VariantReturnSeries(variant_id="b",returns=tuple([-.3]*20+[.4]*20+[-.3]*20+[.4]*20)),VariantReturnSeries(variant_id="c",returns=tuple([.05]*80)))
    assert cscv_pbo(unstable,partitions=8).pbo>=cscv_pbo(_series(),partitions=8).pbo

def test_reality_check_detects_strong_variant():
    r=reality_check(_series(),n_bootstrap=1000,block_length=5,seed=4); assert r.best_variant_id=="stable" and r.p_value<.05 and r.method=="white_reality_check_style_block_bootstrap"

def test_spa_style_reduces_irrelevant_bad_alternative():
    base=_series(); bad=VariantReturnSeries(variant_id="awful",returns=tuple([-.8]*80)); rc=reality_check(base+(bad,),n_bootstrap=800,block_length=5,seed=9); spa=spa_style_test(base+(bad,),n_bootstrap=800,block_length=5,seed=9); assert spa.best_variant_id=="stable" and spa.active_variant_count<len(base)+1 and spa.p_value<=rc.p_value+.10

def test_romano_wolf_adjusted_values_bounded():
    r=romano_wolf_stepdown(_series(),n_bootstrap=800,block_length=5,seed=11); assert set(r.adjusted_p_values)=={"stable","noise1","noise2"}; assert all(0<=r.raw_p_values[k]<=v<=1 for k,v in r.adjusted_p_values.items()); assert r.adjusted_p_values["stable"]<r.adjusted_p_values["noise2"]
