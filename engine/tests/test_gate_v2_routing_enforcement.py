"""Phase 3 FULL — env-flagged gate_v2 routing enforcement.

Feature-flagged by `GATE_V2_ENFORCE_ROUTING` (truthy → ON). When ON,
`generate_instrument_signals` consults `gate_v2_policy.is_ungate_eligible`
and force-overrides entry_signal → NO_TRADE when a symbol lacks a
non-stale PASS verdict.

Activation runbook (intentional manual step):
  1. Confirm `engine/data/gate_v2_verdicts/MES_trend_rank7.json` exists + PASS.
  2. Add `GATE_V2_ENFORCE_ROUTING=1` to engine/.env or PM2 ecosystem config.
  3. Restart engine via restart_engine.ps1.
  4. Watch logs for `[GateV2Policy]` warnings per symbol.

Precedence: DO_NOT_TRADE_SYMBOLS is checked first (static blocklist wins).
Gate v2 enforcement is a dynamic second-layer check that fails open —
a missing or stale verdict means NO_TRADE, never an implicit allow.

Why SPY for most tests: MES takes the TREND path, which on 300 bars of
synthetic bullish data produces all NO_TRADE naturally (SMA 50/200 hasn't
golden-crossed yet). SPY hits the default `generate_signals` path which
emits some entries on this fixture — giving clean signal for the "flag OFF =
baseline" vs "flag ON = all NO_TRADE" distinction. A dedicated MES test
proves the TREND path is hooked.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from backtest.signals import TREND_GATE_V2_FAMILY_PREFIXES, generate_instrument_signals


@pytest.fixture
def bullish_ohlcv_df() -> pd.DataFrame:
    """Same shape as test_do_not_trade_gate's fixture so enforcement tests
    share baseline assumptions."""
    dates = pd.date_range("2024-01-01", periods=300, freq="1h")
    rng = np.random.default_rng(42)
    trend = np.linspace(5700, 5900, 300)
    noise = rng.normal(0, 10, 300)
    close = trend + noise
    return pd.DataFrame(
        {
            "open": close - 5,
            "high": close + 20,
            "low": close - 20,
            "close": close,
            "volume": np.linspace(2_000_000, 4_000_000, 300),
        },
        index=dates,
    )


def _write_verdict(
    dir_: Path, symbol: str, *, verdict: str, passed_via: str | None,
    age_days: float = 0.0,
) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc) - timedelta(days=age_days)
    doc = {
        "symbol": symbol, "family": "trend", "rank": 7,
        "verdict": verdict, "passed_via": passed_via,
        "core_verdict": "PASS" if passed_via == "core" else "FAIL",
        "alt_verdict": "PASS" if passed_via == "alt" else "UNSCORED",
        "n_core_passed": 4 if passed_via == "core" else 2,
        "n_alt_passed": 5 if passed_via == "alt" else 0,
        "created_at": ts.isoformat(),
        "aux_freshness": {},
        "gate_v2": {},
    }
    (dir_ / f"{symbol}_trend_rank7.json").write_text(json.dumps(doc))


@pytest.fixture
def tmp_verdicts_dir(tmp_path, monkeypatch):
    """Redirect gate_v2_policy to a tmp verdicts dir for this test's scope."""
    from backtest import gate_v2_policy as policy
    monkeypatch.setattr(policy, "_default_verdicts_dir", lambda: tmp_path)
    return tmp_path


def _write_verdict_family(
    dir_: Path, symbol: str, *, family: str, rank: int, verdict: str,
    passed_via: str | None, age_days: float = 0.0,
) -> None:
    """Like `_write_verdict` but with a caller-chosen `family` (needed for the
    PRB-02 tests below, which must write an UNRELATED family, not "trend")."""
    dir_.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc) - timedelta(days=age_days)
    doc = {
        "symbol": symbol, "family": family, "rank": rank,
        "verdict": verdict, "passed_via": passed_via,
        "core_verdict": "PASS" if passed_via == "core" else "FAIL",
        "alt_verdict": "PASS" if passed_via == "alt" else "UNSCORED",
        "n_core_passed": 4 if passed_via == "core" else 2,
        "n_alt_passed": 5 if passed_via == "alt" else 0,
        "created_at": ts.isoformat(),
        "aux_freshness": {},
        "gate_v2": {},
    }
    (dir_ / f"{symbol}_{family}_rank{rank}.json").write_text(json.dumps(doc))


def _some_entries_fired(out: pd.DataFrame) -> bool:
    """True if SPY baseline actually emitted non-NO_TRADE entries — used as
    a precondition check so we know the baseline is non-trivial."""
    return not (out["entry_signal"] == "NO_TRADE").all()


# ---------------------------------------------------------- #
# Flag OFF — nothing changes                                 #
# ---------------------------------------------------------- #


def test_flag_off_spy_trades_normally_even_without_verdict(
    bullish_ohlcv_df, tmp_verdicts_dir, monkeypatch
):
    """Default state: flag unset → no gate v2 check. SPY (default path)
    emits some entries on this fixture."""
    monkeypatch.delenv("GATE_V2_ENFORCE_ROUTING", raising=False)
    out = generate_instrument_signals(bullish_ohlcv_df, symbol="SPY")
    assert _some_entries_fired(out), "flag OFF must not force NO_TRADE on SPY"


def test_flag_off_ignores_present_fail_verdict(
    bullish_ohlcv_df, tmp_verdicts_dir, monkeypatch
):
    """Even a FAIL verdict on disk is ignored when the flag is OFF."""
    _write_verdict(tmp_verdicts_dir, "SPY", verdict="FAIL", passed_via=None)
    monkeypatch.delenv("GATE_V2_ENFORCE_ROUTING", raising=False)
    out = generate_instrument_signals(bullish_ohlcv_df, symbol="SPY")
    assert _some_entries_fired(out)


# ---------------------------------------------------------- #
# Flag ON — enforcement engages                              #
# ---------------------------------------------------------- #


def test_flag_on_missing_verdict_forces_no_trade(
    bullish_ohlcv_df, tmp_verdicts_dir, monkeypatch
):
    """Fail-safe: empty verdicts dir → default-deny, SPY forced NO_TRADE."""
    monkeypatch.setenv("GATE_V2_ENFORCE_ROUTING", "1")
    out = generate_instrument_signals(bullish_ohlcv_df, symbol="SPY")
    assert (out["entry_signal"] == "NO_TRADE").all()


def test_flag_on_pass_verdict_allows_trading(
    bullish_ohlcv_df, tmp_verdicts_dir, monkeypatch
):
    """Flag ON + fresh PASS verdict → SPY entries pass through unchanged."""
    _write_verdict(tmp_verdicts_dir, "SPY", verdict="PASS", passed_via="alt")
    monkeypatch.setenv("GATE_V2_ENFORCE_ROUTING", "1")
    out = generate_instrument_signals(bullish_ohlcv_df, symbol="SPY")
    assert _some_entries_fired(out)


def test_flag_on_fail_verdict_forces_no_trade(
    bullish_ohlcv_df, tmp_verdicts_dir, monkeypatch
):
    """Flag ON + FAIL verdict → SPY forced NO_TRADE."""
    _write_verdict(tmp_verdicts_dir, "SPY", verdict="FAIL", passed_via=None)
    monkeypatch.setenv("GATE_V2_ENFORCE_ROUTING", "1")
    out = generate_instrument_signals(bullish_ohlcv_df, symbol="SPY")
    assert (out["entry_signal"] == "NO_TRADE").all()


def test_flag_on_stale_verdict_forces_no_trade(
    bullish_ohlcv_df, tmp_verdicts_dir, monkeypatch
):
    """Stale PASS → treated as missing (prevents one-shot PASS authorizing
    trading forever)."""
    _write_verdict(
        tmp_verdicts_dir, "SPY", verdict="PASS", passed_via="alt",
        age_days=30.0,  # past the 14-day MAX_VERDICT_AGE_DAYS cutoff
    )
    monkeypatch.setenv("GATE_V2_ENFORCE_ROUTING", "1")
    out = generate_instrument_signals(bullish_ohlcv_df, symbol="SPY")
    assert (out["entry_signal"] == "NO_TRADE").all()


def test_flag_on_mes_trend_path_also_enforced(
    bullish_ohlcv_df, tmp_verdicts_dir, monkeypatch
):
    """Proves the TREND early-return path ALSO routes through gate_v2
    override — not just the default generate_signals path. MES naturally
    emits all NO_TRADE on this short data, so this is a weak assertion by
    itself, but combined with the FAIL test below it pins down wiring."""
    monkeypatch.setenv("GATE_V2_ENFORCE_ROUTING", "1")
    out = generate_instrument_signals(bullish_ohlcv_df, symbol="MES")
    assert (out["entry_signal"] == "NO_TRADE").all()


# ---------------------------------------------------------- #
# PRB-02: family-scoped enforcement for TREND_INSTRUMENTS     #
# ---------------------------------------------------------- #


def test_prb02_mes_unrelated_family_pass_no_longer_authorizes(
    bullish_ohlcv_df, tmp_verdicts_dir, monkeypatch
):
    """The literal PRB-02 live bug: MES_stark_gapfill_long_rank1.json PASSes
    (an unrelated signal-generator family MES's trend path never invokes),
    while no trend-family verdict exists at all. Before the fix,
    is_ungate_eligible("MES") was symbol-wide and returned True off that
    unrelated PASS. After the fix, generate_instrument_signals must call
    is_ungate_eligible with family_prefixes scoped to "trend" for MES, so an
    unrelated-family PASS must NOT authorize it — MES stays gated (would be
    NO_TRADE regardless of the underlying signal on this fixture, but the
    call-arguments assertion below proves the WIRING, not just the outcome).
    """
    _write_verdict_family(
        tmp_verdicts_dir, "MES", family="stark_gapfill_long", rank=1,
        verdict="PASS", passed_via="core",
    )
    monkeypatch.setenv("GATE_V2_ENFORCE_ROUTING", "1")

    from backtest import gate_v2_policy as policy

    with patch.object(policy, "is_ungate_eligible", wraps=policy.is_ungate_eligible) as spy:
        # signals.py imports is_ungate_eligible via `from backtest.gate_v2_policy
        # import is_ungate_eligible` at call time (lazy import) — patch the
        # source module's attribute since the lazy `from ... import` binds
        # fresh from the module each call.
        out = generate_instrument_signals(bullish_ohlcv_df, symbol="MES")

    assert spy.called, "is_ungate_eligible must be invoked for MES under enforcement"
    _, kwargs = spy.call_args
    assert kwargs.get("family_prefixes") == TREND_GATE_V2_FAMILY_PREFIXES, (
        "MES must be checked with family_prefixes scoped to 'trend' -- an "
        "unrelated family's PASS (stark_gapfill_long) must not be able to "
        "authorize it (PRB-02)"
    )
    # The unrelated PASS must not authorize: no trend-family verdict exists,
    # so the family-scoped call correctly returns False and MES stays gated.
    assert (out["entry_signal"] == "NO_TRADE").all()


def test_prb02_trend_family_pass_still_authorizes(
    bullish_ohlcv_df, tmp_verdicts_dir, monkeypatch
):
    """Sanity check the fix is not overly restrictive: a genuine "trend"
    (or "trend_*") family PASS for a TREND_INSTRUMENTS symbol must still
    authorize it -- the fix narrows WHICH families count, it does not block
    trend-family PASSes.

    Uses MES, not MGC: MGC joined DO_NOT_TRADE_SYMBOLS 2026-07-31
    (honest-data-drain DSR correction), and per this module's own documented
    precedence (module docstring above: "DO_NOT_TRADE_SYMBOLS is checked
    first, static blocklist wins"), generate_instrument_signals now short
    -circuits MGC to NO_TRADE before ever reaching is_ungate_eligible --
    which would make spy.called always False regardless of this fix. MES is
    the other TREND_INSTRUMENTS member and is not blocked, so it still
    isolates the routing behavior this test exists to prove."""
    _write_verdict_family(
        tmp_verdicts_dir, "MES", family="trend_baseline", rank=1,
        verdict="PASS", passed_via="alt",
    )
    monkeypatch.setenv("GATE_V2_ENFORCE_ROUTING", "1")

    from backtest import gate_v2_policy as policy

    with patch.object(policy, "is_ungate_eligible", wraps=policy.is_ungate_eligible) as spy:
        generate_instrument_signals(bullish_ohlcv_df, symbol="MES")

    assert spy.called
    _, kwargs = spy.call_args
    assert kwargs.get("family_prefixes") == TREND_GATE_V2_FAMILY_PREFIXES
    # Re-invoke the real function directly to confirm the trend_baseline PASS
    # is accepted under the family scope (the fixture's own crossover may or
    # may not fire on this short synthetic series, so assert on the gate's
    # own answer directly rather than on entry_signal output).
    assert policy.is_ungate_eligible("MES", family_prefixes=TREND_GATE_V2_FAMILY_PREFIXES) is True


def test_prb02_non_trend_symbol_keeps_symbol_wide_check(
    bullish_ohlcv_df, tmp_verdicts_dir, monkeypatch
):
    """Symbols outside TREND_INSTRUMENTS (e.g. SPY, the default-path symbol
    used throughout this file) must keep the original symbol-wide behavior --
    this fix is deliberately scoped to the confirmed-live TREND_INSTRUMENTS
    bug, not a blanket behavior change for every routing path."""
    _write_verdict_family(
        tmp_verdicts_dir, "SPY", family="some_other_family", rank=1,
        verdict="PASS", passed_via="core",
    )
    monkeypatch.setenv("GATE_V2_ENFORCE_ROUTING", "1")

    from backtest import gate_v2_policy as policy

    with patch.object(policy, "is_ungate_eligible", wraps=policy.is_ungate_eligible) as spy:
        out = generate_instrument_signals(bullish_ohlcv_df, symbol="SPY")

    assert spy.called
    _, kwargs = spy.call_args
    assert kwargs.get("family_prefixes") is None
    assert _some_entries_fired(out)


# ---------------------------------------------------------- #
# Precedence: DO_NOT_TRADE wins                              #
# ---------------------------------------------------------- #


def test_do_not_trade_precedence_over_gate_v2_pass(
    bullish_ohlcv_df, tmp_verdicts_dir, monkeypatch
):
    """MCL is in DO_NOT_TRADE_SYMBOLS. Even with PASS verdict + flag ON,
    MCL stays NO_TRADE — static blocklist wins."""
    _write_verdict(tmp_verdicts_dir, "MCL", verdict="PASS", passed_via="alt")
    monkeypatch.setenv("GATE_V2_ENFORCE_ROUTING", "1")
    out = generate_instrument_signals(bullish_ohlcv_df, symbol="MCL")
    assert (out["entry_signal"] == "NO_TRADE").all()


# ---------------------------------------------------------- #
# Flag parsing — common truthy / falsey conventions          #
# ---------------------------------------------------------- #


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "YES", "on"])
def test_flag_truthy_values_activate(
    bullish_ohlcv_df, tmp_verdicts_dir, monkeypatch, val
):
    """Any common truthy spelling enables enforcement."""
    monkeypatch.setenv("GATE_V2_ENFORCE_ROUTING", val)
    out = generate_instrument_signals(bullish_ohlcv_df, symbol="SPY")
    assert (out["entry_signal"] == "NO_TRADE").all(), (
        f"'{val}' should activate enforcement"
    )


@pytest.mark.parametrize("val", ["0", "false", "FALSE", "no", "", "off"])
def test_flag_falsey_values_leave_off(
    bullish_ohlcv_df, tmp_verdicts_dir, monkeypatch, val
):
    """Any common falsey spelling leaves enforcement OFF."""
    monkeypatch.setenv("GATE_V2_ENFORCE_ROUTING", val)
    out = generate_instrument_signals(bullish_ohlcv_df, symbol="SPY")
    assert _some_entries_fired(out), (
        f"'{val}' must NOT activate enforcement"
    )


# ---------------------------------------------------------- #
# Output shape preservation                                  #
# ---------------------------------------------------------- #


def test_enforcement_preserves_dataframe_shape(
    bullish_ohlcv_df, tmp_verdicts_dir, monkeypatch
):
    """Caller (Backtester) assumes row alignment — enforcement override
    must not alter length or index."""
    monkeypatch.setenv("GATE_V2_ENFORCE_ROUTING", "1")
    out = generate_instrument_signals(bullish_ohlcv_df, symbol="SPY")
    assert len(out) == len(bullish_ohlcv_df)
    assert list(out.index) == list(bullish_ohlcv_df.index)


def test_enforcement_also_clears_exit_signal_when_present(
    bullish_ohlcv_df, tmp_verdicts_dir, monkeypatch
):
    """If underlying path populates exit_signal, enforcement overrides it
    to NO_EXIT (same invariant as DO_NOT_TRADE override)."""
    monkeypatch.setenv("GATE_V2_ENFORCE_ROUTING", "1")
    out = generate_instrument_signals(bullish_ohlcv_df, symbol="SPY")
    if "exit_signal" in out.columns:
        assert (out["exit_signal"] == "NO_EXIT").all()
