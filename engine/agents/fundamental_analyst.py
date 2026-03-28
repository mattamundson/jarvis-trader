"""
JARVIS TRADER — Fundamental Analyst Agent
==========================================
For futures instruments: fetches macro data from FRED (Fed Funds Rate,
10Y yield, VIX) and uses an LLM to assess the macro regime.
For equity symbols: optionally enriches with Finnhub company profile and
basic financials before the same LLM regime assessment.

Refresh interval: daily (macro data does not change intraday).
Model: Claude Sonnet 4.6
"""
import io
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx

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

# Futures symbols prefix map (for classification)
FUTURES_PREFIXES = {"MES", "MNQ", "MCL", "MGC", "M2K", "MYM", "ES", "NQ", "CL", "GC", "YM", "RTY", "ZB", "ZN", "SI", "HG"}


@dataclass
class FundamentalReport:
    """Structured output from the Fundamental Analyst agent"""
    symbol: str
    timestamp: datetime

    # Signal: -1.0 (risk-off, avoid longs) to +1.0 (risk-on, favor longs)
    signal: float
    confidence: float  # 0.0 to 1.0

    # Macro regime classification
    macro_regime: str  # "risk_on" | "risk_off" | "neutral"

    # Raw metrics fetched
    key_metrics: dict[str, float] = field(default_factory=dict)

    summary: str = ""
    reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "signal": self.signal,
            "confidence": self.confidence,
            "macro_regime": self.macro_regime,
            "key_metrics": self.key_metrics,
            "summary": self.summary,
            "reasoning": self.reasoning,
        }


class FundamentalistAgent:
    """
    Synthesizes macro and fundamental data into a regime-based trading signal.

    For futures: uses FRED macro data (Fed Funds Rate, 10Y yield, VIX).
    For equities: adds Finnhub company profile and basic financials when available.
    """

    FINNHUB_BASE = "https://finnhub.io/api/v1"

    SYSTEM_PROMPT = """You are a macroeconomic and fundamental analyst for JARVIS TRADER,
an autonomous trading system.

Analyze the provided macro and/or fundamental data for the given instrument.
Your task:
1. Assess the current macro regime: risk_on (equities/growth favored), risk_off (defensive/cash favored), or neutral
2. Interpret the Fed Funds Rate, 10Y yield, and VIX in context
3. For equities: consider valuation metrics, growth, and profitability
4. Produce an overall signal (-1.0 = strongly risk-off/sell, +1.0 = strongly risk-on/buy)
5. Assign a confidence score (0.0 to 1.0)

Signal guidelines:
- VIX > 30: strong risk-off pressure (-0.5 or lower)
- VIX < 15: low fear environment, supportive of risk (+0.3 or higher)
- Fed Funds Rate rising rapidly: tightening headwind (moderately bearish for growth)
- 10Y yield inverted vs fed funds (yield curve inversion): recession risk signal
- For futures: the signal reflects macro tailwind/headwind for the underlying

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

    async def analyze(self, symbol: str, is_futures: bool = True) -> "FundamentalReport":
        """Full fundamental/macro analysis pipeline for a symbol"""

        # 1. Always fetch FRED macro data
        macro_metrics = await self._fetch_fred_macro()

        # 2. For equities, optionally enrich with Finnhub fundamentals
        equity_metrics: dict[str, float] = {}
        company_name = symbol
        if not is_futures:
            equity_metrics, company_name = await self._fetch_finnhub_fundamentals(symbol)

        # 3. Merge all metrics
        key_metrics = {**macro_metrics, **equity_metrics}

        if not key_metrics:
            logger.warning(f"No fundamental data available for {symbol}")
            return self._neutral_report(symbol)

        # 4. LLM synthesis
        report = await self._llm_synthesize(symbol, company_name, key_metrics, is_futures)
        return report

    async def _fetch_fred_macro(self) -> dict[str, float]:
        """
        Fetch the most recent data point for each FRED series.
        Returns dict of metric_name -> float value.
        Uses FRED's CSV endpoint (no API key required).
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
                        logger.warning(f"FRED {series_id} returned {resp.status_code}")
                        continue

                    # Parse CSV: header row + data rows, find last non-empty value
                    text = resp.text
                    lines = [l.strip() for l in text.splitlines() if l.strip()]
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

                except Exception as e:
                    logger.warning(f"FRED fetch failed for {series_id}: {e}")

        return metrics

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

    async def _llm_synthesize(
        self,
        symbol: str,
        company_name: str,
        key_metrics: dict[str, float],
        is_futures: bool,
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
            vix_regime = "LOW FEAR" if vix_val < 15 else ("ELEVATED" if vix_val < 25 else ("HIGH FEAR" if vix_val < 35 else "EXTREME FEAR"))
            macro_block += f"- VIX (Fear Index): {vix_val:.1f} [{vix_regime}]\n"

        # Build equity section (if applicable)
        equity_block = ""
        equity_keys = [k for k in key_metrics if k not in ("fed_funds_rate", "us_10y_yield", "vix")]
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

        prompt = f"""Analyze macro and fundamental conditions for {company_name} ({symbol}) — {instrument_type}.

MACRO CONDITIONS:
{macro_block if macro_block else "No macro data available."}
{equity_block}

Respond with JSON in exactly this format:
{{
  "signal": <float -1.0 to 1.0>,
  "confidence": <float 0.0 to 1.0>,
  "macro_regime": "<risk_on|risk_off|neutral>",
  "summary": "<one sentence macro/fundamental assessment>",
  "reasoning": "<2-3 sentence analysis covering macro regime, key risks, and how this affects the instrument>"
}}"""

        try:
            anthropic_key = getattr(self._llm, "api_key", None) or os.getenv("ANTHROPIC_API_KEY", "")

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": anthropic_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-sonnet-4-6",
                        "max_tokens": 1000,
                        "system": self.SYSTEM_PROMPT,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                payload = resp.json()

            response_text = payload["content"][0]["text"].strip()

            # Strip markdown code blocks if present
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            result = json.loads(response_text)

            return FundamentalReport(
                symbol=symbol,
                timestamp=datetime.now(),
                signal=float(result.get("signal", 0.0)),
                confidence=float(result.get("confidence", 0.5)),
                macro_regime=result.get("macro_regime", "neutral"),
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
                macro_regime="neutral",
                key_metrics=key_metrics,
                summary="LLM synthesis failed",
                reasoning=f"Macro data retrieved but LLM analysis failed: {e}",
            )

    def _neutral_report(self, symbol: str) -> "FundamentalReport":
        return FundamentalReport(
            symbol=symbol,
            timestamp=datetime.now(),
            signal=0.0,
            confidence=0.1,
            macro_regime="neutral",
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
