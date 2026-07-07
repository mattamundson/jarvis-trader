"""
JARVIS TRADER — Trade Reviews Mixin
======================================
DatabaseManager mixin providing CRUD methods for the trade_reviews table.
One row per closed trade, populated asynchronously by TradeReviewService.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ._helpers import _utcnow

logger = logging.getLogger("jarvis_trader.database")


class ReviewsMixin:
    """Methods for the ``trade_reviews`` table."""

    def upsert_trade_review(
        self,
        *,
        trade_id: str,
        symbol: str,
        direction: str,
        entry_time: Optional[str] = None,
        exit_time: Optional[str] = None,
        pnl_usd: Optional[float] = None,
        pnl_pct: Optional[float] = None,
        hold_minutes: Optional[float] = None,
        entry_price: Optional[float] = None,
        exit_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        atr_value: Optional[float] = None,
        rr_ratio: Optional[float] = None,
        actual_r: Optional[float] = None,
        regime: Optional[str] = None,
        conviction: Optional[float] = None,
        bull_score: Optional[float] = None,
        bear_score: Optional[float] = None,
        pipeline_summary: Optional[str] = None,
        grade: Optional[str] = None,
        setup_quality: Optional[str] = None,
        strengths: Optional[List[str]] = None,
        weaknesses: Optional[List[str]] = None,
        rule_violations: Optional[List[str]] = None,
        lessons: Optional[str] = None,
        improvement_tags: Optional[List[str]] = None,
        llm_model: Optional[str] = None,
        review_status: str = "pending",
    ) -> None:
        """Insert or replace a trade review record."""
        now = _utcnow()
        sql = """
            INSERT INTO trade_reviews (
                trade_id, symbol, direction,
                entry_time, exit_time,
                pnl_usd, pnl_pct, hold_minutes,
                entry_price, exit_price, stop_loss, take_profit,
                atr_value, rr_ratio, actual_r,
                regime, conviction, bull_score, bear_score, pipeline_summary,
                grade, setup_quality,
                strengths, weaknesses, rule_violations,
                lessons, improvement_tags,
                llm_model, review_status,
                created_at, updated_at
            ) VALUES (
                ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?
            )
            ON CONFLICT(trade_id) DO UPDATE SET
                grade            = excluded.grade,
                setup_quality    = excluded.setup_quality,
                strengths        = excluded.strengths,
                weaknesses       = excluded.weaknesses,
                rule_violations  = excluded.rule_violations,
                lessons          = excluded.lessons,
                improvement_tags = excluded.improvement_tags,
                llm_model        = excluded.llm_model,
                review_status    = excluded.review_status,
                updated_at       = excluded.updated_at
        """
        params = (
            trade_id,
            symbol,
            direction,
            entry_time,
            exit_time,
            pnl_usd,
            pnl_pct,
            hold_minutes,
            entry_price,
            exit_price,
            stop_loss,
            take_profit,
            atr_value,
            rr_ratio,
            actual_r,
            regime,
            conviction,
            bull_score,
            bear_score,
            pipeline_summary,
            grade,
            setup_quality,
            json.dumps(strengths) if strengths is not None else None,
            json.dumps(weaknesses) if weaknesses is not None else None,
            json.dumps(rule_violations) if rule_violations is not None else None,
            lessons,
            json.dumps(improvement_tags) if improvement_tags is not None else None,
            llm_model,
            review_status,
            now,
            now,
        )
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(sql, params)
                conn.commit()
            finally:
                conn.close()

    def get_trade_review(self, trade_id: str) -> Optional[Dict[str, Any]]:
        """Return the review dict for a trade, or None if not found."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM trade_reviews WHERE trade_id = ?", (trade_id,)
                ).fetchone()
                if row is None:
                    return None
                return _review_row_to_dict(row)
            finally:
                conn.close()

    def get_review_grade(self, trade_id: str) -> Optional[str]:
        """Return just the grade for a trade (used in history listing)."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT grade FROM trade_reviews WHERE trade_id = ?", (trade_id,)
                ).fetchone()
                return row["grade"] if row else None
            finally:
                conn.close()

    def list_trade_reviews(
        self,
        *,
        symbol: Optional[str] = None,
        grades: Optional[List[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Return paginated trade reviews with optional filters.

        Returns dict with keys: reviews (list), total (int),
        grade_breakdown (dict A→count).
        """
        filters: List[str] = []
        params: List[Any] = []

        if symbol:
            filters.append("symbol = ?")
            params.append(symbol.upper())
        if grades:
            placeholders = ",".join("?" for _ in grades)
            filters.append(f"grade IN ({placeholders})")
            params.extend(grades)
        if date_from:
            filters.append("entry_time >= ?")
            params.append(date_from)
        if date_to:
            filters.append("entry_time <= ?")
            params.append(date_to)
        if status:
            filters.append("review_status = ?")
            params.append(status)

        where = ("WHERE " + " AND ".join(filters)) if filters else ""

        count_sql = f"SELECT COUNT(*) FROM trade_reviews {where}"
        breakdown_sql = (
            f"SELECT grade, COUNT(*) as cnt FROM trade_reviews {where} " "GROUP BY grade"
        )
        rows_sql = (
            f"SELECT * FROM trade_reviews {where} " "ORDER BY entry_time DESC LIMIT ? OFFSET ?"
        )

        with self._lock:
            conn = self._connect()
            try:
                total = conn.execute(count_sql, params).fetchone()[0]
                breakdown_rows = conn.execute(breakdown_sql, params).fetchall()
                rows = conn.execute(rows_sql, params + [limit, offset]).fetchall()

                grade_breakdown = {r["grade"]: r["cnt"] for r in breakdown_rows if r["grade"]}
                reviews = [_review_row_to_dict(r) for r in rows]
                return {
                    "reviews": reviews,
                    "total": total,
                    "grade_breakdown": grade_breakdown,
                }
            finally:
                conn.close()


def _review_row_to_dict(row: Any) -> Dict[str, Any]:
    """Convert a sqlite3.Row from trade_reviews to a plain dict."""
    d = dict(row)
    for json_col in ("strengths", "weaknesses", "rule_violations", "improvement_tags"):
        raw = d.get(json_col)
        if isinstance(raw, str):
            try:
                d[json_col] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                d[json_col] = []
        elif raw is None:
            d[json_col] = []
    return d
