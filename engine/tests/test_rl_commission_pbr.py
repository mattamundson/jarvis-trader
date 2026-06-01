"""
Unit tests for the PBR (Position-Based Returns) commission-aware reward
addition in TradingEnvironment._calculate_reward (ML/AI Novel #3).

The PBR insight: deduct REAL broker commission from realized_pnl in DOLLARS
before the ATR-normalised reward is computed, so the agent learns strategies
that clear the commission floor (~$1.30/contract MCL round-trip).

Source: docs/digest/ml-ai-synthesis.md Novel #3 (tensortrade-org).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Allow import from engine/ root (mirrors strategies/test_rl_env.py)
ENGINE_DIR = Path(__file__).parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

# Skip the whole module if RL deps are missing
gymnasium = pytest.importorskip(
    "gymnasium", reason="gymnasium not installed — skipping RL tests"
)
stable_baselines3 = pytest.importorskip(
    "stable_baselines3", reason="stable-baselines3 not installed — skipping RL tests"
)

from strategies.rl_config import COMMISSION_BY_INSTRUMENT, REWARD_CONFIG
from strategies.rl_environment import Action, TradingEnvironment


def _make_synthetic_df(n_bars: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = 100.0 + rng.normal(0, 1, n_bars).cumsum()
    atr = np.full(n_bars, 1.0)
    df = pd.DataFrame({
        "open": close, "high": close + 0.5, "low": close - 0.5, "close": close,
        "volume": rng.integers(100, 1000, n_bars), "atr": atr,
        "stc": rng.uniform(20, 80, n_bars), "ema_20": close, "ema_50": close,
        "rsi": rng.uniform(40, 60, n_bars), "vix": np.full(n_bars, 17.0),
        "adx": rng.uniform(15, 35, n_bars), "bb_width": rng.uniform(0.5, 3, n_bars),
        "vpoc": close * 0.998, "va_high": close * 1.002, "va_low": close * 0.995,
        "ib_high": close * 1.003, "ib_low": close * 0.994,
        "above_vah": np.zeros(n_bars, dtype=bool),
        "below_val": np.zeros(n_bars, dtype=bool),
        "above_ib_high": np.zeros(n_bars, dtype=bool),
        "below_ib_low": np.zeros(n_bars, dtype=bool),
        "kc_upper": close + atr * 2, "kc_lower": close - atr * 2, "kc_mid": close,
    })
    return df.reset_index(drop=True)


@pytest.fixture
def df_synth():
    return _make_synthetic_df()


def _env_with_cfg(df, **cfg_overrides) -> TradingEnvironment:
    """Build a TradingEnvironment with reward-config overrides applied."""
    env = TradingEnvironment(symbol="MCL", df=df, initial_capital=10_000.0)
    env._reward_cfg = {**REWARD_CONFIG, **cfg_overrides}
    return env


# ── Default behaviour: commission=0 leaves rewards unchanged ────────────────

def test_default_commission_is_zero():
    """Backward-compat: existing training runs see no behavior change."""
    assert REWARD_CONFIG["commission_usd_per_contract"] == 0.0
    assert REWARD_CONFIG["contracts_per_trade"] == 1


def test_zero_commission_preserves_legacy_reward(df_synth):
    """With commission=0, _calculate_reward output equals pre-PBR formula."""
    env = _env_with_cfg(df_synth, commission_usd_per_contract=0.0)
    reward = env._calculate_reward(
        action=Action.CLOSE,
        realized_pnl=10.0,
        atr=1.0,
        is_new_entry=False,
        forced_close=False,
    )
    # pnl_reward = 10.0 / 1.0 * 1.0 = 10.0; no entry_cost (not is_new_entry);
    # no hold_cost (position=0 in fresh env); flat_hold_reward=0; no t1_bonus
    # because realized_pnl/atr = 10 ≥ t1_atr (1.0) → t1_bonus = 0.50
    assert reward == pytest.approx(10.0 + 0.50)


# ── Commission-aware path: deducted in dollars before ATR normalisation ─────

def test_commission_reduces_reward_in_atr_units(df_synth):
    """$1.30 commission on a $10 PnL trade with ATR=1.0 → reward drops by 1.30."""
    env = _env_with_cfg(df_synth, commission_usd_per_contract=1.30)
    reward = env._calculate_reward(
        action=Action.CLOSE,
        realized_pnl=10.0,
        atr=1.0,
        is_new_entry=False,
        forced_close=False,
    )
    # effective_pnl = 10.0 - 1.30 = 8.70; pnl_reward = 8.70 / 1.0 = 8.70;
    # plus t1_bonus=0.50 (8.70 / 1.0 still ≥ 1.0 t1_atr threshold)
    assert reward == pytest.approx(8.70 + 0.50)


def test_commission_scales_with_contracts(df_synth):
    """Commission deducted per contract — 2 contracts = 2× the dollar drag."""
    env = _env_with_cfg(
        df_synth,
        commission_usd_per_contract=1.30,
        contracts_per_trade=2,
    )
    reward = env._calculate_reward(
        action=Action.CLOSE,
        realized_pnl=10.0,
        atr=1.0,
        is_new_entry=False,
        forced_close=False,
    )
    # effective_pnl = 10.0 - 1.30*2 = 7.40; pnl_reward = 7.40; t1_bonus=0.50 still hits
    assert reward == pytest.approx(7.40 + 0.50)


def test_commission_can_invert_small_winner_to_loser(df_synth):
    """Tiny $1 win becomes a -$0.30 loss after $1.30 commission — agent must learn."""
    env = _env_with_cfg(df_synth, commission_usd_per_contract=1.30)
    reward = env._calculate_reward(
        action=Action.CLOSE,
        realized_pnl=1.0,
        atr=1.0,
        is_new_entry=False,
        forced_close=False,
    )
    # effective_pnl = 1.0 - 1.30 = -0.30; pnl_reward = -0.30; no t1_bonus (negative)
    assert reward == pytest.approx(-0.30)


def test_commission_only_charged_on_closing_trades(df_synth):
    """is_new_entry trades have realized_pnl=0 and pay no commission here.
    The entry_cost penalty fires separately."""
    env = _env_with_cfg(df_synth, commission_usd_per_contract=1.30)
    reward = env._calculate_reward(
        action=Action.BUY,
        realized_pnl=0.0,
        atr=1.0,
        is_new_entry=True,
        forced_close=False,
    )
    # realized_pnl=0 → no commission deducted; entry_cost=-0.01 fires; no other terms
    assert reward == pytest.approx(-0.01)


# ── Per-instrument config sanity ────────────────────────────────────────────

def test_per_instrument_commission_table_present():
    """The per-instrument override table covers MCL, MNQ, MES with realistic values."""
    assert "MCL" in COMMISSION_BY_INSTRUMENT
    assert "MNQ" in COMMISSION_BY_INSTRUMENT
    assert "MES" in COMMISSION_BY_INSTRUMENT
    # Sanity: micro-futures commissions are well under $5/contract round-trip
    for sym, cfg in COMMISSION_BY_INSTRUMENT.items():
        assert 0.0 < cfg["commission_usd_per_contract"] < 5.0, (
            f"{sym} commission outside reasonable range"
        )
        assert cfg["contracts_per_trade"] >= 1


def test_per_instrument_override_application(df_synth):
    """REWARD_CONFIG.update(COMMISSION_BY_INSTRUMENT[sym]) is the wiring contract."""
    cfg = {**REWARD_CONFIG, **COMMISSION_BY_INSTRUMENT["MCL"]}
    assert cfg["commission_usd_per_contract"] == 1.30
    env = TradingEnvironment(symbol="MCL", df=df_synth, initial_capital=10_000.0)
    env._reward_cfg = cfg
    reward = env._calculate_reward(
        action=Action.CLOSE,
        realized_pnl=2.0,
        atr=1.0,
        is_new_entry=False,
        forced_close=False,
    )
    # 2.0 - 1.30 = 0.70 effective; pnl_reward=0.70; no t1_bonus (0.70<1.0)
    assert reward == pytest.approx(0.70)
