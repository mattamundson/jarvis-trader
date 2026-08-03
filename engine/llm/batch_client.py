"""
JARVIS TRADER — Anthropic Message Batches client (async submit/poll/collect).

For OFFLINE agents only (weekend research pass, kairos/dreaming, vault/synthesis —
never the live per-symbol pipeline). The Batches API trades a 1-24h SLA for a flat
50% discount versus synchronous calls; that SLA is incompatible with any agent whose
output gates a same-scan trading decision.

Anthropic-only: no equivalent async-batch leg exists on Vertex/Gemini/OpenAI/Kimi, so
there is no cross-provider fallback to route through at this layer (unlike
JarvisLLMClient's cascade). Constructs its own anthropic.AsyncAnthropic directly.

Failure/fallback policy (tiered — always via JarvisLLMClient.call(), never hand-rolled
retries):
  1. submit_batch() itself raises           -> caller decides on_submit_failure:
                                                "skip" (low-stakes weekly work, try
                                                again next cadence) or "sync_fallback"
                                                (same-day/user-facing consumers should
                                                use this, not "skip").
  2. Individual errored/canceled/expired     -> always sync_fallback via
     results after collect_results()            fallback_sync_for_failed() (cheap: a
                                                handful of items per batch).
  3. Whole batch exceeds 24h without ending  -> sweep_pending() marks it "stale" after
                                                a 25h grace period and the caller should
                                                sync_fallback every custom_id in it.

Results stream back from Anthropic in arbitrary order — always bucket by custom_id,
never assume submission order.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from llm.client import JarvisLLMClient, LLMCallResult

logger = logging.getLogger(__name__)

# A batch not "ended" past this many hours past submission is treated as stale
# (Anthropic's documented max is 24h; 1h grace absorbs clock/poll-cadence skew).
_STALE_AFTER_HOURS = 25


@dataclass
class BatchResultItem:
    """One collected result for a single custom_id."""

    custom_id: str
    result_type: str  # succeeded|errored|canceled|expired
    content: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    error: Optional[str] = None


class JarvisBatchClient:
    """
    Submit/poll/collect Anthropic Message Batches, with SQLite-backed job tracking.

    Not a drop-in replacement for JarvisLLMClient — callers build requests via
    build_request(), submit a batch, then either poll manually or rely on
    sweep_pending() (a scheduler cron) to harvest results as soon as each batch ends.
    """

    def __init__(self, api_key: Optional[str] = None, db_path: str = "data/llm_batches.db"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.client = anthropic.AsyncAnthropic(api_key=self.api_key)
        self.db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS batch_jobs (
                batch_id TEXT PRIMARY KEY,
                agent_name TEXT NOT NULL,
                submitted_at TEXT NOT NULL,
                request_count INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'submitted',
                processing_status TEXT,
                ended_at TEXT,
                results_collected_at TEXT,
                request_meta_json TEXT NOT NULL,
                consumer TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS batch_results (
                custom_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                result_type TEXT NOT NULL,
                content TEXT,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                error TEXT,
                collected_at TEXT NOT NULL,
                consumed INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (batch_id, custom_id)
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_batch_jobs_status ON batch_jobs(status)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_batch_results_consumed ON batch_results(consumed)"
        )
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Request building
    # ------------------------------------------------------------------

    def build_request(
        self,
        custom_id: str,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        shared_system_cache: bool = False,
    ) -> Request:
        """
        Build one Batches API Request. custom_id must be unique within the batch
        (Anthropic uses it to key results, which return in arbitrary order).

        shared_system_cache=True wraps `system` with cache_control: ephemeral —
        use when the same system prompt is reused across many requests in the
        batch, or it exceeds the project's ~1024-token cache threshold, so the
        prompt-cache discount stacks on top of the batch discount.
        """
        if shared_system_cache:
            system_param: Any = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        else:
            system_param = system

        params = MessageCreateParamsNonStreaming(
            model=model,
            max_tokens=max_tokens,
            system=system_param,
            messages=messages,
        )
        return Request(custom_id=custom_id, params=params)

    # ------------------------------------------------------------------
    # Submit / poll / collect
    # ------------------------------------------------------------------

    async def submit_batch(self, agent_name: str, requests: list[Request]) -> str:
        """Submit a batch and persist its job row. Returns the batch_id."""
        batch = await self.client.messages.batches.create(requests=requests)

        request_meta = {r["custom_id"]: r["params"]["model"] for r in requests}
        now = datetime.now(timezone.utc).isoformat()

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO batch_jobs
            (batch_id, agent_name, submitted_at, request_count, status,
             processing_status, request_meta_json, consumer)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch.id,
                agent_name,
                now,
                len(requests),
                "submitted",
                batch.processing_status,
                json.dumps(request_meta),
                agent_name,
            ),
        )
        conn.commit()
        conn.close()
        logger.info(
            "batch_client: submitted batch %s for %s (%d requests)",
            batch.id,
            agent_name,
            len(requests),
        )
        return batch.id

    async def poll_batch(self, batch_id: str) -> str:
        """Retrieve current processing_status ('in_progress'|'canceling'|'ended')."""
        batch = await self.client.messages.batches.retrieve(message_batch_id=batch_id)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE batch_jobs SET processing_status = ?, status = ? WHERE batch_id = ?",
            (
                batch.processing_status,
                "ended" if batch.processing_status == "ended" else "polling",
                batch_id,
            ),
        )
        if batch.ended_at:
            conn.execute(
                "UPDATE batch_jobs SET ended_at = ? WHERE batch_id = ?",
                (batch.ended_at.isoformat(), batch_id),
            )
        conn.commit()
        conn.close()
        return batch.processing_status

    async def collect_results(self, batch_id: str) -> dict[str, BatchResultItem]:
        """
        Stream results for an ended batch, bucket by custom_id, persist to
        batch_results, and return the bucketed dict. Safe to call more than
        once — re-collection upserts the same rows (INSERT OR REPLACE).

        Never assumes result order matches submission order.
        """
        bucketed: dict[str, BatchResultItem] = {}
        now = datetime.now(timezone.utc).isoformat()

        conn = sqlite3.connect(self.db_path)
        async for entry in await self.client.messages.batches.results(
            message_batch_id=batch_id
        ):
            item = self._parse_result_entry(entry)
            bucketed[item.custom_id] = item
            conn.execute(
                """
                INSERT OR REPLACE INTO batch_results
                (custom_id, batch_id, result_type, content, input_tokens,
                 output_tokens, error, collected_at, consumed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?,
                        COALESCE((SELECT consumed FROM batch_results
                                  WHERE batch_id = ? AND custom_id = ?), 0))
                """,
                (
                    item.custom_id,
                    batch_id,
                    item.result_type,
                    item.content,
                    item.input_tokens,
                    item.output_tokens,
                    item.error,
                    now,
                    batch_id,
                    item.custom_id,
                ),
            )
        conn.execute(
            "UPDATE batch_jobs SET results_collected_at = ? WHERE batch_id = ?",
            (now, batch_id),
        )
        conn.commit()
        conn.close()
        logger.info(
            "batch_client: collected %d results for batch %s", len(bucketed), batch_id
        )
        return bucketed

    def _parse_result_entry(self, entry: Any) -> BatchResultItem:
        result = entry.result
        result_type = result.type

        if result_type == "succeeded":
            message = result.message
            content_text = "".join(
                block.text for block in message.content if getattr(block, "type", None) == "text"
            )
            usage = message.usage
            return BatchResultItem(
                custom_id=entry.custom_id,
                result_type=result_type,
                content=content_text,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )

        error_detail = None
        if result_type == "errored":
            error_detail = str(result.error)
        return BatchResultItem(
            custom_id=entry.custom_id,
            result_type=result_type,
            error=error_detail,
        )

    # ------------------------------------------------------------------
    # Sweep — generic poll cadence, decoupled from per-consumer collection
    # ------------------------------------------------------------------

    async def sweep_pending(self) -> dict[str, Any]:
        """
        Poll every non-ended, non-stale batch_jobs row. On 'ended', harvest
        results immediately into batch_results (consumers read from there on
        their own cadence). Batches past _STALE_AFTER_HOURS without ending
        are marked 'stale' so the caller can trigger full sync fallback.

        Returns a summary dict: {polled, newly_ended, newly_stale}.
        """
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT batch_id, submitted_at FROM batch_jobs "
            "WHERE status NOT IN ('ended', 'stale', 'failed_submit')"
        ).fetchall()
        conn.close()

        polled = 0
        newly_ended: list[str] = []
        newly_stale: list[str] = []
        now = datetime.now(timezone.utc)

        for batch_id, submitted_at in rows:
            polled += 1
            submitted_dt = datetime.fromisoformat(submitted_at)
            if now - submitted_dt > timedelta(hours=_STALE_AFTER_HOURS):
                conn = sqlite3.connect(self.db_path)
                conn.execute(
                    "UPDATE batch_jobs SET status = 'stale' WHERE batch_id = ?",
                    (batch_id,),
                )
                conn.commit()
                conn.close()
                newly_stale.append(batch_id)
                logger.warning("batch_client: batch %s marked stale (>%dh)", batch_id, _STALE_AFTER_HOURS)
                continue

            status = await self.poll_batch(batch_id)
            if status == "ended":
                await self.collect_results(batch_id)
                newly_ended.append(batch_id)

        summary = {"polled": polled, "newly_ended": newly_ended, "newly_stale": newly_stale}
        logger.info("batch_client: sweep_pending — %s", summary)
        return summary

    # ------------------------------------------------------------------
    # Fallback — always reuses JarvisLLMClient.call(), never hand-rolled retries
    # ------------------------------------------------------------------

    async def fallback_sync_for_failed(
        self,
        llm_client: JarvisLLMClient,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        agent_name: str,
    ) -> LLMCallResult:
        """
        Replay one failed/stale batch item synchronously through the full
        cross-provider cascade. Caller supplies the original request shape
        (batch_jobs.request_meta_json + the consumer's own prompt-building
        code hold the model/system/messages — this client does not persist
        prompt contents, only metadata).
        """
        return await llm_client.call(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            agent_name=agent_name,
        )

    # ------------------------------------------------------------------
    # Cost — halved COST_PER_MTOK, logged with provider="batch"
    # ------------------------------------------------------------------

    def calculate_batch_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Batch discount is a flat 50% off the synchronous per-model rate."""
        costs = JarvisLLMClient.COST_PER_MTOK.get(model)
        if costs is None:
            logger.warning("batch_client: unknown model %s — no cost calculation", model)
            return 0.0
        input_cost = (input_tokens / 1_000_000) * costs["input"]
        output_cost = (output_tokens / 1_000_000) * costs["output"]
        return (input_cost + output_cost) * 0.5

    async def log_batch_cost(
        self,
        llm_client: JarvisLLMClient,
        model: str,
        input_tokens: int,
        output_tokens: int,
        agent_name: str,
        latency_ms: int = 0,
    ) -> None:
        """
        Log a succeeded batch item's cost with provider="batch". Only call
        this for result_type == "succeeded" — Anthropic doesn't bill
        failed/expired/canceled items, and a later sync fallback for the
        same custom_id is a genuinely separate cost event.

        track_raw_call() on JarvisLLMClient doesn't plumb a provider kwarg
        through to CostTracker, so this logs directly against the same
        cost_tracker instance instead of going through that helper.
        """
        cost = self.calculate_batch_cost(model, input_tokens, output_tokens)
        await llm_client.cost_tracker.log_call(
            timestamp=datetime.now(timezone.utc).isoformat(),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            agent_name=agent_name,
            success=True,
            provider="batch",
        )

    # ------------------------------------------------------------------
    # Consumer-facing reads — used by per-agent collect() functions so they
    # never need to touch this module's SQLite schema directly
    # ------------------------------------------------------------------

    def list_jobs(
        self, agent_name: Optional[str] = None, status: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """List batch_jobs rows, optionally filtered by agent_name and/or status."""
        query = "SELECT * FROM batch_jobs WHERE 1=1"
        params: list[Any] = []
        if agent_name is not None:
            query += " AND agent_name = ?"
            params.append(agent_name)
        if status is not None:
            query += " AND status = ?"
            params.append(status)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_unconsumed_results(self, batch_id: str) -> dict[str, BatchResultItem]:
        """Read not-yet-consumed batch_results rows for a batch from SQLite."""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """
            SELECT custom_id, result_type, content, input_tokens, output_tokens, error
            FROM batch_results
            WHERE batch_id = ? AND consumed = 0
            """,
            (batch_id,),
        ).fetchall()
        conn.close()
        return {
            row[0]: BatchResultItem(
                custom_id=row[0],
                result_type=row[1],
                content=row[2] or "",
                input_tokens=row[3] or 0,
                output_tokens=row[4] or 0,
                error=row[5],
            )
            for row in rows
        }

    def mark_consumed(self, batch_id: str, custom_ids: list[str]) -> None:
        """Mark the given custom_ids as consumed for a batch."""
        if not custom_ids:
            return
        conn = sqlite3.connect(self.db_path)
        conn.executemany(
            "UPDATE batch_results SET consumed = 1 WHERE batch_id = ? AND custom_id = ?",
            [(batch_id, cid) for cid in custom_ids],
        )
        conn.commit()
        conn.close()

    def mark_job_status(self, batch_id: str, status: str) -> None:
        """
        Set a terminal status on a batch_jobs row outside the normal
        submitted/polling/ended lifecycle — e.g. a consumer that fully
        replayed a stale batch via sync fallback marks it "stale_collected"
        so repeat collect() calls skip it instead of re-running the fallback.
        """
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE batch_jobs SET status = ? WHERE batch_id = ?", (status, batch_id)
        )
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def get_batch_health_summary(self) -> dict[str, Any]:
        """
        Non-blocking health snapshot — batches are async by design, so this
        never signals overall /health degradation, only surfaces counts.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status, COUNT(*) FROM batch_jobs GROUP BY status"
        )
        by_status = dict(cursor.fetchall())
        cursor.execute(
            "SELECT COUNT(*) FROM batch_results WHERE consumed = 0"
        )
        unconsumed = cursor.fetchone()[0]
        conn.close()
        return {
            "jobs_by_status": by_status,
            "unconsumed_results": unconsumed,
        }
