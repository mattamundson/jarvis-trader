"""
T9 — Commentary Generator Module
=================================
Imported by main.py, serves GET /api/commentary

Reads the live Strategy C+ signal, fetches market data via yfinance,
and returns a structured commentary dict for the JARVIS dashboard.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
SIGNAL_PATH = Path(
    "/home/user/workspace/jarvis-trader/jarvis-trader/engine/strategy_c/"
    "output/strategy_c_plus_live_signal.json"
)

# ── Optional imports (yfinance may not be installed in all environments) ───────
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    yf = None
    YFINANCE_AVAILABLE = False
    logger.warning("yfinance not installed — market data will use defaults")


# ── Signal reader ───────────────────────────────────────────────────────────────
def _read_live_signal() -> dict:
    """Read the latest Strategy C+ live signal from disk."""
    try:
        with SIGNAL_PATH.open() as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("Signal file not found at %s — using defaults", SIGNAL_PATH)
        return {}
    except json.JSONDecodeError as e:
        logger.error("Failed to parse signal JSON: %s", e)
        return {}


# ── Market data fetch ───────────────────────────────────────────────────────────
def _fetch_market_data() -> dict:
    """
    Fetch current VIX, 10Y yield, ES and NQ futures from yfinance.
    Returns a dict with keys: vix, yield_10y, es_price, es_change_pct,
    nq_price, nq_change_pct.
    Falls back to recent-known values if yfinance is unavailable.
    """
    defaults = {
        "vix": 18.92,
        "yield_10y": 4.699,
        "es_price": 5432.0,
        "es_change_pct": 0.94,
        "nq_price": 19_345.0,
        "nq_change_pct": 0.67,
    }

    if not YFINANCE_AVAILABLE:
        return defaults

    result = dict(defaults)
    tickers = {
        "^VIX":  "vix",
        "^TNX":  "yield_10y",   # 10-Year Treasury yield ×10 = actual %
        "ES=F":  "es",
        "NQ=F":  "nq",
    }

    for symbol, key in tickers.items():
        try:
            t = yf.Ticker(symbol)
            hist = t.history(period="2d", interval="1d")
            if hist.empty:
                continue

            close = float(hist["Close"].iloc[-1])
            prev  = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else close
            pct   = ((close - prev) / prev * 100) if prev != 0 else 0.0

            if key == "vix":
                result["vix"] = round(close, 2)
            elif key == "yield_10y":
                # ^TNX is quoted as ×10 (e.g. 47.0 = 4.70%)
                result["yield_10y"] = round(close / 10, 3)
            elif key == "es":
                result["es_price"]      = round(close, 2)
                result["es_change_pct"] = round(pct, 2)
            elif key == "nq":
                result["nq_price"]      = round(close, 2)
                result["nq_change_pct"] = round(pct, 2)
        except Exception as e:
            logger.warning("Could not fetch %s: %s", symbol, e)

    return result


# ── Brief formatter ─────────────────────────────────────────────────────────────
def _format_brief(
    signal: dict,
    mkt: dict,
    regime: str,
    scale: float,
    holdings: dict,
    risk_flags: list[str],
) -> str:
    """Build the JARVIS morning-brief formatted string."""
    now = datetime.now()
    ts_label = now.strftime("%-I:%M %p CDT").upper()
    date_label = now.strftime("%b %d, %Y").upper()

    vix = mkt.get("vix", 18.92)
    y10 = mkt.get("yield_10y", 4.699)
    es_price = mkt.get("es_price", 5432.0)
    es_pct   = mkt.get("es_change_pct", 0.94)
    nq_pct   = mkt.get("nq_change_pct", 0.67)

    # CoT data from signal if available
    cot_es  = signal.get("cot_es_net",  -115762)
    cot_nq  = signal.get("cot_nq_net",   10821)
    cot_es_sig = _cot_signal(cot_es)
    cot_nq_sig = _cot_signal(cot_nq)

    # Yield curve spread from signal (basis points → %)
    yc_spread = signal.get("yield_curve_spread", 0.699)
    yc_mult   = signal.get("macro_scale", 1.10)

    scale_pct = scale * 100
    xlk = holdings.get("XLK", 0.305) * 100
    qqq = holdings.get("QQQ", 0.305) * 100
    shy = holdings.get("SHY", 0.391) * 100

    risk_block = "\n".join(f"  • {f}" for f in risk_flags) if risk_flags else "  None identified."

    # Regime narrative
    if regime == "RISK_ON":
        regime_narrative = "Current market conditions are favorable for risk-on positioning."
    elif regime == "RISK_OFF":
        regime_narrative = (
            "Market conditions have shifted defensive — reducing equity exposure. "
            "Regime is RISK_OFF; SHY allocation elevated."
        )
    else:
        regime_narrative = (
            "Regime is in TRANSITION — mixed signals detected. Reducing scale "
            "conservatively until confirmation."
        )

    # VIX narrative
    if vix < 15:
        vix_narrative = f"VIX at {vix:.2f} — volatility suppressed, complacency risk noted."
    elif vix < 20:
        vix_narrative = (
            f"VIX at {vix:.2f} — volatility is compressing, which historically "
            "precedes continuation moves in equity markets."
        )
    elif vix < 25:
        vix_narrative = (
            f"VIX elevated at {vix:.2f} — approaching caution threshold. "
            "Scale reduced proportionally."
        )
    else:
        vix_narrative = (
            f"VIX SPIKE detected at {vix:.2f} — regime defense triggered. "
            "Defensive reallocation in progress."
        )

    brief = (
        f"JARVIS MORNING BRIEF — {date_label} — {ts_label}\n\n"
        f"Good morning. {regime_narrative}\n\n"
        f"The {vix_narrative} "
        f"The yield curve spread of +{yc_spread:.3f}% remains a macro tailwind, "
        f"applying a {yc_mult:.2f}× scale multiplier to Strategy C+.\n\n"
        f"ES futures are trading at {es_price:,.0f} ({'+' if es_pct >= 0 else ''}{es_pct:.2f}%) "
        f"with CoT positioning {cot_es_sig} at {cot_es:,} net contracts. "
        f"NQ futures show {'institutional accumulation' if cot_nq > 0 else 'net selling'} "
        f"({cot_nq:+,} net {'long' if cot_nq > 0 else 'short'}).\n\n"
        f"Strategy C+ current allocation: XLK {xlk:.1f}%, QQQ {qqq:.1f}%, "
        f"SHY {shy:.1f}% (defensive buffer). "
        f"Combined scale {scale_pct:.1f}% reflects "
        f"{'moderate' if 40 < scale_pct < 80 else 'strong' if scale_pct >= 80 else 'conservative'} "
        f"conviction — {'below' if scale_pct < 80 else 'at or above'} full deployment threshold of 80%. "
        f"Recommend maintaining current paper allocation through Monday MOO execution.\n\n"
        f"Risk factors:\n{risk_block}\n"
        f"Next signal refresh: Friday 16:05 CDT."
    )

    return brief


def _cot_signal(net: int) -> str:
    """Convert net CoT position to label."""
    if abs(net) < 20_000:
        return "NEUTRAL"
    return "BULLISH" if net > 0 else "BEARISH"


# ── Confidence scorer ───────────────────────────────────────────────────────────
def _compute_confidence(vix: float, scale: float, regime: str) -> float:
    """
    Heuristic confidence score [0.0, 1.0]:
    - Higher scale → higher confidence
    - Lower VIX → higher confidence
    - RISK_ON → slight boost; RISK_OFF → slight penalty
    """
    base = scale  # start with scale (0-1)

    # VIX adjustment: 0 at VIX=30, +0.2 at VIX=10
    vix_adj = max(-0.2, min(0.2, (20 - vix) / 50))
    base += vix_adj

    # Regime adjustment
    if regime == "RISK_ON":
        base += 0.05
    elif regime == "RISK_OFF":
        base -= 0.05

    return round(min(max(base, 0.0), 1.0), 3)


# ── Risk flag extractor ─────────────────────────────────────────────────────────
def _extract_risk_flags(signal: dict, mkt: dict, vix: float) -> list[str]:
    """Extract notable risk flags from signal + market data."""
    flags = []

    # VIX thresholds
    if vix > 25:
        flags.append(f"VIX SPIKE: {vix:.2f} — regime defense may trigger")
    elif vix > 20:
        flags.append(f"VIX elevated at {vix:.2f} — approaching caution zone (threshold 25)")

    # SPY options — pulled from signal if available
    expiring_opts = signal.get("expiring_options", [])
    for opt in expiring_opts:
        flags.append(f"Option expiry: {opt}")

    # Static flag if signal doesn't have options data
    if not expiring_opts:
        flags.append("SPY options expire this week — review 715C and 700P positions")

    # Scale below threshold
    scale = signal.get("combined_scale", 0.609)
    if scale < 0.4:
        flags.append(f"Scale below 40% ({scale:.1%}) — risk-off conditions elevated")

    return flags


# ── Public API ──────────────────────────────────────────────────────────────────
def generate_commentary() -> dict:
    """
    Main entry point — called by main.py to serve GET /api/commentary.

    Returns:
        {
            "timestamp": str,           # ISO-8601
            "regime": str,              # RISK_ON | RISK_OFF | TRANSITIONING
            "vix": float,
            "yield_10y": float,
            "es_price": float,
            "es_change_pct": float,
            "scale": float,             # combined_scale [0,1]
            "holdings": {               # target allocation fractions
                "XLK": float,
                "QQQ": float,
                "SHY": float,
            },
            "brief": str,               # formatted JARVIS brief text
            "risk_flags": list[str],
            "confidence": float,        # [0,1]
            "next_signal": str,
            "engine": str,
        }
    """
    # 1. Read signal
    signal = _read_live_signal()

    # 2. Extract core signal fields (with fallbacks)
    regime = signal.get("regime", "RISK_ON")
    scale  = float(signal.get("combined_scale", 0.609))
    holdings = {
        "XLK": float(signal.get("weight_XLK", signal.get("holdings", {}).get("XLK", 0.305))),
        "QQQ": float(signal.get("weight_QQQ", signal.get("holdings", {}).get("QQQ", 0.305))),
        "SHY": float(signal.get("weight_SHY", signal.get("holdings", {}).get("SHY", 0.391))),
    }

    # 3. Fetch live market data
    mkt = _fetch_market_data()
    vix = mkt["vix"]

    # 4. Build risk flags
    risk_flags = _extract_risk_flags(signal, mkt, vix)

    # 5. Format brief
    brief = _format_brief(signal, mkt, regime, scale, holdings, risk_flags)

    # 6. Confidence score
    confidence = _compute_confidence(vix, scale, regime)

    return {
        "timestamp":      datetime.now(timezone.utc).isoformat(),
        "regime":         regime,
        "vix":            vix,
        "yield_10y":      mkt.get("yield_10y", 4.699),
        "es_price":       mkt.get("es_price", 5432.0),
        "es_change_pct":  mkt.get("es_change_pct", 0.94),
        "nq_price":       mkt.get("nq_price", 19_345.0),
        "nq_change_pct":  mkt.get("nq_change_pct", 0.67),
        "scale":          scale,
        "holdings":       holdings,
        "brief":          brief,
        "risk_flags":     risk_flags,
        "confidence":     confidence,
        "next_signal":    signal.get("next_signal", "Friday 16:05 CDT"),
        "engine":         "Strategy C+ Engine v3.0",
    }
