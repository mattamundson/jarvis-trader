"""
Strategy C+ Engine — Full Production Implementation
====================================================
Integrates all layers into a single backtest + live signal engine.

Signal stack (applied multiplicatively to position sizing):
  Layer 1: Dual Momentum + Factor Tilt → asset selection + 0/1 equity/cash
  Layer 2: ES/NQ realized vol targeting → scale [0.0, 1.0]
  Layer 3: VIX composite (4-component) → multiplier [0.0, 1.0]
  Layer 4: Macro regime filter (yield curve + CoT) → multiplier [0.5, 1.1]

Final weight = DM_weight × vol_scale × vix_multiplier × macro_multiplier

Target statistics (from reverse-engineered dashboard):
  CAGR: 17.4% | Sharpe: 2.13 | Vol: 7.7% | MDD: -7.7% | Beta: 0.67
  OOS retention: Sharpe 84.6%, CAGR 99.1%

Backtesting: 2017-03-06 → 2026-02-23 (469 weeks)
IS period: 2017-03-06 → 2021-04-30
OOS period: 2021-05-01 → 2026-02-23

Data:
  - Weekly prices: yfinance (SPY, QQQ, EFA, USMV, MTUM, XLK, XLV, IEF, SHY, ^VIX)
  - Daily prices: yfinance ES proxy (SPY), NQ proxy (QQQ) for vol targeting
  - Yield curve: yfinance (^TNX - ^IRX) or FRED fallback
"""
from __future__ import annotations

import json
import logging
import os
import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

from .macro_filter import MacroRegimeFilter  # noqa: E402
from .mtf_filter import MTFFilter  # noqa: E402
from .signals import StrategyCSignals  # noqa: E402
from .vix_composite import VIXComposite  # noqa: E402
from .vol_targeting import VolatilityTargeter  # noqa: E402

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Full ETF universe
UNIVERSE = ["SPY", "QQQ", "EFA", "USMV", "MTUM", "XLK", "XLV", "IEF", "SHY", "^VIX"]

# Backtest window
BACKTEST_START = "2013-01-01"  # Extra warmup for indicators
STRATEGY_START = "2017-03-06"
IS_END = "2021-04-30"
OOS_START = "2021-05-01"
STRATEGY_END = "2026-02-23"


class StrategyCConfig:
    """Configurable parameters for Strategy C+ engine."""

    def __init__(
        self,
        # Vol targeting
        vol_target: float = 8.0,
        vol_lookback_days: int = 10,
        vol_floor: float = 6.0,
        # VIX composite
        vix_ma_period: int = 26,
        vix_mom_period: int = 4,
        vix_weights: tuple = (0.40, 0.25, 0.20, 0.15),
        # Momentum signals
        mom_lookback_primary: int = 52,
        top_n: int = 2,
        use_factor_tilt: bool = True,
        # Macro filter
        use_macro_filter: bool = True,
        use_cot: bool = False,  # Live only — not vectorized for backtest
        # Multi-timeframe momentum confirmation
        use_mtf: bool = True,
        mtf_symbols: list = None,  # defaults to ["XLK", "QQQ", "SPY"]
        # Risk-on universe
        risk_on: Optional[list] = None,
        risk_off: Optional[list] = None,
    ):
        self.vol_target = vol_target
        self.vol_lookback_days = vol_lookback_days
        self.vol_floor = vol_floor
        self.vix_ma_period = vix_ma_period
        self.vix_mom_period = vix_mom_period
        self.vix_weights = vix_weights
        self.mom_lookback_primary = mom_lookback_primary
        self.top_n = top_n
        self.use_factor_tilt = use_factor_tilt
        self.use_macro_filter = use_macro_filter
        self.use_cot = use_cot
        self.use_mtf = use_mtf
        self.mtf_symbols = mtf_symbols  # None → MTFFilter defaults to ["XLK", "QQQ", "SPY"]
        self.risk_on = risk_on or ["QQQ", "SPY", "EFA", "USMV", "MTUM", "XLK", "XLV"]
        self.risk_off = risk_off or ["IEF", "SHY"]


class StrategyCEngine:
    """
    Strategy C+ full backtest and live signal engine.

    Usage:
        engine = StrategyCEngine()
        results = engine.run_backtest()
        signal = engine.get_live_signal()
    """

    def __init__(self, config: Optional[StrategyCConfig] = None):
        self.config = config or StrategyCConfig()
        self.signals = StrategyCSignals(
            risk_on=self.config.risk_on,
            risk_off=self.config.risk_off,
            mom_lookback_primary=self.config.mom_lookback_primary,
            top_n=self.config.top_n,
            use_factor_tilt=self.config.use_factor_tilt,
        )
        self.vol_targeter = VolatilityTargeter(
            vol_target=self.config.vol_target,
            lookback_days=self.config.vol_lookback_days,
            vol_floor=self.config.vol_floor,
        )
        self.vix_composite = VIXComposite(
            vix_ma_period=self.config.vix_ma_period,
            mom_period=self.config.vix_mom_period,
            component_weights=self.config.vix_weights,
        )
        self.macro_filter = MacroRegimeFilter(
            use_cot=self.config.use_cot,
            use_fred=self.config.use_macro_filter,
        )

        # Cached data
        self._weekly_prices: Optional[pd.DataFrame] = None
        self._daily_prices: Optional[pd.DataFrame] = None
        self._weekly_vix: Optional[pd.Series] = None
        self._yield_curve: Optional[pd.Series] = None

    # ─────────────────────────────────────────────────────────────────────────
    # Data Loading
    # ─────────────────────────────────────────────────────────────────────────

    def load_data(self, force_reload: bool = False) -> None:
        """Download all price data from yfinance."""
        if self._weekly_prices is not None and not force_reload:
            return

        print("[Strategy C+] Loading market data...")
        all_tickers = list(set(UNIVERSE + self.config.risk_on + self.config.risk_off))

        # Download daily data (for vol targeting + yield curve)
        raw_daily = yf.download(
            all_tickers + ["^TNX", "^IRX"],
            start=BACKTEST_START,
            end=datetime.today().strftime("%Y-%m-%d"),
            auto_adjust=True,
            progress=False,
        )

        if isinstance(raw_daily.columns, pd.MultiIndex):
            daily_close = raw_daily["Close"]
        else:
            daily_close = raw_daily

        daily_close.index = pd.to_datetime(daily_close.index)
        daily_close = daily_close.ffill()

        # Weekly prices (Friday close)
        self._weekly_prices = daily_close.resample("W-FRI").last()
        self._daily_prices = daily_close

        # VIX series
        vix_col = "^VIX" if "^VIX" in self._weekly_prices.columns else None
        self._weekly_vix = self._weekly_prices[vix_col] if vix_col else None

        # Yield curve: 10Y - 3M (better recession signal than 10Y-2Y)
        if "^TNX" in daily_close.columns and "^IRX" in daily_close.columns:
            tnx_weekly = daily_close["^TNX"].resample("W-FRI").last()
            irx_weekly = daily_close["^IRX"].resample("W-FRI").last()
            self._yield_curve = (tnx_weekly - irx_weekly).rename("yield_curve_10y_3m")
        else:
            self._yield_curve = None

        # Drop VIX and yield curve from price series used for returns
        price_cols = [c for c in self._weekly_prices.columns
                      if c not in ("^VIX", "^TNX", "^IRX")]
        self._weekly_prices = self._weekly_prices[price_cols]

        print(f"[Strategy C+] Loaded {len(self._daily_prices)} daily bars, "
              f"{len(self._weekly_prices)} weekly bars, "
              f"{len(price_cols)} instruments")

    # ─────────────────────────────────────────────────────────────────────────
    # Backtest
    # ─────────────────────────────────────────────────────────────────────────

    def run_backtest(
        self,
        start: str = STRATEGY_START,
        end: str = STRATEGY_END,
        initial_capital: float = 100_000.0,
        save_results: bool = True,
    ) -> dict:
        """
        Run the full Strategy C+ backtest.

        Returns comprehensive results dict including:
          - Equity curve
          - Per-period metrics (CAGR, Sharpe, Sortino, Calmar, MDD)
          - IS/OOS split analysis
          - Deflated Sharpe ratio
          - Vol targeting efficiency statistics
          - Asset allocation history
          - Benchmark (SPY buy-and-hold) comparison
        """
        self.load_data()

        # Filter to backtest window
        wp = self._weekly_prices.loc[start:end].copy()
        dp = self._daily_prices.loc[start:end].copy() if self._daily_prices is not None else None
        weekly_vix = self._weekly_vix.loc[start:end] if self._weekly_vix is not None else None
        yield_curve = self._yield_curve.loc[start:end] if self._yield_curve is not None else None

        print(f"[Strategy C+] Running backtest: {start} → {end} "
              f"({len(wp)} weekly bars)")

        # ── Layer 1: Dual Momentum + Factor Tilt signals ──────────────────────
        print("[Strategy C+] Computing momentum signals...")
        signal_df = self.signals.generate_signals(wp, t1_lag=True)

        # ── Layer 2: Vol Targeting Scale ──────────────────────────────────────
        print("[Strategy C+] Computing volatility targeting...")
        es_daily = dp["SPY"] if dp is not None and "SPY" in dp.columns else None
        nq_daily = dp["QQQ"] if dp is not None and "QQQ" in dp.columns else None

        if es_daily is not None and nq_daily is not None:
            vol_df = self.vol_targeter.build_scale_series(
                es_daily, nq_daily, wp.index
            )
        else:
            vol_df = pd.DataFrame(
                {"scale": 1.0, "realized_vol": 15.0}, index=wp.index
            )

        # ── Layer 3: VIX Composite Multiplier ─────────────────────────────────
        print("[Strategy C+] Computing VIX composite...")
        if weekly_vix is not None:
            rv_weekly = vol_df["realized_vol"]
            vix_df = self.vix_composite.compute(weekly_vix, rv_weekly)
            vix_multiplier = vix_df["position_multiplier"]
        else:
            vix_multiplier = pd.Series(1.0, index=wp.index)

        # ── Layer 4: Macro Regime Multiplier ───────────────────────────────────
        print("[Strategy C+] Computing macro regime filter...")
        if self.config.use_macro_filter and yield_curve is not None:
            macro_mult = self.macro_filter.get_historical_multiplier_series(
                wp.index, yield_curve
            )
        else:
            macro_mult = pd.Series(1.0, index=wp.index)

        # ── Compute Portfolio Returns ─────────────────────────────────────────
        print("[Strategy C+] Computing portfolio returns...")
        equity_curve, allocation_log = self._compute_returns(
            wp, signal_df, vol_df["scale"],
            vix_multiplier, macro_mult, initial_capital
        )

        # ── Compute Metrics ───────────────────────────────────────────────────
        print("[Strategy C+] Computing performance metrics...")
        spy_returns = wp["SPY"].pct_change().reindex(equity_curve.index) if "SPY" in wp.columns else None
        spy_benchmark = self._benchmark_equity(spy_returns, initial_capital)

        full_metrics = self._compute_metrics(equity_curve, "FULL")
        is_mask = equity_curve.index <= pd.Timestamp(IS_END)
        oos_mask = equity_curve.index >= pd.Timestamp(OOS_START)

        is_metrics = self._compute_metrics(equity_curve[is_mask], "IS") if is_mask.sum() > 10 else {}
        oos_metrics = self._compute_metrics(equity_curve[oos_mask], "OOS") if oos_mask.sum() > 10 else {}

        # OOS retention
        oos_retention = {}
        if is_metrics and oos_metrics:
            for key in ["sharpe", "cagr"]:
                if key in is_metrics and key in oos_metrics and is_metrics[key] != 0:
                    oos_retention[f"{key}_retention_pct"] = round(
                        oos_metrics[key] / is_metrics[key] * 100, 1
                    )

        # Deflated Sharpe (multiple-testing correction for parameter grid)
        dsr_result = self._compute_deflated_sharpe(equity_curve)

        # Vol targeting stats
        vol_stats = self.vol_targeter.summary_stats(vol_df)

        # Compile results
        results = {
            "metadata": {
                "strategy": "Strategy C+",
                "version": "2.0",
                "generated_at": datetime.now().isoformat(),
                "backtest_start": start,
                "backtest_end": end,
                "n_weeks": len(wp),
                "initial_capital": initial_capital,
                "config": vars(self.config),
            },
            "equity_curve": equity_curve,
            "spy_benchmark": spy_benchmark,
            "allocation_log": allocation_log,
            "full_metrics": full_metrics,
            "is_metrics": is_metrics,
            "oos_metrics": oos_metrics,
            "oos_retention": oos_retention,
            "deflated_sharpe": dsr_result,
            "vol_stats": vol_stats,
            "vol_df": vol_df,
            "vix_multiplier": vix_multiplier,
            "macro_multiplier": macro_mult,
        }

        if save_results:
            self._save_results(results)

        self._print_summary(full_metrics, is_metrics, oos_metrics,
                            oos_retention, dsr_result, vol_stats)

        return results

    # ─────────────────────────────────────────────────────────────────────────
    # Return Computation
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_returns(
        self,
        weekly_prices: pd.DataFrame,
        signal_df: pd.DataFrame,
        vol_scale: pd.Series,
        vix_multiplier: pd.Series,
        macro_mult: pd.Series,
        initial_capital: float,
    ) -> tuple[pd.Series, pd.DataFrame]:
        """
        Compute weekly portfolio returns from layered signals.

        Each week:
          1. Look up held assets from signal_df (holdings dict)
          2. Compute asset return (this week's close / last week's close - 1)
          3. Weight by holdings (e.g., 50/50 if top-2)
          4. Multiply by combined scale: vol_scale × vix_multiplier × macro_mult
          5. Remainder fraction goes to cash (earns SHY return if available)
        """
        weekly_returns = weekly_prices.pct_change()
        shy_returns = weekly_returns.get("SHY", pd.Series(0.0, index=weekly_prices.index))

        portfolio_returns = pd.Series(0.0, index=weekly_prices.index)
        allocation_records = []

        for i, date in enumerate(weekly_prices.index):
            if i == 0:
                continue

            # Get holdings from signal (already T+1 lagged)
            row = signal_df.iloc[i] if i < len(signal_df) else None
            holdings = row["holdings"] if row is not None and isinstance(row.get("holdings"), dict) else {}

            # Compute raw asset return for this bar
            asset_ret = 0.0
            for asset, weight in holdings.items():
                if asset in weekly_returns.columns:
                    ret = weekly_returns[asset].iloc[i]
                    if not np.isnan(ret):
                        asset_ret += weight * ret

            # Combined scale factor
            vol_s = float(vol_scale.iloc[i]) if i < len(vol_scale) else 1.0
            vix_m = float(vix_multiplier.iloc[i]) if i < len(vix_multiplier) else 1.0
            macro_m = float(macro_mult.iloc[i]) if i < len(macro_mult) else 1.0
            combined_scale = vol_s * vix_m * macro_m

            # Cash fraction earns SHY rate
            cash_fraction = max(0.0, 1.0 - combined_scale)
            cash_ret = float(shy_returns.iloc[i]) if not np.isnan(shy_returns.iloc[i]) else 0.0

            # Total portfolio return
            port_ret = combined_scale * asset_ret + cash_fraction * cash_ret
            portfolio_returns.iloc[i] = port_ret

            # Allocation log
            allocation_records.append({
                "date": date,
                "holdings": str(holdings),
                "risk_regime": row.get("risk_regime", "?") if row is not None else "?",
                "vol_scale": round(vol_s, 4),
                "vix_multiplier": round(vix_m, 4),
                "macro_multiplier": round(macro_m, 4),
                "combined_scale": round(combined_scale, 4),
                "portfolio_return": round(port_ret, 6),
            })

        # Build equity curve
        equity_curve = (1 + portfolio_returns).cumprod() * initial_capital
        equity_curve.name = "Strategy_C_Plus"

        allocation_df = pd.DataFrame(allocation_records).set_index("date")
        return equity_curve, allocation_df

    def _benchmark_equity(
        self, spy_returns: Optional[pd.Series], initial_capital: float
    ) -> Optional[pd.Series]:
        """Build SPY buy-and-hold equity curve."""
        if spy_returns is None:
            return None
        spy_clean = spy_returns.fillna(0)
        equity = (1 + spy_clean).cumprod() * initial_capital
        equity.name = "SPY_Benchmark"
        return equity

    # ─────────────────────────────────────────────────────────────────────────
    # Metrics
    # ─────────────────────────────────────────────────────────────────────────

    def _compute_metrics(self, equity: pd.Series, label: str = "") -> dict:
        """Compute comprehensive performance metrics from an equity curve."""
        if len(equity) < 10:
            return {}

        returns = equity.pct_change().dropna()
        if len(returns) < 5:
            return {}

        n_years = len(returns) / 52.0
        ann_factor = np.sqrt(52)

        # CAGR
        total_return = (equity.iloc[-1] / equity.iloc[0]) - 1.0
        cagr = (1 + total_return) ** (1 / n_years) - 1.0 if n_years > 0 else 0.0

        # Volatility
        ann_vol = float(returns.std() * ann_factor)

        # Sharpe
        rf_weekly = 0.0  # Assume 0 risk-free for simplicity (SHY ~4% already captured)
        sharpe = float((returns.mean() - rf_weekly) / returns.std() * ann_factor) if returns.std() > 0 else 0.0

        # Sortino (downside deviation)
        downside = returns[returns < 0].std()
        sortino = float(returns.mean() / downside * ann_factor) if downside > 0 else 0.0

        # Maximum Drawdown (close-to-close)
        rolling_max = equity.expanding().max()
        drawdown = equity / rolling_max - 1.0
        max_dd_close = float(drawdown.min())

        # MDD wick (maximum intrabar drawdown — approximated here as close-based)
        max_dd_wick = max_dd_close  # Same for weekly, no intrabar data

        # Calmar ratio
        calmar = cagr / abs(max_dd_close) if max_dd_close != 0 else 0.0

        # Beta vs SPY (approx — uses equity curve slope)
        final_equity = float(equity.iloc[-1])
        initial_equity = float(equity.iloc[0])

        # Win rate (positive weeks)
        win_rate = float((returns > 0).mean())

        # Skew and kurtosis (for DSR)
        from scipy import stats as sp_stats
        skew_val = float(sp_stats.skew(returns.values))
        kurt_val = float(sp_stats.kurtosis(returns.values))  # excess kurtosis

        return {
            "label": label,
            "cagr": round(cagr * 100, 2),
            "ann_vol": round(ann_vol * 100, 2),
            "sharpe": round(sharpe, 4),
            "sortino": round(sortino, 4),
            "calmar": round(calmar, 4),
            "max_dd_close_pct": round(max_dd_close * 100, 2),
            "max_dd_wick_pct": round(max_dd_wick * 100, 2),
            "win_rate_pct": round(win_rate * 100, 1),
            "skew": round(skew_val, 4),
            "excess_kurtosis": round(kurt_val, 4),
            "n_weeks": len(returns),
            "n_years": round(n_years, 2),
            "final_equity": round(final_equity, 2),
            "total_return_pct": round(total_return * 100, 1),
            "final_multiple_x": round(final_equity / initial_equity, 3) if initial_equity > 0 else 0,
        }

    def _compute_deflated_sharpe(self, equity: pd.Series) -> dict:
        """
        Compute Bailey-López de Prado Deflated Sharpe Ratio.

        Accounts for the multiple testing penalty from grid search over
        vol targeting and VIX composite parameters.
        """
        try:
            from engine.backtest.deflated_sharpe import deflated_sharpe_from_returns
        except ImportError:
            try:
                # Try standalone import
                import sys
                sys.path.insert(0, str(Path(__file__).parent.parent.parent))
                from engine.backtest.deflated_sharpe import deflated_sharpe_from_returns
            except ImportError:
                return {"error": "deflated_sharpe module not available"}

        returns = equity.pct_change().dropna()
        # Approximate number of trials from a reasonable grid search:
        # vol_target: 5 values × lookback: 3 values × vix_weights: 4 combos = 60 trials
        n_trials = 60
        return deflated_sharpe_from_returns(returns.values, n_trials=n_trials, ann_factor=52.0)

    # ─────────────────────────────────────────────────────────────────────────
    # Live Signal
    # ─────────────────────────────────────────────────────────────────────────

    def get_live_signal(self) -> dict:
        """
        Generate the live signal for the current week.

        Returns a full signal dict suitable for the IBKR execution layer
        and the dashboard widget.
        """
        self.load_data()

        # Signal layer
        signal = self.signals.get_current_signal(self._weekly_prices)

        # Vol targeting
        es_daily = self._daily_prices.get("SPY") if self._daily_prices is not None else None
        nq_daily = self._daily_prices.get("QQQ") if self._daily_prices is not None else None
        if es_daily is not None and nq_daily is not None:
            vol_scale, realized_vol = self.vol_targeter.compute_scale(es_daily, nq_daily)
            vol_regime = self.vol_targeter.vol_regime(realized_vol)
        else:
            vol_scale, realized_vol, vol_regime = 1.0, 15.0, "UNKNOWN"

        # VIX composite
        if self._weekly_vix is not None and len(self._weekly_vix.dropna()) > 10:
            rv_series = None
            if es_daily is not None and nq_daily is not None:
                # Build weekly realized vol for the whole history
                vol_df = self.vol_targeter.build_scale_series(
                    es_daily, nq_daily, self._weekly_vix.index
                )
                rv_series = vol_df["realized_vol"]
            vix_signal = self.vix_composite.get_current_signal(
                self._weekly_vix.dropna(), rv_series
            )
        else:
            vix_signal = {"vix": 18.0, "vix_regime": "NORMAL", "position_multiplier": 1.0}

        # Macro filter (live FRED + CoT)
        macro_mult, macro_detail = self.macro_filter.get_live_multiplier()

        # Pre-MTF combined scale
        combined_scale = (
            vol_scale
            * vix_signal.get("position_multiplier", 1.0)
            * macro_mult
        )
        pre_mtf_scale = combined_scale

        # MTF momentum confirmation layer
        mtf_signal: dict = {
            "mtf_scale": 1.0,
            "weekly_momentum": "NEUTRAL",
            "monthly_momentum": "NEUTRAL",
            "daily_confirmation": "NEUTRAL",
            "breadth": "NEUTRAL",
            "votes_bull": 0,
            "votes_bear": 0,
            "confidence": "LOW",
            "details": {"skipped": True},
        }
        if self.config.use_mtf:
            mtf_filter = MTFFilter()
            mtf_syms = self.config.mtf_symbols or ["XLK", "QQQ", "SPY"]
            mtf_signal = mtf_filter.get_mtf_signal(mtf_syms)
            # Apply MTF multiplier and cap at 1.0
            combined_scale = min(1.0, combined_scale * mtf_signal.get("mtf_scale", 1.0))

        # Holdings after scaling (scale reduces position; remainder in SHY)
        raw_holdings = signal.get("holdings", {})
        scaled_holdings = {k: v * combined_scale for k, v in raw_holdings.items()}
        cash_weight = max(0.0, 1.0 - combined_scale)
        if cash_weight > 0.01:
            scaled_holdings["SHY"] = scaled_holdings.get("SHY", 0.0) + cash_weight

        live_signal = {
            "generated_at": datetime.now().isoformat(),
            "strategy": "Strategy_C_Plus",
            "effective_date": datetime.now().strftime("%Y-%m-%d"),
            "execution_note": "T+1 lag: execute Monday open after Friday signal",

            # Scaled final holdings
            "holdings": {k: round(v, 4) for k, v in scaled_holdings.items()},
            "combined_scale": round(combined_scale, 4),
            "pre_mtf_scale": round(pre_mtf_scale, 4),

            # Layer breakdown
            "layers": {
                "momentum_signal": {
                    "raw_holdings": raw_holdings,
                    "risk_regime": signal.get("risk_regime", "UNKNOWN"),
                    "absolute_mom_pass": signal.get("absolute_mom_pass", False),
                },
                "vol_targeting": {
                    "scale": round(vol_scale, 4),
                    "realized_vol_pct": round(realized_vol, 2),
                    "vol_target_pct": self.config.vol_target,
                    "vol_regime": vol_regime,
                },
                "vix_composite": vix_signal,
                "macro_filter": macro_detail,
                "mtf_signal": mtf_signal,
            },

            # Execution guidance for IBKR
            "ibkr_instructions": self._generate_ibkr_instructions(scaled_holdings),
        }

        return live_signal

    def _generate_ibkr_instructions(self, scaled_holdings: dict) -> dict:
        """
        Generate IBKR execution instructions from scaled holdings.

        Maps ETF holdings to executable IBKR orders.
        Respects paper trading constraint (LIVE_TRADING_ENABLED = False).
        """
        instructions = {
            "account": os.environ.get("IB_ACCOUNT_ID", ""),
            "mode": "PAPER",
            "gateway_port": 4002,
            "execution_timing": "MOO (Market On Open) — Monday morning",
            "orders": [],
            "rebalance_required": len(scaled_holdings) > 0,
        }

        for ticker, weight in scaled_holdings.items():
            if weight < 0.005:  # Skip negligible weights
                continue
            instructions["orders"].append({
                "symbol": ticker,
                "action": "BUY",
                "weight_pct": round(weight * 100, 2),
                "order_type": "MKT",
                "tif": "OPG",  # At open
                "note": f"Strategy C+ allocation: {weight:.1%}",
            })

        return instructions

    # ─────────────────────────────────────────────────────────────────────────
    # Output
    # ─────────────────────────────────────────────────────────────────────────

    def _save_results(self, results: dict) -> None:
        """Save results to JSON and CSV."""
        # Save live signal JSON
        signal_path = OUTPUT_DIR / "strategy_c_plus_live_signal.json"
        live_signal = self.get_live_signal()
        with open(signal_path, "w") as f:
            json.dump(live_signal, f, indent=2, default=str)
        print(f"[Strategy C+] Live signal → {signal_path}")

        # Save metrics JSON
        metrics_payload = {
            "full": results["full_metrics"],
            "is_period": results["is_metrics"],
            "oos_period": results["oos_metrics"],
            "oos_retention": results["oos_retention"],
            "deflated_sharpe": results["deflated_sharpe"],
            "vol_stats": results["vol_stats"],
        }
        metrics_path = OUTPUT_DIR / "strategy_c_plus_metrics.json"
        with open(metrics_path, "w") as f:
            json.dump(metrics_payload, f, indent=2, default=str)
        print(f"[Strategy C+] Metrics → {metrics_path}")

        # Save equity curve CSV
        if results["equity_curve"] is not None:
            eq_path = OUTPUT_DIR / "equity_curve.csv"
            results["equity_curve"].to_csv(eq_path, header=True)
            if results["spy_benchmark"] is not None:
                spy_path = OUTPUT_DIR / "spy_benchmark.csv"
                results["spy_benchmark"].to_csv(spy_path, header=True)

        # Save allocation log
        if results["allocation_log"] is not None:
            alloc_path = OUTPUT_DIR / "allocation_log.csv"
            results["allocation_log"].to_csv(alloc_path)
            print(f"[Strategy C+] Allocation log → {alloc_path}")

    def _print_summary(
        self,
        full: dict,
        is_m: dict,
        oos: dict,
        retention: dict,
        dsr: dict,
        vol_stats: dict,
    ) -> None:
        """Print formatted performance summary."""
        print("\n" + "=" * 70)
        print("  STRATEGY C+ PERFORMANCE SUMMARY")
        print("=" * 70)

        def fmt(d: dict, label: str) -> None:
            if not d:
                return
            print(f"\n  ── {label} ({d.get('n_years', '?'):.1f}y) ──")
            print(f"     CAGR:        {d.get('cagr', 0):>7.2f}%")
            print(f"     Sharpe:      {d.get('sharpe', 0):>7.4f}")
            print(f"     Sortino:     {d.get('sortino', 0):>7.4f}")
            print(f"     Vol:         {d.get('ann_vol', 0):>7.2f}%")
            print(f"     MDD (close): {d.get('max_dd_close_pct', 0):>7.2f}%")
            print(f"     Calmar:      {d.get('calmar', 0):>7.4f}")
            print(f"     Win Rate:    {d.get('win_rate_pct', 0):>7.1f}%")
            print(f"     Final EQ:    {d.get('final_multiple_x', 0):>7.2f}x")

        fmt(full, "FULL PERIOD")
        fmt(is_m, "IN-SAMPLE (IS)")
        fmt(oos, "OUT-OF-SAMPLE (OOS)")

        if retention:
            print("\n  ── OOS Retention ──")
            for k, v in retention.items():
                print(f"     {k}: {v:.1f}%")

        if dsr and "dsr" in dsr:
            print("\n  ── Deflated Sharpe (Bailey-LdP 2014) ──")
            print(f"     Raw Sharpe:      {dsr.get('raw_sharpe', 0):.4f}")
            print(f"     Expected Max SR: {dsr.get('expected_max_sharpe', 0):.4f} ({dsr.get('n_trials', 0)} trials)")
            print(f"     DSR p-value:     {dsr.get('dsr', 0):.4f}  "
                  f"{'✓ PASSES' if dsr.get('passes_at_10pct') else '✗ FAILS'} at 10%")

        print("\n  ── Vol Targeting Stats ──")
        print(f"     Target:          {vol_stats.get('vol_target_pct', 0):.1f}%")
        print(f"     Mean scale:      {vol_stats.get('mean_scale', 0):.4f}")
        print(f"     At max (1.0):    {vol_stats.get('pct_at_max', 0):.1f}% of weeks")
        print(f"     Mean realized:   {vol_stats.get('mean_realized_vol_pct', 0):.2f}%")

        print("=" * 70 + "\n")
