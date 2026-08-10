"""IBKR market-depth client for the DOM / order-flow Phase-1 service.

Wraps ``reqMktDepth`` for MES on the paper gateway (port 4002), maintains an
in-memory top-10 book, and recomputes the order-flow snapshot on each depth
update. Read-only: this module has no path to order placement.

Isolation contract (per spec):
- Own ``ib_async`` connection with a distinct client ID (default 3 — the
  engine's executor uses ``IBKR_CLIENT_ID``=1 and the data leg uses +1=2).
- Imports nothing from ``engine.risk``, ``engine.config``, or any
  safety-critical module.
- Graceful fallback: if IB Gateway is unreachable or ``reqMktDepth``
  disconnects, the service keeps running and callers receive the last-known
  snapshot with ``stale: true`` + ``age_seconds``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("domflow.ib_client")

# Defaults — overridable via env (read here, NOT from engine/config.py, to keep
# this service decoupled from the safety-critical config surface).
DEFAULT_HOST = os.environ.get("DOMFLOW_IB_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("DOMFLOW_IB_PORT", "4002"))
DEFAULT_CLIENT_ID = int(os.environ.get("DOMFLOW_IB_CLIENT_ID", "3"))
CONNECT_TIMEOUT = float(os.environ.get("DOMFLOW_IB_CONNECT_TIMEOUT", "5.0"))
MAX_DEPTH_ROWS = 10  # top-10 book per spec (IB allows up to 10 for L2)


@dataclass
class BookSnapshot:
    """Immutable-ish snapshot of the DOM book + computed signal at one moment."""

    symbol: str
    ts_utc: str
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    mid_price: Optional[float] = None
    spread: Optional[float] = None
    bid_volume_top5: float = 0.0
    ask_volume_top5: float = 0.0
    imbalance_ratio: float = 0.0
    raw_book_json: str = ""
    depth_tier: str = "L1_DELAYED"  # "L2" (real DOM) or "L1_DELAYED" (top-of-book fallback)
    stale: bool = False
    age_seconds: Optional[float] = None
    connected: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "ts_utc": self.ts_utc,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "mid_price": self.mid_price,
            "spread": self.spread,
            "bid_volume_top5": self.bid_volume_top5,
            "ask_volume_top5": self.ask_volume_top5,
            "imbalance_ratio": self.imbalance_ratio,
            "raw_book_json": self.raw_book_json,
            "depth_tier": self.depth_tier,
            "stale": self.stale,
            "age_seconds": self.age_seconds,
            "connected": self.connected,
        }


class DomflowIBClient:
    """Maintains the MES depth book via ``ib_async``.

    Usage (single asyncio loop, e.g. inside FastAPI lifespan):

        client = DomflowIBClient()
        await client.start()          # connect + subscribe, non-fatal on failure
        snapshot = client.current_snapshot()   # always returns something
        await client.stop()           # disconnect cleanly
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        client_id: int = DEFAULT_CLIENT_ID,
        symbol: str = "MES",
        max_depth_rows: int = MAX_DEPTH_ROWS,
    ) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._symbol = symbol
        self._max_depth_rows = max_depth_rows
        self._ib = None
        self._ticker = None
        self._l1_ticker = None
        self._contract = None
        self._connected = False
        self._last_book_ts: Optional[float] = None
        self._book: dict[int, tuple[float, float]] = {}  # side 0=ask, 1=bid -> (price, size)
        # Stored as (side, position, price, size) to replay inserts/updates.
        self._lock = asyncio.Lock()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> bool:
        """Connect to IB Gateway and subscribe to MES depth. Never raises.

        Returns True if the depth subscription is live; False on any failure
        (caller should keep serving last-known snapshots as stale).
        """
        try:
            from ib_async import IB

            self._ib = IB()
            await asyncio.wait_for(
                self._ib.connectAsync(self._host, self._port, clientId=self._client_id),
                timeout=CONNECT_TIMEOUT,
            )
            # Delayed-data stopgap for the IB paper-account market-data
            # subscription gap (Error 10168/354: futures data not subscribed),
            # mirroring engine/data/market_data.py. reqMarketDataType(3) asks
            # IB for DELAYED data when no live subscription exists; IB still
            # returns LIVE for anything that IS subscribed, so this never
            # downgrades a good live feed. 1=live 2=frozen 3=delayed
            # 4=delayed-frozen. Non-fatal: a failure here must never abort an
            # otherwise-good connect.
            try:
                _mdt = int(os.environ.get("IB_MARKET_DATA_TYPE", "3"))
                if _mdt in (1, 2, 3, 4):
                    self._ib.reqMarketDataType(_mdt)
                    logger.info(
                        "domflow: market-data type set to %d (1=live 2=frozen 3=delayed 4=delayed-frozen)",
                        _mdt,
                    )
            except Exception as _mdt_exc:  # noqa: BLE001
                logger.warning("domflow: reqMarketDataType failed (non-fatal): %s", _mdt_exc)
        except asyncio.TimeoutError:
            logger.warning("domflow: IB connect timed out after %ss (%s:%s)", CONNECT_TIMEOUT, self._host, self._port)
            return False
        except Exception as e:  # noqa: BLE001 — never crash the read-only service
            logger.warning("domflow: IB connect failed (%s:%s, clientId=%s): %s", self._host, self._port, self._client_id, e)
            return False

        try:
            self._contract = await self._resolve_front_month()
            # Primary tier: real L2 depth (works when the account holds a
            # depth subscription; Error 354 otherwise).
            self._ticker = self._ib.reqMktDepth(
                self._contract,
                numRows=self._max_depth_rows,
                isSmartDepth=False,
            )
            self._ticker.updateEvent += self._on_depth_update
            # Fallback tier: top-of-book L1 (delayed via reqMarketDataType(3)
            # when no live subscription exists). IB does NOT offer delayed L2,
            # so on an unsubscribed paper account this L1 stream is the only
            # live depth the service can get — the snapshot is tagged
            # depth_tier="L1_DELAYED" so the dashboard never presents it as L2.
            try:
                self._l1_ticker = self._ib.reqMktData(
                    self._contract,
                    genericTickList="",
                    snapshot=False,
                    regulatorySnapshot=False,
                )
                self._l1_ticker.updateEvent += self._on_depth_update
            except Exception as l1_exc:  # noqa: BLE001 — L1 is a fallback, not a requirement
                logger.warning("domflow: L1 fallback subscribe failed (non-fatal): %s", l1_exc)
                self._l1_ticker = None
            self._connected = True
            logger.info("domflow: depth subscribed %s (clientId=%s, rows=%s)", self._symbol, self._client_id, self._max_depth_rows)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("domflow: depth subscribe failed for %s: %s", self._symbol, e)
            try:
                self._ib.disconnect()
            except Exception:
                pass
            return False

    async def stop(self) -> None:
        if self._ib:
            try:
                self._ib.disconnect()
            except Exception:
                pass
        self._connected = False

    async def _resolve_front_month(self):
        """Resolve MES front-month contract (live, non-expired) via IB.

        Mirrors ``engine.data.market_data._resolve_front_month`` logic but
        without importing that module (keeps this service decoupled).
        """
        from datetime import date

        from ib_async import Future

        generic = Future(self._symbol, exchange="CME", currency="USD")
        try:
            details = await self._ib.reqContractDetailsAsync(generic)
            if details:
                today_yyyymmdd = date.today().strftime("%Y%m%d")
                live = [
                    d
                    for d in details
                    if (d.contract.lastTradeDateOrContractMonth or "") >= today_yyyymmdd
                ]
                if live:
                    live.sort(key=lambda d: d.contract.lastTradeDateOrContractMonth)
                    return live[0].contract
                details.sort(key=lambda d: d.contract.lastTradeDateOrContractMonth, reverse=True)
                return details[0].contract
        except Exception as e:  # noqa: BLE001
            logger.warning("domflow: front-month resolution failed for %s: %s", self._symbol, e)
        return generic

    # ── depth updates ─────────────────────────────────────────────────────────

    def _on_depth_update(self, ticker) -> None:
        """IB depth update callback — maintains the book + recomputes signal."""
        try:
            # Primary tier: L2 DOM book (lists of DOMLevel NamedTuples).
            bids = list(getattr(ticker, "domBids", []) or [])
            asks = list(getattr(ticker, "domAsks", []) or [])
            if bids or asks:
                self._store_book(bids, asks, depth_tier="L2")
                return
            # Fallback tier: L1 top-of-book ticker (bid/ask/sizes).
            if ticker is self._l1_ticker or (not bids and not asks):
                self._store_l1(ticker)
        except Exception as e:  # noqa: BLE001
            logger.warning("domflow: depth update handler error: %s", e)

    def _store_l1(self, ticker) -> None:
        """Top-of-book snapshot from an L1 ticker (delayed on paper accounts).

        IB does not offer delayed L2, so on an account without a depth
        subscription this is the best live depth available; the payload is
        tagged depth_tier=\"L1_DELAYED\" to keep the dashboard honest.
        """
        from .imbalance import compute_imbalance

        bid_price = getattr(ticker, "bid", None)
        ask_price = getattr(ticker, "ask", None)
        bid_size = float(getattr(ticker, "bidSize", 0) or 0)
        ask_size = float(getattr(ticker, "askSize", 0) or 0)

        bids = [type("_L", (), {"price": bid_price, "size": bid_size})()] if bid_price is not None and bid_size > 0 else []
        asks = [type("_L", (), {"price": ask_price, "size": ask_size})()] if ask_price is not None and ask_size > 0 else []
        ratio = compute_imbalance(bids, asks, top_n=1)

        mid = None
        spread = None
        if bid_price is not None and ask_price is not None:
            mid = round((float(bid_price) + float(ask_price)) / 2.0, 2)
            spread = round(float(ask_price) - float(bid_price), 2)

        import json

        raw = {
            "bids": [{"price": bid_price, "size": bid_size, "mm": ""}],
            "asks": [{"price": ask_price, "size": ask_size, "mm": ""}],
        }

        self._book = {
            "bids": bids,
            "asks": asks,
            "best_bid": float(bid_price) if bid_price is not None else None,
            "best_ask": float(ask_price) if ask_price is not None else None,
            "mid_price": mid,
            "spread": spread,
            "bid_volume_top5": bid_size,
            "ask_volume_top5": ask_size,
            "imbalance_ratio": ratio,
            "raw_book_json": json.dumps(raw),
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "depth_tier": "L1_DELAYED",
        }
        self._last_book_ts = time.time()

    def _store_book(self, bids, asks, depth_tier: str = "L2") -> None:
        from .imbalance import compute_imbalance

        bid_vol = sum(float(b.size) for b in bids[:5] if b.size and float(b.size) > 0)
        ask_vol = sum(float(a.size) for a in asks[:5] if a.size and float(a.size) > 0)
        ratio = compute_imbalance(bids, asks, top_n=5)

        best_bid = bids[0].price if bids else None
        best_ask = asks[0].price if asks else None
        mid = None
        spread = None
        if best_bid is not None and best_ask is not None:
            mid = round((best_bid + best_ask) / 2.0, 2)
            spread = round(best_ask - best_bid, 2)

        import json

        raw = {
            "bids": [{"price": b.price, "size": float(b.size), "mm": getattr(b, "marketMaker", "")} for b in bids[:10]],
            "asks": [{"price": a.price, "size": float(a.size), "mm": getattr(a, "marketMaker", "")} for a in asks[:10]],
        }

        self._book = {
            "bids": bids[: self._max_depth_rows],
            "asks": asks[: self._max_depth_rows],
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid_price": mid,
            "spread": spread,
            "bid_volume_top5": bid_vol,
            "ask_volume_top5": ask_vol,
            "imbalance_ratio": ratio,
            "raw_book_json": json.dumps(raw),
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "depth_tier": depth_tier,
        }
        self._last_book_ts = time.time()

    # ── accessors ─────────────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return bool(self._connected and self._ib is not None)

    def current_snapshot(self) -> BookSnapshot:
        """Return the latest computed snapshot, or a stale/empty one."""
        base = {
            "symbol": self._symbol,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "best_bid": None,
            "best_ask": None,
            "mid_price": None,
            "spread": None,
            "bid_volume_top5": 0.0,
            "ask_volume_top5": 0.0,
            "imbalance_ratio": 0.0,
            "raw_book_json": "",
            "depth_tier": "L1_DELAYED",
            "stale": True,
            "age_seconds": None,
            "connected": self.connected,
        }
        if self._book and self._last_book_ts is not None:
            age = round(time.time() - self._last_book_ts, 1)
            # _book carries bids/asks lists for debugging but BookSnapshot has
            # no such fields — copy only the payload keys.
            for k in (
                "best_bid", "best_ask", "mid_price", "spread",
                "bid_volume_top5", "ask_volume_top5", "imbalance_ratio",
                "raw_book_json", "depth_tier", "ts_utc",
            ):
                if k in self._book:
                    base[k] = self._book[k]
            base["stale"] = age > 30.0 or not self.connected
            base["age_seconds"] = age
            base["connected"] = self.connected
        return BookSnapshot(**base)
