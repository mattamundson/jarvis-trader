"""Isolated tests for family_fdr.py verdict-extraction helpers.

test_family_fdr.py covers these only INDIRECTLY via build_family(); this file pins the
fail-open vs fail-safe None semantics of the extraction layer directly, so a verdict-schema
drift (missing keys, null fields, wrong types) is caught at the source. Separate file (not
appended to test_family_fdr.py) to avoid a merge conflict with the peer-active branch.

Pure dict/number logic; read-only analysis module, not on the trading path.
"""

from __future__ import annotations

from backtest import family_fdr as ff

# --- _n_oos ----------------------------------------------------------------


def test_n_oos_primary_key():
    assert ff._n_oos({"wfo_config": {"n_oos_windows": 7}}) == 7


def test_n_oos_falls_back_to_n_windows():
    assert ff._n_oos({"wfo_config": {"n_windows": 5}}) == 5


def test_n_oos_prefers_n_oos_windows_over_n_windows():
    assert ff._n_oos({"wfo_config": {"n_oos_windows": 7, "n_windows": 19}}) == 7


def test_n_oos_missing_config_is_zero():
    assert ff._n_oos({}) == 0
    assert ff._n_oos({"wfo_config": None}) == 0


def test_n_oos_zero_value_is_falsy_returns_zero():
    # `if v:` treats 0 as absent and falls through to 0.
    assert ff._n_oos({"wfo_config": {"n_oos_windows": 0}}) == 0


def test_n_oos_coerces_digit_string_skips_garbage():
    assert ff._n_oos({"wfo_config": {"n_oos_windows": "7"}}) == 7
    # garbage in the primary key -> skip -> fall through to 0 (no n_windows present)
    assert ff._n_oos({"wfo_config": {"n_oos_windows": "abc"}}) == 0


# --- _total_oos_trades (None = unknown, fail-safe) -------------------------


def test_total_oos_trades_present():
    assert ff._total_oos_trades({"wfo_config": {"total_oos_trades": 67}}) == 67


def test_total_oos_trades_absent_is_none():
    assert ff._total_oos_trades({"wfo_config": {}}) is None
    assert ff._total_oos_trades({}) is None


def test_total_oos_trades_null_is_none():
    assert ff._total_oos_trades({"wfo_config": {"total_oos_trades": None}}) is None


def test_total_oos_trades_bad_type_is_none():
    assert ff._total_oos_trades({"wfo_config": {"total_oos_trades": "abc"}}) is None


def test_total_oos_trades_coerces_digit_string():
    assert ff._total_oos_trades({"wfo_config": {"total_oos_trades": "30"}}) == 30


# --- _per_window_oos_trades (None = no breakdown, fail-open) ---------------


def test_per_window_oos_trades_basic():
    v = {"windows": [{"oos_trades": 60}, {"oos_trades": 55}]}
    assert ff._per_window_oos_trades(v) == [60, 55]


def test_per_window_oos_trades_no_windows_is_none():
    assert ff._per_window_oos_trades({}) is None
    assert ff._per_window_oos_trades({"windows": []}) is None
    assert ff._per_window_oos_trades({"windows": "notalist"}) is None


def test_per_window_oos_trades_skips_none_and_bad_entries():
    v = {"windows": [{"oos_trades": None}, None, {"oos_trades": "x"}, {"oos_trades": 40}]}
    assert ff._per_window_oos_trades(v) == [40]


def test_per_window_oos_trades_all_missing_is_none():
    v = {"windows": [{"oos_trades": None}, {"foo": 1}]}
    assert ff._per_window_oos_trades(v) is None


# --- _per_window_adequacy --------------------------------------------------


def test_per_window_adequacy_none_or_empty_is_all_none():
    for arg in (None, []):
        out = ff._per_window_adequacy(arg)
        assert out["median_oos_trades_per_window"] is None
        assert out["n_thin_windows"] is None
        assert out["frac_trades_in_thin_windows"] is None
        assert out["per_window_adequate"] is None


def test_per_window_adequacy_all_fat_is_adequate():
    out = ff._per_window_adequacy([60, 55, 64])
    assert out["median_oos_trades_per_window"] == 60  # integer median -> int
    assert out["n_thin_windows"] == 0
    assert out["frac_trades_in_thin_windows"] == 0.0
    assert out["per_window_adequate"] is True


def test_per_window_adequacy_thin_median_blocks():
    # median([2,3,60]) = 3 (< 5) -> not adequate; two thin windows; frac=5/65.
    out = ff._per_window_adequacy([2, 3, 60])
    assert out["median_oos_trades_per_window"] == 3
    assert out["n_thin_windows"] == 2
    assert out["frac_trades_in_thin_windows"] == round(5 / 65, 4)
    assert out["per_window_adequate"] is False


def test_per_window_adequacy_fractional_median_rounded():
    # median([4,5]) = 4.5 -> not integer -> round(.,1); 4.5 < 5 -> not adequate.
    out = ff._per_window_adequacy([4, 5])
    assert out["median_oos_trades_per_window"] == 4.5
    assert out["per_window_adequate"] is False


def test_per_window_adequacy_zero_total_no_zero_division():
    out = ff._per_window_adequacy([0, 0])
    assert out["frac_trades_in_thin_windows"] == 0.0  # guarded `if total else 0.0`
    assert out["per_window_adequate"] is False


def test_min_oos_trades_per_window_is_five():
    # Documents the floor the adequacy logic gates on (mirrored across modules).
    assert ff.MIN_OOS_TRADES_PER_WINDOW == 5
