from __future__ import annotations

import pytest

from domain.instruments import (
    AmbiguousInstrumentAliasError,
    AssetClass,
    DEFAULT_INSTRUMENT_REGISTRY,
    InstrumentRegistry,
    InstrumentSpec,
    UnknownInstrumentError,
)


def test_canonical_root_resolves_without_implying_authorization():
    spec = DEFAULT_INSTRUMENT_REGISTRY.resolve(" mes ")
    assert spec.root == "MES"
    assert spec.asset_class is AssetClass.FUTURE
    assert spec.point_value_usd == 5.0
    assert not hasattr(spec, "enabled")
    assert not hasattr(spec, "authorized")


def test_unknown_symbol_fails_closed():
    with pytest.raises(UnknownInstrumentError):
        DEFAULT_INSTRUMENT_REGISTRY.resolve("UNKNOWN")


@pytest.mark.parametrize("alias", ["MES=F", "NQ=F", "CL=F", "GC=F"])
def test_legacy_provider_aliases_require_explicit_disposition(alias: str):
    with pytest.raises(AmbiguousInstrumentAliasError, match="requires explicit B-01"):
        DEFAULT_INSTRUMENT_REGISTRY.resolve(alias)


def test_registry_key_must_match_spec_root():
    with pytest.raises(ValueError, match="must equal spec.root"):
        InstrumentRegistry(
            {
                "WRONG": InstrumentSpec(
                    root="MES",
                    asset_class=AssetClass.FUTURE,
                    point_value_usd=5.0,
                )
            }
        )


def test_seed_preserves_explicit_legacy_root_values_only():
    expected = {
        "MES": 5.0,
        "MNQ": 2.0,
        "MCL": 100.0,
        "MGC": 10.0,
        "MHG": 2500.0,
        "M2K": 5.0,
        "MSI": 1000.0,
        "ES": 50.0,
        "NQ": 20.0,
        "SPY": 1.0,
        "QQQ": 1.0,
        "AAPL": 1.0,
        "TSLA": 1.0,
    }
    assert {root: DEFAULT_INSTRUMENT_REGISTRY.resolve(root).point_value_usd for root in expected} == expected
