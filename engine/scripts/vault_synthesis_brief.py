"""vault_synthesis_brief.py — 6am daily synthesis brief (#1).

Reads the last 7 days of vault notes, asks Claude to synthesise (connections,
pattern, contradiction, best capture), and writes 00-Inbox/brief-YYYY-MM-DD.md.

Gated by ENABLE_VAULT_SYNTHESIS (default off) so it is inert until armed —
read fresh at run time, no restart needed to toggle.

Usage:
    python scripts/vault_synthesis_brief.py
    Or scheduled in PM2 at 06:00 (see ecosystem.config.js: jarvis-vault-synthesis).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Allow `python scripts/vault_synthesis_brief.py` from the engine dir.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger("vault_synthesis_brief")


def _enabled() -> bool:
    return os.getenv("ENABLE_VAULT_SYNTHESIS", "0").strip().lower() in {"1", "true", "yes", "on"}


async def _run() -> int:
    from llm.client import JarvisLLMClient
    from vault import synthesis

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    model = os.getenv("VAULT_SYNTHESIS_MODEL", synthesis.DEFAULT_SYNTHESIS_MODEL)
    days = int(os.getenv("VAULT_SYNTHESIS_DAYS", "7"))

    client = JarvisLLMClient(api_key=api_key or "ollama-local")
    try:
        out = await synthesis.run_synthesis_brief(client, days=days, model=model)
    finally:
        await client.close()

    if out is None:
        logger.info("No brief produced (no recent notes or LLM unavailable).")
        return 0
    logger.info("Brief written: %s", out)
    return 0


def main() -> int:
    if not _enabled():
        logger.info("ENABLE_VAULT_SYNTHESIS not set — skipping synthesis brief.")
        return 0
    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 — cron entry point, never crash the runner
        logger.exception("synthesis brief failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
