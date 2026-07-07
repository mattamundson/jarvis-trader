import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

# Map of raw symbols from Discord embed titles to clean symbols
SYMBOL_MAP = {
    "ES1!": "ES",
    "NQ1!": "NQ",
    "GC1!": "GC",
    "CL1!": "CL",
    "YM1!": "YM",
    "RTY1!": "RTY",
    "EURUSD": "EURUSD",
    "BTCUSD": "BTC",
    "BTCUSDT": "BTC",
    "BTC": "BTC",
    "SPYUSDT": "SPY",
    "SPY": "SPY",
    # Also handle without "1!"
    "ES": "ES",
    "NQ": "NQ",
    "GC": "GC",
    "CL": "CL",
    "YM": "YM",
    "RTY": "RTY",
}


def parse_float(value: str) -> Optional[float]:
    """Parse a float from a string, handling +/- prefixes and % suffix."""
    if not value:
        return None
    value = value.strip().rstrip("%").replace("+", "").replace(",", "")
    try:
        return float(value)
    except ValueError:
        return None


def parse_symbol_timeframe(title: str):
    """Parse symbol and timeframe from embed title like 'ES1! 1 m' or 'NQ1! 15 m'."""
    if not title:
        return None, None
    parts = title.strip().split()
    raw_symbol = parts[0] if parts else ""
    symbol = SYMBOL_MAP.get(raw_symbol, raw_symbol.replace("1!", ""))
    timeframe = " ".join(parts[1:]) if len(parts) > 1 else None
    return symbol, timeframe


def parse_direction_type(author_name: str):
    """Parse direction and signal type from author name like 'LONG ENTRY :' or 'SHORT EXIT :'."""
    if not author_name:
        return None, None
    upper = author_name.upper()
    direction = "LONG" if "LONG" in upper else ("SHORT" if "SHORT" in upper else None)
    signal_type = "ENTRY" if "ENTRY" in upper else ("EXIT" if "EXIT" in upper else None)
    return direction, signal_type


def parse_description(description: str) -> dict:
    """Parse the embed description into a dict of field values."""
    result = {}
    if not description:
        return result

    # Patterns to match "Label : value" or "Label: value"
    patterns = {
        "entry_price": r"Entry\s*:\s*([\d.,+-]+)",
        "target1": r"Target\s*1\s*:\s*([\d.,+-]+)",
        "target2": r"Target\s*2\s*:\s*([\d.,+-]+)",
        "stop1": r"Stop\s*1\s*:\s*([\d.,+-]+)",
        "stop2": r"Stop\s*2\s*:\s*([\d.,+-]+)",
        "exit_price": r"Exit\s*:\s*([\d.,+-]+)",
        "wins": r"Wins\s*:\s*(\d+)",
        "losses": r"Losses\s*:\s*(\d+)",
        "win_rate": r"Win\s*Rate\s*:\s*([\d.]+)%?",
        "mfe": r"MFE\s*:\s*([\d.,+-]+)",
        "mae": r"MAE\s*:\s*([\d.,+-]+)",
        "rr": r"RR\s*:\s*([\d.,+-]+)",
        "gain": r"Gain\s*:\s*([\d.,+-]+)",
        "draw": r"Draw(?:down)?\s*:\s*([\d.,+-]+)",
        "net": r"Net\s*:\s*([\d.,+-]+)",
    }

    for field, pattern in patterns.items():
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            result[field] = match.group(1).strip()

    return result


def parse_bot_message(message: dict, source_channel: str) -> Optional[dict]:
    """
    Parse a single bot message from Discord JSON.
    Returns a dict matching BotSignal fields, or None if not parseable.

    Bot messages have content="" and data in embeds.
    """
    # Only process messages with embeds
    if not message.get("embeds"):
        return None

    # Skip if content is non-empty (likely not a bot alert)
    # But some bot messages may have content too, so we check embeds first
    embeds = message["embeds"]
    if not embeds:
        return None

    embed = embeds[0]
    author_name = embed.get("author", {}).get("name", "")
    title = embed.get("title", "")
    description = embed.get("description", "")
    footer_text = embed.get("footer", {}).get("text", "")

    # Parse symbol and timeframe from title
    symbol, timeframe = parse_symbol_timeframe(title)

    # Parse direction and type from author name
    direction, signal_type = parse_direction_type(author_name)

    # If we couldn't get a symbol from title, try to infer from channel name
    if not symbol and source_channel:
        channel_to_symbol = {
            "es": "ES",
            "nq": "NQ",
            "gc": "GC",
            "cl": "CL",
            "ym": "YM",
            "rty": "RTY",
            "eurusd": "EURUSD",
            "btc": "BTC",
            "spy": "SPY",
            "proton-bot-alerts": "MIXED",
        }
        # Extract channel name from source_channel path
        for key, val in channel_to_symbol.items():
            if key in source_channel.lower():
                symbol = val
                break

    if not symbol:
        symbol = "UNKNOWN"

    # Parse description fields
    fields = parse_description(description)

    # Determine entry price (could be "entry_price" or "exit_price")
    entry_price = parse_float(fields.get("entry_price") or fields.get("exit_price"))

    # Parse last price from footer
    last_price = None
    if footer_text:
        price_match = re.search(r"[\d.,]+", footer_text.replace(",", ""))
        if price_match:
            last_price = parse_float(price_match.group())

    return {
        "message_id": str(message.get("id", "")),
        "timestamp": message.get("timestamp", ""),
        "symbol": symbol,
        "timeframe": timeframe,
        "direction": direction,
        "signal_type": signal_type,
        "entry_price": entry_price,
        "target1": parse_float(fields.get("target1")),
        "target2": parse_float(fields.get("target2")),
        "stop1": parse_float(fields.get("stop1")),
        "stop2": parse_float(fields.get("stop2")),
        "win_rate": parse_float(fields.get("win_rate")),
        "wins": int(fields["wins"]) if fields.get("wins") else None,
        "losses": int(fields["losses"]) if fields.get("losses") else None,
        "mfe": parse_float(fields.get("mfe")),
        "mae": parse_float(fields.get("mae")),
        "rr": parse_float(fields.get("rr")),
        "gain": parse_float(fields.get("gain")),
        "draw": parse_float(fields.get("draw")),
        "net": parse_float(fields.get("net")),
        "last_price": last_price,
        "raw_description": description[:2000] if description else None,
        "source_channel": source_channel,
    }


def parse_channel(messages: list, source_channel: str) -> List[dict]:
    """
    Parse all messages from a bot-alerts channel.
    Returns list of dicts matching BotSignal fields.
    """
    results = []
    skipped = 0

    for msg in messages:
        parsed = parse_bot_message(msg, source_channel)
        if parsed and parsed.get("message_id"):
            results.append(parsed)
        else:
            skipped += 1

    logger.info(f"bot_alerts [{source_channel}]: parsed {len(results)}, skipped {skipped}")
    return results
