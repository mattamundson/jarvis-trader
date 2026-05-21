"""
Predictive Maintenance Monitor — JARVIS TRADER
================================================
Detects engine health degradation BEFORE a crash and triggers a preemptive
pm2 restart (when explicitly authorized) or fires a webhook alert.

Safety gates (two independent flags, both must be 1 to auto-restart):
  ENABLE_PREDICTIVE_MAINTENANCE=1  — enables the monitor loop at all
  PREDICTIVE_MAINTENANCE_ALLOW_RESTART=1  — permits pm2 restart action

Default: both OFF.  Start with ENABLE only (alert-only mode), observe for a
week, then enable ALLOW_RESTART.

Degradation score is 0.0 (healthy) to 1.0 (imminent failure), composed of
four independent signals weighted to sum to 1.0:
  memory_growth_rate  0.30  — MB/hour growth trend over rolling 24h history
  ib_reconnect_spike  0.30  — reconnect events in the last 1h from log
  llm_latency_creep   0.20  — p95 latency > 2x baseline (from llm_calls.jsonl
                               or llm_costs.db; omitted when unavailable)
  pm2_restart_delta   0.20  — pm2 restart count increased in last 10min
                               (crash already started)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import subprocess
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Optional

logger = logging.getLogger(__name__)

# ── Env helpers ───────────────────────────────────────────────────────────────

_ENV_ENABLE = "ENABLE_PREDICTIVE_MAINTENANCE"
_ENV_ALLOW_RESTART = "PREDICTIVE_MAINTENANCE_ALLOW_RESTART"
_ENV_WEBHOOK = "PREDICTIVE_MAINTENANCE_WEBHOOK_URL"

# Thresholds (overridable via env at runtime)
_DEFAULT_MEM_GROWTH_MB_PER_HOUR = float(os.getenv("PM_MEM_GROWTH_MB_PER_HOUR", "200"))
_DEFAULT_IB_RECONNECT_THRESHOLD = int(os.getenv("PM_IB_RECONNECT_THRESHOLD", "5"))
_DEFAULT_LLM_LATENCY_BASELINE_MS = float(os.getenv("PM_LLM_LATENCY_BASELINE_MS", "5000"))
_DEFAULT_SCORE_THRESHOLD = float(os.getenv("PM_SCORE_THRESHOLD", "0.7"))
_DEFAULT_RESTART_COOLDOWN_SECONDS = int(os.getenv("PM_RESTART_COOLDOWN_SECONDS", "3600"))

# Paths resolved relative to engine root (cwd when engine starts via pm2)
_ENGINE_ROOT = Path(__file__).resolve().parent.parent
_LOG_DIR = _ENGINE_ROOT / "logs"
_ENGINE_LOG = _LOG_DIR / "jarvis-engine-out.log"
_LLM_CALLS_JSONL = _LOG_DIR / "llm_calls.jsonl"
_LLM_COSTS_DB = _ENGINE_ROOT / "data" / "llm_costs.db"
_HEALTH_SAMPLES_LOG = _LOG_DIR / "health_samples.jsonl"

# Rolling 24-hour history ceiling
_MAX_HISTORY = 288  # 24h at 5-min intervals


def is_predictive_maintenance_enabled() -> bool:
    """Fresh env read — no caching so .env changes take effect without restart."""
    return os.environ.get(_ENV_ENABLE, "0").strip() == "1"


def is_auto_restart_allowed() -> bool:
    """Both flags must be 1 for auto-restart to fire."""
    return is_predictive_maintenance_enabled() and (
        os.environ.get(_ENV_ALLOW_RESTART, "0").strip() == "1"
    )


# ── HealthMonitor ─────────────────────────────────────────────────────────────


class HealthMonitor:
    """
    Collects health samples, scores degradation, and optionally triggers restart.

    Usage:
        monitor = HealthMonitor()
        asyncio.create_task(monitor.monitor_loop())

    The monitor is intentionally stateless between process restarts — history
    is rebuilt from ``health_samples.jsonl`` on boot (future enhancement).
    Currently history lives in-process only; a 24h crash would lose the trend.
    """

    def __init__(
        self,
        mem_growth_threshold_mb_per_hour: float = _DEFAULT_MEM_GROWTH_MB_PER_HOUR,
        ib_reconnect_threshold: int = _DEFAULT_IB_RECONNECT_THRESHOLD,
        llm_latency_baseline_ms: float = _DEFAULT_LLM_LATENCY_BASELINE_MS,
        score_threshold: float = _DEFAULT_SCORE_THRESHOLD,
        restart_cooldown_seconds: int = _DEFAULT_RESTART_COOLDOWN_SECONDS,
    ) -> None:
        self.mem_growth_threshold = mem_growth_threshold_mb_per_hour
        self.ib_reconnect_threshold = ib_reconnect_threshold
        self.llm_latency_baseline_ms = llm_latency_baseline_ms
        self.score_threshold = score_threshold
        self.restart_cooldown_seconds = restart_cooldown_seconds

        self._history: Deque[dict] = deque(maxlen=_MAX_HISTORY)
        self._last_restart_ts: float = 0.0
        self._last_pm2_restart_count: Optional[int] = None
        self._last_pm2_check_ts: float = 0.0
        self._last_pm2_count_snapshot: Optional[int] = None

    # ── Sampling ──────────────────────────────────────────────────────────────

    async def sample_now(self) -> dict:
        """
        Collect a single point-in-time health snapshot.

        Returns a dict with keys:
          ts, memory_mb, ib_reconnects_1h, llm_p95_ms, uptime_seconds, pm2_restart_count
        All values may be None when their source is unavailable — the scoring
        function treats None inputs as 0-contribution rather than erroring.
        """
        ts = datetime.now(timezone.utc).isoformat()
        sample: dict[str, Any] = {
            "ts": ts,
            "memory_mb": None,
            "ib_reconnects_1h": None,
            "llm_p95_ms": None,
            "uptime_seconds": None,
            "pm2_restart_count": None,
        }

        # Memory via psutil on the engine process (this process)
        try:
            import psutil

            proc = psutil.Process(os.getpid())
            sample["memory_mb"] = round(proc.memory_info().rss / 1_048_576, 1)
        except Exception as exc:
            logger.debug("predictive_maintenance: psutil memory read failed: %s", exc)

        # IB reconnect count — grep engine log for last 1h
        sample["ib_reconnects_1h"] = self._count_ib_reconnects_1h()

        # LLM p95 latency
        sample["llm_p95_ms"] = self._read_llm_p95_ms()

        # Engine uptime from /health
        sample["uptime_seconds"] = await self._read_engine_uptime()

        # PM2 restart count
        sample["pm2_restart_count"] = self._read_pm2_restart_count()

        return sample

    def _count_ib_reconnects_1h(self) -> Optional[int]:
        """Count '[IB] reconnect' occurrences in the engine log over the last hour."""
        try:
            if not _ENGINE_LOG.exists():
                return 0
            # Read up to last 50 KB to avoid OOM on huge logs
            log_text = _ENGINE_LOG.read_bytes()[-51200:].decode("utf-8", errors="replace")
            # Regex: find timestamp + reconnect marker, filter by age
            pattern = re.compile(
                r'"timestamp"\s*:\s*"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})[^"]*"'
                r".*?\[IB\] reconnect",
                re.DOTALL,
            )
            now = datetime.now(timezone.utc)
            count = 0
            for m in pattern.finditer(log_text):
                try:
                    ts_str = m.group(1)
                    event_dt = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                    if (now - event_dt).total_seconds() <= 3600:
                        count += 1
                except Exception:
                    continue
            return count
        except Exception as exc:
            logger.debug("predictive_maintenance: IB log parse failed: %s", exc)
            return None

    def _read_llm_p95_ms(self) -> Optional[float]:
        """Read LLM p95 latency from llm_calls.jsonl or llm_costs.db (last 1h)."""
        # Try JSONL first (lightweight)
        try:
            if _LLM_CALLS_JSONL.exists():
                latencies: list[float] = []
                cutoff = time.time() - 3600
                for line in _LLM_CALLS_JSONL.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines():
                    try:
                        obj = json.loads(line)
                        ts = obj.get("ts") or obj.get("timestamp", 0)
                        if isinstance(ts, str):
                            ts = datetime.fromisoformat(ts).timestamp()
                        if ts >= cutoff and (lat := obj.get("latency_ms")):
                            latencies.append(float(lat))
                    except Exception:
                        continue
                if latencies:
                    latencies.sort()
                    idx = max(0, int(len(latencies) * 0.95) - 1)
                    return round(latencies[idx], 1)
        except Exception as exc:
            logger.debug("predictive_maintenance: llm_calls.jsonl read failed: %s", exc)

        # Fallback: llm_costs.db SQLite
        try:
            if _LLM_COSTS_DB.exists():
                cutoff_iso = "strftime('%Y-%m-%dT%H:%M:%S', 'now', '-1 hour')"
                conn = sqlite3.connect(str(_LLM_COSTS_DB))
                try:
                    cur = conn.cursor()
                    cur.execute(
                        f"SELECT latency_ms FROM llm_calls WHERE timestamp > {cutoff_iso} "
                        "AND latency_ms IS NOT NULL"
                    )
                    rows = cur.fetchall()
                finally:
                    conn.close()
                if rows:
                    latencies = sorted(float(r[0]) for r in rows)
                    idx = max(0, int(len(latencies) * 0.95) - 1)
                    return round(latencies[idx], 1)
        except Exception as exc:
            logger.debug("predictive_maintenance: llm_costs.db read failed: %s", exc)

        return None

    async def _read_engine_uptime(self) -> Optional[float]:
        """Read uptime_seconds from /health — non-blocking with 2s timeout."""
        import urllib.error
        import urllib.request

        try:
            req = urllib.request.Request("http://127.0.0.1:8010/health", method="GET")
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=2.0),
            )
            data = json.loads(response.read())
            return float(data.get("uptime_seconds", 0))
        except Exception as exc:
            logger.debug("predictive_maintenance: uptime read failed: %s", exc)
            return None

    def _read_pm2_restart_count(self) -> Optional[int]:
        """Parse pm2 jlist for jarvis-engine restart_time. Returns None if pm2 unavailable."""
        try:
            result = subprocess.run(
                ["pm2", "jlist"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return None
            processes = json.loads(result.stdout)
            for p in processes:
                if p.get("name") == "jarvis-engine":
                    return int(p.get("pm2_env", {}).get("restart_time", 0))
            return None
        except Exception as exc:
            logger.debug("predictive_maintenance: pm2 jlist failed: %s", exc)
            return None

    # ── Scoring ───────────────────────────────────────────────────────────────

    def degradation_score(self, sample: dict, history: list[dict]) -> float:
        """
        Compute a degradation score from 0.0 (healthy) to 1.0 (imminent crash).

        Four weighted inputs:
          memory_growth_rate  0.30 — MB/hour trend over history
          ib_reconnect_spike  0.30 — reconnects in last 1h > threshold
          llm_latency_creep   0.20 — p95 latency > 2x baseline
          pm2_restart_delta   0.20 — pm2 restart count increased in last 10min
        """
        score = 0.0

        # 1. Memory growth rate (0.30)
        mem_score = self._score_memory_growth(sample, history)
        score += 0.30 * mem_score

        # 2. IB reconnect spike (0.30)
        reconnects = sample.get("ib_reconnects_1h")
        if reconnects is not None and reconnects > self.ib_reconnect_threshold:
            score += 0.30

        # 3. LLM latency creep (0.20)
        llm_p95 = sample.get("llm_p95_ms")
        if llm_p95 is not None and self.llm_latency_baseline_ms > 0:
            if llm_p95 > 2.0 * self.llm_latency_baseline_ms:
                score += 0.20

        # 4. PM2 restart delta (0.20) — crash already started
        pm2_score = self._score_pm2_restart_delta(sample, history)
        score += 0.20 * pm2_score

        return min(1.0, round(score, 4))

    def _score_memory_growth(self, sample: dict, history: list[dict]) -> float:
        """1.0 if MB/hour growth exceeds threshold, else proportional."""
        current_mem = sample.get("memory_mb")
        if current_mem is None or len(history) < 2:
            return 0.0

        # Find oldest sample with valid memory reading within the last 2h
        cutoff_ts = time.time() - 7200
        oldest = None
        for h in history:
            h_ts_str = h.get("ts")
            h_mem = h.get("memory_mb")
            if h_ts_str is None or h_mem is None:
                continue
            try:
                h_ts = datetime.fromisoformat(h_ts_str).timestamp()
            except Exception:
                continue
            if h_ts >= cutoff_ts:
                if oldest is None:
                    oldest = (h_ts, h_mem)
                break

        if oldest is None:
            return 0.0

        elapsed_hours = (time.time() - oldest[0]) / 3600.0
        if elapsed_hours < 0.01:
            return 0.0

        growth_mb_per_hour = (current_mem - oldest[1]) / elapsed_hours
        if growth_mb_per_hour <= 0:
            return 0.0
        return min(1.0, growth_mb_per_hour / self.mem_growth_threshold)

    def _score_pm2_restart_delta(self, sample: dict, history: list[dict]) -> float:
        """1.0 if pm2 restart count increased vs 10min-ago sample; 0.0 otherwise."""
        current = sample.get("pm2_restart_count")
        if current is None:
            return 0.0

        cutoff_ts = time.time() - 600  # 10 minutes
        for h in reversed(history):
            h_ts_str = h.get("ts")
            h_count = h.get("pm2_restart_count")
            if h_ts_str is None or h_count is None:
                continue
            try:
                h_ts = datetime.fromisoformat(h_ts_str).timestamp()
            except Exception:
                continue
            if h_ts >= cutoff_ts and h_count < current:
                return 1.0
        return 0.0

    # ── Restart decision ──────────────────────────────────────────────────────

    def should_restart_preemptively(self, score: float, history: list[dict]) -> bool:
        """
        True when:
          - score > score_threshold (default 0.7)
          - No restart fired within the cooldown window (default 1h)

        Cooldown prevents flap: if a preemptive restart doesn't clear the
        degradation signal, the monitor will not fire again for another hour.
        """
        if score <= self.score_threshold:
            return False
        if time.time() - self._last_restart_ts < self.restart_cooldown_seconds:
            return False
        return True

    # ── Webhook ───────────────────────────────────────────────────────────────

    async def _send_webhook_alert(self, score: float, sample: dict) -> None:
        """POST a degradation alert to the configured webhook URL (optional)."""
        url = os.environ.get(_ENV_WEBHOOK, "").strip()
        if not url:
            return
        try:
            import urllib.request as _req

            payload = json.dumps(
                {
                    "content": (
                        f"JARVIS PREDICTIVE MAINTENANCE ALERT\n"
                        f"Degradation score: {score:.2f} (threshold: {self.score_threshold})\n"
                        f"Memory MB: {sample.get('memory_mb')}\n"
                        f"IB reconnects/1h: {sample.get('ib_reconnects_1h')}\n"
                        f"LLM p95 ms: {sample.get('llm_p95_ms')}\n"
                        f"PM2 restarts: {sample.get('pm2_restart_count')}\n"
                        f"TS: {sample.get('ts')}"
                    )
                }
            ).encode()
            req = _req.Request(url, data=payload, headers={"Content-Type": "application/json"})
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: _req.urlopen(req, timeout=5))
            logger.info("predictive_maintenance: webhook alert sent")
        except Exception as exc:
            logger.warning("predictive_maintenance: webhook send failed: %s", exc)

    # ── Restart action ────────────────────────────────────────────────────────

    def _trigger_pm2_restart(self) -> bool:
        """
        Invoke ``pm2 restart jarvis-engine`` — the same command used by
        restart_engine.ps1.  Returns True on success.

        Only called when BOTH env flags are 1 AND should_restart_preemptively()
        returned True.  Never bypasses pm2.
        """
        try:
            result = subprocess.run(
                ["pm2", "restart", "jarvis-engine"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self._last_restart_ts = time.time()
            if result.returncode == 0:
                logger.warning(
                    "predictive_maintenance: pm2 restart jarvis-engine TRIGGERED "
                    "(preemptive — degradation score exceeded threshold)"
                )
                return True
            logger.error(
                "predictive_maintenance: pm2 restart failed (exit %d): %s",
                result.returncode,
                result.stderr[:200],
            )
            return False
        except Exception as exc:
            logger.error("predictive_maintenance: pm2 restart exception: %s", exc)
            return False

    # ── Sample log ────────────────────────────────────────────────────────────

    def _log_sample(self, sample: dict, score: float) -> None:
        """Append sample + score to health_samples.jsonl (non-fatal)."""
        try:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            record = dict(sample)
            record["degradation_score"] = score
            with _HEALTH_SAMPLES_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as exc:
            logger.debug("predictive_maintenance: sample log write failed: %s", exc)

    # ── Monitor loop ──────────────────────────────────────────────────────────

    async def monitor_loop(self, interval_seconds: int = 300) -> None:
        """
        Main loop — runs indefinitely as an asyncio task.

        Samples every ``interval_seconds`` (default 5 min).
        Maintains rolling 24h history.
        Fires WARNING + optional webhook + optional pm2 restart when score > threshold.
        Errors in sample_now() are swallowed — loop continues.
        """
        logger.info(
            "predictive_maintenance: monitor loop started (interval=%ds, threshold=%.2f)",
            interval_seconds,
            self.score_threshold,
        )
        while True:
            try:
                if not is_predictive_maintenance_enabled():
                    # Flag was turned off at runtime — sleep and re-check
                    await asyncio.sleep(interval_seconds)
                    continue

                sample = await self.sample_now()
                history_list = list(self._history)
                score = self.degradation_score(sample, history_list)
                self._history.append(sample)
                self._log_sample(sample, score)

                if score > self.score_threshold:
                    logger.warning(
                        "predictive_maintenance: DEGRADATION WARNING — score=%.2f "
                        "(memory_mb=%s, ib_reconnects=%s, llm_p95_ms=%s, pm2_restarts=%s)",
                        score,
                        sample.get("memory_mb"),
                        sample.get("ib_reconnects_1h"),
                        sample.get("llm_p95_ms"),
                        sample.get("pm2_restart_count"),
                    )
                    await self._send_webhook_alert(score, sample)

                    if is_auto_restart_allowed() and self.should_restart_preemptively(
                        score, history_list
                    ):
                        self._trigger_pm2_restart()
                else:
                    logger.debug("predictive_maintenance: score=%.2f (healthy)", score)

            except Exception as exc:
                logger.warning("predictive_maintenance: sample error (loop continues): %s", exc)

            await asyncio.sleep(interval_seconds)

    # ── History snapshot for /health/predictive ───────────────────────────────

    def get_history_summary(self) -> dict:
        """Return last 24h history for the HTTP endpoint."""
        history = list(self._history)
        if not history:
            return {"sample_count": 0, "samples": []}
        scores = [self.degradation_score(s, history[: i + 1]) for i, s in enumerate(history)]
        return {
            "sample_count": len(history),
            "max_score_24h": max(scores) if scores else 0.0,
            "latest_score": scores[-1] if scores else 0.0,
            "samples": history[-12:],  # last hour at 5-min interval
        }
