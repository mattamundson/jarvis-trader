import logging
from typing import List

logger = logging.getLogger(__name__)


def parse_channel(messages: list, source_channel: str = "market-updates") -> List[dict]:
    results = []
    skipped = 0

    for msg in messages:
        content = msg.get("content", "").strip()

        if not content:
            skipped += 1
            continue

        result = {
            "message_id": str(msg.get("id", "")),
            "timestamp": msg.get("timestamp", ""),
            "content": content[:5000],
            "channel": source_channel,
            "author_id": str(msg.get("author", {}).get("id", "")),
        }
        results.append(result)

    logger.info(f"market_updates: parsed {len(results)}, skipped {skipped}")
    return results
