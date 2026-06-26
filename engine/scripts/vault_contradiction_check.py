"""vault_contradiction_check.py — 7am thesis contradiction scan (#5).

Reads every note in 02-Theses and the last 30 days of 01-Sources, asks Claude
to find only conflict (not agreement), and writes
00-Inbox/contradictions-YYYY-MM-DD.md.

Gated by ENABLE_VAULT_CONTRADICTION (default off), read fresh at run time.

Usage:
    python scripts/vault_contradiction_check.py
    Or scheduled in PM2 at 07:00 (see ecosystem.config.js: jarvis-vault-contradiction).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger("vault_contradiction_check")


def _enabled() -> bool:
    return os.getenv("ENABLE_VAULT_CONTRADICTION", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def _run() -> int:
    from llm.client import JarvisLLMClient
    from vault import synthesis

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    model = os.getenv("VAULT_CONTRADICTION_MODEL", synthesis.DEFAULT_SYNTHESIS_MODEL)
    days = int(os.getenv("VAULT_CONTRADICTION_DAYS", "30"))

    client = JarvisLLMClient(api_key=api_key or "ollama-local")
    try:
        out = await synthesis.run_contradiction_check(client, days=days, model=model)
    finally:
        await client.close()

    if out is None:
        logger.info("No contradiction report produced (need theses + sources, or LLM down).")
        return 0
    logger.info("Contradiction report written: %s", out)
    return 0


def main() -> int:
    if not _enabled():
        logger.info("ENABLE_VAULT_CONTRADICTION not set — skipping contradiction check.")
        return 0
    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 — cron entry point, never crash the runner
        logger.exception("contradiction check failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
