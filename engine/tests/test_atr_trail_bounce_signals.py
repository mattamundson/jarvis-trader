"""Tests for the ATR trailing-stop bounce signal (Matt's /ES bounce hypothesis).

Synthetic, deterministic OHLC. No market data required — verifies the logic and
the point-in-time (no look-ahead) invariant, per .claude/rules/testing.md.
"""

import numpy as np
import pandas as pd
import pytest

from backtest.atr_trail_bounce_signals import (
    generate_atr_trail_bounce_signals,
    generate_atr_trail_confluence_signals,
    generate_atr_trail_fade_signals,
    generate_atr_trail_flip_signals,
    generate_atr_trail_kelt_confluence_signals,
    generate_atr_trail_tpotarget_confluence_signals,
)
from backtest.indicators import (
    atr_trailing_stop,
    keltner_channels,
    keltner_channels_mtf,
    keltner_cloud_mtf,
)


def _ohlc(closes, highs=None, lows=None):
    closes = np.asarray(closes, dtype=float)
    highs = closes + 1.0 if highs is None else np.asarray(highs, dtype=float)
    lows = closes - 1.0 if lows is None else np.asarray(lows, dtype=float)
    return pd.DataFrame(
        {
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": np.full(len(closes), 1000.0),
        }
    )


def test_trailing_stop_long_sits_below_price_in_uptrend():
    # Steady uptrend -> trail should be in long state (+1) and below close.
    closes = np.linspace(100, 130, 40)
    df = _ohlc(closes)
    trail, state = atr_trailing_stop(df["high"], df["low"], df["close"], period=5, factor=3.5)
    last = state.last_valid_index()
    assert state.loc[last] == 1.0
    assert trail.loc[last] < df["close"].loc[last]


def test_trailing_stop_flips_to_short_on_breakdown():
    closes = np.concatenate([np.linspace(100, 130, 30), np.linspace(129, 95, 25)])
    df = _ohlc(closes)
    _, state = atr_trailing_stop(df["high"], df["low"], df["close"], period=5, factor=3.5)
    assert state.dropna().iloc[0] == 1.0  # seeded long
    assert state.dropna().iloc[-1] == -1.0  # flipped short after the drop


def test_clean_bounce_fires_long_entry():
    # Uptrend establishes a long trail; one bar wicks down to the line and
    # closes back above it; price then holds above for the hold window.
    closes = list(np.linspace(100, 120, 25))
    # bounce bar: deep wick toward the rising trail, close stays up
    closes += [120.5, 121.5, 122.5, 123.5]
    df = _ohlc(closes)
    # carve a wick on the first appended bar (index 25)
    df.loc[25, "low"] = df.loc[25, "close"] - 8.0
    out = generate_atr_trail_bounce_signals(df, hold_bars=1, touch_tol_atr=0.5)
    assert (out["entry_signal"] == "ENTRY_NOW").any()
    fire = out.index[out["entry_signal"] == "ENTRY_NOW"][0]
    # stop is the line, below entry price for a long
    assert out.loc[fire, "stop_level"] < out.loc[fire, "close"]
    assert out.loc[fire, "target_1"] > out.loc[fire, "close"]


def test_failed_bounce_does_not_fire():
    # Same tag, but price then collapses through the line within the hold
    # window -> trail flips short -> NO long entry should be recorded at/after.
    closes = list(np.linspace(100, 120, 25)) + [120.5, 108, 100, 95]
    df = _ohlc(closes)
    df.loc[25, "low"] = df.loc[25, "close"] - 8.0
    out = generate_atr_trail_bounce_signals(df, hold_bars=2, touch_tol_atr=0.5)
    # With a 2-bar hold requirement and an immediate flip, the long must not fire.
    longs = out[(out["entry_signal"] == "ENTRY_NOW") & (out["target_1"] > out["close"])]
    assert longs.empty


def test_hold_bars_zero_fires_on_reclaim_bar():
    closes = list(np.linspace(100, 120, 25)) + [120.5, 121.5]
    df = _ohlc(closes)
    df.loc[25, "low"] = df.loc[25, "close"] - 8.0
    out = generate_atr_trail_bounce_signals(df, hold_bars=0, touch_tol_atr=0.5)
    # entry should land exactly on the tag bar when no confirmation is required
    assert out.loc[25, "entry_signal"] == "ENTRY_NOW"


def test_no_lookahead_truncation_invariance():
    # The signal at bar i must not change when future bars are removed.
    closes = list(np.linspace(100, 120, 25)) + [120.5, 121.5, 122.5, 123.5, 124.5]
    df = _ohlc(closes)
    df.loc[25, "low"] = df.loc[25, "close"] - 8.0
    full = generate_atr_trail_bounce_signals(df, hold_bars=1, touch_tol_atr=0.5)
    cutoff = 27
    truncated = generate_atr_trail_bounce_signals(
        df.iloc[: cutoff + 1].copy(), hold_bars=1, touch_tol_atr=0.5
    )
    for i in range(cutoff + 1):
        assert (
            full.loc[i, "entry_signal"] == truncated.loc[i, "entry_signal"]
        ), f"bar {i} changed when future bars were dropped — look-ahead leak"


def test_flip_fires_on_state_change():
    # Uptrend then sharp breakdown -> a +1 -> -1 flip -> short entry on the
    # flip bar; reversal back up -> -1 -> +1 flip -> long entry.
    closes = np.concatenate(
        [
            np.linspace(100, 130, 30),  # long state established
            np.linspace(129, 95, 25),  # breakdown -> flip short
            np.linspace(96, 125, 25),  # recovery -> flip long
        ]
    )
    df = _ohlc(closes)
    out = generate_atr_trail_flip_signals(df, factor=3.5)
    entries = out[out["entry_signal"] == "ENTRY_NOW"]
    assert not entries.empty
    # at least one short (target_1 < close) and one long (target_1 > close)
    assert (entries["target_1"] < entries["close"]).any()
    assert (entries["target_1"] > entries["close"]).any()


def test_flip_entry_aligns_with_state_change():
    closes = np.concatenate([np.linspace(100, 130, 30), np.linspace(129, 95, 25)])
    df = _ohlc(closes)
    out = generate_atr_trail_flip_signals(df, factor=3.5)
    state = out["trail_state"]
    for i in out.index[out["entry_signal"] == "ENTRY_NOW"]:
        pos = out.index.get_loc(i)
        if pos == 0:
            continue
        assert state.iloc[pos] != state.iloc[pos - 1], "flip entry without a state change"


def test_flip_no_lookahead_truncation_invariance():
    closes = list(np.linspace(100, 130, 30)) + list(np.linspace(129, 100, 20))
    df = _ohlc(closes)
    full = generate_atr_trail_flip_signals(df, factor=3.5)
    cutoff = 40
    trunc = generate_atr_trail_flip_signals(df.iloc[: cutoff + 1].copy(), factor=3.5)
    for i in range(cutoff + 1):
        assert (
            full.loc[i, "entry_signal"] == trunc.loc[i, "entry_signal"]
        ), f"flip bar {i} changed when future bars dropped — look-ahead leak"


def _ohlc_dt(closes, highs=None, lows=None):
    """OHLC with an hourly DatetimeIndex (confluence needs it for sessions)."""
    df = _ohlc(closes, highs, lows)
    df.index = pd.date_range("2025-01-02 08:00", periods=len(df), freq="h", tz="UTC")
    return df


def test_confluence_is_subset_of_base():
    # Confluence trades must be a strict subset of the base flip trades —
    # the gate can only remove entries, never add them. This is what keeps
    # attribution clean (we can see exactly what the VA gate costs/adds).
    closes = np.concatenate(
        [
            np.linspace(100, 130, 40),
            np.linspace(129, 95, 30),
            np.linspace(96, 125, 30),
        ]
    )
    df = _ohlc_dt(closes)
    base = generate_atr_trail_flip_signals(df, factor=3.5)
    conf = generate_atr_trail_confluence_signals(df, factor=3.5, base="flip")
    base_entries = set(np.where(base["entry_signal"].to_numpy() == "ENTRY_NOW")[0])
    conf_entries = set(np.where(conf["entry_signal"].to_numpy() == "ENTRY_NOW")[0])
    assert conf_entries.issubset(base_entries), "confluence added entries not in base"


def test_confluence_strict_drops_more_than_loose():
    closes = np.concatenate(
        [
            np.linspace(100, 130, 40),
            np.linspace(129, 95, 30),
            np.linspace(96, 125, 30),
        ]
    )
    df = _ohlc_dt(closes)
    loose = generate_atr_trail_confluence_signals(df, factor=3.5, strict_confluence=False)
    strict = generate_atr_trail_confluence_signals(df, factor=3.5, strict_confluence=True)
    n_loose = int((loose["entry_signal"] == "ENTRY_NOW").sum())
    n_strict = int((strict["entry_signal"] == "ENTRY_NOW").sum())
    assert n_strict <= n_loose, "strict confluence should never keep more trades than loose"


def test_confluence_no_lookahead_truncation_invariance():
    closes = list(np.linspace(100, 130, 40)) + list(np.linspace(129, 100, 30))
    df = _ohlc_dt(closes)
    full = generate_atr_trail_confluence_signals(df, factor=3.5)
    cutoff = 55
    trunc = generate_atr_trail_confluence_signals(df.iloc[: cutoff + 1].copy(), factor=3.5)
    for i in range(cutoff + 1):
        assert (
            full["entry_signal"].iloc[i] == trunc["entry_signal"].iloc[i]
        ), f"confluence bar {i} changed when future bars dropped — look-ahead leak"


def test_mtf_keltner_collapses_to_base_when_rule_equals_bar_freq():
    # With rule == base bar frequency, the developing MTF Keltner must equal the
    # plain single-timeframe keltner_channels exactly (each window is one bar).
    rng = np.random.default_rng(3)
    closes = 100 + np.cumsum(rng.normal(0, 1, 300))
    df = _ohlc(closes)
    df.index = pd.date_range("2025-01-02", periods=len(df), freq="h", tz="UTC")
    u_mtf, b_mtf, l_mtf = keltner_channels_mtf(df, rule="h", sma_len=20, atr_factor=3.0)
    u, b, low = keltner_channels(df["close"], df["high"], df["low"], sma_len=20, atr_factor=3.0)
    # compare where both are defined
    mask = b_mtf.notna() & b.notna()
    assert mask.sum() > 50
    assert np.allclose(b_mtf[mask], b[mask], atol=1e-9)
    assert np.allclose(u_mtf[mask], u[mask], atol=1e-9)
    assert np.allclose(l_mtf[mask], low[mask], atol=1e-9)


def test_mtf_keltner_no_lookahead_truncation_invariance():
    rng = np.random.default_rng(5)
    closes = 100 + np.cumsum(rng.normal(0, 1, 400))
    df = _ohlc(closes)
    df.index = pd.date_range("2025-01-02", periods=len(df), freq="h", tz="UTC")
    _, full_basis, _ = keltner_channels_mtf(df, rule="4h", sma_len=20)
    cutoff = 300
    _, trunc_basis, _ = keltner_channels_mtf(df.iloc[: cutoff + 1].copy(), rule="4h", sma_len=20)
    a = full_basis.iloc[: cutoff + 1].to_numpy()
    b = trunc_basis.to_numpy()
    both = ~(np.isnan(a) | np.isnan(b))
    assert both.sum() > 50
    assert np.allclose(a[both], b[both], atol=1e-9), "MTF Keltner changed when future bars dropped"


def test_kelt_confluence_is_subset_of_base():
    closes = np.concatenate(
        [
            np.linspace(100, 130, 60),
            np.linspace(129, 95, 50),
            np.linspace(96, 125, 50),
        ]
    )
    df = _ohlc_dt(closes)
    base = generate_atr_trail_flip_signals(df, factor=3.5)
    conf = generate_atr_trail_kelt_confluence_signals(df, factor=3.5, base="flip", kelt_rule="4h")
    base_e = set(np.where(base["entry_signal"].to_numpy() == "ENTRY_NOW")[0])
    conf_e = set(np.where(conf["entry_signal"].to_numpy() == "ENTRY_NOW")[0])
    assert conf_e.issubset(base_e), "kelt confluence added entries not in base"


def test_kelt_confluence_strict_subset_of_loose():
    closes = np.concatenate(
        [
            np.linspace(100, 130, 60),
            np.linspace(129, 95, 50),
            np.linspace(96, 125, 50),
        ]
    )
    df = _ohlc_dt(closes)
    loose = generate_atr_trail_kelt_confluence_signals(
        df, factor=3.5, strict_kelt=False, kelt_rule="4h"
    )
    strict = generate_atr_trail_kelt_confluence_signals(
        df, factor=3.5, strict_kelt=True, kelt_rule="4h"
    )
    loose_e = set(np.where(loose["entry_signal"].to_numpy() == "ENTRY_NOW")[0])
    strict_e = set(np.where(strict["entry_signal"].to_numpy() == "ENTRY_NOW")[0])
    assert strict_e.issubset(loose_e), "strict kelt confluence must be a subset of loose"


def test_obomega_cloud_bands_are_ordered_and_nested():
    # outer_upper >= inner_upper >= basis >= inner_lower >= outer_lower
    rng = np.random.default_rng(4)
    closes = 100 + np.cumsum(rng.normal(0, 1, 400))
    df = _ohlc(closes)
    df.index = pd.date_range("2025-01-02", periods=len(df), freq="h", tz="UTC")
    uo, ui, b, li, lo = keltner_cloud_mtf(df, rule="4h", inner_factor=1.5, outer_factor=2.0)
    m = b.notna()
    assert m.sum() > 50
    assert (uo[m] >= ui[m] - 1e-9).all()
    assert (ui[m] >= b[m] - 1e-9).all()
    assert (b[m] >= li[m] - 1e-9).all()
    assert (li[m] >= lo[m] - 1e-9).all()


def test_tpo_target_columns_present_and_pointintime():
    from backtest.tpo_profile import compute_tpo_profile

    rng = np.random.default_rng(6)
    closes = 100 + np.cumsum(rng.normal(0, 1, 500))
    df = _ohlc(closes)
    df.index = pd.date_range("2025-01-02 08:00", periods=len(df), freq="h", tz="UTC")
    out = compute_tpo_profile(df)
    for col in ["tpo_bal", "tpo_imbalance", "tpo_target", "tpo_fail_target"]:
        assert col in out.columns
    # NaN is a legitimate third state (undefined profile / bal==poc, no real
    # imbalance) -- must never silently collapse into BULL_IMBAL.
    assert set(out["tpo_imbalance"].dropna().unique()).issubset({"BEAR_IMBAL", "BULL_IMBAL"})
    # truncation invariance: target at bar i unchanged when future bars dropped
    cutoff = 400
    trunc = compute_tpo_profile(df.iloc[: cutoff + 1].copy())
    a = out["tpo_target"].iloc[: cutoff + 1].to_numpy()
    c = trunc["tpo_target"].to_numpy()
    both = ~(np.isnan(a) | np.isnan(c))
    assert both.sum() > 50
    assert np.allclose(a[both], c[both], atol=1e-9), "TPO target leaked future data"


def test_tpotarget_confluence_is_subset_of_base():
    closes = np.concatenate(
        [
            np.linspace(100, 130, 80),
            np.linspace(129, 95, 70),
            np.linspace(96, 125, 70),
        ]
    )
    df = _ohlc_dt(closes)
    base = generate_atr_trail_flip_signals(df, factor=3.5)
    conf = generate_atr_trail_tpotarget_confluence_signals(df, factor=3.5, base="flip")
    base_e = set(np.where(base["entry_signal"].to_numpy() == "ENTRY_NOW")[0])
    conf_e = set(np.where(conf["entry_signal"].to_numpy() == "ENTRY_NOW")[0])
    assert conf_e.issubset(base_e), "tpo-target confluence added entries not in base"


def test_output_schema_matches_backtester_contract():
    df = _ohlc(np.linspace(100, 120, 30))
    out = generate_atr_trail_bounce_signals(df)
    for col in [
        "entry_signal",
        "exit_signal",
        "stop_level",
        "target_1",
        "target_2",
        "target_3",
        "atr",
        "trail",
        "trail_state",
    ]:
        assert col in out.columns


def test_loader_sets_datetime_index(tmp_path):
    # The Backtester groups by .date() for daily-loss limits, so it needs a
    # DatetimeIndex. _load() must parse the timestamp column into the index;
    # a plain RangeIndex makes every backtest crash with
    # "'int' object has no attribute 'date'", which the runner's broad
    # `except Exception: continue` masks as "no trades — too rare".
    from backtest.run_atr_trail_bounce import _load

    csv = tmp_path / "MES_2024-01-01_2024-01-02_1h.csv"
    csv.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2024-01-01 05:00:00+00:00,100,101,99,100.5,1000\n"
        "2024-01-01 06:00:00+00:00,100.5,102,100,101.5,1200\n"
    )
    out = _load("MES", "1h", str(csv))
    assert isinstance(
        out.index, pd.DatetimeIndex
    ), "loader must return a DatetimeIndex or the Backtester crashes on .date()"


def test_pick_cache_file_prefers_latest_end_not_lexicographic_last(tmp_path):
    # The bug: sorted(glob)[-1] sorts strings, so it picks the file with the latest
    # START date — a short recent tail — and ignores a freshly-refreshed 2-year
    # file. _pick_cache_file must instead pick the file that ENDS latest (and, on
    # a tie, spans the most history), so a data refresh actually feeds the backtest.
    from backtest.run_atr_trail_bounce import _pick_cache_file

    fresh = tmp_path / "MES_2024-04-26_2026-06-25_1h.csv"  # 2-year, freshest end
    tail = tmp_path / "MES_2026-03-21_2026-05-20_1h.csv"  # 2-month recent slice
    short_same_end = tmp_path / "MES_2025-09-02_2026-06-25_1h.csv"  # same end, shorter
    for p in (fresh, tail, short_same_end):
        p.write_text("timestamp,open,high,low,close,volume\n")

    # Sanity: the naive sort really does pick the wrong (tail) file.
    assert sorted([fresh, tail])[-1] == tail

    # Latest end date wins regardless of input order.
    assert _pick_cache_file([fresh, tail]) == fresh
    assert _pick_cache_file([tail, fresh]) == fresh
    # On equal end dates, the longer history wins.
    assert _pick_cache_file([short_same_end, fresh, tail]) == fresh


def test_fade_enters_opposite_the_flip():
    # The fade is the mean-reversion inverse of the flip: it fires on the SAME
    # trail-flip bars but takes the OPPOSITE side (flip-long -> fade-short).
    closes = np.concatenate(
        [
            np.linspace(100, 130, 30),  # long state established
            np.linspace(129, 95, 25),  # breakdown -> flip short
            np.linspace(96, 125, 25),  # recovery -> flip long
        ]
    )
    df = _ohlc(closes)
    fade = generate_atr_trail_fade_signals(df, factor=3.5)
    ent = fade["entry_signal"] == "ENTRY_NOW"
    assert ent.any(), "fade produced no entries on a series with clear flips"
    for pos in np.flatnonzero(ent.to_numpy()):
        st = fade["trail_state"].iloc[pos]
        if st == 1.0:  # trail flipped LONG -> fade SHORT
            assert fade["bias"].iloc[pos] == "LEAN_BEAR"
            assert fade["target_1"].iloc[pos] < fade["close"].iloc[pos]
            assert fade["stop_level"].iloc[pos] > fade["close"].iloc[pos]
        elif st == -1.0:  # trail flipped SHORT -> fade LONG
            assert fade["bias"].iloc[pos] == "LEAN_BULL"
            assert fade["target_1"].iloc[pos] > fade["close"].iloc[pos]
            assert fade["stop_level"].iloc[pos] < fade["close"].iloc[pos]


def test_fade_rr_clears_backtester_entry_gate():
    # The Backtester rejects any entry with |target_1 - price| / |price - stop| < 1.2.
    # The fade's default target_atr=1.5 vs stop_atr=1.0 must clear that gate, else
    # every fade trade is silently dropped and the mode looks empty.
    closes = np.concatenate(
        [np.linspace(100, 130, 30), np.linspace(129, 95, 25), np.linspace(96, 125, 25)]
    )
    df = _ohlc(closes)
    fade = generate_atr_trail_fade_signals(df, stop_atr=1.0, target_atr=1.5)
    ent = fade["entry_signal"] == "ENTRY_NOW"
    assert ent.any()
    for pos in np.flatnonzero(ent.to_numpy()):
        price = fade["close"].iloc[pos]
        rr = abs(fade["target_1"].iloc[pos] - price) / abs(price - fade["stop_level"].iloc[pos])
        assert rr >= 1.2, f"fade R:R {rr:.3f} below the Backtester gate at bar {pos}"


def test_fade_no_lookahead_truncation_invariance():
    # Dropping future bars must not change any past fade signal (no look-ahead).
    closes = list(np.linspace(100, 130, 30)) + list(np.linspace(129, 100, 20))
    df = _ohlc(closes)
    full = generate_atr_trail_fade_signals(df, factor=3.5)
    cutoff = 40
    trunc = generate_atr_trail_fade_signals(df.iloc[: cutoff + 1].copy(), factor=3.5)
    for i in range(cutoff + 1):
        assert (
            full.loc[i, "entry_signal"] == trunc.loc[i, "entry_signal"]
        ), f"fade bar {i} changed when future bars dropped — look-ahead leak"


def test_fade_output_schema_matches_backtester_contract():
    df = _ohlc(np.concatenate([np.linspace(100, 130, 30), np.linspace(129, 95, 25)]))
    out = generate_atr_trail_fade_signals(df)
    for col in [
        "entry_signal",
        "exit_signal",
        "stop_level",
        "target_1",
        "target_2",
        "target_3",
        "atr",
        "bias",
        "regime",
    ]:
        assert col in out.columns


def test_walkforward_oos_preserves_datetime_index(monkeypatch):
    # The walk-forward OOS slice must keep its DatetimeIndex. A
    # `.reset_index(drop=True)` replaces it with a RangeIndex, so the OOS
    # backtest crashes ('int' has no attribute 'date'), the crash is swallowed
    # by `except Exception: return 0.0`, and the walk-forward gate silently
    # rejects EVERY strategy (real_wf_pf == 0). Capture the index type handed to
    # every _backtest call; the OOS call must not be a RangeIndex.
    import backtest.run_atr_trail_bounce as runner

    # Oscillating series -> frequent ATR-trail flips (>=20 in each fold so the
    # in-sample optimizer finds params and the OOS backtest is actually reached).
    n = 600
    closes = 100.0 + 12.0 * np.sin(np.arange(n) / 4.0)
    df = pd.DataFrame(
        {
            "open": closes,
            "high": closes + 1.0,
            "low": closes - 1.0,
            "close": closes,
            "volume": np.full(n, 1000.0),
        }
    )
    df.index = pd.date_range("2025-01-02 00:00", periods=n, freq="h", tz="UTC")

    seen_index_types: list[type] = []
    orig_backtest = runner._backtest

    def _spy(frame, symbol, mode, params):
        seen_index_types.append(type(frame.index))
        return orig_backtest(frame, symbol, mode, params)

    monkeypatch.setattr(runner, "_backtest", _spy)

    wf = runner._make_walkforward_fn("MES", "flip")
    wf(df, train_window=400)  # must reach and run the OOS backtest

    assert seen_index_types, "optimizer never ran a backtest — fold too small to evaluate"
    assert all(t is pd.DatetimeIndex for t in seen_index_types), (
        "an OOS/in-sample backtest received a non-DatetimeIndex frame — "
        "reset_index(drop=True) leak; the walk-forward gate would silently reject all"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
