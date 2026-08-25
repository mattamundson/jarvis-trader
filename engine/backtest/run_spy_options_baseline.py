#!/usr/bin/env python
"""
B6: SPY Options Baseline Validation (narrowed +/-5 strikes, 7-30 DTE)
=====================================================================
Replays SPY SMA-trend signals through a Black-Scholes synthetic options
chain to validate vertical-spread overlays with narrowed parameters.

Parameters (from roadmap B6 spec):
  - Strike width: 5 strikes (narrowed from scaffold default of 1)
  - DTE range: 7-30 days
  - Underlying: SPY (daily bars, 2015-2026 cache)
  - Strategy: debit vertical spreads on SMA trend crossover signals
  - Exit: hold to expiry, settle at intrinsic value
  - Slippage: half-spread + 5bps

Gate Verdict Criteria (gate-v2 ALT path alignment):
  - Profit Factor >= 1.2 (pf_ci_lower proxy)
  - Win Rate significance
  - Max drawdown <= 7% of capital
  - Min 30 OOS trades for statistical significance
  - DSR (deflated Sharpe) >= 0.30

Output: JSON results file + gate verdict + summary printout.
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import norm

# ── Paths ────────────────────────────────────────────────────────────────
ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

CACHE_FILE = ENGINE_ROOT / "backtest" / "cache" / "SPY_2015-01-01_2026-08-17_1d.csv"
OUTPUT_DIR = ENGINE_ROOT / "data" / "options_backtests"

# ── B6 Parameters ────────────────────────────────────────────────────────
SYMBOL = "SPY"
STRIKE_WIDTH = 5          # +/-5 strikes (narrowed per B6 spec)
DTE_MIN = 7               # min days to expiry
DTE_MAX = 30              # max days to expiry
TARGET_DELTA = 0.30       # 30-delta long leg
CONTRACTS_PER_SIGNAL = 1  # 1 spread per signal
SLIPPAGE_BPS = 5.0        # 5 bps additional drag
CAPITAL = 50_000.0        # account capital for DD calc

# SMA trend params (SPY gate-v2 PASS champion: fast=10, slow=40, atr=2.0)
FAST_SMA = 10
SLOW_SMA = 40
ATR_TRAIL_MULT = 2.0
ATR_PERIOD = 14

# Gate thresholds
GATE_PF_FLOOR = 1.2
GATE_DSR_FLOOR = 0.30
GATE_MC_DD_CEILING = 7.0  # percent
GATE_MIN_TRADES = 30


# ══════════════════════════════════════════════════════════════════════════
# Black-Scholes synthetic chain builder
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class SynthContract:
    """Lightweight options contract for synthetic pricing."""
    strike: float
    expiry: date
    option_type: str  # "call" or "put"
    bid: float
    ask: float
    mid: float
    delta: float
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    iv: float = 0.0
    volume: int = 0
    oi: int = 0
    in_the_money: bool = False
    last_price: float = 0.0

    @property
    def spread(self) -> float:
        return round(self.ask - self.bid, 4)


def _bs_d1(s: float, k: float, t: float, sigma: float, r: float) -> float:
    if t <= 0 or sigma <= 0:
        return 0.0
    return (math.log(s / k) + (r + 0.5 * sigma ** 2) * t) / (sigma * math.sqrt(t))


def _bs_d2(d1: float, sigma: float, t: float) -> float:
    if t <= 0 or sigma <= 0:
        return 0.0
    return d1 - sigma * math.sqrt(t)


def bs_price(s: float, k: float, t: float, sigma: float, r: float, opt_type: str) -> float:
    """Black-Scholes option price."""
    if t <= 0:
        if opt_type == "call":
            return max(0.0, s - k)
        return max(0.0, k - s)
    if sigma <= 0:
        if opt_type == "call":
            return max(0.0, s - k * math.exp(-r * t))
        return max(0.0, k * math.exp(-r * t) - s)
    d1 = _bs_d1(s, k, t, sigma, r)
    d2 = _bs_d2(d1, sigma, t)
    if opt_type == "call":
        return s * norm.cdf(d1) - k * math.exp(-r * t) * norm.cdf(d2)
    else:
        return k * math.exp(-r * t) * norm.cdf(-d2) - s * norm.cdf(-d1)


def bs_delta(s: float, k: float, t: float, sigma: float, r: float, opt_type: str) -> float:
    if t <= 0 or sigma <= 0:
        return 0.0
    d1 = _bs_d1(s, k, t, sigma, r)
    if opt_type == "call":
        return norm.cdf(d1)
    return -norm.cdf(-d1)


def bs_gamma(s: float, k: float, t: float, sigma: float, r: float) -> float:
    if t <= 0 or sigma <= 0:
        return 0.0
    d1 = _bs_d1(s, k, t, sigma, r)
    return norm.pdf(d1) / (s * sigma * math.sqrt(t))


def bs_theta(s: float, k: float, t: float, sigma: float, r: float, opt_type: str) -> float:
    if t <= 0 or sigma <= 0:
        return 0.0
    d1 = _bs_d1(s, k, t, sigma, r)
    d2 = _bs_d2(d1, sigma, t)
    common = -(s * norm.pdf(d1) * sigma) / (2 * math.sqrt(t))
    if opt_type == "call":
        return common - r * k * math.exp(-r * t) * norm.cdf(d2)
    return common + r * k * math.exp(-r * t) * norm.cdf(-d2)


def bs_vega(s: float, k: float, t: float, sigma: float, r: float) -> float:
    if t <= 0 or sigma <= 0:
        return 0.0
    d1 = _bs_d1(s, k, t, sigma, r)
    return s * norm.pdf(d1) * math.sqrt(t)
