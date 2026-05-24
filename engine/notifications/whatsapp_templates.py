"""
WhatsApp message templates for JARVIS TRADER signal alerts.

Pure formatting helpers — no I/O, no API calls. Used by the scanner/pipeline
alert path in `main.py` to turn a pipeline result into a rich, human-readable
WhatsApp message with full context: regime, debate scores, TV bridge data,
IB levels, and risk status.

Kept under 1600 characters to fit within a single WhatsApp segment.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

MAX_WHATSAPP_CHARS = 1600


def _fmt(val: Optional[float], precision: int = 2) -> str:
    """Format a float with fallback for None/NaN."""
    if val is None:
        return "—"
    try:
        f = float(val)
    except (TypeError, ValueError):
        return "—"
    if f != f:  # NaN
        return "—"
    return f"{f:,.{precision}f}"


def _fmt_int(val: Optional[float]) -> str:
    if val is None:
        return "—"
    try:
        return f"{int(float(val))}"
    except (TypeError, ValueError):
        return "—"


class SignalAlertTemplate:
    """
    Rich Stage 5 WhatsApp signal alert with full context.

    All parameters are positional/keyword with safe defaults so callers can
    pass whatever subset of fields they have. Missing sections are omitted
    gracefully (e.g., no TV bridge section if tv_snapshot is None).
    """

    @staticmethod
    def render(
        *,
        symbol: str,
        direction: str,
        entry: float,
        stop: float,
        target_1: float,
        target_2: Optional[float] = None,
        rr_ratio: Optional[float] = None,
        conviction: Optional[float] = None,
        regime: Optional[str] = None,
        bull_score: Optional[float] = None,
        bear_score: Optional[float] = None,
        tv_snapshot: Optional[Dict[str, Any]] = None,
        ib_levels: Optional[Dict[str, Any]] = None,
        kill_switch_active: bool = False,
        daily_pnl_pct: Optional[float] = None,
        source: str = "pipeline",
    ) -> str:
        """Return a formatted multi-line WhatsApp message under 1600 chars."""
        lines: list[str] = []

        # ── Header ────────────────────────────────────────────────────────
        prefix = "🚨 " if kill_switch_active else "🎯 "
        header = f"{prefix}JARVIS SIGNAL — {symbol.upper()} {direction.upper()}"
        lines.append(header)

        # ── Entry / Stop / Target ─────────────────────────────────────────
        entry_line = f"Entry: {_fmt(entry)} | Stop: {_fmt(stop)} | T1: {_fmt(target_1)}"
        if target_2 is not None:
            entry_line += f" | T2: {_fmt(target_2)}"
        lines.append(entry_line)

        # ── R:R / Conviction ──────────────────────────────────────────────
        meta_parts: list[str] = []
        if rr_ratio is not None:
            meta_parts.append(f"R:R: {_fmt(rr_ratio, 2)}:1")
        if conviction is not None:
            meta_parts.append(f"Conviction: {_fmt(conviction, 1)}/10")
        if meta_parts:
            lines.append(" | ".join(meta_parts))

        lines.append("")  # blank separator

        # ── Regime / Debate ───────────────────────────────────────────────
        if regime:
            lines.append(f"📊 REGIME: {regime}")
        if bull_score is not None and bear_score is not None:
            net = bull_score - bear_score
            sign = "+" if net >= 0 else ""
            lines.append(
                f"Debate: Bull {_fmt(bull_score, 1)} / Bear {_fmt(bear_score, 1)} (net {sign}{_fmt(net, 1)})"
            )
        if regime or (bull_score is not None and bear_score is not None):
            lines.append("")

        # ── TV Bridge ─────────────────────────────────────────────────────
        if tv_snapshot:
            quality = tv_snapshot.get("data_quality", "live")
            if quality == "unavailable":
                lines.append("🔭 TV BRIDGE: offline")
            else:
                lines.append(f"🔭 TV BRIDGE ({quality})")
                stc_v = tv_snapshot.get("stc_value")
                stc_s = tv_snapshot.get("stc_state")
                if stc_v is not None:
                    stc_str = _fmt(stc_v, 1)
                    if stc_s:
                        stc_str += f" ({stc_s.lower()})"
                    comp = tv_snapshot.get("composite_score")
                    comp_str = ""
                    if comp is not None:
                        sign = "+" if comp >= 0 else ""
                        comp_str = f" | Composite: {sign}{_fmt(comp, 2)}"
                    lines.append(f"STC: {stc_str}{comp_str}")
                atr = tv_snapshot.get("atr_value")
                if atr is not None or (ib_levels and ib_levels.get("ib_high") is not None):
                    parts = []
                    if atr is not None:
                        parts.append(f"ATR: {_fmt(atr, 2)}")
                    if ib_levels and ib_levels.get("ib_high") is not None:
                        parts.append(
                            f"IB: {_fmt(ib_levels.get('ib_high'))} / {_fmt(ib_levels.get('ib_low'))}"
                        )
                    if parts:
                        lines.append(" | ".join(parts))
                corey = tv_snapshot.get("corey_score")
                corey_b = tv_snapshot.get("corey_bias")
                phase = tv_snapshot.get("phase_oscillator")
                parts = []
                if corey is not None:
                    sign = "+" if corey >= 0 else ""
                    bias_str = f" ({corey_b})" if corey_b else ""
                    parts.append(f"Corey: {sign}{_fmt(corey, 2)}{bias_str}")
                if phase is not None:
                    parts.append(f"Phase: {_fmt(phase, 1)}")
                if parts:
                    lines.append(" | ".join(parts))
            lines.append("")
        else:
            lines.append("🔭 TV BRIDGE: offline")
            lines.append("")

        # ── Risk status ───────────────────────────────────────────────────
        risk_parts = []
        if daily_pnl_pct is not None:
            sign = "+" if daily_pnl_pct >= 0 else ""
            status = "OK" if abs(daily_pnl_pct) < 1.5 else ("WARN" if abs(daily_pnl_pct) < 2 else "HALT")
            risk_parts.append(f"Daily P&L: {sign}{_fmt(daily_pnl_pct, 1)}% ({status})")
        if kill_switch_active:
            risk_parts.append("Kill switch: ACTIVE ❌")
        else:
            risk_parts.append("Kill switch: OFF")
        if risk_parts:
            lines.append("⚖️ RISK")
            lines.append(" | ".join(risk_parts))

        msg = "\n".join(lines).rstrip()

        # Phase 4.1: Interactive instructions
        if not kill_switch_active:
            msg += "\n\nReply *Y* to approve, *N* to reject."

        # Hard cap at WhatsApp limit
        if len(msg) > MAX_WHATSAPP_CHARS:
            msg = msg[: MAX_WHATSAPP_CHARS - 4] + "…"

        return msg

    @staticmethod
    def render_from_pipeline_result(
        *,
        symbol: str,
        pipeline_result: Dict[str, Any],
        tv_snapshot: Optional[Dict[str, Any]] = None,
        ib_levels: Optional[Dict[str, Any]] = None,
        kill_switch_active: bool = False,
        daily_pnl_pct: Optional[float] = None,
    ) -> str:
        """
        Convenience wrapper that extracts the common fields from a full
        pipeline result dict. Keeps main.py calling code tiny.
        """
        trade = pipeline_result.get("trade_decision") or {}
        fund = pipeline_result.get("fund_decision") or {}
        debate = pipeline_result.get("debate_result") or {}
        analyst = pipeline_result.get("analyst_reports") or {}
        tech = analyst.get("technical") or {}
        indicators = tech.get("indicators") or {}

        # Derive entry / stop / target from trade decision
        entry = trade.get("limit_price") or trade.get("stop_price") or trade.get("entry_price") or 0.0
        stop = trade.get("stop_loss") or trade.get("stop_price") or 0.0
        target_1 = trade.get("target_1") or trade.get("take_profit") or 0.0
        target_2 = trade.get("target_2")
        try:
            rr = abs(target_1 - entry) / abs(entry - stop) if stop and entry else None
        except (TypeError, ZeroDivisionError):
            rr = None

        conviction = fund.get("final_conviction") or trade.get("confidence")
        if conviction is not None:
            try:
                conviction = float(conviction) * 10.0 if float(conviction) <= 1.0 else float(conviction)
            except (TypeError, ValueError):
                conviction = None

        regime = indicators.get("regime") or indicators.get("tv_regime")
        bull_score = debate.get("bull_score")
        bear_score = debate.get("bear_score")
        action = pipeline_result.get("final_action", trade.get("action", "HOLD"))

        # Prefer the TV bridge data from indicators if not explicitly passed
        if tv_snapshot is None and indicators.get("tv_data_quality") == "live":
            tv_snapshot = {
                "data_quality": "live",
                "stc_value": indicators.get("tv_stc"),
                "stc_state": indicators.get("tv_stc_state"),
                "composite_score": indicators.get("tv_composite"),
                "atr_value": indicators.get("tv_atr"),
                "corey_score": indicators.get("tv_corey_score"),
                "phase_oscillator": indicators.get("tv_phase"),
            }
        if ib_levels is None:
            ib_levels = {
                "ib_high": indicators.get("tv_ib_high"),
                "ib_low": indicators.get("tv_ib_low"),
            }

        return SignalAlertTemplate.render(
            symbol=symbol,
            direction=str(action).upper(),
            entry=float(entry or 0.0),
            stop=float(stop or 0.0),
            target_1=float(target_1 or 0.0),
            target_2=float(target_2) if target_2 else None,
            rr_ratio=rr,
            conviction=conviction,
            regime=regime,
            bull_score=bull_score,
            bear_score=bear_score,
            tv_snapshot=tv_snapshot,
            ib_levels=ib_levels,
            kill_switch_active=kill_switch_active,
            daily_pnl_pct=daily_pnl_pct,
        )
