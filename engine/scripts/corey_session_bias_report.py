"""Print Corey's structured session bias for a date (engine pipeline, not web search).

Wires ``discord.commentary_processor.CoreyCommentaryProcessor`` to a runnable
entry point so callers -- including the ``market-framing-brief`` skill -- can
pull Corey's ACTUAL commentary-derived bias (levels, IB context, triggers)
when it has been ingested into ``discord_corey_commentary`` for the target
date, instead of approximating it from a web search or OHLC geometry.

Read-only: fetches commentary rows, calls the LLM extraction (cached daily in
``corey_session_bias``), and prints the result. Never writes trades, never
touches paper config or risk params. Uses ``build_default_llm_client()`` (the
#209 fix) so this standalone surface gets the same Vertex->Gemini->OpenAI
failover the live engine has, instead of a raw direct-POST call that silently
degrades on an exhausted API key.

Degrades honestly, not silently: if no commentary exists for the date, the LLM
is unreachable, or the DB can't be read, this returns/prints a neutral bias
with data_quality="none" -- it does not raise, and it does not fabricate
levels. Callers MUST check data_quality before trusting key_levels/
directional_bias as real signal (see market-framing-brief SKILL.md).

Run (from engine/ directory):
  cd engine && .venv/Scripts/python.exe scripts/corey_session_bias_report.py
  cd engine && .venv/Scripts/python.exe scripts/corey_session_bias_report.py --date 2026-06-30
  cd engine && .venv/Scripts/python.exe scripts/corey_session_bias_report.py --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from discord.commentary_processor import (  # noqa: E402
    CoreyCommentaryProcessor,
    build_default_llm_client,
)


def format_report(bias) -> str:
    if bias.data_quality == "none":
        return (
            f"Corey session bias for {bias.date.isoformat()}: NO DATA "
            "(no commentary ingested for this date, or LLM/DB unavailable). "
            "Do not treat this as a bearish/neutral market call -- it means "
            "the source is unavailable, not that Corey said nothing mattered."
        )
    lines = [
        f"Corey session bias for {bias.date.isoformat()} "
        f"(data_quality={bias.data_quality}, {bias.message_count} messages, "
        f"conviction={bias.conviction:.2f}):",
        f"  session_type:     {bias.session_type}",
        f"  directional_bias: {bias.directional_bias}",
        f"  ib_bias:          {bias.ib_bias}",
        f"  key_levels:       {bias.key_levels}",
    ]
    if bias.specific_triggers:
        lines.append("  triggers:")
        lines.extend(f"    - {t}" for t in bias.specific_triggers)
    if bias.corey_quote:
        lines.append(f'  quote:            "{bias.corey_quote}"')
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date", type=str, default=None, help="target date YYYY-MM-DD (default: today)"
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument(
        "--db-path",
        default=None,
        help="override the commentary DB path (default: engine/data/jarvis_trader.db)",
    )
    args = parser.parse_args()

    for_date = date.fromisoformat(args.date) if args.date else None
    llm_client = build_default_llm_client(args.db_path)  # None is fine -- graceful fallback
    processor = CoreyCommentaryProcessor(db_path=args.db_path, llm_client=llm_client)
    bias = asyncio.run(processor.get_session_bias(for_date))

    if args.json:
        print(json.dumps(bias.to_dict(), indent=2))
    else:
        print(format_report(bias))

    # 0 = usable bias, 1 = no data -- so this composes as a "should I trust
    # this?" gate for a caller (e.g. the market-framing-brief skill) without
    # having to parse text or JSON just to make that decision.
    return 0 if bias.data_quality != "none" else 1


if __name__ == "__main__":
    raise SystemExit(main())
