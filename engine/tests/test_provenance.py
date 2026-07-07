"""
Golden tests for the Phase 1 data-provenance envelope.

Freshness gating is made deterministic by passing a fixed ``now`` so no test
depends on wall-clock timing.
"""

from data.provenance import (
    DEFAULT_STALE_AFTER_S,
    DataEnvelope,
    build_envelope,
    derive_is_live,
)

NOW = 1_000_000.0


class TestDeriveIsLive:
    def test_live_source_fresh_is_live(self):
        assert derive_is_live("ibkr", as_of=NOW - 5, now=NOW, ibkr_data_connected=True) is True

    def test_live_source_stale_is_not_live(self):
        # 5 minutes old with a 60s window -> stale.
        assert derive_is_live("schwab", as_of=NOW - 300, now=NOW) is False

    def test_cached_source_never_live(self):
        # csv_cache is a STATIC tier: even with a fresh timestamp it is not live.
        assert derive_is_live("csv_cache", as_of=NOW, now=NOW) is False

    def test_polygon_rest_not_live(self):
        assert derive_is_live("polygon", as_of=NOW, now=NOW) is False

    def test_unavailable_not_live(self):
        assert derive_is_live("unavailable", as_of=None, now=NOW) is False

    def test_ibkr_disconnected_data_leg_not_live(self):
        # Fresh IBKR value but the data leg is down -> honest downgrade, not live.
        assert (
            derive_is_live("ibkr", as_of=NOW, now=NOW, ibkr_data_connected=False)
            is False
        )

    def test_ibkr_connected_flag_none_defaults_live_when_fresh(self):
        # Unknown connection state is not treated as disconnected.
        assert derive_is_live("ibkr", as_of=NOW - 1, now=NOW) is True

    def test_live_source_unknown_as_of_stays_live(self):
        # Cannot be disproven stale without a timestamp -> remains live.
        assert derive_is_live("polygon_stream", as_of=None, now=NOW) is True

    def test_none_source_not_live(self):
        assert derive_is_live(None, as_of=NOW, now=NOW) is False

    def test_boundary_exactly_at_window_is_live(self):
        # Age == stale_after_s is within the window (strictly greater is stale).
        assert (
            derive_is_live(
                "schwab", as_of=NOW - DEFAULT_STALE_AFTER_S, now=NOW
            )
            is True
        )


class TestBuildEnvelope:
    def test_shape_and_fields(self):
        env = build_envelope(
            value=5432.25,
            source="ibkr",
            as_of=NOW - 2,
            ibkr_data_connected=True,
            now=NOW,
        )
        assert isinstance(env, DataEnvelope)
        assert env.to_dict() == {
            "value": 5432.25,
            "source": "ibkr",
            "as_of": NOW - 2,
            "is_live": True,
            "stale_after_s": DEFAULT_STALE_AFTER_S,
        }

    def test_csv_cache_value_is_static(self):
        env = build_envelope(value=100.0, source="csv_cache", as_of=NOW, now=NOW)
        assert env.is_live is False
        assert env.source == "csv_cache"

    def test_none_value_never_live(self):
        env = build_envelope(
            value=None, source="ibkr", as_of=NOW, ibkr_data_connected=True, now=NOW
        )
        assert env.is_live is False

    def test_missing_source_normalizes_to_unavailable(self):
        env = build_envelope(value=None, source=None, as_of=None, now=NOW)
        assert env.source == "unavailable"
        assert env.is_live is False

    def test_custom_stale_window_applied(self):
        # 90s old with a 120s window -> still live.
        env = build_envelope(
            value=1.0, source="polygon_stream", as_of=NOW - 90, stale_after_s=120.0, now=NOW
        )
        assert env.is_live is True
        assert env.stale_after_s == 120.0
