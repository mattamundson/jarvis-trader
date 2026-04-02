"""
JARVIS TRADER — ThinkOrSwim Strategy Report Importer

Parses TOS strategy report CSV exports into normalized TOSSignal objects.

Supported TOS export formats (auto-detected):
  1. Strategy Report format — Date, Time, Type, Price, Qty, P/L Open, P/L Day
  2. Trade History format   — Date, Time, Spread, Side, Qty, Price, Pos Effect, Symbol
  3. Simple format          — Date/Time, Signal, Price (JARVIS-compatible direct import)

TOS signal types mapped to JARVIS directions:
  BUY / BUY TO COVER → LONG
  SELL / SELL SHORT   → SHORT
  Signal=BUY          → LONG
  Signal=SELL         → SHORT
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

import pytz

logger = logging.getLogger(__name__)

CT = pytz.timezone("America/Chicago")
UTC = pytz.utc


@dataclass
class TOSSignal:
    """Normalized representation of a single TOS strategy signal."""

    timestamp: datetime  # timezone-aware (CT → UTC converted internally)
    direction: str  # "LONG" or "SHORT"
    price: float  # entry price at signal bar
    quantity: int  # contracts/shares
    raw_type: str  # original TOS signal type string
    pnl: Optional[float] = None  # P/L if available in the export

    @property
    def timestamp_ct(self) -> datetime:
        """Return timestamp in Central Time."""
        if self.timestamp.tzinfo is None:
            return CT.localize(self.timestamp)
        return self.timestamp.astimezone(CT)

    @property
    def timestamp_utc(self) -> datetime:
        """Return timestamp in UTC."""
        if self.timestamp.tzinfo is None:
            ts_ct = CT.localize(self.timestamp)
        else:
            ts_ct = self.timestamp
        return ts_ct.astimezone(UTC)

    def __repr__(self) -> str:
        ts = self.timestamp_ct.strftime("%Y-%m-%d %H:%M CT")
        return f"TOSSignal({self.direction} @ {self.price:.2f} on {ts})"


@dataclass
class TOSImportResult:
    """Result of parsing a TOS CSV file."""

    signals: List[TOSSignal] = field(default_factory=list)
    format_detected: str = "unknown"
    total_rows: int = 0
    skipped_rows: int = 0
    errors: List[str] = field(default_factory=list)
    symbol: Optional[str] = None
    date_range: Optional[tuple] = None  # (start, end) datetime

    @property
    def signal_count(self) -> int:
        return len(self.signals)

    @property
    def long_count(self) -> int:
        return sum(1 for s in self.signals if s.direction == "LONG")

    @property
    def short_count(self) -> int:
        return sum(1 for s in self.signals if s.direction == "SHORT")

    def summary(self) -> dict:
        return {
            "signal_count": self.signal_count,
            "long_count": self.long_count,
            "short_count": self.short_count,
            "format_detected": self.format_detected,
            "total_rows": self.total_rows,
            "skipped_rows": self.skipped_rows,
            "errors": self.errors[:10],  # cap at 10 for JSON safety
            "symbol": self.symbol,
            "date_range": (
                [
                    self.date_range[0].isoformat(),
                    self.date_range[1].isoformat(),
                ]
                if self.date_range
                else None
            ),
        }


# ── Direction mapping ─────────────────────────────────────────────────────────

_LONG_TYPES = {"buy", "buy to cover", "b", "long", "entry_long", "buy_open"}
_SHORT_TYPES = {"sell", "sell short", "s", "short", "entry_short", "sell_open"}


def _map_direction(raw: str) -> Optional[str]:
    """Map TOS signal type string to LONG/SHORT.  Returns None if unrecognized."""
    normalized = raw.strip().lower().rstrip("_")
    if normalized in _LONG_TYPES:
        return "LONG"
    if normalized in _SHORT_TYPES:
        return "SHORT"
    return None


# ── Timestamp parsing ─────────────────────────────────────────────────────────

_DATE_FORMATS = [
    "%m/%d/%y",  # TOS default: 06/03/24
    "%m/%d/%Y",  # 06/03/2024
    "%Y-%m-%d",  # ISO date
    "%Y/%m/%d",
]

_TIME_FORMATS = [
    "%H:%M",  # 09:30
    "%H:%M:%S",  # 09:30:00
    "%I:%M %p",  # 9:30 AM
    "%I:%M:%S %p",
]

_DATETIME_FORMATS = [
    "%m/%d/%y %H:%M",
    "%m/%d/%Y %H:%M",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%m/%d/%y %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
]


def _parse_datetime(date_str: str, time_str: Optional[str] = None) -> Optional[datetime]:
    """Parse TOS date/time strings into a naive datetime (assumed CT)."""
    if time_str:
        combined = f"{date_str.strip()} {time_str.strip()}"
        for fmt in _DATETIME_FORMATS:
            try:
                return datetime.strptime(combined, fmt)
            except ValueError:
                continue

    # Try combined formats
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue

    # Try date-only
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue

    return None


def _parse_price(price_str: str) -> Optional[float]:
    """Parse price string, removing $ and commas."""
    cleaned = price_str.strip().replace("$", "").replace(",", "").replace("N/A", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_qty(qty_str: str) -> int:
    """Parse quantity, stripping +/- and fractional parts."""
    cleaned = qty_str.strip().replace(",", "").replace("+", "").lstrip("-")
    try:
        return abs(int(float(cleaned)))
    except ValueError:
        return 1


# ── Format detectors ──────────────────────────────────────────────────────────


def _detect_format(headers: List[str]) -> str:
    """Return the detected TOS export format name."""
    lower = [h.lower().strip() for h in headers]

    # TOS Strategy Report (desktop export)
    if "type" in lower and "p/l open" in lower:
        return "strategy_report"

    # TOS Trade History / Account Statement
    if "side" in lower and "spread" in lower:
        return "trade_history"

    # JARVIS-compatible simple format
    if "signal" in lower and "date" in lower:
        return "simple"

    # Generic fallback
    if "type" in lower or "side" in lower:
        return "generic"

    return "unknown"


# ── Format-specific parsers ───────────────────────────────────────────────────


def _parse_strategy_report_row(row: dict, headers_lower: List[str]) -> Optional[TOSSignal]:
    """
    Parse a single row from TOS Strategy Report format.

    Expected columns: Date, Time, Type, Price, Qty (or Contracts), P/L Open, P/L Day
    """
    date_str = row.get("Date", "").strip()
    time_str = row.get("Time", "").strip()
    type_str = row.get("Type", "").strip()
    price_str = row.get("Price", row.get("price", "")).strip()
    qty_str = row.get("Qty", row.get("Contracts", "1")).strip()
    pnl_str = row.get("P/L Day", row.get("P/L Open", "")).strip()

    if not date_str or not type_str:
        return None

    direction = _map_direction(type_str)
    if direction is None:
        return None  # Skip non-entry rows (header repetitions, summary rows)

    ts = _parse_datetime(date_str, time_str if time_str else None)
    if ts is None:
        return None

    price = _parse_price(price_str)
    if price is None or price <= 0:
        return None

    pnl = _parse_price(pnl_str) if pnl_str else None
    qty = _parse_qty(qty_str)

    return TOSSignal(
        timestamp=ts,
        direction=direction,
        price=price,
        quantity=qty,
        raw_type=type_str,
        pnl=pnl,
    )


def _parse_trade_history_row(row: dict) -> Optional[TOSSignal]:
    """
    Parse a single row from TOS Trade History / Account Statement format.

    Expected: Date, Time, Spread, Side, Qty, Price, Pos Effect, Symbol, ...
    """
    date_str = row.get("Date", "").strip()
    time_str = row.get("Time", "").strip()
    side_str = row.get("Side", "").strip()
    price_str = row.get("Price", "").strip()
    qty_str = row.get("Qty", "1").strip()

    if not date_str or not side_str:
        return None

    direction = _map_direction(side_str)
    if direction is None:
        return None

    ts = _parse_datetime(date_str, time_str if time_str else None)
    if ts is None:
        return None

    price = _parse_price(price_str)
    if price is None or price <= 0:
        return None

    return TOSSignal(
        timestamp=ts,
        direction=direction,
        price=price,
        quantity=_parse_qty(qty_str),
        raw_type=side_str,
    )


def _parse_simple_row(row: dict) -> Optional[TOSSignal]:
    """
    Parse JARVIS-compatible simple format.

    Expected: Date, Time (opt), Signal, Price, Qty (opt)
    Signal values: BUY/SELL or LONG/SHORT or ENTRY_LONG/ENTRY_SHORT
    """
    date_str = row.get("Date", row.get("date", "")).strip()
    time_str = row.get("Time", row.get("time", "")).strip()
    signal_str = row.get("Signal", row.get("signal", "")).strip()
    price_str = row.get("Price", row.get("price", "")).strip()
    qty_str = row.get("Qty", row.get("qty", "1")).strip()

    if not date_str or not signal_str:
        return None

    direction = _map_direction(signal_str)
    if direction is None:
        return None

    ts = _parse_datetime(date_str, time_str if time_str else None)
    if ts is None:
        return None

    price = _parse_price(price_str)
    if price is None or price <= 0:
        return None

    return TOSSignal(
        timestamp=ts,
        direction=direction,
        price=price,
        quantity=_parse_qty(qty_str),
        raw_type=signal_str,
    )


# ── Public API ────────────────────────────────────────────────────────────────


def parse_tos_csv(
    csv_content: str,
    symbol: Optional[str] = None,
) -> TOSImportResult:
    """
    Parse a TOS strategy report CSV string into a list of TOSSignal objects.

    Parameters
    ----------
    csv_content : str
        Raw CSV text content from a TOS strategy report or trade history export.
    symbol : str, optional
        Expected symbol name for logging/context. Auto-detected from CSV if present.

    Returns
    -------
    TOSImportResult with signals, format info, and any parse errors.
    """
    result = TOSImportResult(symbol=symbol)

    # Strip BOM and normalize line endings
    csv_content = csv_content.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")

    # Skip any leading non-CSV lines (TOS sometimes prefixes with account info)
    lines = csv_content.strip().split("\n")
    header_idx = 0
    for i, line in enumerate(lines):
        if "," in line and any(
            kw in line.lower() for kw in ("date", "time", "type", "side", "signal", "price")
        ):
            header_idx = i
            break

    cleaned_csv = "\n".join(lines[header_idx:])

    reader = csv.DictReader(io.StringIO(cleaned_csv))
    if reader.fieldnames is None:
        result.errors.append("No headers found in CSV — empty or invalid file")
        return result

    headers = [h.strip() for h in reader.fieldnames]
    headers_lower = [h.lower() for h in headers]
    fmt = _detect_format(headers)
    result.format_detected = fmt

    logger.info(f"[TOS-IMPORT] Detected format: {fmt} | Headers: {headers[:8]}")

    # Auto-detect symbol from headers or first rows if not provided
    if symbol is None and "symbol" in headers_lower:
        symbol_idx = headers_lower.index("symbol")
        # Will be set from first valid row below
        _symbol_header = headers[symbol_idx]
    else:
        _symbol_header = None

    signals: List[TOSSignal] = []
    skipped = 0

    for row_num, row in enumerate(reader, start=2):
        result.total_rows += 1

        # Clean all keys/values
        clean_row = {k.strip(): v.strip() for k, v in row.items() if k}

        # Auto-detect symbol from first data row
        if _symbol_header and result.symbol is None:
            result.symbol = clean_row.get(_symbol_header, symbol)

        try:
            if fmt == "strategy_report":
                sig = _parse_strategy_report_row(clean_row, headers_lower)
            elif fmt == "trade_history":
                sig = _parse_trade_history_row(clean_row)
            elif fmt == "simple":
                sig = _parse_simple_row(clean_row)
            else:
                # Generic: try strategy_report first, then simple
                sig = _parse_strategy_report_row(clean_row, headers_lower)
                if sig is None:
                    sig = _parse_simple_row(clean_row)

            if sig is not None:
                signals.append(sig)
            else:
                skipped += 1

        except Exception as e:
            skipped += 1
            result.errors.append(f"Row {row_num}: {e}")

    result.signals = sorted(signals, key=lambda s: s.timestamp)
    result.skipped_rows = skipped

    if result.signals:
        result.date_range = (
            result.signals[0].timestamp,
            result.signals[-1].timestamp,
        )

    logger.info(
        f"[TOS-IMPORT] Parsed {len(signals)} signals "
        f"({result.long_count} LONG, {result.short_count} SHORT) "
        f"from {result.total_rows} rows ({skipped} skipped)"
    )

    return result


def parse_tos_csv_file(file_path: str, symbol: Optional[str] = None) -> TOSImportResult:
    """Convenience wrapper that reads a CSV file and parses it."""
    with open(file_path, encoding="utf-8-sig") as f:
        content = f.read()
    return parse_tos_csv(content, symbol=symbol)
