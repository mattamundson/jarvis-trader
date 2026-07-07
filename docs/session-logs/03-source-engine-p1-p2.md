# P1/P2 Source Code — Tilt Detection · Memory Consolidation · Speculation · Task Board · Config · Sanitizer


### `engine/risk/tilt_detector.py`
```python
"""
Tilt Detection System — adapted from Claude Code's "frustration detection."
Detects revenge trading, rapid position changes, and behavioral patterns
that indicate the trader is operating emotionally rather than systematically.
Pure Python rules — NO LLM in detection path.
"""

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TiltState:
    is_tilted: bool
    tilt_score: float  # 0.0 (calm) to 1.0 (full tilt)
    tilt_indicators: list[str]  # Which indicators are firing
    position_size_multiplier: float  # 1.0 normal → 0.75 → 0.5 → 0.25 → 0.0 halted
    cooldown_until: Optional[datetime] = None
    severity: str = "none"  # "none" | "caution" | "warning" | "critical"


class TiltDetector:
    """
    Detects emotional/behavioral trading patterns that indicate tilt.

    Tilt indicators (each adds to tilt_score):
    1. Consecutive losses: 3+ → 0.2, 5+ → 0.4, 7+ → halt
    2. Rapid position changes: 5+ trades in 30 min → 0.3
    3. Revenge sizing: position size increased after a loss → 0.25
    4. Rapid re-entry: re-entered same symbol < 5 min after stop-out → 0.25
    5. Risk override: risk manager vetoed 2+ times in 4h → 0.2
    6. Drawdown acceleration: drawdown rate increasing → 0.2

    Position size multiplier:
    - score < 0.3: 1.0 (normal)
    - score 0.3-0.5: 0.75 (caution)
    - score 0.5-0.7: 0.5 (warning)
    - score 0.7-0.85: 0.25 (tilt)
    - score > 0.85: 0.0 (halted — must cool down for 1 hour)
    """

    # Time windows for detection
    RAPID_TRADE_WINDOW_MINUTES = 30
    RAPID_TRADE_THRESHOLD = 5
    REVENGE_REENTRY_MINUTES = 5
    RISK_OVERRIDE_WINDOW_HOURS = 4
    DRAWDOWN_WINDOW_MINUTES = 60

    def __init__(self, config=None, loss_tracker=None):
        self._config = config
        self._loss_tracker = loss_tracker

        # Trade history (rolling window)
        # Each entry: {"timestamp": datetime, "symbol": str, "direction": str,
        #              "size": int, "entry_price": float, "pnl": float|None}
        self._recent_trades: deque = deque(maxlen=100)
        # Stop-out records: {"timestamp": datetime, "symbol": str}
        self._stop_outs: deque = deque(maxlen=20)
        # Risk veto records: {"timestamp": datetime}
        self._risk_vetoes: deque = deque(maxlen=10)

        # Drawdown tracking: {"timestamp": datetime, "drawdown_pct": float}
        self._drawdown_history: deque = deque(maxlen=120)

        # Cooldown state
        self._cooldown_until: Optional[datetime] = None

    # ── Recording API ──────────────────────────────────────────────────────

    def record_trade(
        self,
        symbol: str,
        direction: str,
        size: int,
        entry_price: float,
        pnl: Optional[float] = None,
        is_stop_out: bool = False,
    ) -> None:
        """Record a completed or entered trade for tilt analysis."""
        entry = {
            "timestamp": datetime.now(),
            "symbol": symbol,
            "direction": direction,
            "size": size,
            "entry_price": entry_price,
            "pnl": pnl,
        }
        self._recent_trades.append(entry)
        if is_stop_out or (pnl is not None and pnl < 0):
            self._stop_outs.append({"timestamp": datetime.now(), "symbol": symbol})

    def record_risk_veto(self) -> None:
        """Record that the risk manager vetoed a trade order."""
        self._risk_vetoes.append({"timestamp": datetime.now()})

    def update_drawdown(self, drawdown_pct: float) -> None:
        """Update drawdown tracking. Call this periodically with current drawdown %."""
        self._drawdown_history.append({"timestamp": datetime.now(), "drawdown_pct": drawdown_pct})

    # ── Core Check ────────────────────────────────────────────────────────

    def check(self) -> TiltState:
        """
        Evaluate all tilt indicators and return current tilt state.
        This is the primary entry point — called by safety layer on every order.
        """
        # If currently in cooldown, return halted state immediately
        if self._cooldown_until and datetime.now() < self._cooldown_until:
            return TiltState(
                is_tilted=True,
                tilt_score=1.0,
                tilt_indicators=["cooldown_active"],
                position_size_multiplier=0.0,
                cooldown_until=self._cooldown_until,
                severity="critical",
            )
        elif self._cooldown_until:
            # Cooldown expired — clear it
            self._cooldown_until = None

        indicators: list[str] = []
        tilt_score = 0.0

        # 1. Consecutive losses
        consecutive = self._get_consecutive_losses()

        if consecutive >= 7:
            tilt_score += 0.6
            indicators.append(f"consecutive_losses_{consecutive}")
            # Auto-start cooldown for extreme streak
            if not self._cooldown_until:
                self._cooldown_until = datetime.now() + timedelta(hours=1)
        elif consecutive >= 5:
            tilt_score += 0.4
            indicators.append(f"consecutive_losses_{consecutive}")
        elif consecutive >= 3:
            tilt_score += 0.2
            indicators.append(f"consecutive_losses_{consecutive}")

        # 2. Rapid position changes (churning)
        rapid_count = self._count_rapid_trades()
        if rapid_count >= self.RAPID_TRADE_THRESHOLD:
            tilt_score += 0.3
            indicators.append(f"rapid_trades_{rapid_count}_in_30min")

        # 3. Revenge sizing (increased position size after a loss)
        if self._detect_revenge_sizing():
            tilt_score += 0.25
            indicators.append("revenge_sizing")

        # 4. Rapid re-entry after stop-out on same symbol
        if self._detect_rapid_reentry():
            tilt_score += 0.25
            indicators.append("rapid_reentry_after_stop")

        # 5. Multiple risk manager vetoes in last 4 hours
        veto_count = self._count_recent_vetoes()
        if veto_count >= 2:
            tilt_score += 0.2
            indicators.append(f"risk_overrides_{veto_count}")

        # 6. Drawdown acceleration (rate of loss increasing)
        if self._detect_drawdown_acceleration():
            tilt_score += 0.2
            indicators.append("drawdown_accelerating")

        tilt_score = min(tilt_score, 1.0)
        is_tilted = tilt_score >= 0.3

        # Determine severity and position size multiplier
        if tilt_score < 0.3:
            severity = "none"
            multiplier = 1.0
        elif tilt_score < 0.5:
            severity = "caution"
            multiplier = 0.75
        elif tilt_score < 0.7:
            severity = "warning"
            multiplier = 0.5
        elif tilt_score < 0.85:
            severity = "critical"
            multiplier = 0.25
        else:
            severity = "critical"
            multiplier = 0.0
            if not self._cooldown_until:
                self._cooldown_until = datetime.now() + timedelta(hours=1)

        state = TiltState(
            is_tilted=is_tilted,
            tilt_score=round(tilt_score, 3),
            tilt_indicators=indicators,
            position_size_multiplier=multiplier,
            cooldown_until=self._cooldown_until,
            severity=severity,
        )

        if is_tilted:
            logger.warning(
                "Tilt detected: score=%.2f, indicators=%s, multiplier=%.2f",
                tilt_score,
                indicators,
                multiplier,
            )

        return state

    def get_position_multiplier(self) -> float:
        """Quick accessor — returns just the multiplier for wiring into the safety layer."""
        return self.check().position_size_multiplier

    # ── Status / Reset ────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Return full tilt status dict suitable for an API endpoint."""
        state = self.check()
        return {
            "is_tilted": state.is_tilted,
            "tilt_score": state.tilt_score,
            "severity": state.severity,
            "tilt_indicators": state.tilt_indicators,
            "position_size_multiplier": state.position_size_multiplier,
            "cooldown_until": state.cooldown_until.isoformat() if state.cooldown_until else None,
            "recent_trade_count": len(self._recent_trades),
            "consecutive_losses": self._get_consecutive_losses(),
            "rapid_trades_30min": self._count_rapid_trades(),
            "recent_vetoes": self._count_recent_vetoes(),
        }

    def reset(self) -> None:
        """Manually reset all tilt state (for testing or human override)."""
        self._recent_trades.clear()
        self._stop_outs.clear()
        self._risk_vetoes.clear()
        self._drawdown_history.clear()
        self._cooldown_until = None
        logger.info("TiltDetector: state reset manually")

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get_consecutive_losses(self) -> int:
        """
        Return consecutive loss count, preferring the loss_tracker if available
        (which has persisted state across restarts).
        """
        if self._loss_tracker is not None and hasattr(self._loss_tracker, "get_consecutive_losses"):
            try:
                return int(self._loss_tracker.get_consecutive_losses())
            except Exception:
                pass
        return self._count_consecutive_losses()

    def _count_consecutive_losses(self) -> int:
        """Count trailing consecutive losses from in-memory trade history."""
        count = 0
        for trade in reversed(list(self._recent_trades)):
            pnl = trade.get("pnl")
            if pnl is not None and pnl < 0:
                count += 1
            elif pnl is not None:
                break
            # trades with pnl=None (open) are skipped
        return count

    def _count_rapid_trades(self) -> int:
        """Count how many trades occurred in the last 30 minutes."""
        cutoff = datetime.now() - timedelta(minutes=self.RAPID_TRADE_WINDOW_MINUTES)
        return sum(1 for t in self._recent_trades if t["timestamp"] > cutoff)

    def _detect_revenge_sizing(self) -> bool:
        """
        Return True when the most recent trade increased position size after a loss.
        Classic revenge-trading signature: lose → bet bigger to get it back.
        """
        recent = list(self._recent_trades)
        if len(recent) < 2:
            return False
        last = recent[-1]
        second_last = recent[-2]
        second_last_pnl = second_last.get("pnl")
        return (
            second_last_pnl is not None
            and second_last_pnl < 0
            and last.get("size", 0) > second_last.get("size", 0)
        )

    def _detect_rapid_reentry(self) -> bool:
        """
        Return True if a trade was placed on the same symbol within 5 minutes
        of being stopped out on that symbol.
        """
        cutoff = datetime.now() - timedelta(minutes=self.REVENGE_REENTRY_MINUTES)
        recent_stops = [s for s in self._stop_outs if s["timestamp"] > cutoff]
        if not recent_stops:
            return False
        recent_trade_symbols = {t["symbol"] for t in self._recent_trades if t["timestamp"] > cutoff}
        stop_symbols = {s["symbol"] for s in recent_stops}
        return bool(recent_trade_symbols & stop_symbols)

    def _count_recent_vetoes(self) -> int:
        """Count risk manager vetoes in the last 4 hours."""
        cutoff = datetime.now() - timedelta(hours=self.RISK_OVERRIDE_WINDOW_HOURS)
        return sum(1 for v in self._risk_vetoes if v["timestamp"] > cutoff)

    def _detect_drawdown_acceleration(self) -> bool:
        """
        Return True if the drawdown rate is accelerating (getting worse faster).
        Compares the average drawdown in the first half of the window vs the second half.
        A 20% increase in the second half vs first half is considered acceleration.
        """
        window_start = datetime.now() - timedelta(minutes=self.DRAWDOWN_WINDOW_MINUTES)
        recent_dd = [d for d in self._drawdown_history if d["timestamp"] > window_start]
        if len(recent_dd) < 4:
            return False
        mid = len(recent_dd) // 2
        first_half = recent_dd[:mid]
        second_half = recent_dd[mid:]
        first_avg = sum(d["drawdown_pct"] for d in first_half) / len(first_half)
        second_avg = sum(d["drawdown_pct"] for d in second_half) / len(second_half)
        # Drawdown is expressed as a positive percentage (e.g. 3.5 = 3.5% down).
        # Increasing means it's getting worse — flag when second half is 20% worse.
        return second_avg > first_avg * 1.2

```

### `engine/learning/consolidator.py`
```python
"""
Trading Memory Consolidator — adapted from Claude Code's /dream command.
Nightly consolidation of trading patterns into actionable pattern database.
"""

import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class TradingMemoryConsolidator:
    """
    Converts raw trade history into pattern database.
    Runs nightly, triggered by eod_scheduler.
    """

    def __init__(self, db_manager=None, llm_client=None):
        self._db = db_manager
        self._client = llm_client

    async def consolidate_daily(self, target_date: str = None) -> dict:
        """
        Run nightly consolidation:
        1. Fetch all trades from target_date
        2. Extract patterns (winning conditions, losing conditions)
        3. Score signal accuracy (which directions were correct)
        4. Optional: LLM insights via Haiku
        5. Persist patterns to trading_patterns table
        6. Prune stale patterns (not seen in 30+ days)
        """
        target_date = target_date or date.today().isoformat()
        logger.info(f"Memory consolidation starting for {target_date}")

        # Fetch trades for the day
        trades = await self._fetch_trades(target_date)
        if not trades:
            return {"date": target_date, "status": "no_trades", "patterns": [], "accuracy": {}}

        # Extract patterns
        patterns = self._extract_patterns(trades)

        # Score signal accuracy
        accuracy = self._score_signal_accuracy(trades)

        # Persist patterns
        if self._db:
            for pattern in patterns:
                await self._upsert_pattern(pattern, target_date)
            await self._prune_stale_patterns()

        # Optional LLM insights
        insights = None
        if self._client and len(trades) > 0:
            insights = await self._generate_insights(trades, patterns, accuracy)

        result = {
            "date": target_date,
            "status": "complete",
            "trades_analyzed": len(trades),
            "patterns_extracted": len(patterns),
            "accuracy": accuracy,
            "insights": insights,
        }
        logger.info(f"Memory consolidation complete: {len(patterns)} patterns, accuracy={accuracy}")
        return result

    async def get_active_patterns(self) -> list[dict]:
        """Return patterns active in the last 14 days."""
        if not self._db:
            return []
        cutoff = (date.today() - timedelta(days=14)).isoformat()
        try:
            rows = await self._db.fetch_all(
                "SELECT * FROM trading_patterns WHERE is_active=1 AND last_seen >= ? ORDER BY win_rate DESC LIMIT 20",
                (cutoff,),
            )
            return [dict(r) for r in rows] if rows else []
        except Exception as e:
            logger.error(f"get_active_patterns error: {e}")
            return []

    async def get_signal_accuracy(self, days: int = 30) -> dict:
        """Track signal accuracy over N days."""
        if not self._db:
            return {"days": days, "total": 0, "correct": 0, "accuracy_pct": 0}
        try:
            cutoff = (date.today() - timedelta(days=days)).isoformat()
            rows = await self._db.fetch_all(
                "SELECT direction, COUNT(*) as total, SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins "
                "FROM paper_trades WHERE entry_time >= ? GROUP BY direction",
                (cutoff,),
            )
            result = {"days": days, "by_direction": {}, "total": 0, "correct": 0}
            for row in rows or []:
                d = dict(row)
                result["by_direction"][d.get("direction", "unknown")] = {
                    "total": d.get("total", 0),
                    "wins": d.get("wins", 0),
                    "accuracy_pct": round(d.get("wins", 0) / max(d.get("total", 1), 1) * 100, 1),
                }
                result["total"] += d.get("total", 0)
                result["correct"] += d.get("wins", 0)
            if result["total"] > 0:
                result["accuracy_pct"] = round(result["correct"] / result["total"] * 100, 1)
            return result
        except Exception as e:
            logger.error(f"get_signal_accuracy error: {e}")
            return {"days": days, "total": 0, "correct": 0, "accuracy_pct": 0}

    def _extract_patterns(self, trades: list[dict]) -> list[dict]:
        """Simple rule-based pattern extraction from trades."""
        patterns = []

        # Pattern 1: Time-of-day performance
        hour_pnl = {}
        for trade in trades:
            try:
                hour = datetime.fromisoformat(trade.get("entry_time", "")).hour
                hour_pnl.setdefault(hour, []).append(trade.get("pnl", 0))
            except Exception:
                continue

        for hour, pnls in hour_pnl.items():
            if len(pnls) >= 2:
                win_rate = sum(1 for p in pnls if p > 0) / len(pnls)
                avg_return = sum(pnls) / len(pnls)
                if win_rate > 0.6 or win_rate < 0.3:
                    patterns.append(
                        {
                            "name": f"hour_{hour:02d}_performance",
                            "category": "time",
                            "conditions": json.dumps({"hour": hour}),
                            "win_rate": round(win_rate, 3),
                            "avg_return": round(avg_return, 2),
                            "frequency": len(pnls),
                        }
                    )

        # Pattern 2: Direction bias
        long_trades = [t for t in trades if t.get("direction", "").lower() == "long"]
        short_trades = [t for t in trades if t.get("direction", "").lower() == "short"]

        for direction, direction_trades in [("long", long_trades), ("short", short_trades)]:
            if len(direction_trades) >= 2:
                pnls = [t.get("pnl", 0) for t in direction_trades]
                win_rate = sum(1 for p in pnls if p > 0) / len(pnls)
                patterns.append(
                    {
                        "name": f"{direction}_bias_today",
                        "category": "regime",
                        "conditions": json.dumps(
                            {"direction": direction, "date": date.today().isoformat()}
                        ),
                        "win_rate": round(win_rate, 3),
                        "avg_return": round(sum(pnls) / len(pnls), 2),
                        "frequency": len(pnls),
                    }
                )

        return patterns

    def _score_signal_accuracy(self, trades: list[dict]) -> dict:
        """Score how accurate the pipeline signals were today."""
        if not trades:
            return {"total": 0, "wins": 0, "accuracy_pct": 0}
        wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
        total = len(trades)
        return {
            "total": total,
            "wins": wins,
            "losses": total - wins,
            "accuracy_pct": round(wins / total * 100, 1),
            "total_pnl": round(sum(t.get("pnl", 0) for t in trades), 2),
        }

    async def _fetch_trades(self, target_date: str) -> list[dict]:
        """Fetch paper trades for the given date from DB."""
        if not self._db:
            return []
        try:
            rows = await self._db.fetch_all(
                "SELECT * FROM paper_trades WHERE DATE(entry_time) = ? ORDER BY entry_time",
                (target_date,),
            )
            return [dict(r) for r in rows] if rows else []
        except Exception as e:
            logger.debug(f"fetch_trades: {e}")
            return []

    async def _upsert_pattern(self, pattern: dict, today: str) -> None:
        """Insert or update a pattern in the DB."""
        if not self._db:
            return
        try:
            existing = await self._db.fetch_one(
                "SELECT id, frequency FROM trading_patterns WHERE name = ?", (pattern["name"],)
            )
            if existing:
                await self._db.execute(
                    "UPDATE trading_patterns SET win_rate=?, avg_return=?, frequency=frequency+?, "
                    "last_seen=?, is_active=1 WHERE name=?",
                    (
                        pattern["win_rate"],
                        pattern["avg_return"],
                        pattern["frequency"],
                        today,
                        pattern["name"],
                    ),
                )
            else:
                await self._db.execute(
                    "INSERT INTO trading_patterns (name, category, conditions, frequency, win_rate, "
                    "avg_return, last_seen, first_seen, is_active, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                    (
                        pattern["name"],
                        pattern["category"],
                        pattern["conditions"],
                        pattern["frequency"],
                        pattern["win_rate"],
                        pattern["avg_return"],
                        today,
                        today,
                        datetime.now().isoformat(),
                    ),
                )
        except Exception as e:
            logger.error(f"upsert_pattern error: {e}")

    async def _prune_stale_patterns(self) -> None:
        """Mark patterns not seen in 30 days as inactive."""
        if not self._db:
            return
        try:
            cutoff = (date.today() - timedelta(days=30)).isoformat()
            await self._db.execute(
                "UPDATE trading_patterns SET is_active=0 WHERE last_seen < ?", (cutoff,)
            )
        except Exception as e:
            logger.error(f"prune_stale_patterns error: {e}")

    async def _generate_insights(self, trades, patterns, accuracy) -> Optional[str]:
        """Generate LLM insights using Haiku."""
        try:
            summary = f"""Trades today: {len(trades)}
Accuracy: {accuracy.get('accuracy_pct', 0)}%
Total P&L: {accuracy.get('total_pnl', 0)}
Patterns found: {len(patterns)}
Key patterns: {[p['name'] for p in patterns[:5]]}"""

            result = await self._client.call(
                model="claude-haiku-4-5-20251001",
                system="You are a trading coach analyzing daily performance patterns.",
                messages=[
                    {
                        "role": "user",
                        "content": f"Provide 3 actionable insights from today's trading:\n{summary}",
                    }
                ],
                max_tokens=300,
            )
            return result.get("content", [{}])[0].get("text", "")
        except Exception as e:
            logger.error(f"LLM insights failed: {e}")
            return None

```

### `engine/learning/pattern_db.py`
```python
"""
Trading patterns SQLite table definition.

Used by TradingMemoryConsolidator to persist extracted trading patterns.
Import TRADING_PATTERNS_DDL and run it via the migration system.
"""

TRADING_PATTERNS_DDL = """
CREATE TABLE IF NOT EXISTS trading_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    conditions TEXT NOT NULL,
    frequency INTEGER DEFAULT 0,
    win_rate REAL DEFAULT 0.0,
    avg_return REAL DEFAULT 0.0,
    last_seen TEXT,
    first_seen TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_patterns_active ON trading_patterns(is_active, last_seen);
"""

```

### `engine/speculation/__init__.py`
```python
from .engine import SpeculationEngine, get_speculation_engine, set_speculation_engine

__all__ = ["SpeculationEngine", "get_speculation_engine", "set_speculation_engine"]

```

### `engine/speculation/engine.py`
```python
"""
Speculation/Pre-execution Engine — adapted from Claude Code's speculation feature.
Pre-computes likely next pipeline inputs during idle periods to reduce latency.
"""

import logging
from datetime import datetime
from typing import Optional

from .prefetch_cache import PrefetchCache

logger = logging.getLogger(__name__)

_speculation_instance: Optional["SpeculationEngine"] = None


def get_speculation_engine() -> Optional["SpeculationEngine"]:
    return _speculation_instance


def set_speculation_engine(engine: "SpeculationEngine") -> None:
    global _speculation_instance
    _speculation_instance = engine


class SpeculationEngine:
    """
    Pre-computes market data and technical indicators during idle periods.
    Results are cached for PREFETCH_TTL_SECONDS (default: 10 min).

    Pipeline agents check PrefetchCache before computing — if cache hit,
    latency drops from ~20s (data fetch + compute) to ~1s (cache lookup).
    """

    def __init__(self, config, data_manager=None, prefetch_ttl: int = 600):
        self._config = config
        self._data = data_manager
        self.cache = PrefetchCache(ttl_seconds=prefetch_ttl)
        self._speculation_count = 0
        self._cache_hits = 0  # Tracked externally by pipeline
        self._last_speculation: Optional[datetime] = None
        self._running = False

    async def speculate(self) -> dict:
        """
        Run one speculation cycle:
        1. Pre-fetch OHLCV data for all watchlist symbols
        2. Pre-compute technical indicators (STC, ATR, regime state)
        3. Cache results for pipeline consumption
        Returns: dict with symbols_processed, cache_size, duration_ms
        """
        start = datetime.now()
        self._speculation_count += 1

        watchlist = list(getattr(self._config, "FUTURES_WATCHLIST", ["MES", "MNQ"]))
        # Add options watchlist if available
        options_list = list(getattr(self._config, "OPTIONS_WATCHLIST", []))
        all_symbols = list(set(watchlist + options_list))

        processed = []
        errors = []

        for symbol in all_symbols:
            try:
                # Pre-fetch market data
                bars = await self.prefetch_market_data(symbol)
                if bars is not None:
                    # Pre-compute indicators
                    indicators = await self.precompute_indicators(symbol, bars)
                    if indicators:
                        self.cache.set(f"indicators:{symbol}:1h", indicators)
                        processed.append(symbol)
            except Exception as e:
                errors.append({"symbol": symbol, "error": str(e)})
                logger.debug(f"Speculation failed for {symbol}: {e}")

        self._last_speculation = datetime.now()
        duration_ms = (datetime.now() - start).total_seconds() * 1000

        result = {
            "speculation_count": self._speculation_count,
            "symbols_processed": len(processed),
            "symbols_requested": len(all_symbols),
            "symbols": processed,
            "errors": errors,
            "cache_size": self.cache.stats()["valid_keys"],
            "duration_ms": round(duration_ms, 1),
        }

        logger.debug(
            f"Speculation cycle complete: {len(processed)}/{len(all_symbols)} symbols "
            f"in {duration_ms:.0f}ms"
        )
        return result

    async def prefetch_market_data(self, symbol: str, interval: str = "1h", limit: int = 100):
        """Fetch and cache OHLCV bars for a symbol."""
        cache_key = f"bars:{symbol}:{interval}"

        # Return cached if fresh
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        if not self._data:
            return None

        try:
            # Try get_bars method (check actual signature in market_data.py)
            if hasattr(self._data, "get_bars"):
                bars = await self._data.get_bars(symbol, interval=interval, limit=limit)
            elif hasattr(self._data, "fetch_bars"):
                bars = await self._data.fetch_bars(symbol, interval=interval, limit=limit)
            else:
                return None

            if bars is not None and len(bars) > 0:
                self.cache.set(cache_key, bars, ttl=300)  # 5 min TTL for raw bars
                return bars
        except Exception as e:
            logger.debug(f"prefetch_market_data {symbol}: {e}")
        return None

    async def precompute_indicators(self, symbol: str, bars=None) -> Optional[dict]:
        """Compute technical indicators and cache results."""
        cache_key = f"indicators:{symbol}:1h"

        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        if bars is None:
            bars = self.cache.get(f"bars:{symbol}:1h")

        if bars is None:
            return None

        try:
            # Import signals computation — compute_all_indicators returns a DataFrame,
            # so we extract the last row as a dict for caching
            from backtest.signals import compute_all_indicators

            indicators_df = compute_all_indicators(bars)
            if indicators_df is not None and len(indicators_df) > 0:
                last = indicators_df.iloc[-1]
                result = {
                    "symbol": symbol,
                    "timestamp": datetime.now().isoformat(),
                    "cached_at": datetime.now().isoformat(),
                }
                # Safely extract key indicator columns
                for col in ("stc_val", "stc_signal", "atr", "kama_val", "kama_signal"):
                    if col in last.index:
                        val = last[col]
                        # Convert numpy scalar to Python native type
                        try:
                            result[col] = (
                                float(val) if col not in ("stc_signal", "kama_signal") else str(val)
                            )
                        except (TypeError, ValueError):
                            result[col] = str(val)
                self.cache.set(cache_key, result, ttl=600)
                return result
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"precompute_indicators {symbol}: {e}")

        # Fallback: compute basic price info from raw bars
        try:
            if hasattr(bars, "iloc"):
                latest = bars.iloc[-1]
                result = {
                    "symbol": symbol,
                    "timestamp": datetime.now().isoformat(),
                    "price": float(latest.get("close", latest.get("Close", 0))),
                    "volume": (
                        float(latest.get("volume", latest.get("Volume", 0)))
                        if "volume" in latest.index or "Volume" in latest.index
                        else 0
                    ),
                    "cached_at": datetime.now().isoformat(),
                }
                self.cache.set(cache_key, result, ttl=600)
                return result
        except Exception:
            pass

        return None

    def get_cached_indicators(self, symbol: str, interval: str = "1h") -> Optional[dict]:
        """Pipeline-facing: get pre-computed indicators (synchronous)."""
        return self.cache.get(f"indicators:{symbol}:{interval}")

    def get_cached_bars(self, symbol: str, interval: str = "1h"):
        """Pipeline-facing: get pre-fetched bars (synchronous)."""
        return self.cache.get(f"bars:{symbol}:{interval}")

    def record_cache_hit(self) -> None:
        """Called by pipeline when it successfully uses cached data."""
        self._cache_hits += 1

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "speculation_count": self._speculation_count,
            "cache_hits": self._cache_hits,
            "last_speculation": (
                self._last_speculation.isoformat() if self._last_speculation else None
            ),
            "cache": self.cache.stats(),
            "cached_symbols": self.cache.keys_by_prefix("indicators:"),
        }

```

### `engine/speculation/prefetch_cache.py`
```python
"""TTL-based in-memory cache for pre-fetched market data and indicators."""

import threading
import time
from typing import Any, Optional


class PrefetchCache:
    """
    Thread-safe in-memory TTL cache.
    Stores: market_data, technical_indicators, regime_states per symbol.
    Default TTL: 10 minutes (data freshness window).
    """

    DEFAULT_TTL_SECONDS = 600  # 10 minutes

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[Any, float]] = {}  # key -> (value, expiry_time)
        self._lock = threading.Lock()

    def set(self, key: str, value: Any, ttl: int = None) -> None:
        """Set a value with TTL."""
        expiry = time.monotonic() + (ttl or self._ttl)
        with self._lock:
            self._store[key] = (value, expiry)

    def get(self, key: str) -> Optional[Any]:
        """Get value if not expired. Returns None if missing or expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expiry = entry
            if time.monotonic() > expiry:
                del self._store[key]
                return None
            return value

    def has(self, key: str) -> bool:
        """Check if key exists and is not expired."""
        return self.get(key) is not None

    def invalidate(self, key: str) -> None:
        """Remove a key from cache."""
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def stats(self) -> dict:
        """Return cache statistics."""
        with self._lock:
            now = time.monotonic()
            valid = sum(1 for _, expiry in self._store.values() if expiry > now)
            return {
                "total_keys": len(self._store),
                "valid_keys": valid,
                "expired_keys": len(self._store) - valid,
                "ttl_seconds": self._ttl,
            }

    def keys_by_prefix(self, prefix: str) -> list[str]:
        """Return all valid keys starting with prefix."""
        with self._lock:
            now = time.monotonic()
            return [k for k, (_, exp) in self._store.items() if k.startswith(prefix) and exp > now]

```

### `engine/agents/task_board.py`
```python
"""
Pipeline task board — tracks stage execution for dashboard visibility.
In-memory only; resets on each pipeline run.
"""

import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class PipelineTask:
    stage: str  # e.g. "technical_analyst"
    status: StageStatus = StageStatus.PENDING
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[float] = None
    error: Optional[str] = None
    result_summary: Optional[str] = None  # short one-line summary of result


class PipelineTaskBoard:
    """Thread-safe task board for one pipeline run."""

    def __init__(self):
        self._tasks: dict[str, PipelineTask] = {}
        self._lock = threading.Lock()
        self._run_id: Optional[str] = None
        self._symbol: Optional[str] = None
        self._interval: Optional[str] = None
        self._run_started_at: Optional[str] = None

    def start_run(self, run_id: str, symbol: str, interval: str):
        """Initialize the board for a new pipeline run."""
        with self._lock:
            self._run_id = run_id
            self._symbol = symbol
            self._interval = interval
            self._run_started_at = datetime.utcnow().isoformat()
            # Pre-populate all 10 known stages as PENDING
            stages = [
                "technical_analyst",
                "news_analyst",
                "social_analyst",
                "fundamentalist",
                "bull_researcher",
                "bear_researcher",
                "debate_orchestrator",
                "trader",
                "risk_manager",
                "fund_manager",
            ]
            self._tasks = {s: PipelineTask(stage=s) for s in stages}

    def start_stage(self, stage: str):
        with self._lock:
            if stage in self._tasks:
                self._tasks[stage].status = StageStatus.RUNNING
                self._tasks[stage].started_at = datetime.utcnow().isoformat()

    def complete_stage(self, stage: str, result_summary: Optional[str] = None):
        with self._lock:
            if stage in self._tasks:
                t = self._tasks[stage]
                t.status = StageStatus.DONE
                t.completed_at = datetime.utcnow().isoformat()
                t.result_summary = result_summary
                if t.started_at:
                    start = datetime.fromisoformat(t.started_at)
                    t.duration_ms = (datetime.utcnow() - start).total_seconds() * 1000

    def error_stage(self, stage: str, error: str):
        with self._lock:
            if stage in self._tasks:
                t = self._tasks[stage]
                t.status = StageStatus.ERROR
                t.completed_at = datetime.utcnow().isoformat()
                t.error = error
                if t.started_at:
                    start = datetime.fromisoformat(t.started_at)
                    t.duration_ms = (datetime.utcnow() - start).total_seconds() * 1000

    def skip_stage(self, stage: str):
        with self._lock:
            if stage in self._tasks:
                self._tasks[stage].status = StageStatus.SKIPPED

    def get_status(self) -> dict:
        with self._lock:
            return {
                "run_id": self._run_id,
                "symbol": self._symbol,
                "interval": self._interval,
                "run_started_at": self._run_started_at,
                "stages": {
                    name: {
                        "stage": t.stage,
                        "status": t.status.value,
                        "started_at": t.started_at,
                        "completed_at": t.completed_at,
                        "duration_ms": t.duration_ms,
                        "result_summary": t.result_summary,
                        "error": t.error,
                    }
                    for name, t in self._tasks.items()
                },
                "overall": self._overall_status(),
                "total_stages": len(self._tasks),
                "done_count": sum(1 for t in self._tasks.values() if t.status == StageStatus.DONE),
                "error_count": sum(
                    1 for t in self._tasks.values() if t.status == StageStatus.ERROR
                ),
            }

    def _overall_status(self) -> str:
        statuses = {t.status for t in self._tasks.values()}
        if StageStatus.ERROR in statuses:
            return "error"
        if StageStatus.RUNNING in statuses:
            return "running"
        if all(t.status in (StageStatus.DONE, StageStatus.SKIPPED) for t in self._tasks.values()):
            return "complete"
        return "pending"

    def reset(self):
        with self._lock:
            self._tasks = {}
            self._run_id = None
            self._symbol = None
            self._interval = None
            self._run_started_at = None


# Module-level singleton
_task_board: Optional[PipelineTaskBoard] = None


def get_task_board() -> PipelineTaskBoard:
    global _task_board
    if _task_board is None:
        _task_board = PipelineTaskBoard()
    return _task_board


def set_task_board_instance(board: PipelineTaskBoard):
    global _task_board
    _task_board = board

```

### `engine/routers/pipeline_board_router.py`
```python
"""Pipeline task board router — exposes live stage tracking."""

from fastapi import APIRouter

from agents.task_board import get_task_board

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/board")
async def get_pipeline_board():
    """Get current pipeline stage execution status."""
    return get_task_board().get_status()


@router.post("/board/reset")
async def reset_pipeline_board():
    """Reset the task board (clears last run state)."""
    get_task_board().reset()
    return {"status": "reset"}

```

### `engine/routers/config_router.py`
```python
"""Config overview router — exposes categorized TradingConfig fields (P2-C)."""

from __future__ import annotations

from fastapi import APIRouter

from config import settings

router = APIRouter(prefix="/config", tags=["config"])

SENSITIVE_KEYS = {
    "ANTHROPIC_API_KEY",
    "FINNHUB_API_KEY",
    "POLYGON_API_KEY",
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_WHATSAPP_FROM",
    "WHATSAPP_TO",
    "IBKR_CLIENT_ID",
}

CATEGORIES: dict[str, list[str]] = {
    "safety": [
        "MAX_POSITION_SIZE_PCT",
        "MAX_DAILY_LOSS_PCT",
        "MAX_DRAWDOWN_PCT",
        "MAX_CONTRACTS_PER_INSTRUMENT",
        "MAX_OVERNIGHT_CONTRACTS",
        "MAX_SINGLE_ORDER_VALUE",
        "MAX_MARGIN_UTILIZATION",
        "MAX_CORRELATED_EXPOSURE_PCT",
        "MAX_ORDERS_PER_MINUTE",
        "LIVE_TRADING_ENABLED",
        "REQUIRE_HUMAN_APPROVAL",
    ],
    "broker": [
        "IBKR_HOST",
        "IBKR_PORT",
        "IBKR_CLIENT_ID",
        "IBKR_PAPER_MODE",
    ],
    "data": [
        "POLYGON_API_KEY",
        "FINNHUB_API_KEY",
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "ALPACA_PAPER",
    ],
    "llm": [
        "ANTHROPIC_API_KEY",
        "LLM_PROVIDER",
    ],
    "notifications": [
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_WHATSAPP_FROM",
        "WHATSAPP_TO",
    ],
    "feature_flags": [
        "ENABLE_KAIROS",
        "ENABLE_SPECULATION",
        "ENABLE_TILT_DETECTION",
        "ENABLE_DREAM_CONSOLIDATION",
        "ENABLE_CONTEXT_COMPACTION",
        "ENABLE_CRYPTO",
        "ENABLE_POLYMARKET",
        "ENABLE_RL_TRADING",
        "ENABLE_SIGNAL_SANITIZATION",
        "KAIROS_TICK_SECONDS",
        "KAIROS_OFF_HOURS_TICK_SECONDS",
        "KAIROS_NOTIFY_SEVERITY",
    ],
}


def _mask(key: str, value) -> str:
    if key in SENSITIVE_KEYS and value:
        s = str(value)
        if len(s) > 4:
            return "***" + s[-4:]
        return "***"
    return value


@router.get("/overview")
async def config_overview():
    """Return all TradingConfig fields grouped by category, sensitive values masked."""
    config_dict = settings.model_dump() if hasattr(settings, "model_dump") else settings.dict()

    # Pull feature flags from registry (they live there, not in TradingConfig)
    try:
        from flags.registry import get_flags

        try:
            flags_registry = get_flags()
            flag_data = {
                name: info["enabled"] for name, info in flags_registry.list_flags().items()
            }
        except RuntimeError:
            # Singleton not initialized (e.g. in tests) — use static FLAG_DEFINITIONS defaults
            from flags.registry import FLAG_DEFINITIONS

            flag_data = {f["name"]: f["default"] for f in FLAG_DEFINITIONS}
    except Exception:
        flag_data = {}

    categorized: dict[str, list] = {}
    seen_keys: set[str] = set()

    for category, keys in CATEGORIES.items():
        items = []
        for key in keys:
            # Feature flags come from registry, other keys from config_dict
            if category == "feature_flags" and key in flag_data:
                items.append(
                    {
                        "key": key,
                        "value": flag_data[key],
                        "sensitive": False,
                    }
                )
                seen_keys.add(key)
            elif key in config_dict:
                items.append(
                    {
                        "key": key,
                        "value": _mask(key, config_dict[key]),
                        "sensitive": key in SENSITIVE_KEYS,
                    }
                )
                seen_keys.add(key)
        categorized[category] = items

    # Uncategorized fields
    other: list = []
    for key, value in config_dict.items():
        if key not in seen_keys and key != "AGENT_MAX_TOKENS":
            other.append(
                {
                    "key": key,
                    "value": _mask(key, value),
                    "sensitive": key in SENSITIVE_KEYS,
                }
            )
    if other:
        categorized["other"] = other

    return {
        "categories": categorized,
        "total_fields": len(config_dict),
    }


@router.get("/health-check")
async def config_health_check():
    """Check which critical API keys are configured (not their values)."""
    config_dict = settings.model_dump() if hasattr(settings, "model_dump") else settings.dict()

    critical_keys = [
        "ANTHROPIC_API_KEY",
        "FINNHUB_API_KEY",
        "POLYGON_API_KEY",
        "ALPACA_API_KEY",
        "TWILIO_ACCOUNT_SID",
        "WHATSAPP_TO",
    ]

    return {
        "configured": {k: bool(config_dict.get(k)) for k in critical_keys},
        "live_trading_enabled": config_dict.get("LIVE_TRADING_ENABLED", False),
        "require_human_approval": config_dict.get("REQUIRE_HUMAN_APPROVAL", True),
        "paper_trading": not config_dict.get("LIVE_TRADING_ENABLED", False),
    }

```

### `engine/security/__init__.py`
```python
"""
JARVIS TRADER — Security Package
"""

from security.log_sanitizer import (
    SanitizingFormatter,
    install_sanitizing_formatter,
    sanitize_message,
)

__all__ = [
    "sanitize_message",
    "SanitizingFormatter",
    "install_sanitizing_formatter",
]

```

### `engine/security/log_sanitizer.py`
```python
"""
Anti-signal-leakage log sanitizer.
Scrubs sensitive data from all log output when ENABLE_SIGNAL_SANITIZATION=True.
Inspired by Claude Code's signal sanitization pattern.
"""

import logging
import re
from typing import Optional

# Patterns that match sensitive data
SENSITIVE_PATTERNS = [
    # API keys (various formats)
    (re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"), "sk-ant-***"),
    (re.compile(r"sk-[A-Za-z0-9]{40,}"), "sk-***"),
    (re.compile(r"AC[a-f0-9]{32}"), "AC***"),  # Twilio Account SID
    # Phone numbers (WhatsApp format)
    (re.compile(r"whatsapp:\+\d{10,15}"), "whatsapp:+***"),
    (re.compile(r"\+1\d{10}"), "+1***"),
    # IB account patterns
    (re.compile(r"\b[A-Z]{1}[0-9]{6}\b"), "IB***"),  # e.g. U123456
    # Futures prices (prevent signal leakage)
    (re.compile(r"LONG\s+[A-Z]{2,4}\s+@\s+[\d,]+\.?\d*"), "LONG *** @ ***"),
    (re.compile(r"SHORT\s+[A-Z]{2,4}\s+@\s+[\d,]+\.?\d*"), "SHORT *** @ ***"),
]

# These patterns are only applied when ENABLE_SIGNAL_SANITIZATION=True
SIGNAL_PATTERNS = [
    # Entry/exit prices
    (re.compile(r"entry[:\s]+[\d,]+\.?\d*", re.IGNORECASE), "entry: ***"),
    (re.compile(r"stop[:\s]+[\d,]+\.?\d*", re.IGNORECASE), "stop: ***"),
    (re.compile(r"target[:\s]+[\d,]+\.?\d*", re.IGNORECASE), "target: ***"),
    # Position sizes
    (re.compile(r"\d+\s+contract[s]?", re.IGNORECASE), "*** contracts"),
    # P&L amounts
    (re.compile(r"[+-]\$[\d,]+\.?\d*"), "+/-$***"),
]


def sanitize_message(message: str, sanitize_signals: bool = False) -> str:
    """
    Apply sanitization patterns to a log message.

    Args:
        message: Raw log message
        sanitize_signals: If True, also sanitize trade signals and prices

    Returns:
        Sanitized message with sensitive data replaced
    """
    result = str(message)

    # Always apply API key / credential patterns
    for pattern, replacement in SENSITIVE_PATTERNS:
        if replacement is not None:
            result = pattern.sub(replacement, result)

    # Optionally apply signal patterns
    if sanitize_signals:
        for pattern, replacement in SIGNAL_PATTERNS:
            result = pattern.sub(replacement, result)

    return result


class SanitizingFormatter(logging.Formatter):
    """
    Custom logging formatter that sanitizes sensitive data from log records.
    Active when ENABLE_SIGNAL_SANITIZATION=True in config.
    """

    def __init__(
        self,
        fmt: Optional[str] = None,
        datefmt: Optional[str] = None,
        sanitize_signals: bool = False,
    ):
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.sanitize_signals = sanitize_signals

    def format(self, record: logging.LogRecord) -> str:
        # Format normally first
        formatted = super().format(record)
        # Then sanitize the fully-formatted string
        return sanitize_message(formatted, sanitize_signals=self.sanitize_signals)

    def formatMessage(self, record: logging.LogRecord) -> str:
        # Pre-format the message using original args (preserves %d, %f, etc.)
        # then sanitize the fully-interpolated string, clearing args to avoid
        # a second % interpolation by super().formatMessage() that would fail
        # if we had converted numeric args to strings.
        try:
            formatted_msg = record.getMessage()
        except Exception:
            formatted_msg = str(record.msg)
        sanitized_msg = sanitize_message(formatted_msg, sanitize_signals=self.sanitize_signals)
        record.msg = sanitized_msg
        record.args = None
        return super().formatMessage(record)


def install_sanitizing_formatter(sanitize_signals: bool = False) -> None:
    """
    Install the sanitizing formatter on the root logger and known sub-loggers.
    Should be called at startup when ENABLE_SIGNAL_SANITIZATION=True.

    Args:
        sanitize_signals: If True, trade signals and prices are also masked.
    """
    fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    sanitizing_formatter = SanitizingFormatter(fmt=fmt, sanitize_signals=sanitize_signals)

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.setFormatter(sanitizing_formatter)

    # Also apply to the uvicorn loggers
    for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"]:
        uvicorn_logger = logging.getLogger(logger_name)
        for handler in uvicorn_logger.handlers:
            handler.setFormatter(sanitizing_formatter)

```
