"""Daily digest — ranks last 24h of analyses, writes vault page, optionally DMs via Hermes."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import httpx

from vault.paths import vault_root as _vault_root

logger = logging.getLogger(__name__)

HERMES_BASE = os.getenv("HERMES_BASE_URL", "http://127.0.0.1:8765")
DM_USER = os.getenv("DEEP_ANALYZER_DM_USER", "amo")


def _fetch_last_24h(db_path: Path | str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT a.*, b.posted_at
            FROM discord_analyses a
            JOIN discord_bookmarks b ON a.bookmark_id = b.message_id
            WHERE datetime(a.created_at) >= datetime('now', '-24 hours')
            ORDER BY a.created_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _priority(row: dict) -> int:
    try:
        return int(json.loads(row.get("structured_json") or "{}").get("priority", 0))
    except (json.JSONDecodeError, ValueError, TypeError):
        return 0


def _render_page(rows: list[dict]) -> str:
    # Filter P0 (FAILED / broken-extract) out of the digest entirely. These
    # rows still have vault pages written for searchability, but they don't
    # belong in the morning brief. Counted separately so Amo sees the noise
    # floor without having to scroll past it.
    p0_rows = [r for r in rows if _priority(r) == 0]
    signal_rows = [r for r in rows if _priority(r) > 0]
    rows_sorted = sorted(signal_rows, key=_priority, reverse=True)
    total_cost = sum(float(r.get("cost_usd") or 0) for r in rows)
    by_type: dict[str, int] = {}
    for r in rows_sorted:
        by_type[r["artifact_type"]] = by_type.get(r["artifact_type"], 0) + 1

    lines = [
        "",
        "## Overnight feed",
        "",
        f"Total: {len(rows_sorted)}  |  Cost: ${total_cost:.4f}",
        f"By type: {', '.join(f'{k}={v}' for k, v in by_type.items()) or '(none)'}",
        f"Filtered (P0 / broken extracts): {len(p0_rows)}",
        "",
        "### Top items",
        "",
    ]
    for r in rows_sorted[:10]:
        prio = _priority(r)
        struct: dict = {}
        try:
            struct = json.loads(r.get("structured_json") or "{}")
        except json.JSONDecodeError:
            pass
        tickers = struct.get("tickers", [])
        ticker_str = f" `{','.join(tickers)}`" if tickers else ""
        lines.append(f"- **[{prio}]{ticker_str}** ({r['artifact_type']}) {r['summary']}")
    return "\n".join(lines) + "\n"


def render(*, db_path: Path | str, vault_root: Path | None = None) -> Path:
    """Generate the daily digest. Returns path to the daily page that was appended."""
    # Canonical resolver (honours JARVIS_VAULT_ROOT) — one shared vault root.
    root = Path(vault_root) if vault_root else _vault_root()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    folder = root / "Daily"
    folder.mkdir(parents=True, exist_ok=True)
    page = folder / f"{today}.md"

    rows = _fetch_last_24h(db_path)
    body = _render_page(rows)

    existing = page.read_text(encoding="utf-8") if page.exists() else f"# {today}\n"
    page.write_text(existing + body, encoding="utf-8")
    return page


async def send_dm_via_hermes(*, page_path: Path, n_items: int, cost: float) -> None:
    """Fire-and-forget DM to Amo via Hermes. Errors logged, never raised."""
    msg = (
        f"Overnight feed: {n_items} items analyzed, ${cost:.4f} spent. "
        f"Top 3 in vault: {page_path}"
    )
    try:
        async with httpx.AsyncClient(base_url=HERMES_BASE, timeout=20.0) as cli:
            await cli.post("/v1/dm/send", json={"to": DM_USER, "text": msg})
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.warning("digest: Hermes DM failed: %s", e)


def render_and_dm(*, db_path: Path | str, vault_root: Path | None = None) -> Path:
    """Convenience: render the digest page and DM Amo. Returns path."""
    rows = _fetch_last_24h(db_path)
    path = render(db_path=db_path, vault_root=vault_root)
    cost = sum(float(r.get("cost_usd") or 0) for r in rows)
    asyncio.run(send_dm_via_hermes(page_path=path, n_items=len(rows), cost=cost))
    return path
