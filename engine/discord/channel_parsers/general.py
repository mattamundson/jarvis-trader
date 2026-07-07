import logging
from typing import List

logger = logging.getLogger(__name__)

TATHEDOG_ID = "564449478174703646"


def parse_channel(messages: list, source_channel: str = "general") -> List[dict]:
    """
    Parse general channel messages.
    CRITICAL: Only messages from tathedog (author.id 564449478174703646) are stored.
    All other users' messages are IGNORED.
    """
    results = []
    skipped_other_users = 0
    skipped_empty = 0

    for msg in messages:
        author_id = str(msg.get("author", {}).get("id", ""))

        # CRITICAL FILTER: only tathedog messages
        if author_id != TATHEDOG_ID:
            skipped_other_users += 1
            continue

        content = msg.get("content", "").strip()

        if not content:
            skipped_empty += 1
            continue

        result = {
            "message_id": str(msg.get("id", "")),
            "timestamp": msg.get("timestamp", ""),
            "content": content[:5000],
            "channel": source_channel,
            "author_id": author_id,
        }
        results.append(result)

    logger.info(
        f"general: parsed {len(results)} tathedog messages, "
        f"skipped {skipped_other_users} other users, "
        f"skipped {skipped_empty} empty"
    )
    return results
