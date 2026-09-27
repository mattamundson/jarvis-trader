"""
Strategy C+ Engine v2 — Full Upgraded Implementation
=====================================================
All 13 improvements wired in. Replaces engine.py for backtesting.
Live signal generation still uses engine.py (stable); swap after validation.

Layer stack (v2):
  Layer 1: Dual Momentum + Factor Tilt + AbsoluteMomentumGate (T2-6)
  Layer 2: Blended vol targeting (40/60, winsorized) + MinimumHoldPeriod (T3-11)
  Layer 3: VIX composite (unchanged — already working)
  Layer 4: DrawdownCircuitBreaker (T2-7, replaces macro filter)
           + KalmanVolRegimeDetector (T3-10, replaces MTF layer)
  Layer 5: RiskParitySizer (T3-12) for within-position weighting
  Layer 6: COT historical multiplier (T1-4) — optional, data-dependent
  TCM:     TransactionCostModel (T1-3, T1-5) — cost drag applied to returns

New config params added to StrategyCConfigV2:
  blend_fast_weight, lookback_long_days, winsorize_sigma
  use_drawdown_cb, dd_tiers, use_min_hold, min_hold_weeks
  use_kalman_mtf, use_risk_parity, use_cot_historical
  use_abs_mom_ma_gate, ma_breach_weeks
  execution_mode ('moc_friday' | 'mkt_monday')
"""
from __future__ import annotations

import json
import logging
import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

from .signals import StrategyCSignals
from .vol_targeting import VolatilityTargeter
from .vix_composite import VIXComposite
from .transaction_costs import TransactionCostModel
from .risk_controls import (
    DrawdownCircuitBreaker,
    MinimumHoldPeriod,
    RiskParitySizer,
    AbsoluteMomentumGate,
    KalmanVolRegimeDetector,
)

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

UNIVERSE = ["SPY", "QQQ", "EFA", "USMV", "MTUM", "XLK", "XLV", "IEF", "SHY", "^VIX"]
BACKTEST_START = "2013-01-01"
STRATEGY_START = "2017-03-06"
IS_END = "2021-04-30"
OOS_START = "2021-05-01"
STRATEGY_END = "2026-06-13"   # Updated to latest available data


class StrategyCConfigV2:
    """Extended config for Strategy C+ v2."""

    def __init__(
        self,
        # Vol targeting (T1-1, T1-2, T2-8)
        vol_target: float = 7.0,
        vol_lookback_days: int = 10,
        lookback_long_days: int = 21,
        blend_fast_weight: float = 0.40,
        vol_floor: float = 6.0,
        winsorize_sigma: Optional[float] = 3.0,
        # VIX composite (unchanged)
        vix_ma_period: int = 26,
        vix_mom_period: int = 4,
        vix_weights: tuple = (0.40, 0.25, 0.20, 0.15),
        # Momentum signals
        mom_lookback_primary: int = 52,
        top_n: int = 2,
        use_factor_tilt: bool = True,
        # T2-6: Enhanced absolute momentum gate
        use_abs_mom_ma_gate: bool = True,
        ma_breach_weeks: int = 3,
        abs_mom_threshold_bear: float = 0.02,
        # T2-7: Drawdown circuit breaker (replaces macro filter)
        use_drawdown_cb: bool = True,
        dd_tiers: Optional[list] = None,   # [(0.08, 0.50), (0.15, 0.25)]
        # T3-10: Kalman regime detector (replaces MTF layer)
        use_kalman_mtf: bool = True,
        kalman_process_noise: float = 0.5,
        kalman_obs_noise: float = 2.0,
        # T3-11: Minimum hold period
        use_min_hold: bool = True,
        min_hold_weeks: int = 2,
        # T3-12: Risk parity sizing
        use_risk_parity: bool = True,
        risk_parity_lookback: int = 21,
        # T1-3/T1-5: Transaction costs
        use_transaction_costs: bool = True,
        execution_mode: str = "moc_friday",
        # T1-4: COT historical (optional — requires CFTC API)
        use_cot_historical: bool = False,
        # Lookahead guard: overlays computed at Friday close t may only size
        # the return of week t+1. 0 = legacy (biased) behavior.
        overlay_lag_weeks: int = 1,
        # Universe
        risk_on: Optional[list] = None,
        risk_off: Optional[list] = None,
    ):
        self.vol_target = vol_target
        self.vol_lookback_days = vol_lookback_days
        self.lookback_long_days = lookback_long_days
        self.blend_fast_weight = blend_fast_weight
        self.vol_floor = vol_floor
        self.winsorize_sigma = winsorize_sigma
        self.vix_ma_period = vix_ma_period
        self.vix_mom_period = vix_mom_period
        self.vix_weights = vix_weights
        self.mom_lookback_primary = mom_lookback_primary
        self.top_n = top_n
        self.use_factor_tilt = use_factor_tilt
        self.use_abs_mom_ma_gate = use_abs_mom_ma_gate
        self.ma_breach_weeks = ma_breach_weeks
        self.abs_mom_threshold_bear = abs_mom_threshold_bear
        self.use_drawdown_cb = use_drawdown_cb
        self.dd_tiers = dd_tiers or [(0.08, 0.50), (0.15, 0.25)]
        self.use_kalman_mtf = use_kalman_mtf
        self.kalman_process_noise = kalman_process_noise
        self.kalman_obs_noise = kalman_obs_noise
        self.use_min_hold = use_min_hold
        self.min_hold_weeks = min_hold_weeks
        self.use_risk_parity = use_risk_parity
        self.risk_parity_lookback = risk_parity_lookback
        self.use_transaction_costs = use_transaction_costs
        self.execution_mode = execution_mode
        self.use_cot_historical = use_cot_historical
        self.overlay_lag_weeks = overlay_lag_weeks
        self.risk_on = risk_on or ["QQQ", "SPY", "EFA", "USMV", "MTUM", "XLK", "XLV"]
        self.risk_off = risk_off or ["IEF", "SHY"]


class StrategyCEngineV2:
    """Strategy C+ v2 engine with all improvements integrated."""

    def __init__(self, config: Optional[StrategyCConfigV2] = None):
        self.config = config or StrategyCConfigV2()
        c = self.config

        # Layer 1: Signals
        self.signals = StrategyCSignals(
            risk_on=c.risk_on,
            risk_off=c.risk_off,
            mom_lookback_primary=c.mom_lookback_primary,
            top_n=c.top_n,
            use_factor_tilt=c.use_factor_tilt,
        )

        # Layer 2: Vol targeting (blended + winsorized)
        self.vol_targeter = VolatilityTargeter(
            vol_target=c.vol_target,
            lookback_days=c.vol_lookback_days,
            lookback_long_days=c.lookback_long_days,
            blend_fast_weight=c.blend_fast_weight,
            vol_floor=c.vol_floor,
            winsorize_sigma=c.winsorize_sigma,
        )

        # Layer 3: VIX composite (unchanged)
        self.vix_composite = VIXComposite(
            vix_ma_period=c.vix_ma_period,
            mom_period=c.vix_mom_period,
            component_weights=c.vix_weights,
        )

        # Layer 4a: Drawdown circuit breaker (replaces macro filter)
        self.dd_circuit = DrawdownCircuitBreaker(tiers=c.dd_tiers) if c.use_drawdown_cb else None

        # Layer 4b: Kalman regime detector (replaces MTF layer)
        self.kalman_detector = KalmanVolRegimeDetector(
            process_noise=c.kalman_process_noise,
            observation_noise=c.kalman_obs_noise,
        ) if c.use_kalman_mtf else None

        # Layer 5: Risk parity sizer
        self.rp_sizer = RiskParitySizer(vol_lookback_days=c.risk_parity_lookback) if c.use_risk_parity else None

        # Risk controls
        self.abs_mom_gate = AbsoluteMomentumGate(
            ma_breach_weeks=c.ma_breach_weeks,
            absolute_mom_threshold_bear=c.abs_mom_threshold_bear,
        ) if c.use_abs_mom_ma_gate else None
        self.min_hold = MinimumHoldPeriod(min_hold_weeks=c.min_hold_weeks) if c.use_min_hold else None

        # TCM
        self.tcm = TransactionCostModel(execution_mode=c.execution_mode) if c.use_transaction_costs else None

        # Data cache
        self._weekly_prices: Optional[pd.DataFrame] = None
        self._daily_prices: Optional[pd.DataFrame] = None
        self._weekly_vix: Optional[pd.Series] = None

    def load_data(self, force_reload: bool = False) -> None:
        if self._weekly_prices is not None and not force_reload:
            return
        print("[StrategyC+ v2] Loading market data...")
        all_tickers = list(set(UNIVERSE + self.config.risk_on + self.config.risk_off))
        raw = yf.download(
            all_tickers,
            start=BACKTEST_START,
            end=datetime.today().strftime("%Y-%m-%d"),
            auto_adjust=True,
            progress=False,
        )
        if isinstance(raw.columns, pd.MultiIndex):
            daily = raw["Close"]
        else:
            daily = raw
        daily.index = pd.to_datetime(daily.index)
        daily = daily.ffill()
        self._weekly_prices = daily.resample("W-FRI").last()
        self._daily_prices = daily
        vix_col = "^VIX" if "^VIX" in self._weekly_prices.columns else None
        self._weekly_vix = self._weekly_prices[vix_col] if vix_col else None

        # Intraday VIX guard: W-FRI resample captures partial intraday VIX
        # when the cron runs before Friday market close (4pm ET / 21:00 UTC).
        # Drop the current-week row so VIX composite uses the prior confirmed close.
        if self._weekly_vix is not None and len(self._weekly_vix) > 1:
            now_utc = pd.Timestamp.utcnow()
            is_friday = now_utc.weekday() == 4
            before_close = now_utc.hour < 21   # 4pm ET = 21:00 UTC
            if is_friday and before_close:
                _dropped_vix = self._weekly_vix.iloc[-1]
                self._weekly_vix = self._weekly_vix.iloc[:-1]
                print(f"[StrategyC+ v2] Intraday VIX guard: dropped intraday row "
                      f"({_dropped_vix:.2f} at {now_utc.strftime('%H:%M')} UTC). "
                      f"Using prior confirmed Friday close.")

        price_cols = [c for c in self._weekly_prices.columns if c not in ("^VIX",)]
        self._weekly_prices = self._weekly_prices[price_cols]
        print(f"[StrategyC+ v2] {len(self._daily_prices)} daily | "
              f"{len(self._weekly_prices)} weekly | {len(price_cols)} instruments")

    def run_backtest(
        self,
        start: str = STRATEGY_START,
        end: str = STRATEGY_END,
        initial_capital: float = 100_000.0,
        label: str = "v2",
    ) -> dict:
        self.load_data()
        c = self.config

        wp = self._weekly_prices.loc[start:end].copy()
        dp = self._daily_prices.loc[start:end].copy()
        weekly_vix = self._weekly_vix.loc[start:end] if self._weekly_vix is not None else None

        print(f"[StrategyC+ v2] Backtest: {start} → {end} ({len(wp)} weeks)")

        # ── Layer 1: Momentum signals ─────────────────────────────────────────
        print("[StrategyC+ v2] L1: Momentum signals...")
        signal_df = self.signals.generate_signals(wp, t1_lag=True)

        # T2-6: Enhanced absolute momentum gate (200d MA co-trigger)
        if self.abs_mom_gate is not None:
            spy_daily = dp.get("SPY") if dp is not None else None
            abs_gate_df = self.abs_mom_gate.compute_gate_series(
                self._weekly_prices.loc[start:end], spy_daily
            )
            # Override RISK_ON → RISK_OFF when MA bear zone + return below bear threshold
            for date in abs_gate_df.index:
                if date not in signal_df.index:
                    continue
                if not abs_gate_df.loc[date, "abs_mom_pass"]:
                    row = signal_df.loc[date]
                    if isinstance(row.get("risk_regime"), str) and "RISK_ON" in row.get("risk_regime", ""):
                        signal_df.at[date, "risk_regime"] = "RISK_OFF_MA"
                        signal_df.at[date, "holdings"] = {"SHY": 1.0}

        # ── Layer 2: Vol targeting (blended + winsorized) ──────────────────────
        print("[StrategyC+ v2] L2: Vol targeting (blended 40/60)...")
        es_daily = dp["SPY"] if "SPY" in dp.columns else None
        nq_daily = dp["QQQ"] if "QQQ" in dp.columns else None
        vol_df = self.vol_targeter.build_scale_series(es_daily, nq_daily, wp.index)

        # ── Layer 3: VIX composite ─────────────────────────────────────────────
        print("[StrategyC+ v2] L3: VIX composite...")
        if weekly_vix is not None:
            rv_weekly = vol_df["realized_vol"]
            vix_df = self.vix_composite.compute(weekly_vix, rv_weekly)
            vix_mult = vix_df["position_multiplier"]
        else:
            vix_mult = pd.Series(1.0, index=wp.index)

        # ── Layer 4a: Kalman regime multiplier (replaces MTF) ─────────────────
        print("[StrategyC+ v2] L4a: Kalman vol regime detector...")
        if self.kalman_detector is not None:
            kal_df = self.kalman_detector.build_regime_series(vol_df["realized_vol"])
            kalman_mult = kal_df["regime"].map(self.kalman_detector.get_regime_multiplier)
            kalman_mult = kalman_mult.reindex(wp.index).fillna(1.0)
        else:
            kalman_mult = pd.Series(1.0, index=wp.index)

        # ── Layer 4b: COT historical (optional) ───────────────────────────────
        if c.use_cot_historical:
            print("[StrategyC+ v2] L4b: COT historical data...")
            try:
                from engine.data.cot_historical import COTHistoricalData
                cot = COTHistoricalData()
                cot_mult = cot.get_multiplier_series(wp.index)
            except Exception as e:
                logger.warning("COT historical fetch failed: %s — using neutral", e)
                cot_mult = pd.Series(1.0, index=wp.index)
        else:
            cot_mult = pd.Series(1.0, index=wp.index)

        # ── Compute portfolio returns with all layers ──────────────────────────
        print("[StrategyC+ v2] Computing portfolio returns...")
        # Lookahead guard (2026-09-27 audit): vol/VIX/Kalman/COT are all
        # computed from data through Friday t, while weekly_returns[t] is the
        # Fri(t-1)->Fri(t) return. Without a lag the overlay "sees" the week
        # it sizes. Lagging 1w dropped full-period Sharpe 1.35 -> 0.55.
        lag = int(getattr(c, "overlay_lag_weeks", 1) or 0)
        if lag > 0:
            vs_series = vol_df["scale"].shift(lag).bfill()
            vix_mult = vix_mult.shift(lag).fillna(1.0)
            kalman_mult = kalman_mult.shift(lag).fillna(1.0)
            cot_mult = cot_mult.shift(lag).fillna(1.0)
        else:
            vs_series = vol_df["scale"]
        self._overlay_lag_weeks = lag
        equity_curve, alloc_log = self._compute_returns_v2(
            wp, signal_df,
            vol_scale=vs_series,
            vix_mult=vix_mult,
            kalman_mult=kalman_mult,
            cot_mult=cot_mult,
            daily_prices=dp,
            initial_capital=initial_capital,
        )

        # ── Metrics ────────────────────────────────────────────────────────────
        print("[StrategyC+ v2] Computing metrics...")
        spy_ret = wp["SPY"].pct_change() if "SPY" in wp.columns else None
        spy_bm = (1 + spy_ret.fillna(0)).cumprod() * initial_capital if spy_ret is not None else None

        full_metrics = self._compute_metrics(equity_curve, "FULL")
        is_mask  = equity_curve.index <= pd.Timestamp(IS_END)
        oos_mask = equity_curve.index >= pd.Timestamp(OOS_START)
        is_metrics  = self._compute_metrics(equity_curve[is_mask], "IS") if is_mask.sum() > 10 else {}
        oos_metrics = self._compute_metrics(equity_curve[oos_mask], "OOS") if oos_mask.sum() > 10 else {}

        oos_retention = {}
        for key in ["sharpe", "cagr"]:
            if is_metrics.get(key) and oos_metrics.get(key) and is_metrics[key] != 0:
                oos_retention[f"{key}_retention_pct"] = round(
                    oos_metrics[key] / is_metrics[key] * 100, 1
                )

        vol_stats = self.vol_targeter.summary_stats(vol_df)
        tcm_summary = {}
        if self.tcm:
            # Use last allocation for TCM estimate
            sample_holdings = {"XLK": 0.277, "QQQ": 0.277, "SHY": 0.446}
            tcm_summary = self.tcm.annual_cost_summary(sample_holdings)

        results = {
            "label": label,
            "equity_curve": equity_curve,
            "spy_benchmark": spy_bm,
            "allocation_log": alloc_log,
            "full_metrics": full_metrics,
            "is_metrics": is_metrics,
            "oos_metrics": oos_metrics,
            "oos_retention": oos_retention,
            "vol_stats": vol_stats,
            "tcm_summary": tcm_summary,
            "vol_df": vol_df,
            "kalman_mult": kalman_mult,
            "vix_mult": vix_mult,
        }
        self._print_summary(full_metrics, is_metrics, oos_metrics, oos_retention, vol_stats, tcm_summary)
        return results

    def _compute_returns_v2(
        self,
        weekly_prices,
        signal_df,
        vol_scale,
        vix_mult,
        kalman_mult,
        cot_mult,
        daily_prices,
        initial_capital,
    ):
        weekly_returns = weekly_prices.pct_change()
        shy_ret = weekly_returns.get("SHY", pd.Series(0.0, index=weekly_prices.index))
        c = self.config

        portfolio_returns = pd.Series(0.0, index=weekly_prices.index)
        alloc_records = []
        equity_running = initial_capital
        prev_equity = initial_capital
        prev_holdings = {}
        prev_regime = None

        # Reset stateful risk controls
        if self.dd_circuit:
            self.dd_circuit.reset()
        if self.min_hold:
            self.min_hold.reset()

        for i, date in enumerate(weekly_prices.index):
            if i == 0:
                continue

            row = signal_df.iloc[i] if i < len(signal_df) else None
            holdings_raw = row["holdings"] if row is not None and isinstance(row.get("holdings"), dict) else {}
            risk_regime = row.get("risk_regime", "UNKNOWN") if row is not None else "UNKNOWN"

            # ── Risk parity sizing (T3-12) ──────────────────────────────────
            if self.rp_sizer and holdings_raw and risk_regime not in ("RISK_OFF", "RISK_OFF_MA"):
                risk_on_assets = [a for a in holdings_raw if a not in ("IEF", "SHY")]
                if len(risk_on_assets) > 1:
                    as_of = date - pd.Timedelta(weeks=getattr(self, "_overlay_lag_weeks", 0))
                    rp_weights = self.rp_sizer.size_portfolio(
                        risk_on_assets, daily_prices, as_of
                    )
                    total_rp = sum(rp_weights.values())
                    # Normalize to match original total risk-on weight
                    total_orig = sum(holdings_raw.get(a, 0) for a in risk_on_assets)
                    if total_rp > 0 and total_orig > 0:
                        scale_factor = total_orig / total_rp
                        holdings_raw = {a: rp_weights.get(a, 0) * scale_factor for a in risk_on_assets}
                        # Add back risk-off
                        for a, w in row["holdings"].items():
                            if a not in risk_on_assets:
                                holdings_raw[a] = w

            # ── Vol scale ──────────────────────────────────────────────────
            vs = float(vol_scale.iloc[i]) if i < len(vol_scale) else 1.0
            vm = float(vix_mult.iloc[i]) if i < len(vix_mult) else 1.0
            km = float(kalman_mult.iloc[i]) if i < len(kalman_mult) else 1.0
            cm = float(cot_mult.iloc[i]) if i < len(cot_mult) else 1.0

            pre_cb_scale = vs * vm * km * cm

            # ── Minimum hold period (T3-11) ────────────────────────────────
            dd_pct = max(0.0, (prev_equity - equity_running) / prev_equity) if prev_equity > 0 else 0.0
            if self.min_hold:
                pre_cb_scale, _ = self.min_hold.apply(risk_regime, pre_cb_scale, dd_pct)

            # ── Drawdown circuit breaker (T2-7) ────────────────────────────
            cb_mult = 1.0
            if self.dd_circuit:
                cb_mult, _ = self.dd_circuit.update_and_get_multiplier(equity_running)
            combined_scale = min(1.0, pre_cb_scale * cb_mult)

            # ── Asset returns ───────────────────────────────────────────────
            asset_ret = 0.0
            for asset, weight in holdings_raw.items():
                if asset in weekly_returns.columns:
                    ret = weekly_returns[asset].iloc[i]
                    if not np.isnan(ret):
                        asset_ret += weight * ret

            # Cash earns SHY
            cash_frac = max(0.0, 1.0 - combined_scale)
            shy_r = float(shy_ret.iloc[i]) if not np.isnan(shy_ret.iloc[i]) else 0.0
            port_ret = combined_scale * asset_ret + cash_frac * shy_r

            # ── TCM cost deduction (T1-3) ────────────────────────────────
            if self.tcm:
                cost_est = self.tcm.estimate_portfolio_weekly_cost(
                    holdings_raw, prev_holdings, portfolio_value=equity_running
                )
                port_ret -= cost_est["total_cost_pct"]

            portfolio_returns.iloc[i] = port_ret
            prev_equity = equity_running
            equity_running *= (1 + port_ret)

            prev_holdings = dict(holdings_raw)
            prev_regime = risk_regime

            alloc_records.append({
                "date": date,
                "holdings": str(holdings_raw),
                "risk_regime": risk_regime,
                "vol_scale": round(vs, 4),
                "vix_mult": round(vm, 4),
                "kalman_mult": round(km, 4),
                "cot_mult": round(cm, 4),
                "cb_mult": round(cb_mult, 4),
                "combined_scale": round(combined_scale, 4),
                "portfolio_return": round(port_ret, 6),
            })

        equity_curve = (1 + portfolio_returns).cumprod() * initial_capital
        equity_curve.name = "Strategy_C_Plus_v2"
        alloc_df = pd.DataFrame(alloc_records).set_index("date")
        return equity_curve, alloc_df

    def _compute_metrics(self, equity, label=""):
        if len(equity) < 10:
            return {}
        returns = equity.pct_change().dropna()
        if len(returns) < 5:
            return {}
        n_years = len(returns) / 52.0
        ann = np.sqrt(52)
        total_ret = float(equity.iloc[-1] / equity.iloc[0]) - 1.0
        cagr = (1 + total_ret) ** (1 / n_years) - 1.0 if n_years > 0 else 0.0
        sharpe = float(returns.mean() / returns.std() * ann) if returns.std() > 0 else 0.0
        downside = returns[returns < 0].std()
        sortino = float(returns.mean() / downside * ann) if downside > 0 else 0.0
        roll_max = equity.expanding().max()
        dd = (equity / roll_max - 1.0)
        max_dd = float(dd.min())
        calmar = cagr / abs(max_dd) if max_dd != 0 else 0.0
        win_rate = float((returns > 0).mean())
        return {
            "label": label,
            "cagr": round(cagr * 100, 2),
            "ann_vol": round(float(returns.std() * ann * 100), 2),
            "sharpe": round(sharpe, 4),
            "sortino": round(sortino, 4),
            "calmar": round(calmar, 4),
            "max_dd_pct": round(max_dd * 100, 2),
            "win_rate_pct": round(win_rate * 100, 1),
            "n_years": round(n_years, 2),
            "final_equity": round(float(equity.iloc[-1]), 2),
            "total_return_pct": round(total_ret * 100, 1),
            "final_multiple_x": round(float(equity.iloc[-1] / equity.iloc[0]), 3),
        }

    def _print_summary(self, full, is_m, oos, retention, vol_stats, tcm):
        print("\n" + "=" * 70)
        print("  STRATEGY C+ v2 — PERFORMANCE SUMMARY")
        print("=" * 70)
        for d, label in [(full, "FULL"), (is_m, "IN-SAMPLE"), (oos, "OUT-OF-SAMPLE")]:
            if not d:
                continue
            print(f"\n  ── {label} ({d.get('n_years', 0):.1f}y) ──────────────────")
            print(f"     CAGR:     {d.get('cagr', 0):>8.2f}%")
            print(f"     Sharpe:   {d.get('sharpe', 0):>8.4f}")
            print(f"     Sortino:  {d.get('sortino', 0):>8.4f}")
            print(f"     Vol:      {d.get('ann_vol', 0):>8.2f}%")
            print(f"     MDD:      {d.get('max_dd_pct', 0):>8.2f}%")
            print(f"     Calmar:   {d.get('calmar', 0):>8.4f}")
            print(f"     Win Rate: {d.get('win_rate_pct', 0):>8.1f}%")
            print(f"     Final EQ: {d.get('final_multiple_x', 0):>8.2f}x  (${d.get('final_equity',0):,.0f})")
        if retention:
            print(f"\n  ── OOS Retention ──")
            for k, v in retention.items():
                print(f"     {k}: {v:.1f}%")
        print(f"\n  ── Vol Targeting (blended 40/60) ──")
        print(f"     Mean scale: {vol_stats.get('mean_scale', 0):.4f}")
        print(f"     At max:     {vol_stats.get('pct_at_max', 0):.1f}% of weeks")
        print(f"     Mean vol:   {vol_stats.get('mean_realized_vol_pct', 0):.2f}%")
        if tcm:
            print(f"\n  ── Transaction Costs ({tcm.get('execution_mode','')}) ──")
            print(f"     Annual drag: {tcm.get('annual_drag_bps', 0):.1f} bps "
                  f"({tcm.get('annual_drag_pct', 0):.2f}%)")
        print("=" * 70 + "\n")

    def get_live_signal(self) -> dict:
        """
        Generate the live signal for the current week using v2 layer stack.

        Layer stack:
          L1: Dual momentum + AbsoluteMomentumGate (T2-6)
          L2: Blended vol targeting (T2-8)
          L3: VIX composite
          L4: DrawdownCircuitBreaker (T2-7) × KalmanVolRegimeDetector (T3-10)
          L5: RiskParitySizer (T3-12)

        Returns a signal dict compatible with the cron notification format.
        Note: DrawdownCircuitBreaker requires a running equity NAV — on live
        signal we bootstrap from the last known equity level stored in
        engine_v2_state.json, defaulting to full scale (1.0) if not available.
        """
        self.load_data()
        c = self.config
        wp = self._weekly_prices
        dp = self._daily_prices

        # ── L1: Momentum signal ───────────────────────────────────────────────
        signal = self.signals.get_current_signal(wp)
        raw_holdings = signal.get("holdings", {})
        risk_regime   = signal.get("risk_regime", "UNKNOWN")

        # AbsoluteMomentumGate override
        if self.abs_mom_gate is not None:
            spy_daily = dp.get("SPY") if dp is not None else None
            try:
                abs_gate_df = self.abs_mom_gate.compute_gate_series(
                    wp.tail(60), spy_daily
                )
                if len(abs_gate_df) > 0 and not abs_gate_df.iloc[-1]["abs_mom_pass"]:
                    if "RISK_ON" in risk_regime:
                        risk_regime  = "RISK_OFF_MA"
                        raw_holdings = {"SHY": 1.0}
            except Exception as e:
                logger.warning("AbsMomGate live error: %s", e)

        # ── L2: Vol targeting ─────────────────────────────────────────────────
        es_daily = dp.get("SPY") if dp is not None else None
        nq_daily = dp.get("QQQ") if dp is not None else None
        if es_daily is not None and nq_daily is not None:
            vol_scale, realized_vol = self.vol_targeter.compute_scale(es_daily, nq_daily)
            vol_regime = self.vol_targeter.vol_regime(realized_vol)
        else:
            vol_scale, realized_vol, vol_regime = 1.0, 15.0, "UNKNOWN"

        # ── L3: VIX composite ─────────────────────────────────────────────────
        if self._weekly_vix is not None and len(self._weekly_vix.dropna()) > 10:
            rv_series = None
            if es_daily is not None and nq_daily is not None:
                vol_df_full = self.vol_targeter.build_scale_series(
                    es_daily, nq_daily, self._weekly_vix.index
                )
                rv_series = vol_df_full["realized_vol"]
            vix_signal = self.vix_composite.get_current_signal(
                self._weekly_vix.dropna(), rv_series
            )
        else:
            vix_signal = {"vix": 18.0, "vix_regime": "NORMAL", "position_multiplier": 1.0,
                          "composite_score": 0.0}

        # ── L4a: Drawdown circuit breaker ─────────────────────────────────────
        cb_mult = 1.0
        cb_detail = {"active": False, "multiplier": 1.0, "drawdown_pct": 0.0}
        if self.dd_circuit is not None:
            try:
                state_path = OUTPUT_DIR / "engine_v2_state.json"
                if state_path.exists():
                    with open(state_path) as f:
                        state = json.load(f)
                    last_equity = float(state.get("last_equity", 100_000))
                else:
                    last_equity = 100_000.0
                cb_mult, cb_detail = self.dd_circuit.update_and_get_multiplier(last_equity)
            except Exception as e:
                logger.warning("DrawdownCB live error: %s", e)

        # ── L4b: Kalman vol regime ─────────────────────────────────────────────
        kalman_mult   = 1.0
        kalman_regime = "NORMAL"
        if self.kalman_detector is not None and es_daily is not None and nq_daily is not None:
            try:
                vol_df_k = self.vol_targeter.build_scale_series(
                    es_daily, nq_daily, wp.index
                )
                kal_df = self.kalman_detector.build_regime_series(vol_df_k["realized_vol"])
                if len(kal_df) > 0:
                    kalman_regime = str(kal_df.iloc[-1]["regime"])
                    kalman_mult   = self.kalman_detector.get_regime_multiplier(kalman_regime)
            except Exception as e:
                logger.warning("Kalman live error: %s", e)

        # ── L5: Risk parity sizer ─────────────────────────────────────────────
        risk_on_assets = [a for a in raw_holdings if a not in ("IEF", "SHY")]
        if self.rp_sizer is not None and risk_on_assets and risk_regime not in ("RISK_OFF", "RISK_OFF_MA"):
            try:
                rp_weights = self.rp_sizer.compute_weights(risk_on_assets, dp)
                if rp_weights:
                    total_risk_on = sum(raw_holdings.get(a, 0) for a in risk_on_assets)
                    raw_holdings = {a: rp_weights.get(a, 0) * total_risk_on for a in risk_on_assets}
                    for a, w in signal.get("holdings", {}).items():
                        if a in ("IEF", "SHY"):
                            raw_holdings[a] = w
            except Exception as e:
                logger.warning("RiskParity live error: %s", e)

        # ── Combine scales ────────────────────────────────────────────────────
        pre_cb_scale = vol_scale * vix_signal.get("position_multiplier", 1.0) * kalman_mult
        combined_scale = min(1.0, pre_cb_scale * cb_mult)

        # Scale holdings, remainder to SHY
        scaled_holdings: dict = {k: v * combined_scale for k, v in raw_holdings.items()}
        cash_weight = max(0.0, 1.0 - combined_scale)
        if cash_weight > 0.005:
            scaled_holdings["SHY"] = scaled_holdings.get("SHY", 0.0) + cash_weight
        scaled_holdings = {k: round(v, 4) for k, v in scaled_holdings.items() if v > 0.001}

        live_signal = {
            "generated_at": datetime.now().isoformat(),
            "strategy": "Strategy_C_Plus_v2",
            "effective_date": datetime.now().strftime("%Y-%m-%d"),
            "execution_note": "T+1 lag: execute Monday open after Friday signal",
            "holdings": scaled_holdings,
            "combined_scale": round(combined_scale, 4),
            "pre_mtf_scale": round(pre_cb_scale, 4),
            "layers": {
                "momentum_signal": {
                    "raw_holdings": raw_holdings,
                    "risk_regime": risk_regime,
                    "absolute_mom_pass": signal.get("absolute_mom_pass", False),
                },
                "vol_targeting": {
                    "scale": round(vol_scale, 4),
                    "realized_vol_pct": round(realized_vol, 2),
                    "vol_target_pct": c.vol_target,
                    "vol_regime": vol_regime,
                },
                "vix_composite": vix_signal,
                "kalman_regime": {
                    "regime": kalman_regime,
                    "multiplier": round(kalman_mult, 4),
                },
                "drawdown_circuit_breaker": cb_detail,
                "macro_filter": {"multiplier": 1.0, "note": "replaced by DrawdownCB in v2"},
                # Cron-compat keys (v1 cron reads these)
                "mtf_signal": {
                    "mtf_scale": round(kalman_mult, 4),
                    "weekly_momentum": kalman_regime,
                    "monthly_momentum": kalman_regime,
                    "daily_confirmation": kalman_regime,
                    "breadth": "N/A",
                    "votes_bull": int(kalman_mult >= 1.0) * 3,
                    "confidence": "HIGH" if kalman_mult >= 1.0 else "LOW",
                },
            },
            "ibkr_instructions": self._generate_ibkr_instructions(scaled_holdings),
        }

        # Persist signal
        output_dir = OUTPUT_DIR
        output_dir.mkdir(exist_ok=True)
        with open(output_dir / "strategy_c_plus_live_signal.json", "w") as f:
            json.dump(live_signal, f, indent=2, default=str)

        return live_signal

    def _generate_ibkr_instructions(self, scaled_holdings: dict) -> dict:
        orders = []
        for ticker, weight in scaled_holdings.items():
            if weight < 0.005:
                continue
            orders.append({
                "symbol": ticker,
                "action": "BUY",
                "weight_pct": round(weight * 100, 2),
                "order_type": "MKT",
                "tif": "OPG",
                "note": f"Strategy C+ v2 allocation: {weight:.1%}",
            })
        return {
            "account": "DUP662235",
            "mode": "PAPER",
            "gateway_port": 4002,
            "execution_timing": "MOO (Market On Open) — Monday morning",
            "orders": orders,
            "rebalance_required": len(orders) > 0,
        }
