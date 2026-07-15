"""
JARVIS TRADER — Trading Pipeline
===================================
Orchestrates the complete multi-agent analysis and decision pipeline for a symbol.

Pipeline order:
  1. Analyst stage (parallel):  technical, news, social, fundamental
  2. Debate stage:               bull agent + bear agent → debate orchestrator
  3. Trader:                     synthesizes everything → TradeDecision
  4. Risk Manager:               validates TradeDecision → RiskDecision
  5. Fund Manager:               portfolio-level final approval → FundDecision

All intermediate results are preserved in the returned pipeline_result dict
for audit logging, dashboards, and post-trade review.

The pipeline is non-blocking at each stage — if an analyst fails it returns
a neutral/empty report and the pipeline continues. Failures are logged and
captured in pipeline_result["errors"].
"""

import asyncio
import datetime as _dt
import logging
import os
import uuid
import zoneinfo
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from analysis.regime_engine import MarketRegime as _LegacyRegime
from analysis.regime_engine import RegimeStatus
from backtest.regime_classifier import RegimeClassifierV2
from database import repository

try:
    from profiling.pipeline_profiler import PipelineProfiler

    _PROFILER_AVAILABLE = True
except Exception:  # pragma: no cover — optional dependency
    _PROFILER_AVAILABLE = False

try:
    from cache import (
        cache_signal,
        get_cached_signal,
        should_use_cache,
    )

    _CACHE_AVAILABLE = True
except Exception:  # pragma: no cover — optional dependency
    _CACHE_AVAILABLE = False

try:
    _WA_AVAILABLE = True
except Exception:  # pragma: no cover — optional dependency
    _WA_AVAILABLE = False

try:
    from analysis.hidden_pivots import HPScanResult, full_hidden_pivots_scan

    _HP_AVAILABLE = True
except Exception:  # pragma: no cover — optional dependency
    _HP_AVAILABLE = False

try:
    from analysis.discord_time_patterns import compute_time_patterns

    _TIME_PATTERNS_AVAILABLE = True
except Exception:  # pragma: no cover — optional dependency
    _TIME_PATTERNS_AVAILABLE = False

try:
    from services.recipe_loader import RecipeLoader

    _RECIPE_LOADER_AVAILABLE = True
except Exception:  # pragma: no cover — optional dependency
    _RECIPE_LOADER_AVAILABLE = False

from agents.kronos_classifier import KronosClassifier, is_kronos_enabled

logger = logging.getLogger(__name__)

# ── Time-of-Day Filter Config ──────────────────────────────────────────────────
TIME_OF_DAY_FILTER_ENABLED: bool = True
_TIME_OF_DAY_MIN_CONVICTION: float = 0.35  # hours below this win_rate are skipped

# ── Validation-Only Instruments ────────────────────────────────────────────────
# Instruments in this set are included in the pipeline for signal generation and
# dashboard visibility, but their verdicts NEVER reach the order submission path.
#
# These are instruments whose WFE scores are below the paper-trading threshold,
# kept in the watchlist for continued walk-forward validation only:
#   MES — WFE=0.09 (REJECTED 2026-04-02); Tier 3 paper walk-forward authorized 2026-04-09
#   MGC — WFE=0.14 (HALTED); pipeline-only for validation feedback
#
# Flip-to-active criteria (remove from this set when ALL met):
#   1. WFE >= 0.6 on a fresh rolling walk-forward run
#   2. Gate v2 PASS (pf_ci_lower>=1.10, p_edge>=0.95, mc_95th_dd<=5%, dsr>=0.10)
#   3. Explicit Tier 3 authorization from Amo
#
# This constant is checked in approval/service.py:ensure_approval_allowed() — a
# second layer above the safety layer's DO_NOT_TRADE_SYMBOLS blocklist. The safety
# layer is canonical; any conflict resolves in favor of safety.
VALIDATION_ONLY_INSTRUMENTS: frozenset[str] = frozenset()
# MES promoted 2026-05-24 (Tier 3 auth, p_edge=0.75 ALT PASS, SMA(60,200))
# MGC promoted 2026-05-24 (Tier 3 auth, p_edge=0.6842 ALT PASS, SMA(50,120))

# ── Validation-Only Strategies (by stark_signal value) ────────────────────────
# Strategy signals in this set are blocked from producing paper trades until
# a full WFO run exists AND gate v2 returns PASS. The pipeline still runs to
# completion and the stark_signal is visible in the dashboard; only the
# scanner's paper-mode bypass (signal_scanner.py) is blocked.
#
# Current entries:
#   SHORT_GAP_FILL — StarkTPOStrategy.GAP_IMBALANCE short-side signal.
#     Gated 2026-05-21 following the 2026-05-09 to 2026-05-11 phantom-price
#     drawdown incident.  Root-cause: NULL wfe_snapshots metrics indicate no
#     completed WFO run; signal bypassed gate v2 entirely.
#     Incident doc: docs/session-logs/drawdown-root-cause-may-9-to-11.md
#
# Flip-to-active criteria (remove from this set when ALL met):
#   1. WFE >= 0.6 on a fresh rolling walk-forward run (wfe_snapshots non-NULL)
#   2. Gate v2 PASS (pf_ci_lower>=1.10, p_edge>=0.95, mc_95th_dd<=5%, dsr>=0.10)
#   3. Explicit Tier 3 authorization from Amo
#
# NOTE: this is a STRATEGY gate (blocks by stark_signal name), distinct from
# VALIDATION_ONLY_INSTRUMENTS (blocks by symbol).  Existing open positions are
# NOT force-closed — the gate only prevents NEW paper submissions.
VALIDATION_ONLY_STRATEGIES: frozenset[str] = frozenset({"SHORT_GAP_FILL"})

__all__ = [
    "TradingPipeline",
    "pre_filter_signal",
    "VALIDATION_ONLY_INSTRUMENTS",
    "VALIDATION_ONLY_STRATEGIES",
]

# ── Economic Calendar Blackout ─────────────────────────────────────────────────
_ECONOMIC_BLACKOUT_EVENTS: list[dict] = [
    # FOMC meetings 2026 (decision day, 2:00pm ET / 1:00pm CT)
    {"name": "FOMC", "date": _dt.date(2026, 3, 19)},
    {"name": "FOMC", "date": _dt.date(2026, 5, 7)},
    {"name": "FOMC", "date": _dt.date(2026, 6, 18)},
    # NFP — first Friday of each month (8:30am ET / 7:30am CT)
    {"name": "NFP", "date": _dt.date(2026, 4, 3)},
    {"name": "NFP", "date": _dt.date(2026, 5, 1)},
    {"name": "NFP", "date": _dt.date(2026, 6, 5)},
    # CPI (8:30am ET / 7:30am CT)
    {"name": "CPI", "date": _dt.date(2026, 4, 10)},
    {"name": "CPI", "date": _dt.date(2026, 5, 13)},
    {"name": "CPI", "date": _dt.date(2026, 6, 10)},
]
_BLACKOUT_WINDOW_MINUTES: int = 30


def _is_in_economic_blackout() -> bool:
    """Return True if current time is within ±30 min of a scheduled high-impact event."""
    now_ct = _dt.datetime.now(_dt.timezone.utc).astimezone(
        _dt.timezone(_dt.timedelta(hours=-5))  # approximate CT (UTC-5)
    )
    today = now_ct.date()
    for event in _ECONOMIC_BLACKOUT_EVENTS:
        if event["date"] == today:
            release_hour = 13 if event["name"] == "FOMC" else 7
            release_minute = 0 if event["name"] == "FOMC" else 30
            release_time = now_ct.replace(
                hour=release_hour, minute=release_minute, second=0, microsecond=0
            )
            delta_min = abs((now_ct - release_time).total_seconds() / 60)
            if delta_min <= _BLACKOUT_WINDOW_MINUTES:
                return True
    return False


def _make_hold_result(symbol: str, is_futures: bool, reason: str, **extra: Any) -> dict:
    """Build a standard HOLD early-return dict for pre-filter rejections."""
    return {
        "symbol": symbol,
        "is_futures": is_futures,
        "started_at": datetime.now().isoformat(),
        "completed_at": datetime.now().isoformat(),
        "final_action": "hold",
        "final_quantity": 0,
        "requires_human": False,
        "pre_filtered": True,
        "pre_filter_reason": reason,
        "skipped": True,
        "errors": [],
        "cache_hit": False,
        **extra,
    }


async def _check_vix_extreme(vix_extreme_threshold: float = 35.0) -> bool:
    """
    Return True if VIX > 35 (fear extreme — no directional edge).
    Fetches from local macro snapshot endpoint.
    Fails open: returns False if fetch errors.
    """
    try:
        import aiohttp

        _api_key = os.environ.get("API_KEY", "")
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "http://localhost:8010/macro/snapshot",
                headers={"x-api-key": _api_key},
                timeout=aiohttp.ClientTimeout(total=3),
            ) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                vix_val = data.get("vix") or data.get("VIX")
                if vix_val is None:
                    return False
                return float(vix_val) > float(vix_extreme_threshold)
    except Exception:
        return False  # fail open


async def _check_atr_spike(sig_df: Any) -> bool:
    """
    Return True if the latest ATR is > 3x the 20-bar ATR average (volatility spike).
    sig_df must be a DataFrame with an 'atr' column.
    Fails open: returns False on any error.
    """
    try:
        import pandas as pd

        if not isinstance(sig_df, pd.DataFrame):
            return False
        if "atr" not in sig_df.columns or len(sig_df) < 21:
            return False
        atr_series = sig_df["atr"].dropna()
        if len(atr_series) < 21:
            return False
        current_atr = float(atr_series.iloc[-1])
        avg_atr_20 = float(atr_series.iloc[-21:-1].mean())
        if avg_atr_20 <= 0:
            return False
        return current_atr > 3.0 * avg_atr_20
    except Exception:
        return False  # fail open


async def _check_mtf_misalignment(
    symbol: str,
    timeframe: str,
    is_futures: bool,
    data_mgr: Any,
) -> bool:
    """
    Return True if 4h and 1h STC disagree on direction (MTF misalignment).
    Uses MTFFilter with live-fetched bars from data manager.
    Fails open: returns False on any error.
    """
    try:
        from backtest.mtf_filter import MTFFilter
        from backtest.signals import compute_all_indicators, generate_instrument_signals

        df_1h = await data_mgr.get_bars(
            symbol, lookback_days=10, timeframe=timeframe, is_futures=is_futures
        )
        if df_1h is None or df_1h.empty or len(df_1h) < 20:
            return False

        df_4h = await data_mgr.get_bars(
            symbol, lookback_days=30, timeframe="4h", is_futures=is_futures
        )
        if df_4h is None or df_4h.empty or len(df_4h) < 10:
            return False

        # Staleness guard: if 4h bars end more than 48h ago, skip MTF check (fail open)
        if "timestamp" in df_4h.columns:
            last_4h = pd.Timestamp(df_4h["timestamp"].iloc[-1])
            if last_4h.tzinfo is None:
                last_4h = last_4h.tz_localize("UTC")
            age_hours = (pd.Timestamp.now(tz="UTC") - last_4h).total_seconds() / 3600
            if age_hours > 48:
                logger.warning(
                    "[MTF] %s 4h data is %.0fh stale — skipping MTF check (fail open)",
                    symbol,
                    age_hours,
                )
                return False  # False = no misalignment = signal passes

        df_1h_sig = generate_instrument_signals(df_1h.copy(), symbol)
        df_4h_ind = compute_all_indicators(df_4h.copy())

        required_4h = {"stc_signal", "stc_cross_up", "stc_cross_down"}
        if not required_4h.issubset(df_4h_ind.columns):
            return False
        required_1h = {"bias", "entry_signal"}
        if not required_1h.issubset(df_1h_sig.columns):
            return False

        # Force the last 1h bar to ENTRY_NOW so MTFFilter evaluates the current bar
        df_1h_sig = df_1h_sig.copy()
        df_1h_sig.loc[df_1h_sig.index[-1], "entry_signal"] = "ENTRY_NOW"

        mtf = MTFFilter(cross_lookback=3)
        aligned_series = mtf.check_alignment(df_1h_sig, df_4h_ind)
        last_aligned = bool(aligned_series.iloc[-1])
        return not last_aligned  # True = misaligned → block

    except Exception:
        return False  # fail open


async def pre_filter_signal(
    symbol: str,
    timeframe: str,
    is_futures: bool,
    agents: dict,
    vix_extreme_threshold: float = 35.0,
) -> dict | None:
    """
    Pre-filter gate — runs before the LLM pipeline.

    Checks (in order):
      1. VIX > 35 — fear extreme, skip signal
      2. ATR spike — current ATR > 3× 20-bar average, skip
      3. MTF misalignment — 4h and 1h STC disagree on direction, skip
      4. STC mid-range — STC between skip_low and skip_high, skip

    All checks fail open: if data is unavailable the check is skipped
    and the pipeline proceeds normally.

    Returns:
        dict with HOLD result if any filter fires, or None to proceed.
    """
    try:
        from backtest.signals import INSTRUMENT_PARAMS, generate_instrument_signals
        from config import settings as _cfg
        from routers.pipeline_router import record_signal_debug

        _tech_agent = agents.get("technical")
        _data_mgr = getattr(_tech_agent, "_data", None)
        if _data_mgr is None:
            return None

        _df = await _data_mgr.get_bars(
            symbol, lookback_days=5, timeframe=timeframe, is_futures=is_futures
        )
        if _df is None or _df.empty or len(_df) < 20:
            return None

        _sig_df = generate_instrument_signals(_df.copy(), symbol)
        if "stc_val" not in _sig_df.columns:
            return None

        _stc_val = float(_sig_df["stc_val"].iloc[-1])
        _params = INSTRUMENT_PARAMS.get(symbol, (15, 83, 0.70, 1.00, 1.618, 2.618, True))
        _stc_os, _stc_ob = int(_params[0]), int(_params[1])
        _mid_lo = float(_cfg.STC_MIDRANGE_SKIP_LOW)
        _mid_hi = float(_cfg.STC_MIDRANGE_SKIP_HIGH)

        # ── Check 1: VIX extreme ───────────────────────────────────────────
        if await _check_vix_extreme(vix_extreme_threshold=vix_extreme_threshold):
            logger.info("[pre_filter_signal] %s SKIP — VIX > 35 (fear extreme)", symbol)
            record_signal_debug(
                {
                    "timestamp": datetime.now().isoformat(),
                    "symbol": symbol,
                    "stc_val": round(_stc_val, 2),
                    "stage_blocked": "pre_filter",
                    "reason": f"VIX > {float(vix_extreme_threshold):g} — fear extreme, no directional edge",
                }
            )
            return _make_hold_result(
                symbol,
                is_futures,
                f"VIX > {float(vix_extreme_threshold):g} — fear extreme, no directional edge",
            )

        # ── Check 2: ATR spike ────────────────────────────────────────────
        if await _check_atr_spike(_sig_df):
            logger.info("[pre_filter_signal] %s SKIP — ATR spike > 3× 20-bar avg", symbol)
            record_signal_debug(
                {
                    "timestamp": datetime.now().isoformat(),
                    "symbol": symbol,
                    "stc_val": round(_stc_val, 2),
                    "stage_blocked": "pre_filter",
                    "reason": "ATR spike — current ATR > 3× 20-bar average",
                }
            )
            return _make_hold_result(
                symbol, is_futures, "ATR spike — current ATR > 3× 20-bar average"
            )

        # ── Check 3: MTF misalignment ─────────────────────────────────────
        if (
            _data_mgr is not None
            and _cfg.MTF_FILTER_ENABLED
            and await _check_mtf_misalignment(symbol, timeframe, is_futures, _data_mgr)
        ):
            logger.info("[pre_filter_signal] %s SKIP — MTF misalignment (4h vs 1h STC)", symbol)
            record_signal_debug(
                {
                    "timestamp": datetime.now().isoformat(),
                    "symbol": symbol,
                    "stc_val": round(_stc_val, 2),
                    "stage_blocked": "pre_filter",
                    "reason": "MTF misalignment — 4h and 1h STC disagree on direction",
                }
            )
            return _make_hold_result(
                symbol, is_futures, "MTF misalignment — 4h and 1h STC disagree on direction"
            )

        # ── Check 4: Time-of-day conviction ──────────────────────────────
        if TIME_OF_DAY_FILTER_ENABLED and _TIME_PATTERNS_AVAILABLE:
            try:
                _now_et = _dt.datetime.now(zoneinfo.ZoneInfo("America/New_York"))
                _current_hour_et = _now_et.hour
                _tod_patterns = compute_time_patterns(symbol)
                _hour_data = _tod_patterns.get("by_hour", {}).get(_current_hour_et)
                if _hour_data is not None:
                    _hour_conviction = float(_hour_data.get("win_rate", 1.0))
                    if _hour_conviction < _TIME_OF_DAY_MIN_CONVICTION:
                        logger.info(
                            "[pre_filter_signal] %s SKIP — low conviction hour %02d:00 ET "
                            "(win_rate=%.2f < %.2f threshold)",
                            symbol,
                            _current_hour_et,
                            _hour_conviction,
                            _TIME_OF_DAY_MIN_CONVICTION,
                        )
                        return _make_hold_result(
                            symbol,
                            is_futures,
                            f"low conviction hour — {_current_hour_et:02d}:00 ET win_rate={_hour_conviction:.2f}",
                        )
            except Exception as _tod_err:
                logger.debug("[pre_filter_signal] time-of-day filter skipped: %s", _tod_err)

        # ── Check 5: STC mid-range ────────────────────────────────────────
        if not _cfg.STC_MIDRANGE_SKIP_ENABLED or not (_mid_lo < _stc_val < _mid_hi):
            logger.debug(
                "[pre_filter_signal] symbol=%s stc_val=%.1f range=(%.0f–%.0f) action=PASS",
                symbol,
                _stc_val,
                _mid_lo,
                _mid_hi,
            )
            record_signal_debug(
                {
                    "timestamp": datetime.now().isoformat(),
                    "symbol": symbol,
                    "stc_val": round(_stc_val, 2),
                    "stage_blocked": "approved",
                    "reason": f"STC {_stc_val:.1f} outside skip range",
                }
            )
            return None

        logger.info(
            "[pre_filter_signal] symbol=%s stc_val=%.1f range=(%.0f–%.0f) action=SKIP",
            symbol,
            _stc_val,
            _mid_lo,
            _mid_hi,
        )
        record_signal_debug(
            {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "stc_val": round(_stc_val, 2),
                "stage_blocked": "pre_filter",
                "reason": f"STC {_stc_val:.1f} in skip range",
            }
        )

        return {
            "symbol": symbol,
            "is_futures": is_futures,
            "started_at": datetime.now().isoformat(),
            "completed_at": datetime.now().isoformat(),
            "final_action": "hold",
            "final_quantity": 0,
            "requires_human": False,
            "pre_filtered": True,
            "pre_filter_reason": "STC mid-range pre-filter",
            "pre_filter_stc": round(_stc_val, 2),
            "pre_filter_stc_os": _stc_os,
            "pre_filter_stc_ob": _stc_ob,
            "errors": [],
            "cache_hit": False,
        }

    except Exception as e:
        logger.debug("[pre_filter_signal] %s skipped: %s", symbol, e)
        return None


class TradingPipeline:
    """
    Runs the complete multi-agent analysis pipeline for a single symbol.

    Required agents dict keys:
        technical     — TechnicalAnalystAgent
        news          — NewsAnalystAgent
        social        — (any agent with .analyze(symbol) → report with .to_dict())
        fundamental   — (any agent with .analyze(symbol) → report with .to_dict())
        bull          — (any agent with .argue(symbol, analyst_reports) → dict)
        bear          — (any agent with .argue(symbol, analyst_reports) → dict)
        debate        — DebateOrchestrator with .run_debate(bull_arg, bear_arg) → dict
        trader        — TraderAgent
        risk_manager  — RiskManagerAgent
        fund_manager  — FundManagerAgent

    All agents are optional — the pipeline degrades gracefully when absent.
    """

    def __init__(
        self,
        agents: dict,
        safety_layer,
        db_manager=None,
        context_manager=None,
        shadow_tracker=None,
        memory_bridge=None,
    ):
        """
        Args:
            agents:          Dict of named agent instances (see class docstring)
            safety_layer:    SafetyLayer instance — provides get_status() and kill switch
            db_manager:      Optional DatabaseManager — if set, pipeline runs are persisted
            context_manager: Optional context manager instance for pipeline execution context
            shadow_tracker:  Optional ShadowModeTracker for logging blocklisted signals
            memory_bridge:   Optional MemoryBridge for persistent working memory
        """
        self._agents = agents
        self._safety = safety_layer
        self._db = db_manager
        self._shadow_tracker = shadow_tracker
        self._memory = memory_bridge
        self._regime_engine = RegimeClassifierV2()
        self.context_manager = context_manager

        # Phase 3.7: Pattern Vision
        try:
            from agents.vision_analyst import PatternVisionAnalystAgent

            tech = agents.get("technical")
            self._vision_agent = PatternVisionAnalystAgent(llm_client=getattr(tech, "_llm", None))
        except ImportError:
            logger.warning(
                "[Pipeline] vision_analyst unavailable (playwright not installed) — vision stage will return CAUTION"
            )
            self._vision_agent = None

        self.profiler = PipelineProfiler() if _PROFILER_AVAILABLE else None
        # _kronos is NOT set here — use _kronos_or_none property so that
        # /admin/feature-flags toggles take effect without an engine restart.

    async def analyze_and_decide(
        self,
        symbol: str,
        is_futures: bool = True,
        timeframe: str = "1h",
        active_recipe_name: str | None = None,
    ) -> dict:
        """
        Run the full pipeline for a symbol.

        Returns a pipeline_result dict containing:
            symbol              str
            is_futures          bool
            started_at          ISO timestamp
            completed_at        ISO timestamp
            analyst_reports     dict (technical, news, social, fundamental)
            debate_result       dict
            trade_decision      dict  (TradeDecision.to_dict())
            risk_decision       dict  (RiskDecision.to_dict())
            fund_decision       dict  (FundDecision.to_dict()) — present if risk approved
            final_action        str   "buy" | "sell" | "hold" | "pending_human_approval"
            final_quantity      int
            requires_human      bool
            errors              list[str]  — any non-fatal errors encountered
        """
        started_at = datetime.now()
        errors: list[str] = []
        pipeline_result: dict[str, Any] = {
            "symbol": symbol,
            "is_futures": is_futures,
            "started_at": started_at.isoformat(),
            "timeframe": timeframe,
            "errors": errors,
        }

        # Decision-identity fingerprint (P1): stamp WHICH decision configuration
        # produced this result, on every return path. Best-effort and fail-open --
        # a fingerprint failure must never affect the decision itself.
        try:
            from agents.decision_identity import current_decision_identity

            pipeline_result["decision_identity"] = current_decision_identity(symbol)
        except Exception as _did_err:  # pragma: no cover - defensive
            logger.debug("[Pipeline] decision_identity stamp failed: %s", _did_err)

        logger.info(f"[Pipeline] Starting analysis for {symbol} (futures={is_futures})")

        active_recipe = None
        if active_recipe_name and _RECIPE_LOADER_AVAILABLE:
            try:
                recipes_dir = Path(__file__).resolve().parent.parent / "recipes"
                active_recipe = RecipeLoader(recipes_dir).load(active_recipe_name)
                pipeline_result["active_recipe"] = {
                    "name": active_recipe.name,
                    "version": active_recipe.version,
                    "parameters": {
                        "entry_max_vix": active_recipe.parameters.entry_max_vix,
                        "min_confluence": active_recipe.parameters.min_confluence,
                        "size_mult": active_recipe.parameters.size_mult,
                    },
                    "required_tools": list(active_recipe.required_tools),
                    "steps": list(active_recipe.steps),
                }
                logger.info("[Pipeline] %s using active recipe %s", symbol, active_recipe.name)
            except Exception as exc:
                err = f"Recipe load failed for {active_recipe_name}: {exc}"
                logger.warning("[Pipeline] %s", err)
                errors.append(err)
                pipeline_result["active_recipe_error"] = err

        # ── Cache Check: Return early if valid cached signal exists ────────────────
        if _CACHE_AVAILABLE:
            # Check if cached signal should be used (regime hasn't changed)
            if await should_use_cache(symbol):
                cached = await get_cached_signal(symbol)
                if cached:
                    logger.info(
                        f"[Pipeline] {symbol} cache hit — skipping full pipeline (saves LLM calls)"
                    )
                    cached["cache_hit"] = True
                    # Update completed_at timestamp for response
                    cached["completed_at"] = datetime.now().isoformat()
                    return cached

        # ── Economic Calendar Blackout ─────────────────────────────────────────
        if _is_in_economic_blackout():
            logger.info(
                "[Pipeline] %s HOLD — economic calendar blackout (scheduled event ±30 min)", symbol
            )
            return _make_hold_result(
                symbol,
                is_futures,
                "Economic calendar blackout — scheduled event ±30 min",
            )

        # ── Pre-Filter Gate (STC, VIX, ATR spike, MTF) ────────────────────────
        recipe_vix_threshold = (
            float(active_recipe.parameters.entry_max_vix) if active_recipe is not None else 35.0
        )
        pre_filter_result = await pre_filter_signal(
            symbol,
            timeframe,
            is_futures,
            self._agents,
            vix_extreme_threshold=recipe_vix_threshold,
        )
        if pre_filter_result is not None:
            return pre_filter_result

        # ── Stage 1: Analysts in parallel ─────────────────────────────────

        if self.profiler:
            await self.profiler.start_stage("analysts")
        analyst_reports = await self._run_analysts(symbol, is_futures, errors, timeframe=timeframe)
        if self.profiler:
            await self.profiler.end_stage("analysts")

        # ── A1: Hidden Pivots scan (post Stage-1, non-blocking) ───────────
        if _HP_AVAILABLE:
            try:
                _hp_data_mgr = getattr(self._agents.get("technical"), "_data", None)
                if _hp_data_mgr is not None:
                    _hp_df = await _hp_data_mgr.get_bars(
                        symbol, lookback_days=30, timeframe=timeframe, is_futures=is_futures
                    )
                    if _hp_df is not None and not _hp_df.empty and len(_hp_df) >= 20:
                        hp_result: HPScanResult = full_hidden_pivots_scan(
                            symbol=symbol, df=_hp_df, timeframe=timeframe
                        )
                        analyst_reports["hidden_pivots"] = {
                            "bias": hp_result.bias,
                            "pattern": hp_result.pattern,
                            "trigger_price": hp_result.trigger_price,
                            "ema_alignment": hp_result.ema_alignment,
                            "confidence": hp_result.confidence,
                            "oscillator_state": hp_result.oscillator_state,
                            "soh": hp_result.soh,
                            "notes": hp_result.notes,
                            "targets": hp_result.targets,
                        }
                        logger.info(
                            "[Pipeline] %s HiddenPivots: bias=%s pattern=%s ema=%s confidence=%.2f",
                            symbol,
                            hp_result.bias,
                            hp_result.pattern,
                            hp_result.ema_alignment,
                            hp_result.confidence,
                        )
                    else:
                        hp_result = None
                else:
                    hp_result = None
            except Exception as _hp_err:
                logger.debug("[Pipeline] HiddenPivots scan failed (non-fatal): %s", _hp_err)
                hp_result = None
        else:
            hp_result = None

        # ── A1: Inject Hidden Pivots summary into debate context ─────────────
        # analyst_reports["hidden_pivots"] already contains the full dict;
        # add a pre-formatted text line so bull/bear researchers get a clean signal.
        if hp_result is not None and analyst_reports.get("hidden_pivots"):
            _hp = analyst_reports["hidden_pivots"]
            analyst_reports["hidden_pivots_context"] = (
                f"Hidden Pivots Analysis: bias={_hp.get('bias', 0)} | "
                f"pattern={_hp.get('pattern', 'none')} | "
                f"targets={_hp.get('targets', [])} | "
                f"confidence={_hp.get('confidence', 0.0):.2f} | "
                f"ema_alignment={_hp.get('ema_alignment', 'MIXED')}"
            )

        # ── A1: Wire IBLevelProvider — Discord IB report levels ──────────────
        try:
            from datetime import date as _date

            from discord.ib_levels import IBLevelProvider

            _ib_provider = IBLevelProvider()
            _ib_data = _ib_provider.get_levels(symbol, _date.today())
            if _ib_data:
                analyst_reports["ib_levels"] = {
                    "ib_high": _ib_data.get("ib_high"),
                    "ib_low": _ib_data.get("ib_low"),
                    "ib_range": _ib_data.get("ib_range"),
                    "ibu50": _ib_data.get("ibu50"),
                    "ibu100": _ib_data.get("ibu100"),
                    "ibd50": _ib_data.get("ibd50"),
                    "ibd100": _ib_data.get("ibd100"),
                    "auction_context": _ib_data.get("auction_context"),
                    "source": "discord_ib_report",
                }
                # Cross-validate with TV IB if available
                _tv_ib_high = (
                    (analyst_reports.get("technical") or {}).get("indicators", {}).get("tv_ib_high")
                )
                _tv_ib_low = (
                    (analyst_reports.get("technical") or {}).get("indicators", {}).get("tv_ib_low")
                )
                if _tv_ib_high and _ib_data.get("ib_high"):
                    _discord_ib = float(_ib_data["ib_high"])
                    _tv_ib = float(_tv_ib_high)
                    _pct_diff = abs(_discord_ib - _tv_ib) / max(_discord_ib, 0.001) * 100
                    if _pct_diff > 0.5:
                        logger.warning(
                            "[Pipeline] %s IB cross-validation: Discord=%.2f vs TV=%.2f (%.1f%% diff)",
                            symbol,
                            _discord_ib,
                            _tv_ib,
                            _pct_diff,
                        )
                        analyst_reports["ib_levels"][
                            "cross_validation"
                        ] = f"Discord/TV diff={_pct_diff:.1f}%"
                logger.info(
                    "[Pipeline] %s IBLevels: H=%.2f L=%.2f range=%.2f",
                    symbol,
                    _ib_data.get("ib_high", 0),
                    _ib_data.get("ib_low", 0),
                    _ib_data.get("ib_range", 0),
                )
        except Exception as _ib_err:
            logger.debug("[Pipeline] IBLevelProvider failed (non-fatal): %s", _ib_err)

        # ── A1: Unified Discord briefing — aggregates Corey bias + IB levels +
        # keyword sentiment + recent bot signal into a single dict that
        # bull/bear/debate can read without re-wiring 4 providers each.
        # Facade has a 5-min TTL; per-bar cost is negligible after first call.
        # enriched_with_knowledge attaches advisory curated-knowledge hits
        # (knowledge_context) for the agents' prompt context. It is ADVISORY ONLY —
        # gate-v2/sizing/execution never read it — and fully fallback-safe (daemon
        # down → field stays None), so the whole block stays non-fatal.
        try:
            from discord.briefing import get_discord_briefing

            _briefing = await get_discord_briefing(
                symbol, lookback_hours=24, enriched_with_knowledge=True
            )
            analyst_reports["discord_briefing"] = _briefing.to_dict()
            if _briefing.warnings:
                logger.debug(
                    "[Pipeline] Discord briefing warnings for %s: %s",
                    symbol,
                    _briefing.warnings,
                )
        except Exception as _brief_err:
            logger.debug("[Pipeline] Discord briefing failed (non-fatal): %s", _brief_err)

        # ── A2: MES forward-recorder feedback (roadmap P0.5) ──────────────
        # Observational-only injection, MES-only. See _inject_forward_recorder.
        self._inject_forward_recorder(symbol, analyst_reports)

        pipeline_result["analyst_reports"] = analyst_reports

        # ── Pipeline WS: emit analyst signals (fire-and-forget, never blocks) ──
        try:
            from websocket.pipeline_ws import emit_analyst_signals

            asyncio.create_task(emit_analyst_signals(symbol, analyst_reports))
        except Exception:  # pragma: no cover
            pass

        # ── Technical-Only Fallback: LLM credits exhausted ────────────────
        # If all three LLM analysts (news, social, fundamental) failed with
        # Anthropic 400 errors AND technical has a clear STC signal, skip the
        # LLM debate/trader and synthesize directly from technicals.
        _tech_fallback = self._check_technical_only_fallback(symbol, analyst_reports, errors)
        if _tech_fallback is not None:
            pipeline_result.update(_tech_fallback)
            pipeline_result["completed_at"] = datetime.now().isoformat()
            pipeline_result["errors"] = errors
            logger.info(
                "[Pipeline] %s — technical-only fallback complete: action=%s conviction=%s",
                symbol,
                _tech_fallback.get("final_action"),
                _tech_fallback.get("final_conviction", 3),
            )
            return pipeline_result

        # ── Stage 2: Bull/Bear Debate ──────────────────────────────────────

        if self.profiler:
            await self.profiler.start_stage("debate")
        debate_result = await self._run_debate(symbol, analyst_reports, errors)
        if self.profiler:
            await self.profiler.end_stage("debate")
        pipeline_result["debate_result"] = debate_result

        # Adversarial scoring: if the debate is INCONCLUSIVE force HOLD
        # immediately without consulting the TraderAgent.
        debate_verdict = debate_result.get("verdict", "")
        debate_score = debate_result.get("debate_score", 0.0)
        if debate_verdict == "INCONCLUSIVE" and not debate_result.get("scoring_failed", False):
            logger.info(
                f"[Pipeline] {symbol} — debate INCONCLUSIVE "
                f"(debate_score={debate_score:+.3f}); forcing HOLD before TraderAgent"
            )
            hold_decision: dict = {
                "action": "hold",
                "quantity": 0,
                "confidence": 0.0,
                "reasoning": (
                    f"Debate inconclusive (score={debate_score:+.3f}). "
                    "Bull and bear cases are too evenly matched — holding."
                ),
                "risk_notes": "Forced HOLD by debate scoring",
                "timestamp": datetime.now().isoformat(),
                "forced_hold": True,
                "debate_score": debate_score,
                "debate_verdict": debate_verdict,
            }
            pipeline_result["trade_decision"] = hold_decision
            pipeline_result["risk_decision"] = {
                "approved": False,
                "reason": "Forced HOLD — debate inconclusive",
                "forced_hold": True,
            }
            pipeline_result["fund_decision"] = None
            pipeline_result["final_action"] = "hold"
            pipeline_result["final_quantity"] = 0
            pipeline_result["requires_human_approval"] = False
            pipeline_result["completed_at"] = datetime.now().isoformat()
            pipeline_result["errors"] = errors
            return pipeline_result

        logger.info(
            f"[Pipeline] {symbol} — debate verdict={debate_verdict or 'N/A'} "
            f"debate_score={debate_score:+.3f}; proceeding to TraderAgent"
        )

        # ── Stage 3: Trader Decision ───────────────────────────────────────

        if self.profiler:
            await self.profiler.start_stage("trader")
        safety_status = self._safety.get_status()
        trade_decision = await self._run_trader(
            symbol, debate_result, analyst_reports, safety_status, errors
        )
        if self.profiler:
            await self.profiler.end_stage("trader")
        if active_recipe is not None and trade_decision.get("action") not in ("hold", "HOLD"):
            size_mult = float(active_recipe.parameters.size_mult)
            original_qty = int(trade_decision.get("quantity", 0) or 0)
            if original_qty > 0 and size_mult != 1.0:
                scaled_qty = max(1, round(original_qty * size_mult))
                trade_decision["quantity"] = scaled_qty
                trade_decision["reasoning"] = (
                    f"{trade_decision.get('reasoning', '')}\n\n[Recipe] size_mult={size_mult:.2f} scaled quantity {original_qty} -> {scaled_qty}"
                ).strip()
                pipeline_result["recipe_size_adjustment"] = {
                    "size_mult": size_mult,
                    "original_quantity": original_qty,
                    "adjusted_quantity": scaled_qty,
                }

            min_confluence = float(active_recipe.parameters.min_confluence)
            if float(trade_decision.get("confidence", 0.0) or 0.0) < min_confluence:
                trade_decision.update(
                    {
                        "action": "hold",
                        "quantity": 0,
                        "reasoning": (
                            f"{trade_decision.get('reasoning', '')}\n\n[Recipe] confidence below min_confluence "
                            f"({float(trade_decision.get('confidence', 0.0) or 0.0):.2f} < {min_confluence:.2f}); forcing HOLD."
                        ).strip(),
                        "risk_notes": (
                            f"{trade_decision.get('risk_notes', '')} | Recipe confluence floor triggered"
                        ).strip(" |"),
                    }
                )
                pipeline_result["recipe_confluence_gate"] = {
                    "min_confluence": min_confluence,
                    "trade_confidence": float(trade_decision.get("confidence", 0.0) or 0.0),
                    "forced_hold": True,
                }

        pipeline_result["trade_decision"] = trade_decision

        # ── Stage 4: Risk Manager Review ──────────────────────────────────

        if self.profiler:
            await self.profiler.start_stage("risk_manager")
        # We always pass an empty portfolio if none is available — callers should
        # inject a real portfolio dict via a wrapper or subclass
        portfolio = await self._get_portfolio()
        risk_decision = await self._run_risk_manager(
            trade_decision, safety_status, portfolio, errors
        )
        if self.profiler:
            await self.profiler.end_stage("risk_manager")
        pipeline_result["risk_decision"] = risk_decision

        # ── Stage 5: Fund Manager (only if Risk Manager approved) ──────────

        fund_decision: Optional[dict] = None
        if risk_decision.get("approved", False):
            if self.profiler:
                await self.profiler.start_stage("fund_manager")
            open_positions = portfolio.get("positions", [])
            fund_decision = await self._run_fund_manager(
                trade_decision, risk_decision, portfolio, open_positions, errors
            )
            if self.profiler:
                await self.profiler.end_stage("fund_manager")
        else:
            logger.info(f"[Pipeline] Risk Manager vetoed {symbol} — skipping Fund Manager")

        pipeline_result["fund_decision"] = fund_decision

        # ── Resolve final action ───────────────────────────────────────────

        final_action, final_quantity, requires_human = self._resolve_final_action(
            trade_decision, risk_decision, fund_decision
        )

        # ── Futures confidence boost + minimum confidence gate ─────────────
        # Apply futures-specific tuning before committing the final action.
        # Futures (MCL, MNQ, MES) have cleaner technical signals but fewer
        # available analyst inputs (no fundamentals/social), so:
        #   1. Apply a small additive confidence boost to compensate
        #   2. Gate directional signals on instrument-specific min-confidence
        # This prevents low-data HOLDs from leaking through as weak directional
        # signals while also catching genuinely low-confidence reads.
        if final_action not in ("hold", "HOLD"):
            try:
                from config import settings as _cfg

                raw_confidence = float(trade_decision.get("confidence", 0.0))
                if is_futures:
                    boosted = raw_confidence + float(_cfg.FUTURES_CONFIDENCE_BOOST)
                    min_thresh = float(_cfg.FUTURES_MIN_CONFIDENCE_TO_TRADE)
                else:
                    boosted = raw_confidence  # no boost for equities
                    min_thresh = float(_cfg.EQUITY_MIN_CONFIDENCE_TO_TRADE)

                # Also skip zero-weight technical reports (no_price_data abstentions)
                tech_weight = (
                    analyst_reports.get("technical", {})
                    .get("indicators", {})
                    .get("weight", 1.0)  # default 1.0 = normal weight
                )
                if tech_weight == 0.0:
                    logger.warning(
                        "[Pipeline] %s: technical analyst abstained (no_price_data) — "
                        "confidence computed without technical input",
                        symbol,
                    )
                    # Without technical signal, drop below threshold to force HOLD
                    boosted = 0.0

                # ── ConfidenceScorer: symbol-performance adjustment ────────────
                # Multiplies boosted confidence by a factor [0.60, 1.40] derived
                # from win rate and R-ratio of recent trades for this symbol.
                # Wraps in try/except — failure leaves confidence unchanged.
                try:
                    from learning.confidence_scorer import get_confidence_adjustment

                    adjustment = await get_confidence_adjustment(symbol, self._db)
                    adjusted_confidence = boosted * adjustment
                    logger.info(
                        "Confidence adjusted %.2f → %.2f (multiplier: %.2f)",
                        boosted,
                        adjusted_confidence,
                        adjustment,
                    )
                    boosted = adjusted_confidence
                    pipeline_result["confidence_scorer_adjustment"] = round(adjustment, 4)
                except Exception as _cs_err:
                    logger.warning(
                        "[Pipeline] ConfidenceScorer failed (non-fatal), "
                        "using boosted confidence unchanged: %s",
                        _cs_err,
                    )
                    pipeline_result["confidence_scorer_adjustment"] = 1.0

                pipeline_result["raw_confidence"] = round(raw_confidence, 4)
                pipeline_result["boosted_confidence"] = round(boosted, 4)
                pipeline_result["confidence_threshold"] = round(min_thresh, 4)

                if boosted < min_thresh:
                    logger.info(
                        "[Pipeline] %s: confidence %.2f (boosted from %.2f) below threshold %.2f "
                        "— downgrading %s → HOLD",
                        symbol,
                        boosted,
                        raw_confidence,
                        min_thresh,
                        final_action.upper(),
                    )
                    final_action = "hold"
                    final_quantity = 0
                    pipeline_result["confidence_gate_triggered"] = True
                    pipeline_result["confidence_gate_reason"] = (
                        f"boosted_confidence={boosted:.3f} < threshold={min_thresh:.3f}"
                    )
                else:
                    pipeline_result["confidence_gate_triggered"] = False
                    logger.debug(
                        "[Pipeline] %s: confidence %.2f (boosted %.2f) ≥ threshold %.2f — "
                        "%s passes gate",
                        symbol,
                        raw_confidence,
                        boosted,
                        min_thresh,
                        final_action.upper(),
                    )
            except Exception as _cg_err:
                logger.warning("[Pipeline] Confidence gate error (non-fatal): %s", _cg_err)

        pipeline_result["final_action"] = final_action
        pipeline_result["final_quantity"] = final_quantity
        pipeline_result["requires_human"] = requires_human

        # ── A1: Hidden Pivots conviction adjustment ───────────────────────────
        # CONFLICT: HP bias opposes final verdict → reduce boosted_confidence -0.15
        # CONFIRMS: HP bias aligns with final verdict → boost boosted_confidence +0.10
        # Never overrides verdict — only adjusts confidence score.
        if hp_result is not None and final_action not in ("hold", "HOLD"):
            _hp_bias = hp_result.bias  # "LONG" | "SHORT" | "WATCH" | "SOH"
            _action_is_long = final_action.lower() == "buy"
            _action_is_short = final_action.lower() == "sell"
            _hp_conflicts = (_hp_bias == "LONG" and _action_is_short) or (
                _hp_bias == "SHORT" and _action_is_long
            )
            _hp_confirms = (_hp_bias == "LONG" and _action_is_long) or (
                _hp_bias == "SHORT" and _action_is_short
            )
            _old_boosted = pipeline_result.get("boosted_confidence", 0.0)
            if _hp_conflicts:
                _new_boosted = max(0.0, _old_boosted - 0.15)
                pipeline_result["boosted_confidence"] = round(_new_boosted, 4)
                pipeline_result["hp_conflict"] = True
                pipeline_result["hp_confirms"] = False
                pipeline_result["hp_bias"] = _hp_bias
                logger.warning(
                    "[Pipeline] %s HiddenPivots CONFLICT: HP=%s but final_action=%s — "
                    "reducing conviction %.2f → %.2f (-0.15, not overriding verdict)",
                    symbol,
                    _hp_bias,
                    final_action.upper(),
                    _old_boosted,
                    _new_boosted,
                )
            elif _hp_confirms:
                _new_boosted = min(1.0, _old_boosted + 0.10)
                pipeline_result["boosted_confidence"] = round(_new_boosted, 4)
                pipeline_result["hp_conflict"] = False
                pipeline_result["hp_confirms"] = True
                pipeline_result["hp_bias"] = _hp_bias
                logger.info(
                    "[Pipeline] %s HiddenPivots CONFIRMS: HP=%s aligns with final_action=%s — "
                    "boosting conviction %.2f → %.2f (+0.10)",
                    symbol,
                    _hp_bias,
                    final_action.upper(),
                    _old_boosted,
                    _new_boosted,
                )
            else:
                # WATCH / SOH — neutral, no adjustment
                pipeline_result["hp_conflict"] = False
                pipeline_result["hp_confirms"] = False
                pipeline_result["hp_bias"] = _hp_bias

        completed_at = datetime.now()
        pipeline_result["completed_at"] = completed_at.isoformat()
        elapsed = (completed_at - started_at).total_seconds()

        # ── Human-readable summary line ────────────────────────────────────────
        regime = analyst_reports.get("technical", {}).get("regime", "UNKNOWN")
        trend = analyst_reports.get("technical", {}).get("trend", "UNKNOWN")
        confidence = fund_decision.get("final_conviction", 0.0) if fund_decision else 0.0
        pipeline_result["summary"] = (
            f"{symbol} | regime={regime} trend={trend} | "
            f"action={final_action.upper()} qty={final_quantity} | "
            f"conviction={confidence:.0%} human={requires_human}"
        )

        logger.info(
            f"[Pipeline] {symbol} complete in {elapsed:.1f}s — "
            f"final_action={final_action} qty={final_quantity} "
            f"requires_human={requires_human} errors={len(errors)}"
        )

        # ── Log decisions to PostgreSQL (audit trail) ──────────────────────────
        await self._log_pipeline_to_postgres(symbol, pipeline_result, trade_decision, errors)

        # ── Cache the pipeline result (signal caching for next 30 minutes) ───────────
        if _CACHE_AVAILABLE:
            try:
                await cache_signal(symbol, pipeline_result)
                logger.debug(f"[Pipeline] Cached signal for {symbol} (TTL=30min)")
            except Exception as e:
                logger.debug(f"[Pipeline] Failed to cache signal: {e}")

        # Emit WebSocket event for pipeline completion
        try:
            from websocket.events import emit_pipeline_complete

            timing = {
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "elapsed_seconds": elapsed,
            }
            asyncio.create_task(emit_pipeline_complete(symbol, final_action, timing))
        except ImportError:
            # WebSocket module may not be available in all contexts (e.g., backtesting)
            pass
        except Exception as e:
            logger.debug(f"Failed to emit pipeline_complete event: {e}")

        # ── Pipeline WS: emit verdict to subscribed dashboard clients ────────
        # Fire-and-forget via create_task — broadcast failure NEVER affects pipeline.
        try:
            from websocket.pipeline_ws import emit_verdict

            _verdict_payload = {
                "final_action": final_action,
                "final_quantity": final_quantity,
                "requires_human": requires_human,
                "confidence": float(
                    fund_decision.get("final_conviction", 0.0) if fund_decision else 0.0
                ),
                "regime": analyst_reports.get("technical", {}).get("regime", "UNKNOWN"),
                "elapsed_seconds": elapsed,
            }
            asyncio.create_task(emit_verdict(symbol, _verdict_payload))
        except Exception:  # pragma: no cover
            pass

        # Add cache_hit flag for logging
        pipeline_result["cache_hit"] = False

        # Finish profiler run (stores report in history)
        if self.profiler:
            await self.profiler.finish_run()

        # Publish pipeline result event
        try:
            from events.bus import publish as publish_event

            _ev_action = pipeline_result.get("final_action", "HOLD").upper()
            _ev_conviction = pipeline_result.get("boosted_confidence", 0.0)
            publish_event(
                "pipeline_run",
                f"{symbol} → {_ev_action} confidence={_ev_conviction:.0%}",
                symbol=symbol,
                severity="info",
            )
        except Exception as e:
            logger.warning(f"Failed to publish pipeline event: {e}")

        # ── Multi-channel signal broadcast on LONG / SHORT signals ─────────────
        # One fan-out to every enabled channel (Telegram / Discord / WhatsApp /
        # Windows toast). The shared per-symbol cooldown inside broadcast_signal
        # dedupes the redundant call sites in main.py and pipeline_router.py.
        if final_action.lower() not in ("hold", "pending_human_approval"):
            try:
                from notifications.signal_broadcast import broadcast_signal

                asyncio.create_task(broadcast_signal(symbol, pipeline_result, source="pipeline"))
                logger.info(
                    f"[Pipeline] Signal broadcast queued for {symbol} {final_action.upper()}"
                )
            except Exception as _bc_err:
                logger.warning(f"[Pipeline] Signal broadcast failed (non-fatal): {_bc_err}")

        # ── Automated Shadow Mode Logging (P1.5) ───────────────────────────
        # If the symbol is blocklisted (DO_NOT_TRADE_SYMBOLS) but the pipeline
        # emitted a signal, log it to the shadow tracker for walk-forward validation.
        if self._shadow_tracker and final_action.lower() in ("buy", "sell"):
            try:
                from backtest.signals import DO_NOT_TRADE_SYMBOLS

                if symbol.upper() in DO_NOT_TRADE_SYMBOLS:
                    _px = (
                        trade_decision.get("limit_price")
                        or trade_decision.get("stop_price")
                        or trade_decision.get("entry_price")
                        or 0.0
                    )
                    _stark_sig = (
                        analyst_reports.get("technical", {})
                        .get("indicators", {})
                        .get("stark_signal", "unknown")
                    )
                    self._shadow_tracker.log_shadow_entry(
                        symbol=symbol,
                        side=final_action,
                        quantity=float(final_quantity),
                        price=float(_px),
                        strategy_name=_stark_sig,
                        reasoning=trade_decision.get("reasoning", ""),
                        stop_loss=trade_decision.get("stop_price"),
                        take_profit=trade_decision.get("target_price"),
                    )
                    logger.info("[Shadow] Auto-logged blocklisted signal for %s", symbol)
            except Exception as _sh_err:
                logger.warning("[Pipeline] Shadow logging failed (non-fatal): %s", _sh_err)

        # ── Phase 3.5: Working Memory Storage ───────────────────────────
        # Store high-confidence or actionable reasoning for future recall.
        if self._memory and final_action.lower() in ("buy", "sell"):
            try:
                self._memory.remember(
                    agent_name="trader",
                    content=trade_decision.get("reasoning", "")[:500],  # Keep snippets concise
                    symbol=symbol,
                    topic="trade_thesis",
                    metadata={
                        "action": final_action,
                        "confidence": float(
                            fund_decision.get("final_conviction", 0.0) if fund_decision else 0.0
                        ),
                    },
                )
            except Exception as _mem_err:
                logger.warning("[Pipeline] Working memory storage failed (non-fatal): %s", _mem_err)

        return pipeline_result

    # ── Technical-Only Fallback Helpers ───────────────────────────────────

    @staticmethod
    def _is_anthropic_400_error(err_str: str) -> bool:
        """
        Return True if the error string suggests an Anthropic HTTP 400 (credits / billing).

        Anthropic credit exhaustion surfaces as HTTP 400 with body mentioning
        "credit_balance_too_low" or similar.  httpx raises it as:
          "Client error '400 Bad Request' for url 'https://api.anthropic.com/...'"
        """
        low = err_str.lower()
        # Explicit Anthropic 400: URL references api.anthropic.com + 4xx indicator
        has_anthropic_url = "api.anthropic.com" in low or "anthropic" in low
        has_4xx = "400" in low or "bad request" in low or "client error" in low
        # Explicit credit/billing mention regardless of status code
        has_credit_ref = any(
            kw in low for kw in ("credit", "billing", "credit_balance", "insufficient")
        )
        return (has_anthropic_url and has_4xx) or (has_anthropic_url and has_credit_ref)

    @staticmethod
    def _extract_technical_stc(analyst_reports: dict) -> Optional[float]:
        """
        Pull the latest STC value from the technical analyst report.
        Returns None if unavailable or NaN.
        """
        try:
            stc = analyst_reports.get("technical", {}).get("indicators", {}).get("stc")
            if stc is None:
                return None
            val = float(stc)
            if val != val:  # NaN check
                return None
            return val
        except Exception:
            return None

    @staticmethod
    def _stc_to_action(stc_val: float) -> tuple[str, str]:
        """
        Map STC value to a directional action using canonical JARVIS thresholds (OS=15, OB=83).

        Returns: (action, signal_description)
          action is "buy" | "sell" | "hold"
        """
        STC_OS = 15
        STC_OB = 83
        if stc_val < STC_OS:
            return "buy", "OVERSOLD"
        elif stc_val > STC_OB:
            return "sell", "OVERBOUGHT"
        else:
            return "hold", "NEUTRAL"

    def _inject_forward_recorder(self, symbol: str, analyst_reports: dict) -> None:
        """Attach the MES forward-recorder metric to analyst_reports.

        Roadmap P0.5. MES-only: the 08:30 CT / 15:15 CT recorder is a dedicated
        experiment (see ``experiments/mes_session_*.py``). Observational — never
        blocks the pipeline. Swallows all errors so a missing DB/table can never
        break signal generation.

        Mutates ``analyst_reports`` in-place. Adds a single key
        ``forward_recorder_metric`` with ``hit_rate``, ``samples``, ``degraded``,
        and ``last_hypothesis`` entries. The downstream agent prompts (bull /
        bear / trader) serialize ``analyst_reports`` to JSON and pass it through
        to the LLM, so the metric becomes prompt-visible without any prompt
        rewrite.
        """
        if symbol.upper() != "MES":
            return
        try:
            from experiments.feedback_aggregator import (
                get_last_session_hypothesis,
                get_recent_hit_rate,
            )

            hit_rate, samples = get_recent_hit_rate(n=10, max_age_days=14)
            last = get_last_session_hypothesis()
            analyst_reports["forward_recorder_metric"] = {
                "hit_rate": hit_rate,
                "samples": samples,
                "degraded": samples < 5,
                "last_hypothesis": last,
            }
        except Exception as exc:
            logger.debug("[Pipeline] forward_recorder_metric failed (non-fatal): %s", exc)

    def _check_technical_only_fallback(
        self,
        symbol: str,
        analyst_reports: dict,
        errors: list,
    ) -> Optional[dict]:
        """
        Check whether to activate technical-only mode.

        Conditions:
          - All three LLM analysts (news, social, fundamental) failed with errors
            that match Anthropic 400 patterns (credits exhausted / billing)
          - Technical analyst has a valid STC in oversold (<15) or overbought (>83) territory

        Returns a partial pipeline_result update dict if fallback fires, or None to continue.
        """
        # Count how many of the three LLM analyst errors look like Anthropic 400s
        llm_agent_names = (
            "news analyst failed",
            "social analyst failed",
            "fundamental analyst failed",
        )
        llm_400_errors = [
            e
            for e in errors
            if any(name in e.lower() for name in llm_agent_names)
            and self._is_anthropic_400_error(e)
        ]

        # Need all three LLM analysts to have failed with 400 to activate fallback
        if len(llm_400_errors) < 3:
            return None

        stc_val = self._extract_technical_stc(analyst_reports)
        if stc_val is None:
            logger.warning(
                "[Pipeline] %s — all LLM analysts failed (Anthropic 400) but STC unavailable; "
                "cannot use technical-only fallback → HOLD",
                symbol,
            )
            return None

        stc_action, stc_signal = self._stc_to_action(stc_val)

        logger.warning(
            "[Pipeline] %s — LLM credits exhausted, using technical-only fallback. "
            "STC=%.1f, signal=%s, conviction=3/10",
            symbol,
            stc_val,
            stc_signal,
        )

        if stc_action == "hold":
            logger.info(
                "[Pipeline] %s — technical-only fallback: STC=%.1f is NEUTRAL → HOLD",
                symbol,
                stc_val,
            )
            return {
                "final_action": "hold",
                "final_quantity": 0,
                "requires_human": False,
                "technical_only_mode": True,
                "technical_only_stc": round(stc_val, 2),
                "technical_only_signal": stc_signal,
                "trade_decision": {
                    "symbol": symbol,
                    "action": "hold",
                    "quantity": 0,
                    "signal_score": 0.0,
                    "confidence": 0.0,
                    "reasoning": (
                        f"LLM credits exhausted — technical-only mode. "
                        f"STC={stc_val:.1f} (NEUTRAL — no actionable signal). HOLD."
                    ),
                    "risk_notes": "Technical-only mode — STC mid-range, no edge",
                    "technical_only_mode": True,
                    "timestamp": datetime.now().isoformat(),
                },
                "risk_decision": {"approved": False, "reason": "Technical-only NEUTRAL → HOLD"},
                "fund_decision": None,
                "summary": (
                    f"{symbol} | technical-only mode | STC={stc_val:.1f} NEUTRAL | "
                    "action=HOLD conviction=3/10"
                ),
            }

        # Directional signal — build minimal trade/risk/fund decisions
        conviction = 3
        quantity = 1
        trade_decision = {
            "symbol": symbol,
            "action": stc_action,
            "quantity": quantity,
            "order_type": "market",
            "limit_price": None,
            "stop_price": None,
            "time_in_force": "day",
            "signal_score": 0.3 if stc_action == "buy" else -0.3,
            "confidence": 0.3,
            "reasoning": (
                f"LLM credits exhausted — technical-only mode. "
                f"STC={stc_val:.1f} ({stc_signal}). "
                f"Conviction={conviction}/10 (pure technical, no LLM synthesis)."
            ),
            "risk_notes": "Technical-only mode — reduced conviction",
            "technical_only_mode": True,
            "technical_only_stc": round(stc_val, 2),
            "technical_only_signal": stc_signal,
            "timestamp": datetime.now().isoformat(),
        }
        risk_decision = {
            "approved": True,
            "veto_reason": None,
            "modified_quantity": quantity,
            "modified_limit_price": None,
            "risk_score": 0.5,
            "reasoning": "Technical-only fallback — risk auto-approved at minimum size",
            "timestamp": datetime.now().isoformat(),
        }
        # Human-approval gate honors the REQUIRE_HUMAN_APPROVAL flag even in
        # degraded technical-only mode (owner directive 2026-06-15).
        from config import settings as _cfg

        _require_human = bool(_cfg.REQUIRE_HUMAN_APPROVAL)
        fund_decision = {
            "approved": True,
            "final_quantity": quantity,
            "priority": "immediate",
            "portfolio_impact": "Technical-only fallback — minimum size",
            "reasoning": f"Technical-only mode: STC={stc_val:.1f} {stc_signal} conviction={conviction}/10",
            "requires_human_approval": _require_human,
            "timestamp": datetime.now().isoformat(),
        }
        return {
            "final_action": stc_action,
            "final_quantity": quantity,
            "requires_human": _require_human,
            "technical_only_mode": True,
            "technical_only_stc": round(stc_val, 2),
            "technical_only_signal": stc_signal,
            "final_conviction": conviction / 10.0,
            "trade_decision": trade_decision,
            "risk_decision": risk_decision,
            "fund_decision": fund_decision,
            "summary": (
                f"{symbol} | technical-only mode | STC={stc_val:.1f} {stc_signal} | "
                f"action={stc_action.upper()} qty={quantity} | conviction={conviction}/10 "
                f"human={_require_human}"
            ),
        }

    # ── Stage Runners ──────────────────────────────────────────────────────

    async def _run_analysts(
        self,
        symbol: str,
        is_futures: bool,
        errors: list,
        timeframe: str = "1h",
    ) -> dict:
        """Run all four analysts concurrently via asyncio.gather."""

        async def safe_analyze(name: str, coro) -> dict:
            try:
                report = await coro
                # Support both dataclasses with to_dict() and plain dicts
                if hasattr(report, "to_dict"):
                    result = report.to_dict()
                elif isinstance(report, dict):
                    result = report
                else:
                    result = {
                        "signal": 0.0,
                        "confidence": 0.0,
                        "summary": f"{name} returned unexpected type",
                    }
                # Detect and log zero-weight abstentions
                # (e.g. technical analyst returning no_price_data)
                indicators = result.get("indicators", {})
                if isinstance(indicators, dict) and indicators.get("weight") == 0.0:
                    reason = indicators.get("reason", "unknown")
                    logger.warning(
                        "[Pipeline] %s analyst abstained (weight=0.0, reason=%s) — "
                        "excluded from confidence computation",
                        name,
                        reason,
                    )
                return result
            except Exception as e:
                err = f"{name} analyst failed: {e}"
                logger.warning(f"[Pipeline] {err}")
                errors.append(err)
                return {"signal": 0.0, "confidence": 0.0, "summary": f"{name} unavailable"}

        # Fetch historical edge context before Stage 1 (non-blocking — empty string on failure)
        historical_context = ""
        try:
            from learning.recommendations import get_recommendations

            recs = await get_recommendations(symbol)
            if recs:
                historical_context = "\n\nHistorical edge context:\n" + "\n".join(
                    f"- {r}" for r in recs
                )

            # Phase 3.5: Working Memory Recall
            if self._memory:
                working_memory = self._memory.recall(
                    agent_name="technical-analyst", symbol=symbol, topic="general", limit=3
                )
                if working_memory:
                    historical_context = f"{working_memory}\n{historical_context}"

        except Exception:
            pass  # learning context is optional — never block the pipeline

        # Stage 0: Regime Analysis (Deterministic)
        # Note: Requires access to data manager or bars; assuming technical agent provides access
        # or we fetch here. For this implementation, we assume the technical agent's data manager.
        _tech_agent = self._agents.get("technical")
        _data_mgr = getattr(_tech_agent, "_data", None)
        df = None
        if _data_mgr:
            try:
                df = await _data_mgr.get_bars(
                    symbol, lookback_days=30, timeframe=timeframe, is_futures=is_futures
                )
            except Exception as exc:
                logger.warning("regime prefetch failed — continuing without regime data: %s", exc)
                df = None

        # Phase 5.2: Intraday Regime V2
        regime_report = self._regime_engine.classify_latest(df) if df is not None else None
        regime_name = regime_report["regime"] if regime_report else "RANGE"

        # Build compatibility object for prompts
        # RegimeClassifierV2 uses uppercase values (RANGE, TREND, …); legacy
        # MarketRegime enum uses lowercase (ranging, trending, …). Map first,
        # then fall back to NEUTRAL so an unmapped value never crashes the run.
        _REGIME_V2_MAP = {
            "range": "ranging",
            "trend": "trending",
            "volatile": "volatile",
            "meanrev": "ranging",
            "crisis": "volatile",
        }
        regime_status = None
        if regime_report:
            regime_str = regime_report["regime"].lower()
            regime_str = _REGIME_V2_MAP.get(regime_str, regime_str)
            try:
                _regime_enum = _LegacyRegime(regime_str)
            except ValueError:
                logger.debug(
                    "[Pipeline] Unmapped regime value %r — defaulting to NEUTRAL", regime_str
                )
                _regime_enum = _LegacyRegime("neutral")
            regime_status = RegimeStatus(
                regime=_regime_enum,
                adx=0.0,  # ADX not in V2 directly
                atr_ratio=regime_report.get("atr_norm", 1.0),
                volatility=0.0,
                description=regime_report.get("description", ""),
            )
            logger.info(
                "[Pipeline] %s — Regime V2 classified as %s",
                symbol,
                regime_name,
            )

        # ── Phase 8.2: Regime-Router Logic ──
        regime_override: dict = {}
        if regime_name in ("CRISIS", "VOLATILE"):
            logger.warning(
                f"[Pipeline] 🛡️ Regime Routing: {regime_name} detected. Blocking new entries."
            )
            regime_override = {
                "blocked": True,
                "reason": f"Systemic risk protection: {regime_name} regime detected.",
            }

        # ── X-bookmark edge overlay (Phase 3): advisory macro trend bias ──
        # Flag-gated (ENABLE_MACRO_TREND_BIAS, default off). Folds the market-wide
        # SPX trend regime (weekly Supertrend + monthly momentum) into the LLM's
        # regime context as ADVISORY text — never a mechanical gate, never touches
        # trader.py, and never overrides the CRISIS/VOLATILE hard-block above. When
        # the flag is off (or anything raises), macro_ctx == "" so the injected
        # context is byte-identical to baseline. Every injection is shadow-logged.
        macro_ctx = ""
        try:
            from flags.registry import get_flags

            if get_flags().is_enabled("ENABLE_MACRO_TREND_BIAS"):
                from backtest.macro_regime import compute_macro_regime

                _mr = compute_macro_regime()
                if _mr.get("bias_line"):
                    macro_ctx = f"\n{_mr['bias_line']}"
                    logger.info(
                        "[Pipeline] %s — macro trend bias (%s) injected: %s",
                        symbol,
                        _mr.get("state"),
                        _mr["bias_line"],
                    )
                    # Effect telemetry: durable record of every overlay injection so the
                    # bias can be reviewed against the resulting decision/outcome (join on
                    # symbol + ts against the decision log / trades DB). Best-effort;
                    # a telemetry failure must never affect the trading pipeline.
                    try:
                        import json as _json
                        from datetime import datetime, timezone
                        from pathlib import Path

                        _tel = (
                            Path(__file__).resolve().parents[1]
                            / "data"
                            / "macro_overlay_telemetry.jsonl"
                        )
                        _tel.parent.mkdir(parents=True, exist_ok=True)
                        with _tel.open("a", encoding="utf-8") as _fh:
                            _fh.write(
                                _json.dumps(
                                    {
                                        "ts": datetime.now(timezone.utc).isoformat(),
                                        "symbol": symbol,
                                        "state": _mr.get("state"),
                                        "weekly_trend": _mr.get("weekly_trend"),
                                        "monthly_momentum": _mr.get("monthly_momentum"),
                                        "asof": _mr.get("asof"),
                                        "stale_days": _mr.get("stale_days"),
                                        "bias_line": _mr.get("bias_line"),
                                    }
                                )
                                + "\n"
                            )
                    except Exception as _tel_exc:
                        logger.debug("[Pipeline] macro telemetry skipped: %s", _tel_exc)
        except Exception as _macro_exc:  # fail-safe: never break the pipeline
            logger.debug("[Pipeline] macro trend bias skipped: %s", _macro_exc)

        # Stage 1a: Run technical analyst first
        technical_coro = self._call_agent_analyze(
            "technical",
            symbol,
            is_futures=is_futures,
            timeframe=timeframe,
            historical_context=f"{historical_context}\nREGIME CONTEXT: Market is currently {regime_name}. "
            f"Prioritize {'Trend-Following' if 'TREND' in regime_name else 'Mean-Reversion'} setups.{macro_ctx}",
        )
        technical_result = await safe_analyze("technical", technical_coro)

        # Extract current_price and ATR from technical result for Corey proximity boost
        current_price = float(technical_result.get("current_price") or 0.0)
        atr = float((technical_result.get("indicators") or {}).get("atr") or 0.0)

        # Stage 1b: Run remaining analysts in parallel with real price/ATR values
        news_coro = self._call_agent_analyze("news", symbol)
        social_coro = self._call_agent_analyze("social", symbol)
        fundamental_coro = self._call_agent_analyze("fundamental", symbol)
        corey_coro = self._call_agent_analyze("corey", symbol, current_price=current_price, atr=atr)
        breakout_coro = self._call_agent_analyze(
            "breakout", symbol, is_futures=is_futures, timeframe=timeframe
        )
        harmonic_coro = self._call_agent_analyze(
            "harmonic", symbol, is_futures=is_futures, timeframe=timeframe
        )
        kronos_coro = self._call_agent_analyze_kronos(symbol, is_futures, timeframe)
        options_coro = self._call_agent_analyze_options(
            symbol, current_price, underlying_bias=technical_result.get("bias", "NEUTRAL")
        )

        # Phase 3.7: Pattern Vision Analysis
        if self._vision_agent is not None:
            vision_coro = self._vision_agent.analyze(symbol, bias="NEUTRAL")
        else:

            async def _vision_unavailable():
                return {
                    "visual_verdict": "UNAVAILABLE",
                    "reasoning": "playwright not installed",
                    "data_quality": "unavailable",
                }

            vision_coro = _vision_unavailable()

        results = await asyncio.gather(
            safe_analyze("news", news_coro),
            safe_analyze("social", social_coro),
            safe_analyze("fundamental", fundamental_coro),
            safe_analyze("corey", corey_coro),
            safe_analyze("breakout", breakout_coro),
            safe_analyze("harmonic", harmonic_coro),
            safe_analyze("kronos", kronos_coro),
            safe_analyze("options", options_coro),
            safe_analyze("vision", vision_coro),
        )

        return {
            "technical": technical_result,
            "news": results[0],
            "social": results[1],
            "fundamental": results[2],
            "corey": results[3],
            "breakout": results[4],
            "harmonic": results[5],
            "kronos": results[6],
            "options": results[7],
            "vision": results[8],
            "regime_status": regime_status,
            "regime_override": regime_override,
        }

    async def _call_agent_analyze(self, agent_name: str, symbol: str, **kwargs):
        """Delegates to the named agent's analyze() method, or returns neutral if absent."""
        agent = self._agents.get(agent_name)
        if agent is None:
            return {"signal": 0.0, "confidence": 0.0, "summary": f"{agent_name} unavailable"}
        return await agent.analyze(symbol, **kwargs)

    @property
    def _options_analyst_or_none(self):
        """Return an OptionsAnalyst when ENABLE_OPTIONS_ANALYST=1, else None. Re-checked on each access."""
        from agents.options_analyst import OptionsAnalyst, is_options_analyst_enabled

        if not is_options_analyst_enabled():
            self._options_analyst_cached = None
            return None
        if not hasattr(self, "_options_analyst_cached") or self._options_analyst_cached is None:
            self._options_analyst_cached = OptionsAnalyst()
        return self._options_analyst_cached

    async def _call_agent_analyze_options(
        self, symbol: str, spot_price: Optional[float], underlying_bias: str = "NEUTRAL"
    ) -> dict:
        """Call the OptionsAnalyst if enabled, else return a neutral disabled dict."""
        analyst = self._options_analyst_or_none
        if analyst is None:
            return {
                "signal": 0.0,
                "confidence": 0.0,
                "summary": "options analyst disabled",
                "indicators": {"weight": 0.0},
            }
        try:
            return await analyst.analyze(symbol, spot_price=spot_price)
        except Exception as exc:
            logger.warning("[Pipeline] OptionsAnalyst failed: %s", exc)
            return {
                "signal": 0.0,
                "confidence": 0.0,
                "summary": f"options analyst error: {exc}",
                "indicators": {"weight": 0.0},
            }

    @property
    def _kronos_or_none(self) -> "KronosClassifier | None":
        """Return a ``KronosClassifier`` instance when ``ENABLE_KRONOS=1``, else ``None``.

        Re-checks the env flag on every access (no startup caching) so that
        ``/admin/feature-flags`` toggles take effect without an engine restart.
        The instance itself is cached in ``_kronos_cached`` until the flag flips
        off, avoiding repeated construction overhead during a single run.
        """
        if not is_kronos_enabled():
            self._kronos_cached = None  # type: ignore[attr-defined]
            return None
        if not hasattr(self, "_kronos_cached") or self._kronos_cached is None:
            self._kronos_cached = KronosClassifier()  # type: ignore[attr-defined]
        return self._kronos_cached  # type: ignore[attr-defined]

    async def _call_agent_analyze_kronos(
        self, symbol: str, is_futures: bool, timeframe: str
    ) -> dict:
        """Run the Kronos classifier and return a debate-compatible dict.

        Returns a neutral dict when Kronos is disabled (``ENABLE_KRONOS != "1"``),
        when data is unavailable, or when fewer than ``MIN_BARS`` rows are present.
        ``classify()`` now accepts a ``pd.DataFrame`` directly (paper schema);
        no ``.to_dict("records")`` conversion needed.
        """
        kronos = self._kronos_or_none
        if kronos is None:
            return {"signal": 0.0, "confidence": 0.0, "summary": "Kronos disabled"}
        try:
            _tech = self._agents.get("technical")
            _data_mgr = getattr(_tech, "_data", None)
            if _data_mgr is None:
                return {"signal": 0.0, "confidence": 0.0, "summary": "data unavailable"}
            df = await _data_mgr.get_bars(
                symbol, lookback_days=10, timeframe=timeframe, is_futures=is_futures
            )
            if df is None or df.empty or len(df) < 20:
                return {"signal": 0.0, "confidence": 0.0, "summary": "insufficient bars"}
            # Pass the DataFrame and symbol directly — classify() validates shape
            # internally and uses the per-instrument calibrated threshold.
            result = await kronos.classify(df, symbol=symbol)
            return result
        except Exception as e:
            logger.warning("[Pipeline] Kronos classify failed: %s", e)
            return {"signal": 0.0, "confidence": 0.0, "summary": f"Kronos error: {e}"}

    async def _run_debate(
        self,
        symbol: str,
        analyst_reports: dict,
        errors: list,
    ) -> dict:
        """Run the bull/bear debate. Returns neutral dict on failure."""
        try:
            bull_agent = self._agents.get("bull")
            bear_agent = self._agents.get("bear")
            debate_agent = self._agents.get("debate")

            if not all([bull_agent, bear_agent, debate_agent]):
                logger.debug("[Pipeline] Bull/bear/debate agents not configured — skipping debate")
                return {
                    "verdict": "neutral",
                    "bull_score": 0.5,
                    "bear_score": 0.5,
                    "summary": "Debate agents not configured",
                    "bull_arguments": [],
                    "bear_arguments": [],
                }

            # Debate orchestrator runs bull + bear internally.
            # Pass the regime string from TechnicalAnalystAgent so the debate
            # can use adaptive verdict thresholds (see REGIME_DEBATE_THRESHOLDS).
            _regime_str: Optional[str] = (
                analyst_reports.get("technical", {}).get("regime")
                if isinstance(analyst_reports.get("technical"), dict)
                else None
            )
            debate_result = await debate_agent.run_debate(
                symbol=symbol,
                analyst_reports=analyst_reports,
                bull=bull_agent,
                bear=bear_agent,
                regime=_regime_str,
            )

            # Normalise to dict
            if hasattr(debate_result, "to_dict"):
                return debate_result.to_dict()
            elif isinstance(debate_result, dict):
                return debate_result
            else:
                return {"verdict": "neutral", "summary": str(debate_result)}

        except Exception as e:
            err = f"Debate stage failed: {e}"
            logger.warning(f"[Pipeline] {err}")
            errors.append(err)
            return {
                "verdict": "neutral",
                "bull_score": 0.5,
                "bear_score": 0.5,
                "summary": "Debate failed — defaulting to neutral",
                "bull_arguments": [],
                "bear_arguments": [],
            }

    async def _run_trader(
        self,
        symbol: str,
        debate_result: dict,
        analyst_reports: dict,
        safety_status: dict,
        errors: list,
    ) -> dict:
        """Run the Trader agent. Returns HOLD on failure."""
        try:
            trader = self._agents.get("trader")
            if trader is None:
                logger.warning("[Pipeline] Trader agent not configured")
                return {
                    "symbol": symbol,
                    "action": "hold",
                    "quantity": 0,
                    "order_type": "market",
                    "limit_price": None,
                    "stop_price": None,
                    "time_in_force": "day",
                    "signal_score": 0.0,
                    "confidence": 0.0,
                    "reasoning": "Trader agent not configured",
                    "risk_notes": "Pipeline misconfiguration",
                    "timestamp": datetime.now().isoformat(),
                }

            decision = await trader.decide(symbol, debate_result, analyst_reports, safety_status)
            return decision.to_dict() if hasattr(decision, "to_dict") else decision

        except Exception as e:
            err = f"Trader stage failed: {e}"
            logger.error(f"[Pipeline] {err}")
            errors.append(err)

            # ── Last-resort STC fallback: TraderAgent also hit LLM 400 ───────
            # If this is an Anthropic 400 (credits exhausted), try to act on
            # the raw STC value from the technical analyst report.
            if self._is_anthropic_400_error(str(e)):
                stc_val = self._extract_technical_stc(analyst_reports)
                if stc_val is not None:
                    stc_action, stc_signal = self._stc_to_action(stc_val)
                    if stc_action != "hold":
                        logger.warning(
                            "[Pipeline] %s — LLM credits exhausted, using technical-only "
                            "fallback (TraderAgent). STC=%.1f, signal=%s, conviction=3/10",
                            symbol,
                            stc_val,
                            stc_signal,
                        )
                        return {
                            "symbol": symbol,
                            "action": stc_action,
                            "quantity": 1,
                            "order_type": "market",
                            "limit_price": None,
                            "stop_price": None,
                            "time_in_force": "day",
                            "signal_score": 0.3 if stc_action == "buy" else -0.3,
                            "confidence": 0.3,
                            "reasoning": (
                                f"LLM credits exhausted — TraderAgent offline. "
                                f"Last-resort STC fallback: STC={stc_val:.1f} ({stc_signal}). "
                                f"Conviction=3/10 (technical-only)."
                            ),
                            "risk_notes": "Technical-only last-resort — no LLM synthesis",
                            "technical_only_mode": True,
                            "technical_only_stc": round(stc_val, 2),
                            "technical_only_signal": stc_signal,
                            "timestamp": datetime.now().isoformat(),
                        }

            return {
                "symbol": symbol,
                "action": "hold",
                "quantity": 0,
                "order_type": "market",
                "limit_price": None,
                "stop_price": None,
                "time_in_force": "day",
                "signal_score": 0.0,
                "confidence": 0.0,
                "reasoning": f"Trader agent exception: {e}",
                "risk_notes": "LLM failure — defaulting to HOLD",
                "timestamp": datetime.now().isoformat(),
            }

    async def _run_risk_manager(
        self,
        trade_decision: dict,
        safety_status: dict,
        portfolio: dict,
        errors: list,
    ) -> dict:
        """Run the Risk Manager. Approves trivially on failure to avoid blocking holds."""
        try:
            risk_manager = self._agents.get("risk_manager")
            if risk_manager is None:
                logger.warning("[Pipeline] Risk Manager not configured — auto-approving")
                return {
                    "approved": True,
                    "veto_reason": None,
                    "modified_quantity": None,
                    "modified_limit_price": None,
                    "risk_score": 0.5,
                    "reasoning": "Risk Manager not configured — passed without review",
                    "timestamp": datetime.now().isoformat(),
                }

            risk = await risk_manager.review(trade_decision, safety_status, portfolio)
            return risk.to_dict() if hasattr(risk, "to_dict") else risk

        except Exception as e:
            err = f"Risk Manager stage failed: {e}"
            logger.error(f"[Pipeline] {err}")
            errors.append(err)
            return {
                "approved": False,
                "veto_reason": f"Risk Manager exception: {e}",
                "modified_quantity": None,
                "modified_limit_price": None,
                "risk_score": 1.0,
                "reasoning": f"Risk Manager failed with exception: {e}. Defaulting to VETO for safety.",
                "timestamp": datetime.now().isoformat(),
            }

    async def _run_fund_manager(
        self,
        trade_decision: dict,
        risk_decision: dict,
        portfolio: dict,
        open_positions: list,
        errors: list,
    ) -> dict:
        """Run the Fund Manager. Approves conservatively on failure."""
        try:
            fund_manager = self._agents.get("fund_manager")
            if fund_manager is None:
                logger.warning("[Pipeline] Fund Manager not configured — auto-approving")
                qty = risk_decision.get("modified_quantity") or trade_decision.get("quantity", 0)
                from config import settings as _cfg

                return {
                    "approved": True,
                    "final_quantity": int(qty),
                    "priority": "immediate",
                    "portfolio_impact": "Fund Manager not configured — passed without portfolio review",
                    "reasoning": "Fund Manager not configured.",
                    "requires_human_approval": bool(_cfg.REQUIRE_HUMAN_APPROVAL),
                    "timestamp": datetime.now().isoformat(),
                }

            fund = await fund_manager.approve(
                trade_decision, risk_decision, portfolio, open_positions
            )
            return fund.to_dict() if hasattr(fund, "to_dict") else fund

        except Exception as e:
            err = f"Fund Manager stage failed: {e}"
            logger.error(f"[Pipeline] {err}")
            errors.append(err)
            qty = risk_decision.get("modified_quantity") or trade_decision.get("quantity", 1)
            from config import settings as _cfg

            return {
                "approved": True,
                "final_quantity": min(int(qty), 1),
                "priority": "immediate",
                "portfolio_impact": "Fund Manager failed — conservative fallback approval",
                "reasoning": f"Fund Manager exception: {e}. Approved at min size (approval per REQUIRE_HUMAN_APPROVAL flag).",
                "requires_human_approval": bool(_cfg.REQUIRE_HUMAN_APPROVAL),
                "timestamp": datetime.now().isoformat(),
            }

    # Symbols that bypass Fund Manager review when Risk Manager has approved.
    # Matt Morrison (system owner) has explicitly authorized these bypasses.
    FUND_MANAGER_BYPASS_SYMBOLS = {"MES"}

    def _resolve_final_action(
        self, trade_decision: dict, risk_decision: dict, fund_decision: dict
    ) -> tuple:
        """
        Resolve final action from multi-stage decisions.

        Logic:
        1. If risk manager rejected → HOLD
        2. If symbol is in FUND_MANAGER_BYPASS_SYMBOLS and risk approved → execute directly
        3. If fund manager rejected → HOLD
        4. Otherwise use fund_decision action/quantity

        Returns: (final_action, final_quantity, requires_human)
        """
        # Risk manager veto
        if risk_decision and not risk_decision.get("approved", False):
            logger.info("[Resolution] Risk manager veto → HOLD")
            return "hold", 0, False

        # Owner-authorized bypass: skip Fund Manager for specified symbols
        symbol = (trade_decision or {}).get("symbol", "")
        if symbol in self.FUND_MANAGER_BYPASS_SYMBOLS:
            action = (trade_decision or {}).get("action", "hold").lower()
            quantity = risk_decision.get("modified_quantity") or (trade_decision or {}).get(
                "quantity", 1
            )
            logger.info(
                f"[Resolution] {symbol} bypass — Fund Manager skipped → {action} qty={quantity}"
            )
            return action, int(quantity), False

        # Fund manager decision — fix schema: FundDecision.to_dict() uses "approved"/"final_quantity"
        if fund_decision:
            approved = fund_decision.get("approved", fund_decision.get("execute", False))
            if not approved:
                logger.info("[Resolution] Fund manager rejected → HOLD")
                return "hold", 0, False

            priority = fund_decision.get("priority", "skip")
            if priority == "skip":
                logger.info("[Resolution] Fund manager priority=skip → HOLD")
                return "hold", 0, False

            action = (trade_decision or {}).get("action", "hold").lower()
            quantity = fund_decision.get(
                "final_quantity", fund_decision.get("contracts", fund_decision.get("quantity", 0))
            )
            requires_human = fund_decision.get(
                "requires_human_approval", fund_decision.get("human_approval_required", False)
            )
            logger.info(
                f"[Resolution] Fund approved → {action} qty={quantity} human={requires_human}"
            )
            return action, int(quantity), requires_human

        # Fallback: use trade decision if we got here (risk approved but no fund decision)
        if trade_decision:
            action = trade_decision.get("action", "hold").lower()
            quantity = trade_decision.get("quantity", 0)
            logger.info(f"[Resolution] No fund decision, using trade → {action} qty={quantity}")
            return action, int(quantity), False

        # Default to HOLD if nothing else available
        logger.warning("[Resolution] No decision available → HOLD")
        return "hold", 0, False

    # ── Portfolio Data ─────────────────────────────────────────────────────

    async def _get_portfolio(self) -> dict:
        """
        Retrieve current portfolio state.

        Override this method in a subclass (or inject a portfolio_provider into
        the agents dict as "portfolio") to supply real broker data.
        Falls back to a safe empty portfolio so the pipeline never crashes.
        """
        portfolio_provider = self._agents.get("portfolio")
        if portfolio_provider is not None:
            try:
                if asyncio.iscoroutinefunction(getattr(portfolio_provider, "get_portfolio", None)):
                    return await portfolio_provider.get_portfolio()
                elif callable(getattr(portfolio_provider, "get_portfolio", None)):
                    return portfolio_provider.get_portfolio()
            except Exception as e:
                logger.warning(f"[Pipeline] Portfolio fetch failed: {e}")

        # Safe default — Risk Manager and Fund Manager handle missing data gracefully
        equity = (
            self._safety._current_equity if hasattr(self._safety, "_current_equity") else 10_000.0
        )
        return {
            "total_value": equity,
            "available_cash": equity * 0.5,
            "margin_used_pct": 0.0,
            "daily_pnl": getattr(self._safety, "_daily_realized_pnl", 0.0),
            "open_position_count": 0,
            "positions": [],
        }

    # ── PostgreSQL Audit Logging ──────────────────────────────────────────────

    async def _log_pipeline_to_postgres(
        self,
        symbol: str,
        pipeline_result: dict,
        trade_decision: dict,
        errors: list,
    ) -> None:
        """
        Log pipeline execution to PostgreSQL for audit trail and analysis.

        Logs each agent's decision independently, plus the final trade decision.
        Gracefully handles database unavailability — never blocks the pipeline.

        Args:
            symbol: Trading symbol
            pipeline_result: Complete pipeline result dict
            trade_decision: Final trade decision dict
            errors: Any errors encountered
        """
        try:
            analyst_reports = pipeline_result.get("analyst_reports", {})
            fund_decision = pipeline_result.get("fund_decision")

            # Log each analyst's decision
            for agent_name in ["technical", "news", "social", "fundamental"]:
                report = analyst_reports.get(agent_name, {})
                if report and isinstance(report, dict):
                    await repository.insert_decision(
                        agent_name=agent_name,
                        symbol=symbol,
                        signal=report.get("signal", 0.0),
                        confidence=report.get("confidence", 0.0),
                        reasoning=report.get("summary", ""),
                        indicators=report.get("indicators"),
                        model_used=report.get("model_used"),
                        tokens_used=report.get("tokens_used"),
                        latency_ms=report.get("latency_ms"),
                        timeframe=report.get("timeframe"),
                    )

            # Log debate result (if present)
            debate_result = pipeline_result.get("debate_result", {})
            if debate_result and isinstance(debate_result, dict):
                await repository.insert_decision(
                    agent_name="debate",
                    symbol=symbol,
                    signal=debate_result.get("bull_score", 0.5)
                    - debate_result.get("bear_score", 0.5),
                    confidence=0.5,  # Debate doesn't have a direct confidence
                    reasoning=debate_result.get("summary", ""),
                )

            # Log trader decision (main decision point)
            if trade_decision and isinstance(trade_decision, dict):
                final_conviction = (
                    fund_decision.get("final_conviction", 0.0) if fund_decision else 0.0
                )
                await repository.insert_decision(
                    agent_name="trader",
                    symbol=symbol,
                    signal=trade_decision.get("signal_score", 0.0),
                    confidence=trade_decision.get("confidence", final_conviction),
                    reasoning=trade_decision.get("reasoning", ""),
                    model_used=trade_decision.get("model_used"),
                    tokens_used=trade_decision.get("tokens_used"),
                    latency_ms=trade_decision.get("latency_ms"),
                )

            # Log risk manager decision (if available)
            risk_decision = pipeline_result.get("risk_decision", {})
            if risk_decision and isinstance(risk_decision, dict):
                await repository.insert_decision(
                    agent_name="risk_manager",
                    symbol=symbol,
                    signal=1.0 if risk_decision.get("approved") else -1.0,
                    confidence=risk_decision.get("risk_score", 0.5),
                    reasoning=risk_decision.get("reasoning", ""),
                )

            # Log fund manager decision (if available)
            if fund_decision and isinstance(fund_decision, dict):
                await repository.insert_decision(
                    agent_name="fund_manager",
                    symbol=symbol,
                    signal=1.0 if fund_decision.get("approved") else -1.0,
                    confidence=fund_decision.get("final_conviction", 0.0),
                    reasoning=fund_decision.get("reasoning", ""),
                )

            logger.debug(f"[DB] Pipeline decisions logged for {symbol}")

        except Exception as e:
            # Never block pipeline execution due to database errors
            logger.warning(f"[DB] Failed to log pipeline to PostgreSQL: {e}")

    # ── Webhook Entry Point ────────────────────────────────────────────────

    async def run_on_signal(self, signal: dict) -> dict:
        """
        Entry point for TradingView webhook signals.
        Called by webhook_router when a LONG/SHORT/CLOSE alert arrives.

        Args:
            signal: Normalized webhook event dict with keys:
                symbol (str), action (str), price (float), timeframe (str),
                atr (float), regime (str), os_value (float), ob_value (float),
                received_at (str), source (str)

        Returns:
            dict with pipeline result or skip reason
        """
        symbol = signal.get("symbol", "MES")
        action = signal.get("action", "HOLD")
        source = signal.get("source", "tradingview")
        req_id = str(uuid.uuid4())[:8]

        logger.info(f"[Webhook:{req_id}] Signal received: {symbol} {action} from {source}")

        # Only run pipeline for actionable signals
        if action not in ("LONG", "SHORT", "CLOSE"):
            logger.debug(f"[Webhook:{req_id}] Skipping non-actionable action: {action}")
            return {
                "status": "skipped",
                "symbol": symbol,
                "action": action,
                "reason": f"Action '{action}' is not actionable — pipeline not triggered",
                "req_id": req_id,
            }

        # Determine is_futures from symbol name (micro futures naming convention)
        is_futures = not symbol.upper().startswith(("SPY", "QQQ", "IWM"))

        try:
            result = await self.analyze_and_decide(symbol, is_futures=is_futures)
            result["req_id"] = req_id
            result["webhook_action"] = action
            result["webhook_source"] = source
            logger.info(
                f"[Webhook:{req_id}] Pipeline complete: {symbol} "
                f"final_action={result.get('final_action', 'unknown')}"
            )
            return result
        except Exception as exc:
            logger.error(f"[Webhook:{req_id}] Pipeline raised for {symbol}: {exc}", exc_info=True)
            return {
                "status": "error",
                "symbol": symbol,
                "action": action,
                "req_id": req_id,
                "error": str(exc),
            }
