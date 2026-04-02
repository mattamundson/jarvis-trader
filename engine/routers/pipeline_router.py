"""Pipeline notification router - test webhooks."""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
logger = logging.getLogger(__name__)


class PipelineRunRequest(BaseModel):
    """Request to execute the trading pipeline for a symbol"""

    symbol: str = Field(..., description="Trading symbol (e.g., MCL, MNQ, SPY)")
    is_futures: bool = Field(True, description="True for futures, False for options")


class SchedulerJobInfo(BaseModel):
    """Job information from APScheduler."""

    id: str
    name: str
    next_run: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SchedulerStatusResponse(BaseModel):
    """Status of the APScheduler and decision logging."""

    running: bool
    total_jobs: int
    jobs: list[SchedulerJobInfo]
    total_decisions_logged: int

    model_config = ConfigDict(from_attributes=True)


# Global references (injected from main.py)
_scheduler = None
_trading_pipeline = None
_safety_layer = None
_db_manager = None
_paper_tracker = None
_telegram_notifier = None


def inject_dependencies(scheduler, trading_pipeline, safety_layer, db_manager, paper_tracker=None):
    """Inject global dependencies from main.py"""
    global _scheduler, _trading_pipeline, _safety_layer, _db_manager, _paper_tracker
    _scheduler = scheduler
    _trading_pipeline = trading_pipeline
    _safety_layer = safety_layer
    _db_manager = db_manager
    _paper_tracker = paper_tracker


def set_notifier(notifier) -> None:
    """Inject the Telegram notifier (called from main.py lifespan startup)."""
    global _telegram_notifier
    _telegram_notifier = notifier


@router.post("/notifications/telegram/test")
async def test_telegram():
    """Test Telegram notification config"""
    from datetime import datetime
    from datetime import timezone as _tz

    try:
        from notifications.telegram import get_notifier

        notifier = get_notifier()
        ts = datetime.now(_tz.utc).isoformat()
        if not notifier.enabled:
            return {
                "sent": False,
                "status": "not_configured",
                "message": "Add TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID to .env",
                "timestamp": ts,
            }
        ok = await notifier.test()
        return {
            "sent": ok,
            "status": "ok" if ok else "failed",
            "timestamp": ts,
        }
    except ImportError:
        return {
            "sent": False,
            "status": "module_not_found",
            "message": "Telegram module not installed",
        }
    except Exception as e:
        logger.error(f"[TELEGRAM] Test failed: {e}")
        raise HTTPException(500, f"Telegram test failed: {e}") from e


@router.get("/scheduler/status")
async def scheduler_status() -> SchedulerStatusResponse:
    """
    Get scheduler status and decision logging metrics.

    Returns:
        running: Whether APScheduler is currently running
        total_jobs: Number of scheduled jobs
        jobs: List of job details (id, name, next_run)
        total_decisions_logged: Count of decisions in the database
    """
    try:
        # Get scheduler status
        is_running = _scheduler is not None and _scheduler.running
        total_jobs = 0
        jobs_list: list[SchedulerJobInfo] = []

        if _scheduler is not None:
            total_jobs = len(_scheduler.get_jobs())
            for job in _scheduler.get_jobs():
                job_next_run = (
                    job.next_run_time.isoformat() if job.next_run_time is not None else None
                )
                jobs_list.append(
                    SchedulerJobInfo(
                        id=job.id,
                        name=job.name or job.id,
                        next_run=job_next_run,
                    )
                )

        # Get decision count from database
        total_decisions = 0
        if _db_manager is not None:
            try:
                decisions = _db_manager.get_decisions(limit=999999)
                total_decisions = len(decisions)
            except Exception:
                total_decisions = 0

        return SchedulerStatusResponse(
            running=is_running,
            total_jobs=total_jobs,
            jobs=jobs_list,
            total_decisions_logged=total_decisions,
        )
    except Exception as e:
        logger.error(f"[SCHEDULER] Status query failed: {e}")
        raise HTTPException(500, f"Scheduler status query failed: {e}") from e


@router.post("/scheduler/manual-scan")
async def manual_scan():
    """Manually trigger market scan"""
    try:
        from schedulers.market_scanner import MarketScanner

        scanner = MarketScanner()
        result = await scanner.scan_all_markets()
        return {"status": "ok", "scanned": result}
    except Exception as e:
        logger.error(f"[SCHEDULER] Manual scan failed: {e}")
        raise HTTPException(500, f"Scan failed: {e}") from e


@router.post("/notifications/whatsapp/test")
async def test_whatsapp():
    """Test WhatsApp notification config"""
    from datetime import datetime
    from datetime import timezone as _tz

    try:
        from notifications.whatsapp import get_notifier

        notifier = get_notifier()
        ts = datetime.now(_tz.utc).isoformat()
        if not notifier.enabled:
            return {
                "sent": False,
                "status": "not_configured",
                "message": "Add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, WHATSAPP_TO to .env",
                "timestamp": ts,
            }
        ok = await notifier.test()
        return {
            "sent": ok,
            "status": "ok" if ok else "failed",
            "timestamp": ts,
        }
    except ImportError:
        return {
            "sent": False,
            "status": "module_not_found",
            "message": "WhatsApp module not installed",
        }
    except Exception as e:
        logger.error(f"[WHATSAPP] Test failed: {e}")
        raise HTTPException(500, f"WhatsApp test failed: {e}") from e


async def _send_signal_alert(symbol: str, final_action: str, result: dict) -> None:
    """
    Fire-and-forget Telegram alert for a non-HOLD pipeline result.

    Formats the canonical JARVIS SIGNAL line:
        JARVIS SIGNAL: LONG MCL @ 75.32 | Stop: 74.80 | Target: 76.20 | R:R: 1.71 | Conviction: 8/10

    Skips gracefully if the notifier is None or disabled.
    """
    notifier = _telegram_notifier
    if notifier is None:
        # Fall back to the module-level singleton if no injected notifier
        try:
            from notifications.telegram import get_notifier

            notifier = get_notifier()
        except Exception:
            logger.warning("[PIPELINE] Telegram notifier unavailable — signal alert skipped")
            return

    if not notifier.enabled:
        return

    trade_dec = result.get("trade_decision") or {}
    analyst_reports = result.get("analyst_reports") or {}
    technical_report = analyst_reports.get("technical") or {}
    fund_decision = result.get("fund_decision") or {}

    entry_price = (
        trade_dec.get("entry_price")
        or trade_dec.get("limit_price")
        or technical_report.get("current_price")
        or technical_report.get("price")
        or 0.0
    )
    stop_price = trade_dec.get("stop_price") or 0.0
    target_price = (
        trade_dec.get("target_1")
        or trade_dec.get("target_price")
        or trade_dec.get("take_profit")
        or 0.0
    )
    conviction_raw = fund_decision.get("final_conviction") or trade_dec.get("conviction") or 0.0
    conviction_score = round(float(conviction_raw) * 10, 1)

    # Risk:Reward ratio
    if entry_price and stop_price and target_price and stop_price != entry_price:
        risk = abs(float(entry_price) - float(stop_price))
        reward = abs(float(target_price) - float(entry_price))
        rr_ratio = f"{reward / risk:.2f}" if risk else "N/A"
    else:
        rr_ratio = "N/A"

    direction = final_action.upper()
    price_str = f"{float(entry_price):.2f}" if entry_price else "N/A"
    stop_str = f"{float(stop_price):.2f}" if stop_price else "N/A"
    target_str = f"{float(target_price):.2f}" if target_price else "N/A"

    message = (
        f"<b>JARVIS SIGNAL: {direction} {symbol}</b>\n"
        f"@ {price_str} | Stop: {stop_str} | Target: {target_str} | R:R: {rr_ratio} | "
        f"Conviction: {conviction_score}/10"
    )

    try:
        await notifier.send(message)
        logger.info("[PIPELINE] Telegram signal alert sent for %s %s", direction, symbol)
    except Exception as exc:
        logger.error("[PIPELINE] Telegram send failed for %s: %s", symbol, exc)


async def _run_pipeline_and_log(symbol: str, is_futures: bool) -> None:
    """
    Internal coroutine: runs the pipeline and auto-logs paper trades for LONG/SHORT decisions.

    Called as a background task from run_pipeline() so the HTTP response is immediate.
    Paper trade logging is best-effort — failures are caught and logged.
    """
    try:
        result = await _trading_pipeline.analyze_and_decide(symbol=symbol, is_futures=is_futures)
    except Exception as exc:
        logger.error("[PIPELINE] analyze_and_decide raised for %s: %s", symbol, exc)
        return

    final_action = result.get("final_action", "hold")
    logger.info(
        "[PIPELINE] %s complete — final_action=%s requires_human=%s",
        symbol,
        final_action,
        result.get("requires_human"),
    )

    # Auto-log paper trade when the pipeline produces a directional decision
    if final_action not in ("hold", "HOLD") and _paper_tracker is not None:
        try:
            trade_dec = result.get("trade_decision") or {}
            analyst_reports = result.get("analyst_reports") or {}
            technical_report = analyst_reports.get("technical") or {}
            fund_decision = result.get("fund_decision") or {}

            # Entry price: prefer limit_price, then current market price from technical analyst
            entry_price = (
                trade_dec.get("limit_price")
                or technical_report.get("current_price")
                or technical_report.get("price")
            )
            stop_price = trade_dec.get("stop_price") or None
            target_price = trade_dec.get("target_price") or trade_dec.get("take_profit") or None
            conviction = fund_decision.get("final_conviction", 0.0) or trade_dec.get(
                "confidence", 0.0
            )
            final_qty = result.get("final_quantity", 1) or 1

            if entry_price:
                trade_id = _paper_tracker.add_paper_trade(
                    symbol=symbol,
                    side=final_action,
                    quantity=float(final_qty),
                    entry_price=float(entry_price),
                    stop_loss=float(stop_price) if stop_price else None,
                    take_profit=float(target_price) if target_price else None,
                    strategy_params={
                        "source": "pipeline",
                        "conviction": round(float(conviction), 4),
                        "direction": final_action.upper(),
                        "summary": result.get("summary", ""),
                    },
                )
                logger.info(
                    "[PAPER] Auto-logged %s %s qty=%s @ %.4f  sl=%s  tp=%s  conviction=%.0f%%  id=%s",
                    symbol,
                    final_action.upper(),
                    final_qty,
                    float(entry_price),
                    f"{stop_price:.4f}" if stop_price else "none",
                    f"{target_price:.4f}" if target_price else "none",
                    float(conviction) * 100,
                    trade_id[:8],
                )
            else:
                logger.warning(
                    "[PAPER] Skipped auto-log for %s %s — no entry price available "
                    "(technical analyst did not return current_price)",
                    symbol,
                    final_action.upper(),
                )
        except Exception as exc:
            logger.error("[PAPER] Auto-log failed for %s: %s", symbol, exc)
    elif final_action not in ("hold", "HOLD") and _paper_tracker is None:
        logger.warning(
            "[PAPER] Skipping paper trade log for %s %s — paper_tracker not injected",
            symbol,
            final_action.upper(),
        )

    # Send Telegram alert for non-HOLD decisions
    if final_action not in ("hold", "HOLD"):
        try:
            await _send_signal_alert(symbol, final_action, result)
        except Exception as exc:
            logger.error("[PIPELINE] Telegram alert failed for %s: %s", symbol, exc)


@router.post("/run")
async def run_pipeline(request: PipelineRunRequest):
    """
    Execute the full 5-stage trading pipeline for a symbol.

    Starts the pipeline as a background task and returns immediately.
    When the pipeline produces a LONG or SHORT decision the result is
    automatically recorded in the paper portfolio tracker.

    Pipeline stages: analysts → debate → trader → risk manager → fund manager.

    Request body:
        symbol (str): Trading symbol (e.g., "MCL", "MNQ", "SPY")
        is_futures (bool): True for futures contracts, False for options

    Returns:
        status: "running" | "halted"
        symbol: The requested symbol
        is_futures: The instrument type
        message: Description of result
        pipeline_id: Task ID (for debugging)
    """
    try:
        if _trading_pipeline is None:
            raise ValueError("Trading pipeline not initialized (ANTHROPIC_API_KEY missing)")

        if _safety_layer is None:
            raise ValueError("Safety layer not initialized")

        # Normalize symbol
        symbol = request.symbol.upper().strip()

        # Check if kill switch is active
        safety_status = _safety_layer.get_status()
        if safety_status.get("kill_switch_active"):
            return {
                "status": "halted",
                "message": "Kill switch is active",
                "reason": safety_status.get("kill_switch_reason"),
            }

        # Queue pipeline execution as background task (non-blocking)
        # The wrapper coroutine handles paper trade logging after the pipeline completes.
        task = asyncio.create_task(
            _run_pipeline_and_log(symbol=symbol, is_futures=request.is_futures)
        )

        logger.info(
            "[PIPELINE] Started background task for %s (futures=%s)", symbol, request.is_futures
        )

        return {
            "status": "running",
            "message": "Pipeline execution started — paper trade will be logged on LONG/SHORT decision",
            "symbol": symbol,
            "is_futures": request.is_futures,
            "pipeline_id": id(task),
        }
    except Exception as e:
        logger.error("[PIPELINE] Execution failed: %s", e)
        raise HTTPException(500, f"Pipeline execution failed: {e}") from e
