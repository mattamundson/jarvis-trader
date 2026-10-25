"""Regression tests for pipeline LLM cost accounting rates."""

from database._mixins_llm_costs import MODEL_RATES
from llm import JarvisLLMClient


def test_pipeline_cost_registry_covers_every_client_model() -> None:
    """Every client-priced model must be priced identically for DB cost rows."""
    missing = sorted(set(JarvisLLMClient.COST_PER_MTOK) - set(MODEL_RATES))

    assert missing == [], (
        "pipeline_llm_costs would record $0.00 for client model(s) with no "
        f"database rate: {missing}"
    )


def test_pipeline_cost_registry_matches_client_rates() -> None:
    """The database mixin must not silently drift from the LLM client rates."""
    mismatches = {
        model: {
            "client": JarvisLLMClient.COST_PER_MTOK[model],
            "database": MODEL_RATES[model],
        }
        for model in sorted(set(JarvisLLMClient.COST_PER_MTOK) & set(MODEL_RATES))
        if MODEL_RATES[model] != JarvisLLMClient.COST_PER_MTOK[model]
    }

    assert mismatches == {}
