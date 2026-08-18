"""
JARVIS TRADER — VWAP Reversion SOTA Cross-Validation (audit-fix follow-up)

The gate-v2 PASS for MES VWAP Reversion (2026-08-04, corrected empirical DSR)
was produced by the CUSTOM `vwap_backtester` engine. This harness re-runs the
same champion parameters through the SHARED Backtester with SOTA execution
hardening (gap stops, pessimistic tie-break, vol-scaled slippage, POV impact,
margin cap) to confirm the edge survives the same honest-execution treatment
that killed the SMA variants.

Champion (from run_mes_vwap_rank1.py verdict):
    band_mult=2.5, stop_mult=0.75, require_reversal_bar=False, regime_filter=True

Adapter: vwap_signals.generate_vwap_signals emits LONG_ENTRY/SHORT_ENTRY with
per-bar vwap_stop/targets. The shared Backtester consumes ENTRY_NOW/NO_TRADE
with bias + atr and recomputes stops/targets from stop_atr_mult/t1_atr_mult.
We map LONG_ENTRY -> bias=STRONG_BULL, SHORT_ENTRY -> bias=STRONG_BEAR, and
set stop_atr_mult = 0.75 (the VWAP champion stop_mult).

Usage:
    cd engine && python backtest/run_mes_vwap_sota_crossval.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from backtest.backtester import Backtester

SYMBOL = "MES"
MULTIPLIER = 5.0
CAPITAL = 50_000.0

# VWAP champion from the corrected-gate PASS verdict
BAND_MULT = 2.5
STOP_MULT = 0.75
REQUIRE_REVERSAL = False
REGIME_FILTER = True

# SOTA execution-realism hardening (PR #592)
SOTA_KWARGS = {
    "gap_stop_worst_fill": True,
    "pessimistic_tie_breaker": True,
    "volatility_scaled_slippage": True,
    "vol_slippage_lookback": 20,
    "vol_slippage_min_mult": 0.5,
    "vol_slippage_max_mult": 4.0,
    "max_volume_pct": 0.10,
    "initial_margin_per_contract": 1500.0,
}


def _load_widest_1h() -> pd.DataFrame:
    cache_dir = engine_root / "backtest" / "cache"
    matches = list(cache_dir.glob("MES_*_1h.csv"))
    if not matches:
        raise FileNotFoundError(f"No MES *_1h.csv in {cache_dir}")

    def _row_count(path) -> int:
        try:
            with open(path) as fh:
                return sum(1 for _ in fh) - 1
        except Exception:
            return 0

    data_file = max(matches, key=_row_count)
    print(f"  data: {data_file.name} ({_row_count(data_file)} rows)")
    df = pd.read_csv(data_file, parse_dates=["timestamp"])
    df.set_index("timestamp", inplace=True)
    if "volume" not in df.columns:
        df["volume"] = 1000
    return df


def _adapt_to_shared_engine(df: pd.DataFrame, stop_atr_mult: float = STOP_MULT) -> pd.DataFrame:
    """Map VWAP LONG/SHORT_ENTRY into the shared Backtester's column contract."""
    out = df.copy()
    out["entry_signal"] = np.where(
        out["vwap_signal"].isin(["LONG_ENTRY", "SHORT_ENTRY"]), "ENTRY_NOW", "NO_TRADE"
    )
    out["bias"] = np.where(out["vwap_signal"] == "LONG_ENTRY", "STRONG_BULL", "NEUTRAL")
    out.loc[out["vwap_signal"] == "SHORT_ENTRY", "bias"] = "STRONG_BEAR"
    out["stop_level"] = out.get("vwap_stop", np.nan)
    out["target_1"] = out.get("vwap_target_1", np.nan)
    out["target_2"] = out.get("vwap_target_2", np.nan)
    # Shared engine recomputes stops/targets from ATR multiples; feed it the
    # VWAP stop_mult and a T1 multiple consistent with "T1 = VWAP" roughly
    # (the custom engine's target_1 equals vwap; we approximate with the
    # ATR multiple implied by the champion's typical vwap distance).
    out["stop_atr_mult"] = stop_atr_mult
    out["t1_atr_mult"] = 1.0
    out["t2_atr_mult"] = 2.0
    return out


def run_crossval():
    print("=" * 80)
    print("MES VWAP REVERSION — SOTA CROSS-VALIDATION (shared Backtester + hardening)")
    print(f"Date: {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 80)
    print(f"Champion: band_mult={BAND_MULT} stop_mult={STOP_MULT} "
          f"reversal={REQUIRE_REVERSAL} regime={REGIME_FILTER}")
    print()

    df = _load_widest_1h()
    print(f"  {len(df)} bars | {df.index.min()} -> {df.index.max()}")

    from backtest.vwap_signals import generate_vwap_signals

    df_sig = generate_vwap_signals(
        df,
        symbol=SYMBOL,
        band_mult=BAND_MULT,
        stop_mult=STOP_MULT,
        require_reversal_bar=REQUIRE_REVERSAL,
        regime_filter=REGIME_FILTER,
    )
    df_shared = _adapt_to_shared_engine(df_sig)
    n_long = int((df_sig["vwap_signal"] == "LONG_ENTRY").sum())
    n_short = int((df_sig["vwap_signal"] == "SHORT_ENTRY").sum())
    print(f"  Signals: {n_long} LONG + {n_short} SHORT = {n_long + n_short}")

    import backtest.vwap_backtester as vwap_bt

    print("\n--- CUSTOM vwap_backtester, NO SOTA (reproduces gate PASS path) ---")
    res_cust_base = vwap_bt.run_vwap_backtest(
        df, symbol=SYMBOL, contracts=1, band_mult=BAND_MULT, stop_mult=STOP_MULT,
        require_reversal_bar=REQUIRE_REVERSAL, regime_filter=REGIME_FILTER,
    )
    s_cust_base = res_cust_base.summary()
    print(f"  PF={s_cust_base.get('profit_factor', 0):.3f}  "
          f"trades={s_cust_base.get('n_trades', 0)}  "
          f"pnl={s_cust_base.get('net_pnl', 0):.0f}")

    print("\n--- CUSTOM vwap_backtester WITH SOTA hardening ---")
    res_cust_sota = vwap_bt.run_vwap_backtest(
        df, symbol=SYMBOL, contracts=1, band_mult=BAND_MULT, stop_mult=STOP_MULT,
        require_reversal_bar=REQUIRE_REVERSAL, regime_filter=REGIME_FILTER,
        pessimistic_tie_breaker=True,
        gap_stop_worst_fill=True,
        volatility_scaled_slippage=True,
        max_volume_pct=0.10,
        initial_margin_per_contract=1500.0,
        initial_capital=CAPITAL,
    )
    s_cust_sota = res_cust_sota.summary()
    print(f"  PF={s_cust_sota.get('profit_factor', 0):.3f}  "
          f"trades={s_cust_sota.get('n_trades', 0)}  "
          f"pnl={s_cust_sota.get('net_pnl', 0):.0f}")

    print("\n--- Shared Backtester, NO SOTA hardening (baseline) ---")
    bt_base = Backtester(
        initial_capital=CAPITAL,
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.20,
        commission_per_contract=0.62,
        slippage_ticks=2.0,
    )
    res_base = bt_base.run(df_shared, symbol=SYMBOL, multiplier=MULTIPLIER)
    print(f"  PF={res_base.profit_factor:.3f}  trades={res_base.total_trades}  "
          f"sharpe={res_base.sharpe_ratio:.3f}  DD={res_base.max_drawdown_pct:.3%}")

    print("\n--- Shared Backtester WITH SOTA hardening ---")
    bt_sota = Backtester(
        initial_capital=CAPITAL,
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.20,
        commission_per_contract=0.62,
        slippage_ticks=2.0,
        **SOTA_KWARGS,
    )
    res_sota = bt_sota.run(df_shared, symbol=SYMBOL, multiplier=MULTIPLIER)
    print(f"  PF={res_sota.profit_factor:.3f}  trades={res_sota.total_trades}  "
          f"sharpe={res_sota.sharpe_ratio:.3f}  DD={res_sota.max_drawdown_pct:.3%}")

    print()
    print("=" * 80)
    print("CROSS-VALIDATION VERDICT")
    print("=" * 80)
    cust_pf = s_cust_sota.get('profit_factor', 0)
    shared_pf = res_sota.profit_factor
    pf_ok = shared_pf > 1.2
    dd_ok = res_sota.max_drawdown_pct < 0.05
    trades_ok = res_sota.total_trades >= 30
    print(f"  Custom+SSOTA PF {cust_pf:.3f} (gate verdict was on this path)")
    print(f"  Shared+SOTA PF {shared_pf:.3f} > 1.2:      {'PASS' if pf_ok else 'FAIL'}")
    print(f"  Max DD {res_sota.max_drawdown_pct:.3%} < 5%: {'PASS' if dd_ok else 'FAIL'}")
    print(f"  Trades {res_sota.total_trades} >= 30:       {'PASS' if trades_ok else 'FAIL'}")
    print(f"  Overall SOTA survival: {'PASS' if (pf_ok and dd_ok and trades_ok) else 'FAIL'}")


if __name__ == "__main__":
    run_crossval()
