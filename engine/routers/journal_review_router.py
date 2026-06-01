"""
JARVIS TRADER — Trade Journal Review API
=========================================
LLM-powered monthly review endpoints adapted from Koroush AK's framework:

  1. stats      GET  /journal/review/stats?limit=30
     EV, win rate, R:R, trade frequency + bottleneck diagnosis

  2. breakdown  GET  /journal/review/breakdown?limit=30
     Win rate / net P&L by symbol, side, regime, bias — flags N>=5 edges/weaknesses

  3. analyze    POST /journal/review/analyze
     LLM behavioral pattern analysis: mood, duration, conditions, red flags

  4. formalize  POST /journal/review/formalize
     Observation → pressure-tested → falsifiable rule + tracking columns

  5. monthly    GET  /journal/review/monthly?limit=30
     One-shot full review: stats + breakdown + LLM analysis combined
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger("jarvis_trader.routers.journal_review")

# ---------------------------------------------------------------------------
# Injected dependencies — set by main.py at startup
# ---------------------------------------------------------------------------

_db_path: Optional[str] = None
_llm: Optional[Any] = None


def inject_dependencies(db_path: str, llm: Any) -> None:
    global _db_path, _llm
    _db_path = db_path
    _llm = llm


def _require_db() -> str:
    if _db_path is None:
        raise HTTPException(503, "Journal review: db_path not injected")
    return _db_path


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TradeStats(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    total_trades: int
    win_rate: float
    avg_win_usd: float
    avg_loss_usd: float
    risk_reward_ratio: float
    expected_value_usd: float
    trades_per_week: float
    diagnosis: str


class BreakdownRow(BaseModel):
    group_key: str
    group_value: str
    count: int
    win_rate: float
    net_pnl: float
    avg_pnl: float
    flagged: bool
    flag_reason: str


class BreakdownResponse(BaseModel):
    by_symbol: list[BreakdownRow]
    by_side: list[BreakdownRow]
    by_regime: list[BreakdownRow]
    by_bias: list[BreakdownRow]
    flags: list[BreakdownRow]


class AnalyzeRequest(BaseModel):
    limit: int = 100
    include_notes: bool = True


class AnalyzeResponse(BaseModel):
    analysis: str
    trade_count: int
    has_journal_data: bool


class FormalizeRequest(BaseModel):
    observation: str


class FormalizeResponse(BaseModel):
    pressure_tested: str
    falsifiable_rule: str
    journal_columns: list[str]
    sample_size: int
    pass_threshold: str
    fail_threshold: str
    abandonment_criteria: str
    raw_llm_output: str


class MonthlyReviewResponse(BaseModel):
    stats: TradeStats
    breakdown: BreakdownResponse
    llm_analysis: str
    generated_at: str
    trade_count: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fetch_closed_trades(db_path: str, limit: int) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT pt.trade_id, pt.symbol, pt.side, pt.pnl,
                   pt.entry_price, pt.exit_price, pt.stop_loss,
                   pt.entry_time, pt.exit_time,
                   pt.regime, pt.bias, pt.composite_score,
                   pt.notes AS trade_notes, pt.quantity, pt.risk_pct_used,
                   je.mood, je.note AS journal_note, je.lesson, je.tags
            FROM paper_trades pt
            LEFT JOIN trade_journal je ON pt.trade_id = je.trade_id
            WHERE pt.status = 'closed' AND pt.pnl IS NOT NULL
            ORDER BY pt.exit_time DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def _compute_stats(trades: list[dict]) -> TradeStats:
    if not trades:
        return TradeStats(
            total_trades=0,
            win_rate=0.0,
            avg_win_usd=0.0,
            avg_loss_usd=0.0,
            risk_reward_ratio=0.0,
            expected_value_usd=0.0,
            trades_per_week=0.0,
            diagnosis="insufficient_data",
        )

    wins = [t for t in trades if (t["pnl"] or 0) > 0]
    losses = [t for t in trades if (t["pnl"] or 0) <= 0]

    total = len(trades)
    win_rate = len(wins) / total
    avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(t["pnl"] for t in losses) / len(losses)) if losses else 0.0
    rr = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    ev = win_rate * avg_win - (1 - win_rate) * avg_loss

    # Trades per week from exit time span
    freq = float(total)
    try:
        dates = [t["exit_time"] for t in trades if t.get("exit_time")]
        if len(dates) >= 2:
            t_min = min(dates)
            t_max = max(dates)
            span_days = max(
                1,
                (
                    datetime.fromisoformat(t_max.replace("Z", "+00:00"))
                    - datetime.fromisoformat(t_min.replace("Z", "+00:00"))
                ).days,
            )
            freq = total / (span_days / 7)
    except Exception:
        pass

    if total < 5:
        diagnosis = "insufficient_data"
    elif win_rate < 0.40:
        diagnosis = "win_rate"
    elif avg_loss > avg_win:
        diagnosis = "avg_loss"
    elif rr < 1.5:
        diagnosis = "avg_win"
    else:
        diagnosis = "solid"

    return TradeStats(
        total_trades=total,
        win_rate=round(win_rate, 4),
        avg_win_usd=round(avg_win, 2),
        avg_loss_usd=round(avg_loss, 2),
        risk_reward_ratio=round(rr, 2),
        expected_value_usd=round(ev, 2),
        trades_per_week=round(freq, 2),
        diagnosis=diagnosis,
    )


def _group_breakdown(trades: list[dict], key: str) -> list[BreakdownRow]:
    from collections import defaultdict

    groups: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        val = str(t.get(key) or "unknown")
        groups[val].append(t["pnl"] or 0.0)

    rows = []
    for val, pnls in groups.items():
        count = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        wr = wins / count if count else 0.0
        net = sum(pnls)
        avg = net / count if count else 0.0

        flagged = count >= 5 and (wr > 0.55 or wr < 0.40)
        flag_reason = ""
        if flagged:
            flag_reason = (
                f"strong edge (WR={wr:.0%}, n={count})"
                if wr > 0.55
                else f"underperforming (WR={wr:.0%}, n={count})"
            )

        rows.append(
            BreakdownRow(
                group_key=key,
                group_value=val,
                count=count,
                win_rate=round(wr, 4),
                net_pnl=round(net, 2),
                avg_pnl=round(avg, 2),
                flagged=flagged,
                flag_reason=flag_reason,
            )
        )

    return sorted(rows, key=lambda r: r.net_pnl, reverse=True)


def _compute_breakdown(trades: list[dict]) -> BreakdownResponse:
    by_sym = _group_breakdown(trades, "symbol")
    by_side = _group_breakdown(trades, "side")
    by_regime = _group_breakdown(trades, "regime")
    by_bias = _group_breakdown(trades, "bias")
    flags = [r for g in [by_sym, by_side, by_regime, by_bias] for r in g if r.flagged]
    return BreakdownResponse(
        by_symbol=by_sym,
        by_side=by_side,
        by_regime=by_regime,
        by_bias=by_bias,
        flags=flags,
    )


def _build_analysis_prompt(trades: list[dict], stats: TradeStats) -> str:
    rows = []
    for t in trades[:100]:
        duration = ""
        try:
            if t.get("entry_time") and t.get("exit_time"):
                e = datetime.fromisoformat(t["entry_time"].replace("Z", "+00:00"))
                x = datetime.fromisoformat(t["exit_time"].replace("Z", "+00:00"))
                duration = f"{round((x - e).total_seconds() / 3600, 1)}h"
        except Exception:
            pass

        row = (
            f"{(t.get('exit_time') or '?')[:10]} | {t['symbol']} | {t['side']} | "
            f"PnL=${(t['pnl'] or 0):+.2f} | dur={duration} | "
            f"regime={t.get('regime') or '?'} | bias={t.get('bias') or '?'}"
        )
        if t.get("mood"):
            row += f" | mood={t['mood']}"
        if t.get("journal_note"):
            row += f" | note={str(t['journal_note'])[:80]}"
        if t.get("trade_notes"):
            row += f" | sys_notes={str(t['trade_notes'])[:80]}"
        rows.append(row)

    return f"""You are a trading coach reviewing a systematic futures trader's journal.

TRADE HISTORY ({len(trades)} closed trades, most recent first):
{chr(10).join(rows)}

PERFORMANCE STATS:
- Win rate: {stats.win_rate:.1%}
- Avg win: ${stats.avg_win_usd:.2f}  |  Avg loss: ${stats.avg_loss_usd:.2f}
- R:R ratio: {stats.risk_reward_ratio:.2f}  |  EV/trade: ${stats.expected_value_usd:.2f}
- Trades/week: {stats.trades_per_week:.1f}
- Bottleneck: {stats.diagnosis}

Respond using EXACTLY these five section headers:

## Emotional Patterns
Recurring words in mood/notes that correlate with outcomes. Cite specific dates.

## Trade Duration
Avg duration of winners vs losers. What does the gap (or lack of gap) suggest?

## Best and Worst Conditions
Best symbol/regime/bias combo and why. Worst combo and why. One sentence each.

## Behavioral Red Flags
2-3 patterns hurting performance, each backed by specific trade dates from the data.

## One Rule to Add Now
One specific, testable rule for the next review cycle. Must be precise enough that any trade can be checked against it."""


def _build_formalize_prompt(observation: str) -> str:
    return f"""A trader has this observation from their journal:

"{observation}"

Apply the Observation → Hypothesis → Rule framework. Return ONLY valid JSON:

{{
  "pressure_tested": "Is this real or sample noise? Could there be a confound? (2-3 sentences)",
  "falsifiable_rule": "One precise rule. No 'often', 'usually', 'sometimes'. Example: 'Do not take MES longs when 1h regime is BEARISH_CONFIRMED.'",
  "journal_columns": ["column_1", "column_2"],
  "sample_size": 30,
  "pass_threshold": "What passing looks like after N trades",
  "fail_threshold": "What failing looks like after N trades",
  "abandonment_criteria": "What evidence would make you abandon this rule entirely?"
}}"""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/review/stats", summary="Trade statistics for the last N closed trades")
async def get_review_stats(
    limit: int = Query(default=30, ge=5, le=500),
) -> TradeStats:
    """EV, win rate, R:R, trade frequency. Diagnoses the main performance bottleneck."""
    db_path = _require_db()
    trades = await asyncio.to_thread(_fetch_closed_trades, db_path, limit)
    return _compute_stats(trades)


@router.get("/review/breakdown", summary="Performance breakdown by symbol, side, regime, bias")
async def get_review_breakdown(
    limit: int = Query(default=30, ge=5, le=500),
) -> BreakdownResponse:
    """Win rate and P&L by key dimensions. Flags groups with clear edge or weakness (N>=5)."""
    db_path = _require_db()
    trades = await asyncio.to_thread(_fetch_closed_trades, db_path, limit)
    return _compute_breakdown(trades)


@router.post("/review/analyze", summary="LLM behavioral pattern analysis")
async def analyze_journal(body: AnalyzeRequest) -> AnalyzeResponse:
    """LLM analysis of trade history and journal notes. Surfaces emotional patterns and one concrete rule."""
    if _llm is None:
        raise HTTPException(503, "LLM client not injected for journal review")
    db_path = _require_db()
    trades = await asyncio.to_thread(_fetch_closed_trades, db_path, body.limit)
    if not trades:
        raise HTTPException(404, "No closed trades found for analysis")

    stats = _compute_stats(trades)
    result = await _llm.call(
        model="claude-sonnet-4-6",
        system="You are a trading performance coach analyzing a systematic futures trader's journal.",
        messages=[{"role": "user", "content": _build_analysis_prompt(trades, stats)}],
        max_tokens=2048,
        agent_name="journal-reviewer",
        temperature=0.4,
        allow_fallback=True,
        tier="default",
    )

    return AnalyzeResponse(
        analysis=result.content if result.success else f"LLM unavailable: {result.error}",
        trade_count=len(trades),
        has_journal_data=any(t.get("journal_note") or t.get("mood") for t in trades),
    )


@router.post("/review/formalize", summary="Pressure-test an observation into a testable rule")
async def formalize_insight(body: FormalizeRequest) -> FormalizeResponse:
    """Takes a fuzzy observation and returns a falsifiable rule with tracking mechanism."""
    if not body.observation.strip():
        raise HTTPException(422, "observation must not be empty")
    if _llm is None:
        raise HTTPException(503, "LLM client not injected for journal review")

    result = await _llm.call(
        model="claude-sonnet-4-6",
        system="You are a trading performance coach. Return only valid JSON.",
        messages=[{"role": "user", "content": _build_formalize_prompt(body.observation)}],
        max_tokens=1024,
        agent_name="journal-formalizer",
        temperature=0.3,
        allow_fallback=True,
        tier="default",
    )

    raw = result.content if result.success else "{}"
    parsed: dict = {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

    return FormalizeResponse(
        pressure_tested=parsed.get("pressure_tested", ""),
        falsifiable_rule=parsed.get("falsifiable_rule", ""),
        journal_columns=parsed.get("journal_columns", []),
        sample_size=int(parsed.get("sample_size", 30)),
        pass_threshold=parsed.get("pass_threshold", ""),
        fail_threshold=parsed.get("fail_threshold", ""),
        abandonment_criteria=parsed.get("abandonment_criteria", ""),
        raw_llm_output=raw,
    )


@router.get("/review/monthly", summary="Full monthly review report")
async def get_monthly_review(
    limit: int = Query(default=30, ge=5, le=200),
) -> MonthlyReviewResponse:
    """Runs stats + breakdown + LLM analysis. Use this for the monthly review cadence."""
    db_path = _require_db()
    trades = await asyncio.to_thread(_fetch_closed_trades, db_path, limit)
    if not trades:
        raise HTTPException(404, "No closed trades found")

    stats = _compute_stats(trades)
    breakdown = _compute_breakdown(trades)

    llm_analysis = "LLM analysis skipped (no client)"
    if _llm is not None:
        try:
            result = await _llm.call(
                model="claude-sonnet-4-6",
                system="You are a trading performance coach analyzing a systematic futures trader's journal.",
                messages=[{"role": "user", "content": _build_analysis_prompt(trades, stats)}],
                max_tokens=2048,
                agent_name="journal-monthly-reviewer",
                temperature=0.4,
                allow_fallback=True,
                tier="default",
            )
            if result.success:
                llm_analysis = result.content
        except Exception as exc:
            logger.warning("[JournalReview] LLM analysis failed: %s", exc)
            llm_analysis = f"LLM analysis failed: {exc}"

    return MonthlyReviewResponse(
        stats=stats,
        breakdown=breakdown,
        llm_analysis=llm_analysis,
        generated_at=datetime.now(timezone.utc).isoformat(),
        trade_count=len(trades),
    )
