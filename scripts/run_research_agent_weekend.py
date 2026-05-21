"""
Weekend Research Agent runner — Windows Scheduled Task entry point.

Designed to be invoked by the Jarvis-ResearchAgent-Weekend scheduled task:
    pwsh.exe -NonInteractive -Command
        "& 'C:/Users/mattm/.../engine/.venv/Scripts/python.exe'
           'C:/Users/mattm/.../scripts/run_research_agent_weekend.py'"

Environment variables (read from engine/.env via dotenv):
    ENABLE_RESEARCH_AGENT=1            (must be 1 to fire LLM calls)
    RESEARCH_AGENT_DAILY_BUDGET_USD    (default 5.00)
    ANTHROPIC_API_KEY                  (required for LLM calls)

Outputs:
    engine/data/research_hypotheses/<YYYY-MM-DD>/<symbol>-<n>.json
    master-jarvis/second-brain/raw/_session-research/research-pass-<date>.md

Exit codes:
    0 — pass completed (hypotheses may be stubs if flag is off)
    1 — fatal error (import failure, async error)
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: add engine/ to sys.path so engine packages are importable
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent  # scripts/
_REPO_ROOT = _SCRIPT_DIR.parent  # jarvis-trader/
_ENGINE_DIR = _REPO_ROOT / "engine"

if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

# ---------------------------------------------------------------------------
# Load .env early so env vars are available before module imports
# ---------------------------------------------------------------------------

try:
    from dotenv import load_dotenv  # type: ignore

    _env_path = _ENGINE_DIR / ".env"
    if _env_path.exists():
        load_dotenv(str(_env_path))
except ImportError:
    pass  # python-dotenv optional — env vars must be set another way

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("run_research_agent_weekend")

# ---------------------------------------------------------------------------
# Default symbols for the weekend pass
# ---------------------------------------------------------------------------

DEFAULT_SYMBOLS = ["MES", "MNQ", "MCL", "MGC"]
DEFAULT_N_HYPOTHESES = 3


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    """Run the weekend research pass and return an exit code."""
    try:
        from scheduler.research_agent_weekend import run_weekend_research_pass
    except ImportError as exc:
        logger.error("Failed to import research_agent_weekend: %s", exc)
        return 1

    import os

    symbols_env = os.environ.get("RESEARCH_AGENT_SYMBOLS", "")
    symbols = [
        s.strip().upper() for s in symbols_env.split(",") if s.strip()
    ] or DEFAULT_SYMBOLS

    n_hyp_env = os.environ.get("RESEARCH_AGENT_N_HYPOTHESES", str(DEFAULT_N_HYPOTHESES))
    try:
        n_hypotheses = int(n_hyp_env)
    except ValueError:
        n_hypotheses = DEFAULT_N_HYPOTHESES

    logger.info(
        "Weekend research pass starting: symbols=%s, n_per_symbol=%d",
        symbols,
        n_hypotheses,
    )

    try:
        result = await run_weekend_research_pass(
            symbols=symbols,
            n_hypotheses_per_symbol=n_hypotheses,
        )
        logger.info(
            "Pass complete: generated=%d written=%d summary=%s",
            result["total_generated"],
            result["total_written"],
            result["summary_path"],
        )
        return 0
    except Exception as exc:
        logger.error("Weekend research pass failed: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
