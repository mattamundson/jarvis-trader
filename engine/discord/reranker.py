"""
Cross-encoder reranking for semantic search over Corey's Discord commentary.

A reranker re-scores the top-K vector-retrieval candidates with a cross-encoder
(query and document attended jointly), which is markedly more accurate than the
bi-encoder cosine similarity used for first-stage retrieval. Benchmarks put the
lift at +15-40% relevant-result accuracy.

Three tiers, selected automatically, each degrading gracefully to the next so
that semantic_search NEVER breaks because reranking is unavailable:

  Tier 1  voyage   Voyage `rerank-2.5` cross-encoder via native HTTPS API.
                   Finance-tuned, best quality. Gated on VOYAGE_API_KEY.
  Tier 2  local    `bge-reranker-v2-m3` cross-encoder via transformers + torch
                   (already in the engine venv). Free, local, no key. Model is
                   downloaded once (~1 GB) on first use and cached by HF.
  Tier 3  off      Identity — return candidates in their existing (vector) order.
                   The pre-reranker behavior; a safe no-op fallback.

Mode is chosen by the RERANKER_MODE env var:
  auto (default) -> voyage if key present, else local if torch model loads,
                    else off.
  voyage | local | off -> force that tier (still falls back on runtime failure).

Design constraints (engine rules): async with graceful fallback, lazy imports
for the heavy deps (torch/transformers), no blocking the event loop (local
inference runs in a thread executor).
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any, Callable, Sequence

import aiohttp

logger = logging.getLogger(__name__)

# --- configuration ---------------------------------------------------------

VOYAGE_RERANK_URL = "https://api.voyageai.com/v1/rerank"
VOYAGE_MODEL = os.environ.get("VOYAGE_RERANK_MODEL", "rerank-2.5")
LOCAL_MODEL = os.environ.get("RERANKER_LOCAL_MODEL", "BAAI/bge-reranker-v2-m3")
VOYAGE_TIMEOUT_S = float(os.environ.get("RERANKER_VOYAGE_TIMEOUT_S", "10"))

# How many first-stage candidates to over-fetch before reranking down to limit.
# Reranking only helps if it can reorder a pool larger than the final cut.
OVERFETCH_FACTOR = int(os.environ.get("RERANKER_OVERFETCH_FACTOR", "4"))
OVERFETCH_MAX = int(os.environ.get("RERANKER_OVERFETCH_MAX", "40"))


def overfetch_k(limit: int) -> int:
    """Top-K to retrieve from the vector index before reranking down to limit."""
    return min(max(limit, limit * OVERFETCH_FACTOR), OVERFETCH_MAX)


def _mode() -> str:
    return os.environ.get("RERANKER_MODE", "auto").strip().lower()


# --- Tier 1: Voyage rerank-2.5 (native HTTPS API) --------------------------


async def _voyage_scores(query: str, docs: Sequence[str]) -> list[float] | None:
    """Return a relevance score per doc from Voyage rerank, or None on failure."""
    key = os.environ.get("VOYAGE_API_KEY")
    if not key:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                VOYAGE_RERANK_URL,
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "query": query,
                    "documents": list(docs),
                    "model": VOYAGE_MODEL,
                },
                timeout=aiohttp.ClientTimeout(total=VOYAGE_TIMEOUT_S),
            ) as resp:
                if resp.status != 200:
                    logger.warning("Voyage rerank HTTP %s; falling back", resp.status)
                    return None
                payload = await resp.json()
    except Exception as exc:  # noqa: BLE001 - graceful fallback is the contract
        logger.warning("Voyage rerank error (%s); falling back", exc)
        return None

    # Response: {"data": [{"index": i, "relevance_score": s}, ...]} (unordered).
    scores = [0.0] * len(docs)
    try:
        for item in payload["data"]:
            scores[int(item["index"])] = float(item["relevance_score"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("Voyage rerank malformed response (%s); falling back", exc)
        return None
    return scores


# --- Tier 2: local bge-reranker-v2-m3 (transformers + torch) ---------------

_local_model: Any = None
_local_tokenizer: Any = None
_local_lock = threading.Lock()
_local_failed = False  # latch: once load fails, don't retry every call


def _load_local() -> bool:
    """Lazily load the local cross-encoder. Returns True if usable."""
    global _local_model, _local_tokenizer, _local_failed
    if _local_model is not None:
        return True
    if _local_failed:
        return False
    with _local_lock:
        if _local_model is not None:
            return True
        if _local_failed:
            return False
        try:
            import torch  # noqa: F401 - imported for thread config + presence check
            from transformers import (
                AutoModelForSequenceClassification,
                AutoTokenizer,
            )

            logger.info("Loading local reranker %s (one-time)...", LOCAL_MODEL)
            _local_tokenizer = AutoTokenizer.from_pretrained(LOCAL_MODEL)
            model = AutoModelForSequenceClassification.from_pretrained(LOCAL_MODEL)
            model.eval()
            _local_model = model
            logger.info("Local reranker ready.")
            return True
        except Exception as exc:  # noqa: BLE001 - any failure -> fall to Tier 3
            logger.warning("Local reranker unavailable (%s); falling back", exc)
            _local_failed = True
            return False


def _local_scores_sync(query: str, docs: Sequence[str]) -> list[float]:
    """Blocking cross-encoder inference. Run via executor, never on the loop.

    bge-reranker-v2-m3 emits a raw pre-sigmoid logit per pair (unbounded, often
    negative even for relevant docs). We apply sigmoid so the local tier returns
    a 0..1 relevance probability — monotonic, so ordering is identical, but now
    on the SAME scale as Voyage rerank-2.5. That makes a single `min_score` floor
    mean the same thing on both tiers (and keeps the exposed rerank_score
    interpretable instead of a meaningless logit like -4.85).
    """
    import torch

    pairs = [[query, d] for d in docs]
    with torch.no_grad():
        inputs = _local_tokenizer(
            pairs,
            padding=True,
            truncation=True,
            return_tensors="pt",
            max_length=512,
        )
        logits = _local_model(**inputs).logits.view(-1)
        scores = torch.sigmoid(logits)
    return scores.float().tolist()


async def _local_scores(query: str, docs: Sequence[str]) -> list[float] | None:
    if not _load_local():
        return None
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _local_scores_sync, query, docs)
    except Exception as exc:  # noqa: BLE001 - graceful fallback
        logger.warning("Local rerank inference error (%s); falling back", exc)
        return None


# --- public API ------------------------------------------------------------


async def rerank(
    query: str,
    candidates: Sequence[dict],
    top_n: int,
    *,
    text_key: str = "content",
    min_score: float = 0.0,
) -> tuple[list[dict], str]:
    """
    Rerank `candidates` against `query`, returning (top_n results, tier_used).

    Each candidate is a dict carrying its document text at `text_key`. The
    returned dicts are the same objects, each annotated with a `rerank_score`
    when a reranker ran, sorted best-first and truncated to `top_n`. The tier
    string ("voyage" | "local" | "off") records which path actually produced
    the ordering, so callers can surface it for observability.

    `min_score` is a relevance floor applied AFTER scoring and BEFORE the
    top_n truncation: candidates whose rerank score is below it are dropped,
    so low-relevance noise (e.g. archive pages that match on vocabulary but
    not intent) can't pad the result set. Both scoring tiers emit a 0..1
    relevance probability (Voyage rerank-2.5 natively; the local bge tier via
    sigmoid over its logits), so a single floor (0.2 is a sensible default)
    means the same thing on either tier.

    Never-empty guard: if the floor would drop EVERY candidate from a non-empty
    pool (a tier-scale mismatch, or a uniformly low-relevance pool), the
    reranked top_n is returned UNFILTERED rather than an empty list — the floor
    only ever trims noise from a set that already has at least one above-floor
    hit. This keeps a Voyage→local fallback from silently blanking results.

    The "off"/identity tier has no scores to compare against, so `min_score` is
    a no-op there (candidates pass through in vector order, truncated to top_n).
    """
    if not candidates:
        return [], "off"

    mode = _mode()
    docs = [str(c.get(text_key) or "") for c in candidates]

    scorers: list[tuple[str, Callable]] = []
    if mode == "voyage":
        scorers = [("voyage", _voyage_scores)]
    elif mode == "local":
        scorers = [("local", _local_scores)]
    elif mode == "off":
        scorers = []
    else:  # auto
        scorers = [("voyage", _voyage_scores), ("local", _local_scores)]

    for tier, scorer in scorers:
        scores = await scorer(query, docs)
        if scores is None:
            continue
        ranked = sorted(zip(candidates, scores, strict=False), key=lambda cs: cs[1], reverse=True)
        kept = []
        for cand, score in ranked:
            if score < min_score:
                break  # sorted desc — everything past here is below the floor
            cand["rerank_score"] = round(float(score), 4)
            kept.append(cand)
            if len(kept) >= top_n:
                break
        if kept:
            return kept, tier
        # Never-empty guard: the floor dropped EVERY candidate from a non-empty
        # pool. That means the floor doesn't match this tier's score distribution
        # (e.g. a Voyage→local fallback where bge probabilities all sit low), not
        # that the pool is worthless — the reranker still ordered it. Returning []
        # here would silently blank search_knowledge / brief enrichment on a tier
        # mismatch. Instead degrade to the reranked top_n unfiltered. The floor
        # only ever trims noise from a set that has at least one above-floor hit
        # (so the Q6 archive-leak fix still applies whenever any hit clears it).
        logger.info(
            "rerank: min_score=%.3f dropped all %d candidates on tier '%s'; "
            "returning reranked top_n unfiltered (tier-scale mismatch / low pool)",
            min_score,
            len(candidates),
            tier,
        )
        out = []
        for cand, score in ranked[:top_n]:
            cand["rerank_score"] = round(float(score), 4)
            out.append(cand)
        return out, tier

    # Tier 3: identity — preserve vector order, just truncate.
    return list(candidates[:top_n]), "off"
