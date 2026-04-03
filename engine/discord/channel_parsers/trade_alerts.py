import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

TATHEDOG_ID = "564449478174703646"

SYMBOL_PATTERNS = [
    r"\b(ES|NQ|GC|CL|YM|RTY|MES|MNQ|SPX|SPY|QQQ|EURUSD)\b",
]

DIRECTION_PATTERNS = [
    r"\b(long|short|buy|sell|bought|sold|entered)\b",
]


def extract_symbol(text: str) -> Optional[str]:
    for pattern in SYMBOL_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def extract_direction(text: str) -> Optional[str]:
    for pattern in DIRECTION_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            word = match.group(1).lower()
            if word in ("long", "buy", "bought", "entered"):
                return "LONG"
            elif word in ("short", "sell", "sold"):
                return "SHORT"
    return None


def extract_price(text: str) -> Optional[float]:
    """Extract a price from text like 'Long 4530' or 'at 4530.25'."""
    match = re.search(r"(?:at|@|entry|price|long|short)\s+([\d,.]+)", text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            pass
    # Fallback: find any standalone number that looks like a price
    match = re.search(r"\b(\d{3,5}(?:\.\d{1,4})?)\b", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def parse_channel(messages: list, source_channel: str = "trade-alerts") -> List[dict]:
    results = []
    skipped = 0

    for msg in messages:
        content = msg.get("content", "").strip()

        if not content:
            skipped += 1
            continue

        # trade-alerts is Corey's channel — accept all messages but note author
        # Most should be from tathedog but include all with content

        author_id = str(msg.get("author", {}).get("id", ""))
        result = {
            "message_id": str(msg.get("id", "")),
            "timestamp": msg.get("timestamp", ""),
            "content": content[:2000],
            "symbol": extract_symbol(content),
            "direction": extract_direction(content),
            "price": extract_price(content),
            "source_channel": source_channel,
            "author_id": author_id,
        }
        results.append(result)

    logger.info(f"trade_alerts: parsed {len(results)}, skipped {skipped}")
    return results
