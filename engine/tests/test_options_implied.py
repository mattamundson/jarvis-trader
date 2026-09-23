"""
Unit tests for analysis/options_implied.py (the SPY/QQQ market-implied options
analytics behind /options-signals). All pure/fixture-based — no network, no DB.
"""

import asyncio
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from analysis.options_implied import (
    DEFAULT_SYMBOLS,
    OptionsImpliedError,
    atm_strike,
    build_regime_block,
    build_snapshot,
    build_symbol_block,
<<<<<<< HEAD
=======
    build_yfinance_vix_raw,
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    classify_term_structure,
    parse_chain,
    parse_occ,
    parse_vix_csv,
    prob_ladder,
    select_expiries,
    straddle_expected_move,
)

_CT = ZoneInfo("America/Chicago")
_NOW = datetime(2026, 7, 15, 13, 30, tzinfo=_CT)  # Wednesday, mid-RTH
_TODAY = _NOW.date()


def _opt(occ, bid=None, ask=None, iv=None, delta=None, last=None, oi=10, vol=5):
    return {
        "option": occ,
        "bid": bid,
        "ask": ask,
        "iv": iv,
        "delta": delta,
        "last_trade_price": last,
        "open_interest": oi,
        "volume": vol,
    }


def _chain_fixture(timestamp="2026-07-15 18:20:00"):
    """SPY mini-chain: two expiries (today + Friday), six strikes on the near
    expiry, one junk OCC symbol, one zero-quote contract.

    The default timestamp is UTC wall time (CBOE convention) = 13:20 CT,
    10 minutes before _NOW — comfortably inside the 60-min staleness guard."""
    near, eow = "260715", "260717"
    options = [
        # near-expiry calls (deltas monotone decreasing in strike)
        _opt(f"SPY{near}C00620000", 8.50, 8.70, 0.14, 0.92),
        _opt(f"SPY{near}C00624000", 4.90, 5.10, 0.135, 0.78),
        _opt(f"SPY{near}C00626000", 3.10, 3.30, 0.133, 0.66),
        _opt(f"SPY{near}C00628000", 1.60, 1.70, 0.131, 0.52),
        _opt(f"SPY{near}C00630000", 0.70, 0.80, 0.130, 0.35),
        _opt(f"SPY{near}C00632000", 0.28, 0.34, 0.132, 0.20),
        # near-expiry puts (negative deltas — must never enter the ladder)
        _opt(f"SPY{near}P00620000", 0.05, 0.07, 0.15, -0.05),
        _opt(f"SPY{near}P00624000", 0.22, 0.28, 0.14, -0.20),
        _opt(f"SPY{near}P00626000", 0.55, 0.65, 0.135, -0.33),
        _opt(f"SPY{near}P00628000", 1.30, 1.40, 0.129, -0.48),
        _opt(f"SPY{near}P00630000", 2.40, 2.60, 0.128, -0.64),
        _opt(f"SPY{near}P00632000", 4.00, 4.30, 0.131, -0.79),
        # end-of-week expiry: one priced ATM pair
        _opt(f"SPY{eow}C00628000", 3.00, 3.20, 0.140, 0.54),
        _opt(f"SPY{eow}P00628000", 2.70, 2.90, 0.138, -0.46),
        # junk OCC symbol — parse_occ must skip, not raise
        _opt("NOT_AN_OCC_SYMBOL", 1.0, 1.1, 0.2, 0.5),
        # foreign root — root filter must drop
        _opt(f"IWM{near}C00220000", 1.0, 1.1, 0.2, 0.5),
        # zero-quote contract — mid must be None
        _opt(f"SPY{near}C00640000", 0, 0, 0.15, 0.05, last=0.03),
    ]
    return {
        "timestamp": timestamp,
        "data": {"current_price": 628.42, "options": options},
    }


<<<<<<< HEAD
=======
def _vix_yfinance_raw_fixture(timestamp="2026-07-15 18:20:00"):
    calls_by_expiry = {
        "2026-07-16": [
            {
                "contractSymbol": "VIX260716C00016000",
                "strike": 16.0,
                "bid": 0.95,
                "ask": 1.05,
                "lastPrice": 1.0,
                "impliedVolatility": 0.82,
                "openInterest": 100,
                "volume": 25,
            },
            {
                # Missing OCC symbol: adapter should synthesize VIX260716C00017000.
                "strike": 17.0,
                "bid": 0.45,
                "ask": 0.55,
                "lastPrice": 0.5,
                "impliedVolatility": 0.84,
                "openInterest": float("nan"),
                "volume": float("nan"),
            },
        ],
        "2026-07-23": [
            {
                "contractSymbol": "VIX260723C00016000",
                "strike": 16.0,
                "bid": 1.40,
                "ask": 1.60,
                "lastPrice": 1.5,
                "impliedVolatility": 0.80,
                "openInterest": 90,
                "volume": 10,
            }
        ],
    }
    puts_by_expiry = {
        "2026-07-16": [
            {
                "contractSymbol": "VIX260716P00016000",
                "strike": 16.0,
                "bid": 0.55,
                "ask": 0.65,
                "lastPrice": 0.6,
                "impliedVolatility": 0.83,
                "openInterest": 70,
                "volume": 9,
            },
            {
                "contractSymbol": "VIX260716P00017000",
                "strike": 17.0,
                "bid": 1.10,
                "ask": 1.30,
                "lastPrice": 1.2,
                "impliedVolatility": 0.85,
                "openInterest": 60,
                "volume": 7,
            },
        ],
        "2026-07-23": [
            {
                "contractSymbol": "VIX260723P00016000",
                "strike": 16.0,
                "bid": 0.80,
                "ask": 1.00,
                "lastPrice": 0.9,
                "impliedVolatility": 0.81,
                "openInterest": 50,
                "volume": 6,
            }
        ],
    }
    return build_yfinance_vix_raw(
        spot=16.4,
        expirations=["2026-07-16", "2026-07-23"],
        calls_by_expiry=calls_by_expiry,
        puts_by_expiry=puts_by_expiry,
        quote_ts=timestamp,
    )


>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
# ---------------------------------------------------------------------------
# parse_occ
# ---------------------------------------------------------------------------


class TestParseOcc:
    def test_spy_call_round_trip(self):
        assert parse_occ("SPY260717C00628000") == ("SPY", date(2026, 7, 17), "C", 628.0)

    def test_qqq_put_fractional_strike(self):
        assert parse_occ("QQQ260715P00707500") == ("QQQ", date(2026, 7, 15), "P", 707.5)

    def test_multi_letter_root(self):
        root, expiry, right, strike = parse_occ("SPXW260716C05500000")
        assert root == "SPXW" and strike == 5500.0

    def test_junk_returns_none(self):
        assert parse_occ("NOT_AN_OCC_SYMBOL") is None
        assert parse_occ("") is None

    def test_impossible_date_returns_none(self):
        assert parse_occ("SPY261332C00628000") is None  # month 13


# ---------------------------------------------------------------------------
# parse_chain
# ---------------------------------------------------------------------------


class TestParseChain:
    def test_spot_and_quote_ts(self):
        spot, quote_ts, contracts = parse_chain(_chain_fixture(), "SPY")
        assert spot == 628.42
        assert quote_ts is not None and quote_ts > 0
        # 15 SPY contracts survive (junk + foreign root dropped, zero-quote kept)
        assert len(contracts) == 15

    def test_foreign_root_dropped(self):
        _, _, contracts = parse_chain(_chain_fixture(), "SPY")
        assert all(c.root == "SPY" for c in contracts)

    def test_zero_quotes_have_no_mid(self):
        _, _, contracts = parse_chain(_chain_fixture(), "SPY")
        dead = next(c for c in contracts if c.strike == 640.0)
        assert dead.bid is None and dead.ask is None and dead.mid is None
        assert dead.last_trade == 0.03

    def test_missing_spot_raises(self):
        with pytest.raises(OptionsImpliedError):
            parse_chain({"data": {"options": []}}, "SPY")

    def test_unparseable_timestamp_is_none(self):
        spot, quote_ts, _ = parse_chain(_chain_fixture(timestamp="garbage"), "SPY")
        assert quote_ts is None

    def test_quote_ts_read_as_utc(self):
        """Pins the live-verified 2026-07-16 finding: CBOE's timestamp wall
        time is UTC — an ET read places quotes 4h in the future."""
        from datetime import timezone

        from analysis.options_implied import _parse_quote_ts

        expected = int(datetime(2026, 7, 16, 18, 55, 31, tzinfo=timezone.utc).timestamp())
        assert _parse_quote_ts("2026-07-16 18:55:31") == expected


<<<<<<< HEAD
=======
class TestYfinanceVixAdapter:
    def test_build_yfinance_vix_raw_parses_as_vix_contracts(self):
        raw = _vix_yfinance_raw_fixture()
        spot, quote_ts, contracts = parse_chain(raw, "VIX")

        assert spot == pytest.approx(16.4)
        assert quote_ts is not None
        assert len(contracts) == 6
        assert all(c.root == "VIX" for c in contracts)
        assert {c.expiry for c in contracts} == {date(2026, 7, 16), date(2026, 7, 23)}
        synthesized = next(c for c in contracts if c.expiry == date(2026, 7, 16) and c.right == "C" and c.strike == 17.0)
        assert synthesized.mid == pytest.approx(0.50)

    def test_build_snapshot_routes_vix_to_yfinance_fetcher_not_cboe(self):
        async def fake_cboe_fetch(url):  # pragma: no cover - should never be called for VIX
            raise AssertionError(f"VIX should not call CBOE fetcher: {url}")

        async def fake_vix_fetch():
            return _vix_yfinance_raw_fixture()

        snapshot, code = asyncio.run(
            build_snapshot(
                ("VIX",),
                fetch_json=fake_cboe_fetch,
                fetch_yfinance_vix=fake_vix_fetch,
                regime=_regime_fixture(),
                now_ct=_NOW,
            )
        )

        assert code == 0
        assert snapshot["data_quality"] == "ok"
        assert snapshot["errors"] == []
        block = snapshot["symbols"]["VIX"]
        assert block["spot"] == pytest.approx(16.4)
        assert block["source"].startswith("yfinance ^VIX")
        assert block["horizons"][0]["expected_move_abs"] == pytest.approx(1.6)
        assert all(row["p_above"] is None for row in block["horizons"][0]["prob_ladder"])
        assert any("vendor deltas unavailable" in note for note in block["horizons"][0]["notes"])


>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
# ---------------------------------------------------------------------------
# select_expiries
# ---------------------------------------------------------------------------


class TestSelectExpiries:
    def test_midweek_nearest_and_friday(self):
        expiries = {date(2026, 7, 15), date(2026, 7, 16), date(2026, 7, 17), date(2026, 7, 24)}
        nearest, eow = select_expiries(expiries, date(2026, 7, 15))  # Wednesday
        assert nearest == date(2026, 7, 15)
        assert eow == date(2026, 7, 17)  # Friday

    def test_friday_promotes_second_horizon_to_next_week(self):
        expiries = {date(2026, 7, 17), date(2026, 7, 20), date(2026, 7, 24)}
        nearest, eow = select_expiries(expiries, date(2026, 7, 17))  # Friday itself
        assert nearest == date(2026, 7, 17)
        assert eow == date(2026, 7, 24)  # next Friday

    def test_holiday_short_week_uses_thursday(self):
        expiries = {date(2026, 7, 15), date(2026, 7, 16)}  # no Friday listed
        nearest, eow = select_expiries(expiries, date(2026, 7, 15))
        assert nearest == date(2026, 7, 15)
        assert eow == date(2026, 7, 16)

    def test_no_second_horizon_returns_none(self):
        expiries = {date(2026, 7, 17)}
        nearest, eow = select_expiries(expiries, date(2026, 7, 17))
        assert nearest == date(2026, 7, 17)
        assert eow is None

    def test_no_future_expiries_raises(self):
        with pytest.raises(OptionsImpliedError):
            select_expiries({date(2026, 7, 10)}, date(2026, 7, 15))


# ---------------------------------------------------------------------------
# atm_strike + straddle expected move
# ---------------------------------------------------------------------------


class TestAtmAndStraddle:
    def setup_method(self):
        _, _, self.contracts = parse_chain(_chain_fixture(), "SPY")
        self.near = date(2026, 7, 15)

    def test_atm_is_nearest_strike_with_both_mids(self):
        assert atm_strike(self.contracts, self.near, 628.42) == 628.0

    def test_atm_tie_breaks_to_lower_strike(self):
        assert atm_strike(self.contracts, self.near, 629.0) == 628.0

    def test_atm_none_when_no_two_sided_strikes(self):
        assert atm_strike(self.contracts, date(2030, 1, 1), 628.42) is None

    def test_straddle_arithmetic(self):
        em = straddle_expected_move(self.contracts, self.near, 628.42)
        # call mid 1.65 + put mid 1.35 = 3.00
        assert em["atm_strike"] == 628.0
        assert em["straddle_mid"] == pytest.approx(3.00)
        assert em["expected_move_abs"] == pytest.approx(3.00)
        assert em["expected_move_pct"] == pytest.approx(3.00 / 628.42)
        assert em["atm_iv"] == pytest.approx((0.131 + 0.129) / 2)
        assert em["quality"] == "ok"

    def test_atm_moves_to_next_two_sided_strike_when_a_leg_loses_quotes(self):
        raw = _chain_fixture()
        for opt in raw["data"]["options"]:
            if opt["option"] == "SPY260715P00628000":
                opt["bid"], opt["ask"] = 0, 0
        _, _, contracts = parse_chain(raw, "SPY")
        em = straddle_expected_move(contracts, self.near, 628.42)
        # 628 no longer has a two-sided put, so ATM selection moves to the next
        # closest fully-quoted strike: |630-628.42|=1.58 vs |626-628.42|=2.42 → 630.
        assert em["atm_strike"] == 630.0
        assert em["quality"] == "ok"

    def test_no_two_sided_strikes_falls_back_to_last_trade_degraded(self):
        raw = _chain_fixture()
        for opt in raw["data"]["options"]:
            if opt["option"].startswith("SPY260717"):
                opt["bid"], opt["ask"], opt["last_trade_price"] = 0, 0, 2.85
        _, _, contracts = parse_chain(raw, "SPY")
        em = straddle_expected_move(contracts, date(2026, 7, 17), 628.42)
        assert em["quality"] == "degraded"
        assert em["straddle_mid"] == pytest.approx(5.70)  # two last trades
        assert any("last_trade_price" in n for n in em["notes"])

    def test_unpriceable_straddle_degrades(self):
        raw = _chain_fixture()
        for opt in raw["data"]["options"]:
            if opt["option"].startswith("SPY260717"):
                opt["bid"], opt["ask"], opt["last_trade_price"] = 0, 0, None
        _, _, contracts = parse_chain(raw, "SPY")
        em = straddle_expected_move(contracts, date(2026, 7, 17), 628.42)
        assert em["quality"] == "degraded"
        assert em["expected_move_abs"] is None


# ---------------------------------------------------------------------------
# prob_ladder
# ---------------------------------------------------------------------------


class TestProbLadder:
    def setup_method(self):
        _, _, self.contracts = parse_chain(_chain_fixture(), "SPY")
        self.near = date(2026, 7, 15)

    def test_interpolated_value_exact(self):
        ladder = prob_ladder(self.contracts, self.near, 628.42, 3.00)
        row = next(r for r in ladder if r["multiple"] == 1.0)
        # level 631.42 between 630 (delta .35) and 632 (delta .20):
        # .35 + (.20-.35) * (631.42-630)/2 = .24350
        assert row["level"] == pytest.approx(631.42)
        assert row["p_above"] == pytest.approx(0.2435, abs=1e-6)

    def test_level_on_listed_strike_uses_vendor_delta(self):
        # spot 628, em 2.0 → +1.0 EM lands exactly on 630
        ladder = prob_ladder(self.contracts, self.near, 628.0, 2.0)
        row = next(r for r in ladder if r["multiple"] == 1.0)
        assert row["p_above"] == pytest.approx(0.35)

    def test_level_outside_strike_range_is_none(self):
        ladder = prob_ladder(self.contracts, self.near, 628.42, 50.0)
        top = next(r for r in ladder if r["multiple"] == 1.0)
        bottom = next(r for r in ladder if r["multiple"] == -1.0)
        assert top["p_above"] is None
        assert bottom["p_above"] is None

    def test_p_above_monotone_down_the_ladder(self):
        ladder = prob_ladder(self.contracts, self.near, 628.42, 3.00)
        probs = [r["p_above"] for r in ladder if r["p_above"] is not None]
        # ladder is ordered +1.0 EM → -1.0 EM, so P(above) must increase
        assert probs == sorted(probs)

    def test_no_expected_move_returns_empty(self):
        assert prob_ladder(self.contracts, self.near, 628.42, None) == []

    def test_put_deltas_never_used(self):
        # remove all calls → ladder has no interpolation source at all
        raw = _chain_fixture()
        raw["data"]["options"] = [
            o for o in raw["data"]["options"] if "P0" in o["option"] and o["option"].startswith("SPY")
        ]
        _, _, contracts = parse_chain(raw, "SPY")
        ladder = prob_ladder(contracts, self.near, 628.42, 3.00)
        assert all(r["p_above"] is None for r in ladder)

<<<<<<< HEAD
=======
    # -- touch / failure columns (reflection rule) --------------------------

    def test_touch_is_double_otm_close_prob_above_spot(self):
        # +1.0 EM row (upper barrier): level 631.42, p_above = .2435
        # → p_touch = 2 × p_above = 0.4870 (reflection rule)
        ladder = prob_ladder(self.contracts, self.near, 628.42, 3.00)
        row = next(r for r in ladder if r["multiple"] == 1.0)
        assert row["p_touch"] == pytest.approx(2 * 0.2435, abs=1e-3)
        assert row["p_fail"] == pytest.approx(1 - row["p_touch"], abs=1e-6)

    def test_touch_reflection_directional(self):
        # Upper barrier: p_touch = 2*p_above; lower barrier: p_touch
        # = 2*(1-p_above); both clamped at 1.0.
        ladder = prob_ladder(self.contracts, self.near, 628.42, 3.00)
        for r in ladder:
            if r["p_above"] is None:
                continue
            expected = 2 * r["p_above"] if r["level"] >= 628.42 else 2 * (1 - r["p_above"])
            assert r["p_touch"] == pytest.approx(min(1.0, expected), abs=1e-6)

    def test_spot_row_touch_near_one(self):
        # ATM delta ≈ 0.5 → p_touch = 2*(1-~0.5) ≈ 1.0 (spot is touched by
        # construction); must be clamped at exactly 1.0, never above.
        ladder = prob_ladder(self.contracts, self.near, 628.42, 3.00)
        row = next(r for r in ladder if r["multiple"] == 0.0)
        assert 0.9 <= row["p_touch"] <= 1.0

    def test_fail_is_one_minus_touch_and_monotone(self):
        # Deeper OTM (further above spot) → lower touch, higher failure.
        ladder = prob_ladder(self.contracts, self.near, 628.42, 3.00)
        above = [r for r in ladder if r["multiple"] in (0.5, 1.0)]
        t05 = next(r for r in above if r["multiple"] == 0.5)
        t10 = next(r for r in above if r["multiple"] == 1.0)
        assert t10["p_touch"] < t05["p_touch"]
        assert t10["p_fail"] > t05["p_fail"]

    def test_touch_none_where_level_out_of_range(self):
        ladder = prob_ladder(self.contracts, self.near, 628.42, 50.0)
        top = next(r for r in ladder if r["multiple"] == 1.0)
        assert top["p_above"] is None
        assert top["p_touch"] is None
        assert top["p_fail"] is None

    def test_empty_ladder_when_no_expected_move(self):
        # regression guard: touch columns must not resurrect the empty ladder
        assert prob_ladder(self.contracts, self.near, 628.42, None) == []

>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2

# ---------------------------------------------------------------------------
# build_symbol_block
# ---------------------------------------------------------------------------


class TestBuildSymbolBlock:
    def test_two_horizons_with_labels(self):
        block = build_symbol_block("SPY", _chain_fixture(), _NOW)
        assert block["spot"] == 628.42
        labels = [h["label"] for h in block["horizons"]]
        assert labels == ["nearest", "end_of_week"]
        assert block["horizons"][0]["expiry"] == "2026-07-15"
        assert block["horizons"][0]["dte_calendar"] == 0
        assert any("0DTE" in n for n in block["horizons"][0]["notes"])

    def test_stale_quote_ts_degrades_all_horizons(self):
        stale = "2026-07-15 15:00:00"  # UTC = 10:00 CT, 3.5h before _NOW
        block = build_symbol_block("SPY", _chain_fixture(timestamp=stale), _NOW)
        assert all(h["quality"] == "degraded" for h in block["horizons"])
        assert any("holiday" in n for h in block["horizons"] for n in h["notes"])


# ---------------------------------------------------------------------------
# VIX / VIX3M regime
# ---------------------------------------------------------------------------


class TestClassifyTermStructure:
    def test_contango(self):
        regime, slope = classify_term_structure(16.0, 16.6)
        assert regime == "CONTANGO"
        assert slope == pytest.approx(0.006)

    def test_backwardation(self):
        regime, slope = classify_term_structure(16.0, 15.4)
        assert regime == "BACKWARDATION"
        assert slope == pytest.approx(-0.006)

    def test_flat_inside_band(self):
        assert classify_term_structure(16.0, 16.4)[0] == "FLAT"
        assert classify_term_structure(16.0, 15.6)[0] == "FLAT"

    def test_parity_with_archived_spot_check(self):
        # options-vrp build-time spot check: VIX 16.4 / VIX3M 19.5 → CONTANGO +0.031
        regime, slope = classify_term_structure(16.4, 19.5)
        assert regime == "CONTANGO"
        assert slope == pytest.approx(0.031)


class TestParseVixCsv:
    def test_iso_and_us_dates_with_header(self):
        text = "DATE,OPEN,HIGH,LOW,CLOSE\n01/02/2026,15.1,16.2,14.9,15.8\n2026-01-05,15.8,16.0,15.0,15.2\n"
        rows = parse_vix_csv(text)
        assert rows == [(date(2026, 1, 2), 15.8), (date(2026, 1, 5), 15.2)]

    def test_junk_rows_skipped(self):
        assert parse_vix_csv("not,a,csv\n,,,,\n") == []


class TestBuildRegimeBlock:
    def test_uses_last_common_date_and_percentile(self):
        base = date(2025, 1, 1).toordinal()
        vix_rows = [(date.fromordinal(base + i), 10.0 + i * 0.05) for i in range(300)]
        vix3m_rows = [(d, c + 2.0) for d, c in vix_rows[:-1]]  # VIX3M lags one day
        block = build_regime_block(vix_rows, vix3m_rows)
        # last common date is vix_rows[-2]
        assert block["as_of_date"] == vix_rows[-2][0].isoformat()
        assert block["regime"] == "CONTANGO"  # +2 vol pts
        # rising series → latest close is the max of its trailing window
        assert block["vix_percentile_1y"] == pytest.approx(1.0)

    def test_no_common_dates_raises(self):
        with pytest.raises(OptionsImpliedError):
            build_regime_block([(date(2026, 1, 1), 15.0)], [(date(2026, 1, 2), 16.0)])

    def test_empty_history_raises(self):
        with pytest.raises(OptionsImpliedError):
            build_regime_block([], [])


# ---------------------------------------------------------------------------
# build_snapshot (injected fetchers — no network)
# ---------------------------------------------------------------------------


def _regime_fixture():
    return {
        "vix": 16.4,
        "vix3m": 19.5,
        "slope": 0.031,
        "regime": "CONTANGO",
        "vix_percentile_1y": 0.42,
        "as_of_date": "2026-07-14",
        "source": "test",
    }


class TestBuildSnapshot:
    def test_all_ok(self):
        async def fake_fetch(url):
            return _chain_fixture()

        snapshot, code = asyncio.run(
            build_snapshot(("SPY",), fetch_json=fake_fetch, regime=_regime_fixture(), now_ct=_NOW)
        )
        assert code == 0
        assert snapshot["data_quality"] == "ok"
        assert snapshot["errors"] == []
        assert snapshot["symbols"]["SPY"]["spot"] == 628.42
        assert snapshot["generated_at"] == int(_NOW.timestamp())
        assert snapshot["quote_ts"] is not None
        assert "no validated predictive edge" in snapshot["disclaimer"]

    def test_one_symbol_fails_partial_exit_2(self):
        async def fake_fetch(url):
            if "QQQ" in url:
                raise TimeoutError("fetch timeout after 30s")
            return _chain_fixture()

        snapshot, code = asyncio.run(
            build_snapshot(DEFAULT_SYMBOLS, fetch_json=fake_fetch, regime=_regime_fixture(), now_ct=_NOW)
        )
        assert code == 2
        assert snapshot["data_quality"] == "partial"
        assert snapshot["symbols"]["QQQ"] is None
        assert snapshot["symbols"]["SPY"] is not None
        assert any("QQQ" in e for e in snapshot["errors"])

    def test_both_fail_still_returns_snapshot_exit_2(self):
        async def fake_fetch(url):
            raise ConnectionError("down")

        snapshot, code = asyncio.run(
            build_snapshot(DEFAULT_SYMBOLS, fetch_json=fake_fetch, regime=_regime_fixture(), now_ct=_NOW)
        )
        assert code == 2
        assert all(v is None for v in snapshot["symbols"].values())
        # the generator's contract: it must NOT overwrite latest.json in this case

    def test_missing_regime_is_partial_with_error(self):
        async def fake_fetch(url):
            return _chain_fixture()

        snapshot, code = asyncio.run(
            build_snapshot(
                ("SPY",),
                fetch_json=fake_fetch,
                regime=None,
                regime_error="regime: VIX CSV fetch failed",
                now_ct=_NOW,
            )
        )
        assert code == 2
        assert snapshot["regime"] is None
        assert "regime: VIX CSV fetch failed" in snapshot["errors"]


# ---------------------------------------------------------------------------
# options_signals_router — /options-signals/latest
# ---------------------------------------------------------------------------


class TestOptionsSignalsRouter:
    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import routers.options_signals_router as osr

        monkeypatch.setattr(osr, "_DATA_DIR", tmp_path)
        app = FastAPI()
        app.include_router(osr.router)
        return TestClient(app), tmp_path

    def test_404_before_first_snapshot(self, client):
        tc, _ = client
        resp = tc.get("/options-signals/latest")
        assert resp.status_code == 404

    def test_200_serves_snapshot_verbatim(self, client):
        tc, data_dir = client
        payload = {"schema_version": 1, "data_quality": "ok", "symbols": {"SPY": None}}
        (data_dir / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
        resp = tc.get("/options-signals/latest")
        assert resp.status_code == 200
        assert resp.json() == payload

    def test_500_on_corrupt_snapshot(self, client):
        tc, data_dir = client
        (data_dir / "latest.json").write_text("{not json", encoding="utf-8")
        resp = tc.get("/options-signals/latest")
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# options_signals_snapshot._update_em_tracking — live EM-vs-realized tracker
# ---------------------------------------------------------------------------


def _em_snapshot(spot=600.0, em=6.0, expiry="2026-07-17", dte=1, quality="ok"):
    return {
        "symbols": {
            "SPY": {
                "spot": spot,
                "horizons": [
                    {
                        "label": "nearest",
                        "expiry": expiry,
                        "dte_calendar": dte,
                        "expected_move_abs": em,
                        "expected_move_pct": em / spot,
                        "quality": quality,
                    }
                ],
            }
        }
    }


class TestUpdateEmTracking:
    @pytest.fixture()
    def tracker(self, tmp_path, monkeypatch):
        import scripts.options_signals_snapshot as oss

        path = tmp_path / "em_tracking.jsonl"
        monkeypatch.setattr(oss, "_EM_TRACKING_PATH", path)
        monkeypatch.setattr(oss, "_DATA_DIR", tmp_path)
        return oss, path

    def _rows(self, path):
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]

    def test_records_nearest_horizon_row(self, tracker):
        oss, path = tracker
        oss._update_em_tracking(_em_snapshot(), "2026-07-16")
        rows = self._rows(path)
        assert len(rows) == 1
        assert rows[0]["symbol"] == "SPY"
        assert rows[0]["em_abs"] == 6.0
        assert "realized" not in rows[0]

    def test_same_day_overwrite_last_wins(self, tracker):
        oss, path = tracker
        oss._update_em_tracking(_em_snapshot(spot=600.0, em=6.0), "2026-07-16")
        oss._update_em_tracking(_em_snapshot(spot=602.5, em=5.5), "2026-07-16")
        rows = self._rows(path)
        assert len(rows) == 1
        assert rows[0]["spot"] == 602.5
        assert rows[0]["em_abs"] == 5.5

    def test_skips_zero_dte_and_degraded(self, tracker):
        oss, path = tracker
        oss._update_em_tracking(_em_snapshot(dte=0), "2026-07-16")
        assert not path.exists()
        oss._update_em_tracking(_em_snapshot(quality="degraded"), "2026-07-16")
        assert not path.exists()

    def test_resolves_on_expiry_day_snapshot(self, tracker):
        oss, path = tracker
        oss._update_em_tracking(
            _em_snapshot(spot=600.0, em=6.0, expiry="2026-07-17", dte=1), "2026-07-16"
        )
        # Expiry day: the nearest horizon is 0-DTE (no new trackable row), but the
        # snapshot's own spot resolves yesterday's record.
        oss._update_em_tracking(
            _em_snapshot(spot=604.5, em=3.0, expiry="2026-07-17", dte=0), "2026-07-17"
        )
        rows = self._rows(path)
        assert len(rows) == 1
        assert rows[0]["realized"] == 4.5
        assert rows[0]["ratio"] == 0.75
        assert rows[0]["resolved_on"] == "2026-07-17"

    def test_resolution_is_idempotent(self, tracker):
        oss, path = tracker
        oss._update_em_tracking(_em_snapshot(spot=600.0, em=6.0), "2026-07-16")
        oss._update_em_tracking(_em_snapshot(spot=604.5, dte=0), "2026-07-17")
        oss._update_em_tracking(_em_snapshot(spot=610.0, dte=0), "2026-07-17")
        rows = self._rows(path)
        assert len(rows) == 1
        assert rows[0]["realized"] == 4.5  # first resolution sticks
