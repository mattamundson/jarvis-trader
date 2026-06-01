"""
JARVIS STRATEGIES — Mean Reversion V2 (Ornstein-Uhlenbeck)
==========================================================
Implements an advanced mean reversion strategy using the OU process.
Estimates theta (speed of reversion), mu (long-term mean), and sigma (volatility).
Optimal for cyclical futures like MCL (Crude Oil) and MGC (Gold).

Formula: dX_t = theta * (mu - X_t) * dt + sigma * dW_t
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import numpy as np
import pandas as pd

logger = logging.getLogger("jarvis_trader.strategies.mean_rev_ou")

class MeanReversionOU:
    """
    Advanced Mean Reversion using Ornstein-Uhlenbeck parameters.
    """

    def __init__(self, window: int = 100):
        self.window = window

    def estimate_params(self, series: pd.Series) -> Dict[str, float]:
        """
        Estimate OU parameters using OLS on discretized series.
        y_t = alpha + beta * y_{t-1} + error
        """
        if len(series) < self.window:
            return {}

        y = series.values[-self.window:]
        y_lag = y[:-1]
        y_curr = y[1:]

        # OLS
        from sklearn.linear_model import LinearRegression
        model = LinearRegression().fit(y_lag.reshape(-1, 1), y_curr)

        alpha = model.intercept_
        beta = model.coef_[0]

        # Discretized to Continuous parameters
        # beta = e^(-theta * dt), assume dt = 1
        theta = -np.log(beta) if beta > 0 else 0.001
        mu = alpha / (1 - beta) if abs(1 - beta) > 1e-6 else np.mean(y)

        # Resid
        y_pred = model.predict(y_lag.reshape(-1, 1))
        sigma_eps = np.std(y_curr - y_pred)
        sigma = sigma_eps * np.sqrt(2 * theta / (1 - beta**2)) if beta < 1 else sigma_eps

        return {
            "theta": theta,
            "mu": mu,
            "sigma": sigma,
            "half_life": np.log(2) / theta if theta > 0 else 999
        }

    def get_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Analyze current price relative to OU mean.
        """
        prices = df["close"]
        current_price = prices.iloc[-1]

        params = self.estimate_params(prices)
        if not params:
            return {"action": "hold", "confidence": 0}

        mu = params["mu"]
        sigma = params["sigma"]
        theta = params["theta"]
        half_life = params["half_life"]

        # Z-Score based on OU steady-state variance: sigma^2 / (2 * theta)
        std_dev = np.sqrt(sigma**2 / (2 * theta)) if theta > 0 else np.std(prices.values[-self.window:])
        z_score = (current_price - mu) / std_dev if std_dev > 0 else 0

        action = "hold"
        confidence = 0.0

        # Thresholds: |Z| > 2.0 (Extreme)
        if z_score > 2.0 and theta > 0.1: # theta check ensures it actually reverts
            action = "sell"
            confidence = min(0.9, (z_score - 2.0) / 2.0 + 0.5)
        elif z_score < -2.0 and theta > 0.1:
            action = "buy"
            confidence = min(0.9, (abs(z_score) - 2.0) / 2.0 + 0.5)

        return {
            "symbol": df.attrs.get("symbol", "unknown"),
            "action": action,
            "confidence": round(confidence, 2),
            "z_score": round(z_score, 2),
            "mu": round(mu, 2),
            "theta": round(theta, 4),
            "half_life": round(half_life, 1),
            "reasoning": f"Price at ${current_price:.2f} vs OU Mean ${mu:.2f} (Z={z_score:.2f}). Half-life: {half_life:.1f} bars."
        }
