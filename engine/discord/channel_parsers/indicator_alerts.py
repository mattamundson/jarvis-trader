import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

SYMBOL_MAP = {
    "ES": "ES",
    "NQ": "NQ",
    "GC": "GC",
    "CL": "CL",
    "YM": "YM",
    "RTY": "RTY",
    "EURUSD": "EURUSD",
    "MES": "MES",
    "MNQ": "MNQ",
    "MGC": "MGC",
    "MCL": "MCL",
}

# TradingView continuous contract symbols (e.g. "ES1!", "NQ1!") → standard symbol
TV_SYMBOL_MAP = {
    "ES1!": "ES",
    "NQ1!": "NQ",
    "GC1!": "GC",
    "CL1!": "CL",
    "YM1!": "YM",
    "RTY1!": "RTY",
    "MES1!": "MES",
    "MNQ1!": "MNQ",
    "MGC1!": "MGC",
    "MCL1!": "MCL",
}


def parse_float(value: str) -> Optional[float]:
    if not value:
        return None
    value = value.strip().replace("+", "").replace(",", "")
    try:
        return float(value)
    except ValueError:
        return None


def extract_symbol(text: str) -> Optional[str]:
    """Extract symbol from text like 'ES1! Daily', 'ES 5m Initial Balance', or '📊 ES 5m IB Report'."""
    # First pass: check for TradingView-style continuous contract symbols (e.g. "ES1!", "NQ1!")
    # These appear as the first token in raw_content lines like "ES1!\nTimestamp: ..."
    for tv_sym, std_sym in TV_SYMBOL_MAP.items():
        if re.search(r"(?<!\w)" + re.escape(tv_sym) + r"(?!\w)", text, re.IGNORECASE):
            return std_sym

    # Second pass: match plain symbols with word boundaries on cleaned text
    clean = re.sub(r"[^\w\s]", " ", text)
    # Sort by length descending so "RTY" matches before "RT", etc.
    for sym in sorted(SYMBOL_MAP.keys(), key=len, reverse=True):
        if re.search(r"\b" + sym + r"\b", clean, re.IGNORECASE):
            return SYMBOL_MAP[sym]
    return None


def extract_timeframe(text: str) -> Optional[str]:
    """Extract timeframe like '5m', '15m', '1h' from text."""
    match = re.search(r"\b(\d+\s*[mMhH])\b", text)
    return match.group(1).strip() if match else None


def parse_ib_description(description: str, title: str = "") -> dict:
    """Parse IB report fields from embed description."""
    result = {}
    full_text = (title + "\n" + description) if title else description

    # Symbol
    result["symbol"] = extract_symbol(full_text) or "UNKNOWN"
    result["timeframe"] = extract_timeframe(full_text)

    # OHLC
    patterns = {
        "ib_open": r"IB\s+Open\s*:\s*([\d.]+)",
        "ib_high": r"IB\s+High\s*:\s*([\d.]+)",
        "ib_low": r"IB\s+Low\s*:\s*([\d.]+)",
        "ib_close": r"IB\s+Close\s*:\s*([\d.]+)",
        "ib_range": r"(?:IB\s*)?(?:OR\s+)?Range\s*:\s*([\d.]+)",
        # IB extension targets: "IB UP 1" / "IB UP 2" / "IB DOWN 1" / "IB DOWN 2"
        # Also accept legacy IBU50/IBU100/IBD50/IBD100 formats
        "ibu50": r"(?:IB\s+UP\s+1|IBU50)\s*:\s*([\d.]+)",
        "ibu100": r"(?:IB\s+UP\s+2|IBU100)\s*:\s*([\d.]+)",
        "ibd50": r"(?:IB\s+DOWN\s+1|IBD50)\s*:\s*([\d.]+)",
        "ibd100": r"(?:IB\s+DOWN\s+2|IBD100)\s*:\s*([\d.]+)",
    }
    for field, pattern in patterns.items():
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            result[field] = parse_float(match.group(1))

    # Context and Plan (multi-line)
    context_match = re.search(
        r"Context\s*:\s*(.+?)(?:\n|Plan\s*:|$)", description, re.IGNORECASE | re.DOTALL
    )
    if context_match:
        result["auction_context"] = context_match.group(1).strip()[:500]

    plan_match = re.search(r"Plan\s*:\s*(.+?)(?:\n\n|$)", description, re.IGNORECASE | re.DOTALL)
    if plan_match:
        result["trade_plan"] = plan_match.group(1).strip()[:500]

    return result


def parse_channel(messages: list, source_channel: str = "indicator-alerts") -> List[dict]:
    results = []
    skipped = 0

    for msg in messages:
        embeds = msg.get("embeds", [])
        if not embeds:
            skipped += 1
            continue

        embed = embeds[0]
        description = embed.get("description", "")
        title = embed.get("title", "") or ""

        if not description and not title:
            skipped += 1
            continue

        fields = parse_ib_description(description, title)

        result = {
            "message_id": str(msg.get("id", "")),
            "timestamp": msg.get("timestamp", ""),
            "symbol": fields.get("symbol", "UNKNOWN"),
            "timeframe": fields.get("timeframe"),
            "ib_open": fields.get("ib_open"),
            "ib_high": fields.get("ib_high"),
            "ib_low": fields.get("ib_low"),
            "ib_close": fields.get("ib_close"),
            "ib_range": fields.get("ib_range"),
            "ibu50": fields.get("ibu50"),
            "ibu100": fields.get("ibu100"),
            "ibd50": fields.get("ibd50"),
            "ibd100": fields.get("ibd100"),
            "auction_context": fields.get("auction_context"),
            "trade_plan": fields.get("trade_plan"),
            "raw_content": (title + "\n" + description)[:3000],
            "source_channel": source_channel,
        }
        results.append(result)

    logger.info(f"indicator_alerts: parsed {len(results)}, skipped {skipped}")
    return results
