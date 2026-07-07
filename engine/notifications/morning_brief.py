"""
JARVIS Morning Intelligence Brief — assembled at 8:45 CT daily.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    from utils.position_sizing import INSTRUMENT_MULTIPLIERS as INSTRUMENT_POINT_VALUES
except ImportError:
    from engine.utils.position_sizing import INSTRUMENT_MULTIPLIERS as INSTRUMENT_POINT_VALUES

logger = logging.getLogger(__name__)

_CT = ZoneInfo("America/Chicago")

# Module-level globals — injected via inject_morning_brief_deps()
_data_manager = None
_paper_tracker = None
_safety_layer = None


def inject_morning_brief_deps(dm, pt, sl) -> None:
    """Inject dependencies from main.py lifespan."""
    global _data_manager, _paper_tracker, _safety_layer
    _data_manager = dm
    _paper_tracker = pt
    _safety_layer = sl


def _compute_unrealized(position: dict, current_price: float | None) -> float | None:
    """Compute unrealized P&L for a single position."""
    if current_price is None:
        return None
    try:
        entry_price = float(position.get("entry_price", 0) or 0)
        quantity = float(position.get("quantity", 1) or 1)
        symbol = str(position.get("symbol", "")).upper()
        action = str(position.get("action", "") or position.get("side", "") or "").lower()
        point_value = INSTRUMENT_POINT_VALUES.get(symbol, 1.0)
        is_long = action in ("buy", "buy_to_open", "long", "buy_to_close")
        if is_long:
            return (current_price - entry_price) * point_value * quantity
        else:
            return (entry_price - current_price) * point_value * quantity
    except Exception:
        return None


async def assemble_morning_brief(
    data_manager=None,
    paper_tracker=None,
    safety_layer=None,
) -> str:
    """Assemble the morning intelligence brief. Never raises — returns fallback on error."""
    dm = data_manager or _data_manager
    pt = paper_tracker or _paper_tracker
    sl = safety_layer or _safety_layer

    try:
        now_ct = datetime.now(_CT)
        ts = now_ct.strftime("%m/%d %H:%M CT")

        # Fetch MCL and MNQ prices concurrently
        prices: dict[str, float | None] = {"MCL": None, "MNQ": None}
        if dm is not None:
            try:
                results = await asyncio.gather(
                    dm.get_current_price("MCL"),
                    dm.get_current_price("MNQ"),
                    return_exceptions=True,
                )

                def _extract_price(r) -> float | None:
                    if isinstance(r, Exception) or r is None:
                        return None
                    if isinstance(r, dict):
                        return (
                            float(
                                r.get("last_price")
                                or r.get("close")
                                or r.get("price")
                                or r.get("last")
                                or 0
                            )
                            or None
                        )
                    return float(r)

                prices["MCL"] = _extract_price(results[0])
                prices["MNQ"] = _extract_price(results[1])
            except Exception as exc:
                logger.warning("[MorningBrief] Price fetch failed: %s", exc)

        # Fetch STC and regime for each symbol
        def _fmt_price(sym: str) -> str:
            px = prices.get(sym)
            return f"${px:.2f}" if px is not None else "N/A"

        async def _get_stc_regime(sym: str) -> tuple[str, str]:
            if dm is None:
                return "N/A", "UNKNOWN"
            try:
                df = await dm.get_bars(sym, lookback_days=3, timeframe="1h")
                if df is None or df.empty:
                    return "N/A", "UNKNOWN"
                from backtest.signals import generate_signals

                df_sig = generate_signals(df, symbol=sym)
                row = df_sig.iloc[-1]
                stc = row.get("stc_val", None)
                regime = str(row.get("regime", "UNKNOWN"))
                stc_str = f"{float(stc):.1f}" if stc is not None else "N/A"
                return stc_str, regime
            except Exception as exc:
                logger.debug("[MorningBrief] STC fetch failed for %s: %s", sym, exc)
                return "N/A", "UNKNOWN"

        # Adaptive Volatility Trend — report-only. Compact per-symbol read of the
        # AVT gated signal + 0-100 score; never drives any decision here.
        async def _get_avt(sym: str) -> str:
            if dm is None:
                return "N/A"
            try:
                df = await dm.get_bars(sym, lookback_days=10, timeframe="1h")
                if df is None or df.empty:
                    return "N/A"
                from analytics.adaptive_volatility_trend import (
                    AVTParams,
                    generate_avt_signals,
                )

                row = generate_avt_signals(df, AVTParams()).iloc[-1]
                sig, score = int(row["avt_signal"]), float(row["avt_score"])
                if sig == 1:
                    return f"long {score:.0f}"
                if sig == -1:
                    return f"short {score:.0f}"
                return "flat"
            except Exception as exc:
                logger.debug("[MorningBrief] AVT fetch failed for %s: %s", sym, exc)
                return "N/A"

        stc_mcl, regime_mcl = await _get_stc_regime("MCL")
        stc_mnq, regime_mnq = await _get_stc_regime("MNQ")
        avt_mcl = await _get_avt("MCL")
        avt_mnq = await _get_avt("MNQ")
        avt_mes = await _get_avt("MES")
        avt_mgc = await _get_avt("MGC")

        # Trading plan based on STC position
        def _trading_plan(sym: str, stc_str: str, regime: str) -> str:
            try:
                stc_val = float(stc_str)
                if stc_val >= 83:
                    return f"STC {stc_val:.0f} (AT/ABOVE OB=83) — SHORT setup active"
                elif stc_val <= 15:
                    return f"STC {stc_val:.0f} (AT/BELOW OS=15) — LONG setup active"
                elif stc_val > 70:
                    return f"STC {stc_val:.0f} — approaching OB=83, watch for SHORT"
                elif stc_val < 25:
                    return f"STC {stc_val:.0f} — approaching OS=15, watch for LONG"
                else:
                    return f"STC {stc_val:.0f} — mid-range, scanner will HOLD"
            except (TypeError, ValueError):
                return f"STC N/A — {regime}"

        plan_mcl = _trading_plan("MCL", stc_mcl, regime_mcl)
        plan_mnq = _trading_plan("MNQ", stc_mnq, regime_mnq)

        # Open positions with unrealized P&L
        open_positions: list[dict] = []
        if pt is not None:
            try:
                open_positions = pt.get_open_positions()
            except Exception as exc:
                logger.warning("[MorningBrief] get_open_positions failed: %s", exc)

        # Recently closed trades (since midnight CT)
        closed_today: list[dict] = []
        if pt is not None:
            try:
                midnight_ct = now_ct.replace(hour=0, minute=0, second=0, microsecond=0)
                all_closed = pt.get_closed_trades() if hasattr(pt, "get_closed_trades") else []
                for t in all_closed:
                    closed_str = t.get("exit_time") or t.get("closed_at") or ""
                    if closed_str and closed_str >= midnight_ct.isoformat()[:10]:
                        closed_today.append(t)
            except Exception as exc:
                logger.debug("[MorningBrief] closed trades fetch failed: %s", exc)

        # Fetch current prices for open positions
        pos_price_map: dict[str, float | None] = {}
        if dm is not None and open_positions:
            syms = list({p.get("symbol", "") for p in open_positions if p.get("symbol")})
            try:
                pos_results = await asyncio.gather(
                    *[dm.get_current_price(s) for s in syms],
                    return_exceptions=True,
                )
                for sym, res in zip(syms, pos_results, strict=True):
                    pos_price_map[sym] = (
                        float(res) if not isinstance(res, Exception) and res is not None else None
                    )
            except Exception:
                pass

        # Safety status
        daily_pnl: float | None = None
        kill_active = False
        if sl is not None:
            try:
                status = sl.get_status()
                daily_pnl = status.get("daily_pnl")
                kill_active = bool(status.get("kill_switch_active", False))
            except Exception:
                pass

        # Assemble message
        lines = [
            f"JARVIS Pre-Market Intelligence — {ts}",
            "",
            "INSTRUMENTS",
            f"  MCL: {_fmt_price('MCL')} | STC: {stc_mcl} | {regime_mcl} | AVT: {avt_mcl}",
            f"  MNQ: {_fmt_price('MNQ')} | STC: {stc_mnq} | {regime_mnq} | AVT: {avt_mnq}",
            f"  MES: AVT {avt_mes} | MGC: AVT {avt_mgc}  (active — report-only)",
            "",
            "TRADING PLAN",
            f"  MCL: {plan_mcl}",
            f"  MNQ: {plan_mnq}",
            "",
        ]

        # Overnight activity
        n_closed = len(closed_today)
        n_pos = len(open_positions)
        if n_closed > 0 or n_pos > 0:
            lines.append("OVERNIGHT ACTIVITY")
            for t in closed_today:
                sym = str(t.get("symbol", "?")).upper()
                side = str(t.get("side") or t.get("action", "")).upper()
                pnl = t.get("pnl")
                pnl_str = f"${pnl:+.2f}" if pnl is not None else "?"
                lines.append(f"  CLOSED: {sym} {side} → {pnl_str}")
            for pos in open_positions:
                sym = str(pos.get("symbol", "?")).upper()
                action = str(pos.get("action", "") or pos.get("side", "")).upper()
                qty = int(pos.get("quantity", 1) or 1)
                entry = float(pos.get("entry_price", 0) or 0)
                cur = pos_price_map.get(sym)
                unr = _compute_unrealized(pos, cur)
                unr_str = f"${unr:+.2f}" if unr is not None else "open"
                lines.append(
                    f"  OPEN: {sym} {action} x{qty} @ ${entry:.2f} | unrealized: {unr_str}"
                )
            lines.append("")

        pnl_str = f"${daily_pnl:+.2f}" if daily_pnl is not None else "N/A"
        kill_str = "ACTIVE — TRADING HALTED" if kill_active else "inactive"
        lines += [
            "SAFETY",
            f"  Daily P&L: {pnl_str} | Kill switch: {kill_str}",
            "",
            "Scanner active: MCL + MNQ | Next RTH scan: 9:30am CT",
        ]

        msg = "\n".join(lines)
        if len(msg) > 400:
            # Truncate positions detail to keep under 400 chars
            short_lines = [
                f"JARVIS Pre-Market Intelligence — {ts}",
                "",
                "INSTRUMENTS",
                f"  MCL: {_fmt_price('MCL')} | STC: {stc_mcl} | {regime_mcl} | AVT: {avt_mcl}",
                f"  MNQ: {_fmt_price('MNQ')} | STC: {stc_mnq} | {regime_mnq} | AVT: {avt_mnq}",
                f"  MES: AVT {avt_mes} | MGC: AVT {avt_mgc}  (active — report-only)",
                "",
                "TRADING PLAN",
                f"  MCL: {plan_mcl}",
                f"  MNQ: {plan_mnq}",
                "",
                "SAFETY",
                f"  Daily P&L: {pnl_str} | Kill switch: {kill_str}",
                "",
                "Scanner active: MCL + MNQ | Next RTH scan: 9:30am CT",
            ]
            msg = "\n".join(short_lines)
        return msg

    except Exception as exc:
        logger.error("[MorningBrief] Assembly failed: %s", exc)
        now_ct = datetime.now(_CT)
        return f"JARVIS Pre-Market Brief — {now_ct.strftime('%m/%d %H:%M CT')}\n[Brief assembly failed — check engine logs]"
