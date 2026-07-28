"""
KAIROS — Dreaming (Nightly Consolidation)
==========================================
Summarises a day's observations into patterns and insights.
Optionally calls claude-haiku-4-5 for qualitative pattern analysis.
Works without an LLM client (returns statistical summary only).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)


class KairosDreamer:
    """
    Nightly consolidation of KAIROS observations.

    Uses the FAST_MODEL (claude-haiku-4-5-20251001 by default) for qualitative
    pattern analysis when an LLM client is available.  Gracefully degrades to a
    pure-Python statistical summary when no client is provided.
    """

    def __init__(self, llm_client=None, observation_log=None) -> None:
        self._client = llm_client
        self._log = observation_log

    # ── Public API ─────────────────────────────────────────────────────────

    async def dream(self, target_date: str = None) -> dict:
        """
        Run nightly consolidation for a given ISO date (default: today).

        Returns a dict with:
          date, total_observations, severity_counts, watcher_hits,
          top_watchers, patterns, insights, generated_at
        """
        target_date = target_date or date.today().isoformat()

        if self._log is None:
            return {"error": "No observation log available"}

        observations = self._log.read_date(target_date)
        if not observations:
            return {
                "date": target_date,
                "summary": "No observations to consolidate.",
                "patterns": [],
                "severity_counts": {"info": 0, "warning": 0, "critical": 0},
                "watcher_hits": {},
                "top_watchers": [],
                "insights": None,
                "generated_at": datetime.now().isoformat(),
            }

        counts = self._log.count_by_severity(target_date)

        watcher_hits: dict[str, int] = {}
        symbol_hits: dict[str, int] = {}
        critical_messages: list[str] = []

        for obs in observations:
            w = obs.get("watcher", "unknown")
            watcher_hits[w] = watcher_hits.get(w, 0) + 1

            sym = obs.get("symbol")
            if sym:
                symbol_hits[sym] = symbol_hits.get(sym, 0) + 1

            if obs.get("severity") == "critical":
                critical_messages.append(obs.get("message", ""))

        # {watcher, count} objects, not bare tuples — a plain Python tuple
        # serializes to a bare JSON array ([name, count]), which the
        # dashboard's Top Watchers section (expecting {watcher, count}) can't
        # consume.
        top_watchers = [
            {"watcher": name, "count": count}
            for name, count in sorted(watcher_hits.items(), key=lambda x: x[1], reverse=True)[:5]
        ]

        # Rule-based pattern detection
        patterns: list[str] = self._detect_patterns(observations, counts, watcher_hits)

        summary: dict = {
            "date": target_date,
            "total_observations": len(observations),
            "severity_counts": counts,
            "watcher_hits": watcher_hits,
            "top_watchers": top_watchers,
            "symbol_hits": symbol_hits,
            "critical_messages": critical_messages[:10],
            "patterns": patterns,
            "insights": None,
            "generated_at": datetime.now().isoformat(),
        }

        # Optional LLM insights via Haiku
        if self._client is not None and len(observations) > 0:
            summary["insights"] = await self._call_llm(observations, target_date)

        return summary

    # ── Pattern detection (no LLM) ─────────────────────────────────────────

    def _detect_patterns(
        self,
        observations: list[dict],
        counts: dict,
        watcher_hits: dict[str, int],
    ) -> list[str]:
        """Simple rule-based pattern identification from observation statistics."""
        patterns: list[str] = []

        total = len(observations)
        critical_count = counts.get("critical", 0)
        warning_count = counts.get("warning", 0)

        if critical_count > 0:
            patterns.append(
                f"High-severity day: {critical_count} CRITICAL observation(s) recorded."
            )

        if total > 0 and warning_count / total > 0.5:
            patterns.append(
                f"Warning-heavy session: {warning_count}/{total} observations were WARNING level."
            )

        # Watcher dominance
        if watcher_hits:
            top_watcher, top_count = max(watcher_hits.items(), key=lambda x: x[1])
            if top_count > total * 0.4:
                patterns.append(
                    f"Watcher '{top_watcher}' dominated with {top_count} hits "
                    f"({top_count/total*100:.0f}% of observations)."
                )

        # VIX activity
        vix_hits = watcher_hits.get("vix_spike", 0)
        if vix_hits >= 3:
            patterns.append(
                f"Elevated VIX activity: {vix_hits} spike observations — high-volatility session."
            )

        # Regime instability
        regime_hits = watcher_hits.get("regime_change", 0)
        if regime_hits >= 3:
            patterns.append(
                f"Regime instability: {regime_hits} regime changes detected — choppy conditions."
            )

        # Spread widening
        spread_hits = watcher_hits.get("spread_widening", 0)
        if spread_hits >= 2:
            patterns.append(f"Liquidity concerns: {spread_hits} spread-widening events logged.")

        # Correlation breaks
        corr_hits = watcher_hits.get("correlation_break", 0)
        if corr_hits >= 2:
            patterns.append(f"MES/MNQ correlation breakdown observed {corr_hits} time(s).")

        if not patterns:
            patterns.append("Uneventful session — no dominant patterns detected.")

        return patterns

    # ── LLM call (Haiku) ──────────────────────────────────────────────────

    async def _call_llm(self, observations: list[dict], target_date: str) -> Optional[str]:
        """Call Haiku for qualitative pattern analysis. Returns None on failure."""
        obs_text = "\n".join(
            [
                f"[{o.get('severity', 'info').upper()}] "
                f"{o.get('watcher', '')}: {o.get('message', '')}"
                for o in observations[:50]
            ]
        )
        prompt = (
            f"Analyze these market observations from {target_date} and identify "
            f"3-5 key patterns or insights for a futures day-trader:\n\n{obs_text}"
        )
        system = (
            "You are a trading pattern analyst. "
            "Identify recurring patterns in market observations. "
            "Be concise and actionable."
        )
        try:
            if hasattr(self._client, "call"):
                # JarvisLLMClient — returns LLMCallResult with .content: str
                result = await self._client.call(
                    model="claude-haiku-4-5-20251001",
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=400,
                    agent_name="kairos_dreaming",
                )
                return result.content or None

            elif hasattr(self._client, "messages"):
                # Raw anthropic.AsyncAnthropic — last-resort path
                msg = await self._client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=400,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
                return msg.content[0].text if msg.content else ""

        except Exception as exc:
            logger.error(f"KAIROS dreaming LLM call failed: {exc}")

        return None
