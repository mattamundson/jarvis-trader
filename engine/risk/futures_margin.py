from typing import Dict

# CME maintenance margin table (per contract, USD).
# Values are IBKR intraday maintenance requirements — refresh periodically.
FUTURES_MARGIN_TABLE: Dict[str, float] = {
    "MES": 1200.0,
    "MCL": 1200.0,
    "MNQ": 2000.0,
    "MGC": 900.0,
    "ES": 12000.0,
    "NQ": 17000.0,
}

FUTURES_SYMBOLS = set(FUTURES_MARGIN_TABLE.keys())


class UnknownFuturesSymbolError(ValueError):
    """Raised when we are asked for margin on an unknown futures symbol."""


def is_futures_symbol(symbol: str) -> bool:
    """Return True if this symbol is treated as a futures contract for sizing."""
    return symbol.upper() in FUTURES_SYMBOLS


def margin_requirement(symbol: str) -> float:
    """
    Return per‑contract margin requirement in dollars.

    Uses the static CME table defined above. If the symbol is not in the
    table, raises UnknownFuturesSymbolError so callers must decide how to
    handle it.
    """
    key = symbol.upper()
    try:
        return FUTURES_MARGIN_TABLE[key]
    except KeyError as exc:
        raise UnknownFuturesSymbolError(f"Unknown futures symbol for margin: {symbol}") from exc
