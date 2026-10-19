"""
ZeroGEX ES Gamma Levels Adapter
================================
Fetches and parses ES gamma positioning data from https://zerogex.io/es-gamma-levels.

Primary entry point: fetch_es_gamma_levels() -> Optional[ZeroGEXLevels]

Returns None on failure (timeout, parse error, network issue) and logs the error.
Never raises — safe for pipeline integration.

Cache: 60-second TTL — gamma levels update every 15 minutes (delayed data).
"""

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)

ZEROGEX_URL = "https://zerogex.io/es-gamma-levels"
FETCH_TIMEOUT_SECONDS = 10
CACHE_TTL_SECONDS = 60

_cached_levels: Optional["ZeroGEXLevels"] = None
_cache_timestamp: float = 0.0


@dataclass
class ZeroGEXLevels:
    """ES gamma positioning levels from ZeroGEX (15-min delayed)."""
    
    contract: str                    # e.g. "ESZ26"
    spot: float                      # Current ES price
    call_wall: float                 # Largest call open interest strike
    put_wall: float                  # Largest put open interest strike
    gamma_flip: float                # Zero-gamma boundary
    net_gex: str                     # Net gamma exposure (e.g. "-$25.26B")
    delayed: bool                    # Always True (15-min delayed data)
    fetched_at: datetime             # When this data was fetched


def fetch_es_gamma_levels(use_cache: bool = True) -> Optional[ZeroGEXLevels]:
    """
    Fetch ES gamma levels from ZeroGEX.
    
    Returns None on any failure (network, parse, timeout).
    Logs errors but never raises.
    
    Args:
        use_cache: If True, return cached data if still fresh (< 60s old)
    
    Returns:
        ZeroGEXLevels instance or None
    """
    global _cached_levels, _cache_timestamp
    
    if not REQUESTS_AVAILABLE:
        logger.error("fetch_es_gamma_levels: requests library not available")
        return None
    
    # Check cache
    now = time.time()
    if use_cache and _cached_levels is not None:
        age = now - _cache_timestamp
        if age < CACHE_TTL_SECONDS:
            logger.debug(
                "fetch_es_gamma_levels: returning cached data (age=%.1fs)", age
            )
            return _cached_levels
    
    # Fetch fresh data
    try:
        logger.debug("fetch_es_gamma_levels: fetching from %s", ZEROGEX_URL)
        response = requests.get(ZEROGEX_URL, timeout=FETCH_TIMEOUT_SECONDS)
        response.raise_for_status()
        html = response.text
        
        # Parse the gamma levels line
        levels = _parse_gamma_line(html)
        if levels is None:
            logger.error(
                "fetch_es_gamma_levels: failed to parse gamma levels from HTML"
            )
            return None
        
        # Update cache
        _cached_levels = levels
        _cache_timestamp = now
        
        logger.info(
            "fetch_es_gamma_levels: fetched %s spot=%.2f flip=%.2f call_wall=%.2f put_wall=%.2f gex=%s",
            levels.contract,
            levels.spot,
            levels.gamma_flip,
            levels.call_wall,
            levels.put_wall,
            levels.net_gex,
        )
        
        return levels
        
    except requests.Timeout:
        logger.error(
            "fetch_es_gamma_levels: timeout after %ds", FETCH_TIMEOUT_SECONDS
        )
        return None
    except requests.RequestException as exc:
        logger.error("fetch_es_gamma_levels: network error: %s", exc)
        return None
    except Exception as exc:
        logger.error(
            "fetch_es_gamma_levels: unexpected error: %s", exc, exc_info=True
        )
        return None


def _parse_gamma_line(html: str) -> Optional[ZeroGEXLevels]:
    """
    Parse the gamma levels line from ZeroGEX HTML.
    
    Expected format:
        ES (ESZ26): spot 7743 | Call Wall 7743 | Put Wall 7733 | Gamma Flip 7809 | Net GEX -$25.26B (delayed
    
    Returns None if the pattern is not found or parsing fails.
    """
    # Match the pattern
    pattern = (
        r'ES \((?P<contract>[A-Z0-9]+)\):\s*'
        r'spot\s+(?P<spot>[\d.]+)\s*\|\s*'
        r'Call Wall\s+(?P<call_wall>[\d.]+)\s*\|\s*'
        r'Put Wall\s+(?P<put_wall>[\d.]+)\s*\|\s*'
        r'Gamma Flip\s+(?P<gamma_flip>[\d.]+)\s*\|\s*'
        r'Net GEX\s+(?P<net_gex>[^(]+)\s*\(delayed'
    )
    
    match = re.search(pattern, html, re.IGNORECASE)
    if not match:
        return None
    
    try:
        return ZeroGEXLevels(
            contract=match.group("contract"),
            spot=float(match.group("spot")),
            call_wall=float(match.group("call_wall")),
            put_wall=float(match.group("put_wall")),
            gamma_flip=float(match.group("gamma_flip")),
            net_gex=match.group("net_gex").strip(),
            delayed=True,
            fetched_at=datetime.now(),
        )
    except (ValueError, KeyError) as exc:
        logger.error("_parse_gamma_line: failed to parse values: %s", exc)
        return None


def clear_cache() -> None:
    """Clear the cached gamma levels (useful for testing)."""
    global _cached_levels, _cache_timestamp
    _cached_levels = None
    _cache_timestamp = 0.0
