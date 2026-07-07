"""
One-shot helper: reprocess CoreyCommentaryProcessor for specific historical dates.

Usage:
    python -m engine.scripts.reprocess_corey_bias_dates 2026-05-04 2026-05-05

Loads engine env via dotenv, invalidates cache for each date, then re-runs
get_session_bias() which calls the LLM and writes a fresh row.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import date
from pathlib import Path

# Load engine env file via dotenv (engine already depends on it)
try:
    from dotenv import load_dotenv

    engine_dir = Path(__file__).resolve().parent.parent
    env_path = engine_dir / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except Exception as e:
    print(f"[WARN] dotenv load failed: {e}")

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("reprocess_corey_bias")

# Ensure repo root on sys.path so `engine.discord` imports resolve
repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(repo_root))

from engine.discord.commentary_processor import CoreyCommentaryProcessor  # noqa: E402


async def reprocess(dates: list[str]) -> int:
    api_key_set = bool(os.environ.get("ANTHROPIC_API_KEY"))
    print(f"ANTHROPIC_API_KEY set: {api_key_set}")
    if not api_key_set:
        print("ERROR: ANTHROPIC_API_KEY not in env — LLM call will return neutral bias.")
        return 1

    # Patch httpx to surface 400 response bodies (otherwise raise_for_status hides them)
    import httpx as _httpx_mod

    _orig_raise = _httpx_mod.Response.raise_for_status

    def _raise_with_body(self):
        if self.status_code >= 400:
            try:
                print(f"  [httpx body for {self.status_code}] {self.text[:1500]}")
            except Exception:
                pass
        return _orig_raise(self)

    _httpx_mod.Response.raise_for_status = _raise_with_body

    proc = CoreyCommentaryProcessor()
    print(f"DB path: {proc.db_path}")

    rc = 0
    for d_str in dates:
        try:
            d = date.fromisoformat(d_str)
        except ValueError:
            print(f"SKIP: {d_str} is not a valid ISO date")
            rc = 1
            continue

        print(f"\n=== Reprocessing {d_str} ===")
        proc.invalidate_cache(d)
        bias = await proc.get_session_bias(d)
        print(
            f"  Result: bias={bias.directional_bias} "
            f"conviction={bias.conviction:.2f} quality={bias.data_quality} "
            f"session={bias.session_type} ib={bias.ib_bias} "
            f"levels={bias.key_levels} msgs={bias.message_count}"
        )
        if bias.corey_quote:
            print(f"  Quote: {bias.corey_quote[:200]}")
        if bias.data_quality == "none":
            print("  WARNING: result is data_quality='none' — LLM call likely failed again.")
            rc = 2

    return rc


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m engine.scripts.reprocess_corey_bias_dates <YYYY-MM-DD> [...]")
        return 1
    return asyncio.run(reprocess(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
