"""
JARVIS TRADER — Fundamental Analyst Agent
==========================================
For futures instruments: fetches macro data from FRED (Fed Funds Rate,
10Y yield, VIX) and uses an LLM to assess the macro regime.
For equity symbols: optionally enriches with Finnhub company profile and
basic financials before the same LLM regime assessment.

Refresh interval: daily (macro data does not change intraday).
Model: Claude Sonnet 4.6

Macro regime classification (deterministic, pre-LLM):
  RISK_ON  — VIX < 20, yield curve normal (≥ 0)
  NEUTRAL  — VIX 20–25, or mixed signals
  RISK_OFF — VIX > 25, or yield curve inverted (< 0)
  CRISIS   — VIX > 35

Symbol-class weighting:
  Equity index futures (MES, MNQ, ES, NQ, YM, RTY, M2K, MYM):
    Primary: VIX + yield curve spread
  Energy futures (MCL, CL):
    Primary: supply/demand proxy (Fed tightening pace), dollar strength signal
  Metals (MGC, GC, SI, HG):
    Primary: real yields (10Y - CPI proxy), dollar strength
  Bonds (ZB, ZN):
    Primary: Fed Funds trajectory, yield curve shape
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime

import httpx

try:
    from data.cot_fetcher import CoTFetcher as _CoTFetcher
    _COT_AVAILABLE = True
except ImportError:
    _CoTFetcher = None  # type: ignore[assignment,misc]
    _COT_AVAILABLE = False

try:
    from data.sector_rotation import SectorRotationMonitor as _SectorRotationMonitor
    _SECTOR_AVAILABLE = True
except ImportError:
    _SectorRotationMonitor = None  # type: ignore[assignment,misc]
    _SECTOR_AVAILABLE = False

try:
    import anthropic as _anthropic_sdk

    _ANTHROPIC_SDK_AVAILABLE = True
except ImportError:
    _anthropic_sdk = None  # type: ignore[assignment]
    _ANTHROPIC_SDK_AVAILABLE = False

from utils.llm_json import parse_llm_json

logger = logging.getLogger(__name__)

__all__ = ["FundamentalistAgent", "FundamentalReport"]

# FRED base URL for CSV series download — no API key required for basic data
FRED_CSV_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# FRED series IDs
FRED_SERIES = {
    "fed_funds_rate": "FEDFUNDS",
    "us_10y_yield": "DGS10",
    "vix": "VIXCLS",
}

# Fallback defaults used when FRED is unavailable (rate-limited, maintenance, no network).
# Values reflect approximate current-cycle levels; update quarterly if needed.
FRED_DEFAULTS: dict[str, float] = {
    "fed_funds_rate": 4.33,  # Fed Funds rate as of Q1 2026
    "us_10y_yield": 4.30,  # 10-Year Treasury yield as of Q1 2026
    "vix": 20.0,  # Neutral VIX assumption when data unavailable
}

# ---------------------------------------------------------------------------
# Macro regime thresholds (calibrated for April 2026 market environment)
# ---------------------------------------------------------------------------
# VIX buckets — tuned for futures trading regimes
VIX_RISK_ON_MAX = 20.0      # VIX < 20 → RISK_ON (low fear, trend-friendly)
VIX_NEUTRAL_MAX = 25.0      # VIX 20–25 → NEUTRAL
VIX_RISK_OFF_MAX = 35.0     # VIX 25–35 → RISK_OFF (elevated volatility)
VIX_CRISIS_MIN = 35.0       # VIX ≥ 35 → CRISIS (panic regime)

# Yield curve spread (10Y minus Fed Funds) — inversion is recession signal
YIELD_CURVE_INVERSION_THRESHOLD = 0.0   # spread < 0 → inverted → headwind
YIELD_CURVE_STEEP_THRESHOLD = 0.5       # spread ≥ 0.5 → healthy steepener → tailwind

# Fed Funds thresholds for late-cycle / easing inflection signals
FED_FUNDS_LATE_CYCLE = 5.0   # > 5.0% → clearly restrictive (was 5.5% peak in 2023)
FED_FUNDS_NEUTRAL = 3.5      # < 3.5% → accommodative / neutral

# 10Y yield thresholds — compression above 4.5% hurts equity multiples
YIELD_10Y_COMPRESSION = 4.5  # > 4.5% → yield compression risk for equities
YIELD_10Y_FAVORABLE = 4.0    # < 4.0% → accommodative for equity index futures

# Unemployment thresholds for labor market signal
UNEMPLOYMENT_STRONG = 4.5   # < 4.5% → strong labor market (growth-supportive)
UNEMPLOYMENT_WEAK = 5.5     # > 5.5% → weakening labor market (defensive signal)

# ---------------------------------------------------------------------------
# Symbol class routing — maps root symbols to asset class for prompt weighting
# ---------------------------------------------------------------------------
EQUITY_INDEX_FUTURES = {"MES", "MNQ", "ES", "NQ", "YM", "RTY", "M2K", "MYM"}
ENERGY_FUTURES = {"MCL", "CL"}
METALS_FUTURES = {"MGC", "GC", "SI", "HG"}
BOND_FUTURES = {"ZB", "ZN"}

# Futures symbols prefix map (for classification)
FUTURES_PREFIXES = {
    "MES",
    "MNQ",
    "MCL",
    "MGC",
    "M2K",
    "MYM",
    "ES",
    "NQ",
    "CL",
    "GC",
    "YM",
    "RTY",
    "ZB",
    "ZN",
    "SI",
    "HG",
}


@dataclass
class FundamentalReport:
    """Structured output from the Fundamental Analyst agent"""

    symbol: str
    timestamp: datetime

    # Signal: -1.0 (risk-off, avoid longs) to +1.0 (risk-on, favor longs)
    signal: float
    confidence: float  # 0.0 to 1.0

    # Macro regime classification — 4-tier
    # "RISK_ON" | "NEUTRAL" | "RISK_OFF" | "CRISIS"
    macro_regime: str

    # True if macro environment supports taking a trend trade right now.
    # Computed deterministically from raw metrics (not from LLM) so it is
    # consistent and fast even when LLM synthesis is skipped.
    macro_tailwind: bool = True

    # Raw metrics fetched
    key_metrics: dict[str, float] = field(default_factory=dict)

    summary: str = ""
    reasoning: str = ""

    # Silent-default guard: when the keyless FRED CSV fetch fails (network /
    # rate-limit / maintenance), _fetch_fred_macro substitutes hardcoded
    # FRED_DEFAULTS so analysis is never blocked — but that means the macro
    # regime is computed from stale constants, not live data. These flags make
    # that visible in the decision trace instead of degrading silently.
    macro_data_is_default: bool = False
    macro_defaulted_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "signal": self.signal,
            "confidence": self.confidence,
            "macro_regime": self.macro_regime,
            "macro_tailwind": self.macro_tailwind,
            "key_metrics": self.key_metrics,
            "summary": self.summary,
            "reasoning": self.reasoning,
            "macro_data_is_default": self.macro_data_is_default,
            "macro_defaulted_keys": self.macro_defaulted_keys,
        }


class FundamentalistAgent:
    """
    Synthesizes macro and fundamental data into a regime-based trading signal.

    For futures: uses FRED macro data (Fed Funds Rate, 10Y yield, VIX).
    For equities: adds Finnhub company profile and basic financials when available.
    """

    FINNHUB_BASE = "https://finnhub.io/api/v1"

    SYSTEM_PROMPT = """You are a macroeconomic and fundamental analyst for JARVIS TRADER,
an autonomous futures trading system.

Analyze the provided macro and/or fundamental data for the given instrument.
Your task:
1. Assess the current macro regime using the 4-tier classification:
   - RISK_ON:  VIX < 20 and yield curve normal (spread ≥ 0) — trend trades favored
   - NEUTRAL:  VIX 20–25 or mixed signals — selective trend exposure
   - RISK_OFF: VIX > 25 or yield curve inverted (spread < 0) — defensive posture
   - CRISIS:   VIX > 35 — avoid directional exposure entirely
2. Interpret the Fed Funds Rate, 10Y yield, and VIX in context
3. For equities: consider valuation metrics, growth, and profitability
4. Produce an overall signal (-1.0 = strongly risk-off/sell, +1.0 = strongly risk-on/buy)
5. Assign a confidence score (0.0 to 1.0)

UPDATED signal guidelines (calibrated April 2026, Fed Funds ~4.33%, 10Y ~4.3%):
- VIX > 35: CRISIS — strong risk-off pressure (-0.6 or lower)
- VIX 25–35: RISK_OFF — elevated fear (-0.2 to -0.5)
- VIX 20–25: NEUTRAL — mixed (-0.1 to +0.1)
- VIX < 20: supportive of trend exposure (+0.2 or higher)
- VIX < 15: very low fear, strong risk-on (+0.4 or higher)
- Fed Funds > 5.0%: clearly restrictive, late-cycle headwind for growth
- Fed Funds 3.5–5.0%: mildly restrictive / neutral
- 10Y yield > 4.5%: multiple compression risk for equity index futures
- Yield curve inverted (10Y < Fed Funds): recession signal — moderately bearish
- Yield curve spread ≥ 0.5%: healthy steepener — growth-supportive

INSTRUMENT-SPECIFIC WEIGHTING:
- MES / MNQ / ES / NQ / YM (equity index futures):
  Primary factors: VIX level, yield curve spread, 10Y vs 4.5% compression threshold.
  VIX < 20 + normal curve → tailwind. VIX > 25 or inverted curve → headwind.
- MCL / CL (crude oil futures):
  Primary factors: dollar strength signal (Fed trajectory), global growth proxy.
  Rising Fed Funds + strong dollar → headwind for oil (demand destruction).
  Falling Fed Funds + weak dollar → tailwind for oil (reflation).
  Secondary: VIX as risk-appetite proxy (VIX > 30 → demand destruction fear).
- MGC / GC / SI / HG (metals futures):
  Primary factors: real yield (10Y yield - inflation proxy), dollar direction.
  Rising real yields → headwind for gold/metals. Falling real yields → tailwind.
  CRISIS regime (VIX > 35) → gold specifically benefits as safe haven.
- ZB / ZN (bond futures):
  Primary factors: Fed Funds trajectory, inflation expectations.
  Falling rates → tailwind for bond futures. Rising rates → headwind.

For futures: the signal reflects macro tailwind/headwind for the underlying contract.
For equities: also consider valuation metrics, growth, and profitability.

Respond with valid JSON only. Do not add any explanation outside the JSON.
"""

    def __init__(self, llm_client, data_manager=None):
        """
        Args:
            llm_client: Object with .api_key attribute (Anthropic key) and
                        optionally .finnhub_key for equity fundamental data.
            data_manager: Optional data manager (unused for fundamentals but
                          accepted for interface consistency).
        """
        self._llm = llm_client
        self._data = data_manager
        # Populated by _fetch_fred_macro: FRED series that fell back to hardcoded
        # FRED_DEFAULTS this cycle. Empty when all series fetched live.
        self._macro_defaulted_keys: list[str] = []

    @staticmethod
    def classify_macro_regime(metrics: dict[str, float]) -> tuple[str, bool]:
        """
        Deterministic macro regime classification from raw metrics.

        Returns (macro_regime, macro_tailwind):
          macro_regime: "RISK_ON" | "NEUTRAL" | "RISK_OFF" | "CRISIS"
          macro_tailwind: True if macro supports taking trend trades

        Logic (in priority order):
          1. CRISIS if VIX ≥ VIX_CRISIS_MIN (35)
          2. RISK_OFF if VIX > VIX_NEUTRAL_MAX (25)  OR yield curve inverted
          3. RISK_ON if VIX < VIX_RISK_ON_MAX (20) AND yield curve not inverted
          4. NEUTRAL otherwise (VIX 20-25, mixed signals)

        macro_tailwind is True only in RISK_ON or NEUTRAL.
        RISK_OFF and CRISIS are headwinds for directional trend trades.
        """
        vix = metrics.get("vix", FRED_DEFAULTS["vix"])
        fed_funds = metrics.get("fed_funds_rate", FRED_DEFAULTS["fed_funds_rate"])
        yield_10y = metrics.get("us_10y_yield", FRED_DEFAULTS["us_10y_yield"])
        spread = yield_10y - fed_funds  # positive = normal, negative = inverted

        if vix >= VIX_CRISIS_MIN:
            return "CRISIS", False

        if vix > VIX_NEUTRAL_MAX or spread < YIELD_CURVE_INVERSION_THRESHOLD:
            return "RISK_OFF", False

        if vix < VIX_RISK_ON_MAX and spread >= YIELD_CURVE_INVERSION_THRESHOLD:
            return "RISK_ON", True

        # VIX 20-25, curve not inverted — neutral / mixed signals
        return "NEUTRAL", True

    async def analyze(self, symbol: str, is_futures: bool = True) -> "FundamentalReport":
        """Full fundamental/macro analysis pipeline for a symbol"""

        # 1. Always fetch FRED macro data (direct FRED pull)
        macro_metrics = await self._fetch_fred_macro()

        # 2. Enrich with JARVIS engine macro snapshot (cached, includes unemployment)
        engine_macro = await self._fetch_engine_macro_snapshot()

        # Merge engine macro — fills gaps left by FRED (e.g. unemployment) and
        # uses the engine's cached + processed values as a cross-check.
        for key, value in engine_macro.items():
            if key not in macro_metrics and value is not None:
                macro_metrics[key] = value

        # 3. For equities, optionally enrich with Finnhub fundamentals
        equity_metrics: dict[str, float] = {}
        company_name = symbol
        if not is_futures:
            equity_metrics, company_name = await self._fetch_finnhub_fundamentals(symbol)

        # 4. Merge all metrics
        key_metrics = {**macro_metrics, **equity_metrics}

        if not key_metrics:
            logger.warning(f"No fundamental data available for {symbol}")
            return self._neutral_report(symbol)

        # 5. Deterministic regime + tailwind classification (fast, no LLM cost)
        macro_regime, macro_tailwind = self.classify_macro_regime(key_metrics)
        logger.debug(
            f"{symbol} deterministic regime: {macro_regime}, tailwind={macro_tailwind} "
            f"(VIX={key_metrics.get('vix', 'n/a')}, "
            f"spread={(key_metrics.get('us_10y_yield', 0) - key_metrics.get('fed_funds_rate', 0)):.2f})"
        )

        # 6. CoT positioning (optional — CFTC weekly data, graceful fallback)
        cot_data = None
        cot_bias = 0.0
        if _COT_AVAILABLE:
            try:
                _cot = _CoTFetcher()
                cot_data = _cot.get_positioning(symbol)
                cot_bias = _cot.get_bias_adjustment(symbol)
            except Exception as e:
                logger.debug("CoT fetch failed for %s: %s", symbol, e)

        # 7. Sector rotation context (optional — requires market_data_manager)
        sector_ctx = None
        if _SECTOR_AVAILABLE and self._data is not None:
            try:
                _sector = _SectorRotationMonitor(self._data)
                sector_ctx = _sector.get_sector_context(symbol)
            except Exception as e:
                logger.debug("Sector rotation failed for %s: %s", symbol, e)

        # 8. LLM synthesis — passes symbol for instrument-specific prompt weighting
        report = await self._llm_synthesize(
            symbol, company_name, key_metrics, is_futures,
            deterministic_regime=macro_regime,
            deterministic_tailwind=macro_tailwind,
            cot_data=cot_data,
            cot_bias=cot_bias,
            sector_ctx=sector_ctx,
        )
        # Surface FRED silent-default fallback in the decision trace. When the
        # keyless CSV fetch failed for one or more series this cycle, the macro
        # regime was computed partly from hardcoded constants — flag it so the
        # aggregator / dashboard can down-weight or annotate rather than treating
        # stale defaults as live macro data.
        defaulted = list(self._macro_defaulted_keys)
        if defaulted:
            report.macro_data_is_default = True
            report.macro_defaulted_keys = defaulted
            logger.warning(
                "%s fundamental report computed with %d defaulted FRED series: %s "
                "(macro regime partly from hardcoded FRED_DEFAULTS, not live data)",
                symbol, len(defaulted), defaulted,
            )
        return report

    async def _fetch_fred_macro(self) -> dict[str, float]:
        """
        Fetch the most recent data point for each FRED series.
        Returns dict of metric_name -> float value.
        Uses FRED's CSV endpoint (no API key required).

        If a series fetch fails (network error, rate-limit, maintenance), falls back
        to the hardcoded FRED_DEFAULTS so downstream analysis is never blocked.
        """
        metrics: dict[str, float] = {}

        async with httpx.AsyncClient(timeout=15.0) as client:
            for metric_name, series_id in FRED_SERIES.items():
                try:
                    resp = await client.get(
                        FRED_CSV_BASE,
                        params={"id": series_id},
                    )
                    if resp.status_code != 200:
                        logger.warning(
                            f"FRED {series_id} returned HTTP {resp.status_code} — "
                            f"will use default fallback for '{metric_name}'"
                        )
                        continue

                    # Parse CSV: header row + data rows, find last non-empty value
                    text = resp.text
                    lines = [line.strip() for line in text.splitlines() if line.strip()]
                    # Lines format: "DATE,VALUE"
                    last_value = None
                    for line in reversed(lines[1:]):  # skip header
                        parts = line.split(",")
                        if len(parts) == 2 and parts[1] not in (".", ""):
                            try:
                                last_value = float(parts[1])
                                break
                            except ValueError:
                                continue

                    if last_value is not None:
                        metrics[metric_name] = last_value
                        logger.debug(f"FRED {series_id}: {last_value}")
                    else:
                        logger.warning(
                            f"FRED {series_id} CSV contained no parseable value — "
                            f"will use default fallback for '{metric_name}'"
                        )

                except Exception as e:
                    logger.warning(
                        f"FRED fetch failed for {series_id} ({metric_name}): {e} — "
                        f"will use default fallback"
                    )

        # Apply defaults for any series that failed to fetch so analysis is never blocked.
        missing = [k for k in FRED_SERIES if k not in metrics]
        # Record which series fell back to hardcoded constants so the report can
        # flag that the macro regime is computed from stale defaults, not live data.
        self._macro_defaulted_keys = list(missing)
        if missing:
            for key in missing:
                default_val = FRED_DEFAULTS.get(key)
                if default_val is not None:
                    metrics[key] = default_val
                    logger.warning(
                        f"FRED '{key}' unavailable — using hardcoded default {default_val} "
                        f"(update FRED_DEFAULTS quarterly)"
                    )

        return metrics

    async def _fetch_engine_macro_snapshot(self) -> dict[str, float]:
        """
        Fetch JARVIS engine's processed macro snapshot from /macro/snapshot.
        This endpoint uses a 5-minute in-memory cache and returns a flat dict:
        {"vix": float, "fed_funds_rate": float, "ten_year_yield": float, "unemployment": float}.

        Supplements FRED direct fetches with additional fields (e.g. unemployment)
        and uses the engine's cached/validated values. Never blocks the pipeline.
        """
        try:
            _api_key = os.environ.get("API_KEY", "")
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "http://localhost:8010/macro/snapshot",
                    headers={"x-api-key": _api_key},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    metrics: dict[str, float] = {}
                    # Map engine field names to our internal metric names
                    field_map = {
                        "vix": "vix",
                        "fed_funds_rate": "fed_funds_rate",
                        "ten_year_yield": "us_10y_yield",
                        "unemployment": "unemployment",
                    }
                    for engine_key, metric_key in field_map.items():
                        val = data.get(engine_key)
                        if val is not None:
                            try:
                                metrics[metric_key] = float(val)
                            except (TypeError, ValueError):
                                pass
                    logger.debug(f"Engine macro snapshot fetched: {metrics}")
                    return metrics
                logger.debug(f"Engine macro snapshot returned {resp.status_code}")
        except Exception as e:
            logger.debug(f"Engine macro snapshot fetch failed: {e}")
        return {}

    async def _fetch_finnhub_fundamentals(self, symbol: str) -> tuple[dict[str, float], str]:
        """
        Fetch Finnhub company profile and basic financials for equity symbols.
        Returns (metrics_dict, company_name).
        """
        metrics: dict[str, float] = {}
        company_name = symbol

        finnhub_key = getattr(self._llm, "finnhub_key", None) or os.getenv("FINNHUB_API_KEY", "")
        if not finnhub_key:
            logger.debug("No Finnhub key — skipping equity fundamentals")
            return metrics, company_name

        async with httpx.AsyncClient(timeout=15.0) as client:
            # Company profile
            try:
                resp = await client.get(
                    f"{self.FINNHUB_BASE}/stock/profile2",
                    params={"symbol": symbol, "token": finnhub_key},
                )
                if resp.status_code == 200:
                    profile = resp.json()
                    company_name = profile.get("name", symbol)
                    mktcap = profile.get("marketCapitalization")
                    if mktcap:
                        metrics["market_cap_million"] = float(mktcap)
            except Exception as e:
                logger.debug(f"Finnhub profile fetch failed for {symbol}: {e}")

            # Basic financials
            try:
                resp = await client.get(
                    f"{self.FINNHUB_BASE}/stock/metric",
                    params={"symbol": symbol, "metric": "all", "token": finnhub_key},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    fin = data.get("metric", {})
                    # Extract key valuation/growth metrics (map None → skip)
                    mapping = {
                        "pe_ratio": "peNormalizedAnnual",
                        "pb_ratio": "pbAnnual",
                        "ps_ratio": "psAnnual",
                        "revenue_growth_yoy": "revenueGrowthTTMYoy",
                        "eps_growth_yoy": "epsGrowthTTMYoy",
                        "gross_margin": "grossMarginAnnual",
                        "roe": "roeTTM",
                        "debt_equity": "totalDebt/totalEquityAnnual",
                        "52w_high": "52WeekHigh",
                        "52w_low": "52WeekLow",
                        "beta": "beta",
                        "dividend_yield": "dividendYieldIndicatedAnnual",
                    }
                    for metric_key, finnhub_key_name in mapping.items():
                        val = fin.get(finnhub_key_name)
                        if val is not None:
                            try:
                                metrics[metric_key] = float(val)
                            except (TypeError, ValueError):
                                pass
            except Exception as e:
                logger.debug(f"Finnhub metrics fetch failed for {symbol}: {e}")

        return metrics, company_name

    @staticmethod
    def _symbol_class_hint(symbol: str) -> str:
        """Return an instrument-class context string for injection into the LLM prompt."""
        root = symbol.upper().rstrip("0123456789").rstrip("FGHJKMNQUVXZ")
        sym_upper = symbol.upper()

        if root in EQUITY_INDEX_FUTURES or sym_upper in EQUITY_INDEX_FUTURES:
            return (
                "INSTRUMENT CLASS: Equity index futures (MES/MNQ/ES/NQ family).\n"
                "Weight VIX and yield curve spread most heavily.\n"
                "VIX < 20 + normal yield curve = macro tailwind.\n"
                "VIX > 25 or inverted curve = macro headwind for longs.\n"
                "10Y yield > 4.5% creates multiple compression risk — moderate headwind."
            )
        if root in ENERGY_FUTURES or sym_upper in ENERGY_FUTURES:
            return (
                "INSTRUMENT CLASS: Crude oil futures (MCL/CL family).\n"
                "Weight Fed policy trajectory and dollar strength most heavily.\n"
                "Rising Fed Funds + strong dollar → demand destruction risk → headwind.\n"
                "Falling/pausing Fed + weak dollar → reflation → tailwind.\n"
                "VIX > 30 signals demand-destruction fear — bearish for oil price.\n"
                "Geopolitical and supply-side factors are additive to this macro base."
            )
        if root in METALS_FUTURES or sym_upper in METALS_FUTURES:
            return (
                "INSTRUMENT CLASS: Metals futures (MGC/GC/SI/HG family).\n"
                "Weight real yields (nominal 10Y minus inflation) and dollar direction.\n"
                "Rising real yields → headwind for gold/silver. Falling real yields → tailwind.\n"
                "CRISIS regime (VIX > 35) → gold specifically benefits as safe haven.\n"
                "Copper (HG) follows global growth more than gold — weigh PMI/growth signals."
            )
        if root in BOND_FUTURES or sym_upper in BOND_FUTURES:
            return (
                "INSTRUMENT CLASS: Bond futures (ZB/ZN family).\n"
                "Weight Fed Funds trajectory and inflation expectations most heavily.\n"
                "Fed cutting rates → tailwind for bond futures (prices rise).\n"
                "Fed holding/hiking → headwind. Curve steepening → mixed."
            )
        # Default — generic futures or equity
        return (
            "INSTRUMENT CLASS: Generic futures or equity.\n"
            "Use standard macro framework: VIX, yield curve, and Fed trajectory."
        )

    async def _llm_synthesize(
        self,
        symbol: str,
        company_name: str,
        key_metrics: dict[str, float],
        is_futures: bool,
        deterministic_regime: str = "NEUTRAL",
        deterministic_tailwind: bool = True,
        cot_data: "dict | None" = None,
        cot_bias: float = 0.0,
        sector_ctx: "dict | None" = None,
    ) -> "FundamentalReport":
        """Use LLM to synthesize macro/fundamental data into a structured regime signal"""

        instrument_type = "futures" if is_futures else "equity"

        # Build macro section
        macro_block = ""
        if "fed_funds_rate" in key_metrics:
            macro_block += f"- Fed Funds Rate: {key_metrics['fed_funds_rate']:.2f}%\n"
        if "us_10y_yield" in key_metrics:
            macro_block += f"- US 10Y Treasury Yield: {key_metrics['us_10y_yield']:.2f}%\n"
            if "fed_funds_rate" in key_metrics:
                spread = key_metrics["us_10y_yield"] - key_metrics["fed_funds_rate"]
                macro_block += f"- Yield Curve Spread (10Y - FF): {spread:.2f}% ({'INVERTED' if spread < 0 else 'normal'})\n"
        if "vix" in key_metrics:
            vix_val = key_metrics["vix"]
            vix_regime = (
                "LOW FEAR"
                if vix_val < 15
                else (
                    "ELEVATED"
                    if vix_val < 25
                    else ("HIGH FEAR" if vix_val < 35 else "EXTREME FEAR")
                )
            )
            macro_block += f"- VIX (Fear Index): {vix_val:.1f} [{vix_regime}]\n"
        if "unemployment" in key_metrics:
            macro_block += f"- Unemployment Rate: {key_metrics['unemployment']:.1f}%\n"

        # Build equity section (if applicable)
        _MACRO_KEYS = {"fed_funds_rate", "us_10y_yield", "vix", "unemployment"}
        equity_block = ""
        equity_keys = [k for k in key_metrics if k not in _MACRO_KEYS]
        if equity_keys and not is_futures:
            equity_block = "\nEQUITY FUNDAMENTALS:\n"
            label_map = {
                "market_cap_million": "Market Cap ($M)",
                "pe_ratio": "P/E Ratio",
                "pb_ratio": "P/B Ratio",
                "ps_ratio": "P/S Ratio",
                "revenue_growth_yoy": "Revenue Growth YoY (%)",
                "eps_growth_yoy": "EPS Growth YoY (%)",
                "gross_margin": "Gross Margin (%)",
                "roe": "Return on Equity (%)",
                "debt_equity": "Debt/Equity",
                "52w_high": "52-Week High",
                "52w_low": "52-Week Low",
                "beta": "Beta",
                "dividend_yield": "Dividend Yield (%)",
            }
            for k in equity_keys:
                label = label_map.get(k, k)
                equity_block += f"- {label}: {key_metrics[k]:.2f}\n"

        symbol_hint = self._symbol_class_hint(symbol)

        # Build CoT block (optional)
        cot_block = ""
        if cot_data:
            cot_block = (
                f"\nCFTC Commitment of Traders (latest weekly):\n"
                f"- Commercial net position: {cot_data['commercial_net']:,} ({cot_data['commercial_trend']})\n"
                f"- Large speculator net: {cot_data['large_spec_net']:,}\n"
                f"- CoT bias adjustment: {cot_bias:+.1f}\n"
            )

        # Build sector rotation block (optional)
        sector_block = ""
        if sector_ctx and sector_ctx.get("sector_momentum") != "NEUTRAL" or (
            sector_ctx and sector_ctx.get("description", "").startswith("Sector data unavailable") is False
            and sector_ctx.get("bias_adjustment", 0.0) != 0.0
        ):
            sector_block = (
                f"\nSector Rotation Context:\n"
                f"{sector_ctx['description']}\n"
                f"Bias adjustment: {sector_ctx['bias_adjustment']:+.2f} "
                f"(outperforming = +, underperforming = -)\n"
            )

        prompt = f"""Analyze macro and fundamental conditions for {company_name} ({symbol}) — {instrument_type}.

{symbol_hint}

DETERMINISTIC PRE-CLASSIFICATION (computed from raw data before this call):
  macro_regime: {deterministic_regime}
  macro_tailwind: {deterministic_tailwind}
Use these as a strong prior — override only if fundamental/LLM analysis provides compelling evidence.

MACRO CONDITIONS:
{macro_block if macro_block else "No macro data available."}
{equity_block}{cot_block}{sector_block}
Respond with JSON in exactly this format:
{{
  "signal": <float -1.0 to 1.0>,
  "confidence": <float 0.0 to 1.0>,
  "macro_regime": "<RISK_ON|NEUTRAL|RISK_OFF|CRISIS>",
  "macro_tailwind": <true|false>,
  "summary": "<one sentence macro/fundamental assessment>",
  "reasoning": "<2-3 sentence analysis covering macro regime, key risks, and how this affects the instrument>"
}}"""

        try:
            if not hasattr(self._llm, "call"):
                raise RuntimeError("LLM client does not expose call(); cannot synthesize fundamentals locally")

            model = getattr(self._llm, "default_model", os.getenv("OLLAMA_MODEL", "hermes3:latest"))
            # 2026-08-17: raised from min(256, OLLAMA_NUM_PREDICT) — the 5-field
            # JSON (with multi-sentence summary+reasoning) truncates at 256
            # tokens, causing "no JSON object found" on every analyst call.
            # Match the 1600 budget used by technical_analyst (PR #712).
            max_tokens = min(1600, int(os.getenv("OLLAMA_NUM_PREDICT", "1600")))
            result_obj = await self._llm.call(
                model=model,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                agent_name="fundamental_analyst",
                temperature=0.2,
                allow_fallback=False,
            )
            if not getattr(result_obj, "success", False):
                raise RuntimeError(getattr(result_obj, "error", "local LLM call failed"))
            response_text = getattr(result_obj, "content", "").strip()

            # Tolerant extraction: markdown fences, leading/trailing prose, and
            # trailing commas now recover instead of failing to a zero-signal
            # report (see utils.llm_json — 2026-06-04 synthesis-failure wave).
            result = parse_llm_json(response_text)

            # Normalise regime to uppercase; fall back to deterministic value if LLM
            # returns something unrecognised.
            _valid_regimes = {"RISK_ON", "NEUTRAL", "RISK_OFF", "CRISIS"}
            llm_regime_raw = str(result.get("macro_regime", "")).upper()
            # Accept legacy lowercase variants from older prompts
            _legacy_map = {
                "RISK_ON": "RISK_ON",
                "RISK-ON": "RISK_ON",
                "RISK_OFF": "RISK_OFF",
                "RISK-OFF": "RISK_OFF",
                "NEUTRAL": "NEUTRAL",
                "CRISIS": "CRISIS",
            }
            llm_regime = _legacy_map.get(llm_regime_raw, llm_regime_raw)
            if llm_regime not in _valid_regimes:
                logger.warning(
                    f"LLM returned unrecognised macro_regime '{llm_regime_raw}' for {symbol}"
                    f" — using deterministic fallback '{deterministic_regime}'"
                )
                llm_regime = deterministic_regime

            # LLM can override macro_tailwind; fall back to deterministic if absent/invalid
            llm_tailwind_raw = result.get("macro_tailwind", None)
            if isinstance(llm_tailwind_raw, bool):
                llm_tailwind = llm_tailwind_raw
            else:
                llm_tailwind = deterministic_tailwind

            # Apply sector bias adjustment — clamp to ±1.0
            raw_signal = float(result.get("signal", 0.0))
            sector_bias = sector_ctx.get("bias_adjustment", 0.0) if sector_ctx else 0.0
            adjusted_signal = max(-1.0, min(1.0, raw_signal + sector_bias))
            if sector_bias != 0.0:
                logger.debug(
                    f"{symbol} sector bias {sector_bias:+.2f} applied: "
                    f"signal {raw_signal:.2f} → {adjusted_signal:.2f}"
                )

            return FundamentalReport(
                symbol=symbol,
                timestamp=datetime.now(),
                signal=adjusted_signal,
                confidence=float(result.get("confidence", 0.5)),
                macro_regime=llm_regime,
                macro_tailwind=llm_tailwind,
                key_metrics=key_metrics,
                summary=result.get("summary", ""),
                reasoning=result.get("reasoning", ""),
            )

        except Exception as e:
            logger.error(f"LLM fundamental synthesis failed for {symbol}: {e}")
            return FundamentalReport(
                symbol=symbol,
                timestamp=datetime.now(),
                signal=0.0,
                confidence=0.2,
                macro_regime=deterministic_regime,
                macro_tailwind=deterministic_tailwind,
                key_metrics=key_metrics,
                summary="LLM synthesis failed — deterministic regime used",
                reasoning=f"Macro data retrieved but LLM analysis failed: {e}",
            )

    def _neutral_report(self, symbol: str) -> "FundamentalReport":
        return FundamentalReport(
            symbol=symbol,
            timestamp=datetime.now(),
            signal=0.0,
            confidence=0.1,
            macro_regime="NEUTRAL",
            macro_tailwind=True,  # conservative: don't block trades on missing data
            key_metrics={},
            summary="No fundamental data available",
            reasoning="Could not retrieve macro or fundamental data — returning neutral signal",
        )

    @staticmethod
    def is_futures_symbol(symbol: str) -> bool:
        """
        Convenience helper: returns True if the symbol looks like a futures contract.
        Checks against known micro/standard futures prefixes.
        """
        root = symbol.upper().rstrip("0123456789").rstrip("FGHJKMNQUVXZ")
        return root in FUTURES_PREFIXES or symbol.upper() in FUTURES_PREFIXES
