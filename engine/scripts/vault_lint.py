"""vault_lint.py — vault wikilink lint pass.

Scans the vault for broken [[wikilinks]] and orphan notes, writes
00-Inbox/lint-YYYY-MM-DD.md. Structural only — no LLM, no network.

Gated by ENABLE_VAULT_LINT (default off), read fresh at run time so it can be
toggled without a restart.

Usage:
    python scripts/vault_lint.py
    Or scheduled in PM2 at 06:30 (see ecosystem.config.js: jarvis-vault-lint).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Allow `python scripts/vault_lint.py` from the engine dir.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger("vault_lint")


def _enabled() -> bool:
    return os.getenv("ENABLE_VAULT_LINT", "0").strip().lower() in {"1", "true", "yes", "on"}


def _run() -> int:
    from vault import lint

    out = lint.run_lint()
    if out is None:
        logger.info("No lint report produced (vault has no notes yet).")
        return 0
    logger.info("Lint report written: %s", out)
    return 0


def main() -> int:
    if not _enabled():
        logger.info("ENABLE_VAULT_LINT not set — skipping vault lint.")
        return 0
    try:
        return _run()
    except Exception as exc:  # noqa: BLE001 — cron entry point, never crash the runner
        logger.exception("vault lint failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
