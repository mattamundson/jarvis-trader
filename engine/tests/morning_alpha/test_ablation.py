from morning_alpha.models import StrategyKey
from morning_alpha.research.ablation import AblationKind, AblationRunner


def test_ablation_runner_invokes_one_named_variant_at_a_time():
    calls = []

    def evaluator(strategy, kind):
        calls.append((strategy.canonical, kind))
        return {"expectancy_r": 0.1 if kind is AblationKind.FULL else 0.05}

    strategy = StrategyKey(strategy_id="relative_strength_breakout", version="1.0.0")
    rows = AblationRunner().run(strategy, evaluator)

    assert [kind for _, kind in calls] == list(AblationKind)
    assert [row.kind for row in rows] == list(AblationKind)
    assert all(row.strategy_key == strategy.canonical for row in rows)


def test_original_strategy_identity_is_not_mutated():
    strategy = StrategyKey(strategy_id="relative_strength_breakout", version="1.0.0")
    before = strategy.model_dump()

    AblationRunner().run(strategy, lambda _strategy, kind: {"kind": kind.value})

    assert strategy.model_dump() == before
    assert strategy.canonical == "relative_strength_breakout@1.0.0"


def test_runner_can_execute_explicit_subset_without_implicit_variants():
    seen = []
    subset = (AblationKind.FULL, AblationKind.FULL_MINUS_REGIME_FILTER)

    rows = AblationRunner().run(
        StrategyKey(strategy_id="relative_strength_breakout", version="1.0.0"),
        lambda _strategy, kind: seen.append(kind) or {"ok": True},
        kinds=subset,
    )

    assert seen == list(subset)
    assert tuple(row.kind for row in rows) == subset


def test_evidence_is_preserved_per_variant():
    rows = AblationRunner().run(
        StrategyKey(strategy_id="relative_strength_breakout", version="1.0.0"),
        lambda _strategy, kind: {"variant": kind.value},
        kinds=(AblationKind.FULL_MINUS_ENTRY_CONFIRMATION,),
    )
    assert rows[0].evidence == {"variant": "full_minus_entry_confirmation"}
