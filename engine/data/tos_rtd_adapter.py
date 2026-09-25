"""TOSRTDConnector — thinkorswim desktop RTD (real-time data) adapter.

WHY THIS EXISTS
---------------
``thinkorswim.exe`` exposes live quotes over its registered COM RTD server
(ProgID ``Tos.RTD``, CLSID ``{1B415BA9-E543-41BD-8EB1-CB12A5B7678F}``,
InprocServer32 ``...\\thinkorswim\\lib64\\RTDService.dll``). That DLL is a thin
proxy onto thinkorswim's own TCP listener at ``127.0.0.1:12001`` — the same
server Excel's ``=RTD("TOS.RTD",,"LAST","SPY")`` talks to. When TOS is running
this is the lowest-latency *broker-direct* quote source available to the engine,
so it sits at **Tier 0** of the market-data waterfall.

TRANSPORT — WHAT IS AND IS NOT VERIFIED (read this before trusting a number)
---------------------------------------------------------------------------
Two transports were investigated against the live install:

1. **Raw TCP to 127.0.0.1:12001.** VERIFIED: the port is TOS's and it speaks a
   line-framed handshake — sending ``HELLO 1.1\\n`` returns the banner
   ``RTD SERVER\\n\\n``. That is what :func:`probe_tcp_handshake` uses, and it is
   a cheap, dependency-free liveness pre-flight.
   NOT VERIFIED: the post-handshake *subscription* framing. It is NOT the
   ``LAST=SPY``-style text protocol you might expect — every newline-terminated
   line sent after the banner is rejected and the server closes the socket
   (~95 candidate formats were tried). The DLL's own log strings ("Processed %d
   lines.", "Write send:%d") show the two directions use different, undocumented
   framings. Reversing it was deliberately abandoned in favour of (2), which is
   the vendor's own supported path.

2. **``Tos.RTD`` COM (IRtdServer).** VERIFIED end-to-end: live MES/SPY/QQQ/VIX
   quotes and live SPY option quotes were pulled from the running TOS.
   ``RTDService.dll`` forwards to the 12001 listener for us, so we inherit the
   working framing for free.

   Driven with **pywin32** (``win32com``), which is already present in
   ``engine/.venv`` — no ``comtypes``, no ``pip install``. The interface has no
   usable ``GetTypeInfo`` (``EnsureDispatch`` raises "can not automate the
   makepy process"), so this module calls ``IDispatch::Invoke`` **directly via
   ``InvokeTypes``** with arg/result descriptors transcribed from the registered
   ``RTDServerLib`` typelib. That keeps the module free of ``gencache``/makepy
   side effects (no writes into ``%TEMP%\\gen_py``) and of any generated Python
   that would have to be regenerated per interpreter.

   DO NOT "simplify" this to raw vtable calls. The raw ``IRtdServer`` vtable
   works for ``ServerStart`` / ``Heartbeat`` / ``RefreshData`` /
   ``DisconnectData`` / ``ServerTerminate`` (oVft 56/88/72/80/96) but
   ``ConnectData`` (oVft 64) faults inside the DLL when driven that way. The
   ``InvokeTypes`` (IDispatch) path is the one actually exercised.

THREADING — WHY THERE IS NO WORKER THREAD (hard-won, do not regress)
-------------------------------------------------------------------
``RTDService.dll`` registers **no ``ThreadingModel``**, so COM treats it as
``ThreadingModel=Apartment``: the object is always created inside the process's
*first* single-threaded apartment, and every call from any other apartment is
marshalled into it. A non-pumping STA (which is what an asyncio/uvicorn loop
thread is) never services that marshalled call, so the call hangs forever.

Measured on this machine:

* COM untouched before the adapter runs → a dedicated worker thread works.
* Anything touches COM first (``import win32com.client``, ``CoInitialize()`` on
  the main thread) → the worker thread's ``CoCreateInstance`` blocks forever and
  ``ServerStart`` times out — silently, with no exception.

Reproduced deterministically in both directions. The engine cannot promise it is
the first COM user, so the session is deliberately created **and used on the
calling thread** — in this engine the asyncio/uvicorn main thread, which is the
process's first apartment — with ``CoInitialize()`` done there. Individual RTD
calls are sub-millisecond round trips, so they are safe to make inline; anything
that needs to *wait* (first-fill) is an ``await asyncio.sleep`` loop, never a
blocking sleep.

SEMANTICS THAT MATTER
---------------------
* ``RefreshData`` returns only the topics whose value **changed** since the last
  call, and reports ``TopicCount == 0`` when nothing moved. The connector keeps
  a last-known-value cache per topic and merges deltas into it, so a quiet
  market does not look like a dead feed.
* Because updates are change-driven, an unchanged cache entry is **not** proof
  of freshness. Every value therefore carries ``as_of`` (local wall-clock of the
  last observation), and ``is_connected`` is driven by a live ``Heartbeat`` —
  never by the presence of a cached number.
* ``N/A``, empty strings and blanks are what TOS returns for an unknown symbol
  or a mute field. They are coerced to ``None`` rather than propagated as
  prices (the waterfall's "never emit a silent zero" invariant). A ``0.0`` is
  preserved as a number but ``get_current_price`` never promotes it to
  ``last_price`` (``0.0`` is falsy, so the tier falls through — same rule the
  IBKR/Schwab tiers rely on).
* A cold subscription has no value on the first ``RefreshData``; TOS fills it a
  beat later, so the first read waits (bounded) for the fill.

SAFETY
------
Read-only by construction: the connector only ever calls the RTD *read* API
(``ServerStart`` / ``ConnectData`` / ``RefreshData`` / ``Heartbeat`` /
``DisconnectData`` / ``ServerTerminate``). It has no order path, no account
access, and is never consulted by risk, kill-switch or execution code.
"""

from __future__ import annotations

import asyncio
import logging
import math
import socket
import time
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

from data.provenance import SOURCE_TOS_RTD

from .tos_indicator_engine import (
    Bar,
    IndicatorRegistry,
    IndicatorSnapshot,
)

logger = logging.getLogger(__name__)

# ── Transport constants ──────────────────────────────────────────────────────
RTD_HOST = "127.0.0.1"
RTD_PORT = 12001
RTD_PROGID = "Tos.RTD"
RTD_CLSID = "{1B415BA9-E543-41BD-8EB1-CB12A5B7678F}"

# Handshake accepted by thinkorswim's own RTD listener (verified live).
_TCP_HANDSHAKE = b"HELLO 1.1\n"
_TCP_BANNER = b"RTD SERVER"

# RTD dispmembers, transcribed from the registered RTDServerLib typelib.
_DISPID_SERVER_START = 10
_DISPID_CONNECT_DATA = 11
_DISPID_REFRESH_DATA = 12
_DISPID_DISCONNECT_DATA = 13
_DISPID_HEARTBEAT = 14
_DISPID_SERVER_TERMINATE = 15
_DISPATCH_METHOD = 1

# IDispatch arg/result descriptors (retType, argTypes) — exact typelib values.
_RET_I4 = (3, 0)
_RET_VOID = (24, 0)
_RET_SAFEARRAY_VARIANT = (8204, 0)
_ARGS_SERVER_START = ((9, 1),)  # IRTDUpdateEvent*
_ARGS_CONNECT_DATA = ((3, 1), (24588, 1), (16395, 3))  # long, SAFEARRAY(VARIANT)*, VARIANT_BOOL*
_ARGS_REFRESH_DATA = ((16387, 3),)  # long* (in/out)
_ARGS_DISCONNECT_DATA = ((3, 1),)  # long

# Fields pulled for a plain quote. CLOSE gives the waterfall a prev_close.
_QUOTE_FIELDS = ("LAST", "BID", "ASK", "CLOSE")
_OPTION_FIELDS = ("LAST", "BID", "ASK")

# ── Symbol mapping ───────────────────────────────────────────────────────────
# Verified live against the running TOS (2026-09-25):
#   VIX            -> 15.43      ($VIX.X and VIX.X do NOT resolve — 'N/A' / 0.0)
#   SPY/QQQ        -> resolve as-is
#   /MES:XCME      -> 7785.5     (bare "MES" returns 0.0, "/MES" returns 'N/A';
#                                 TOS futures require the ":/<EXCHANGE>" suffix)
#   .SPY260925C763 -> 4.80       (option symbols need the leading dot)
TOS_RTD_SYMBOLS: dict[str, str] = {
    "MES": "/MES:XCME",
    "ES": "/ES:XCME",
    "MNQ": "/MNQ:XCME",
    "NQ": "/NQ:XCME",
    "SPY": "SPY",
    "QQQ": "QQQ",
    "VIX": "VIX",
}

# TOS returns these for unknown symbols / fields with no print.
_NON_VALUES = frozenset({"n/a", "na", "nan", "null", "none", "-", "--", ""})

# Defaults
DEFAULT_STALE_AFTER_S = 20.0
DEFAULT_POLL_INTERVAL_S = 0.75
DEFAULT_HEARTBEAT_INTERVAL_S = 10.0
DEFAULT_CONNECT_TIMEOUT_S = 10.0
DEFAULT_FILL_TIMEOUT_S = 2.0


def _coerce_value(raw: Any) -> Optional[float]:
    """Coerce a raw RTD value to a float, or None when it is not a real number.

    TOS answers an unknown/mute topic with ``'N/A'``, ``''`` or ``0.0``; those
    must never reach the waterfall as prices.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        val = float(raw)
        return val if math.isfinite(val) else None
    if isinstance(raw, str):
        text = raw.strip().replace(",", "").replace("$", "")
        if text.lower() in _NON_VALUES:
            return None
        try:
            val = float(text)
        except (TypeError, ValueError):
            return None
        return val if math.isfinite(val) else None
    if isinstance(raw, (list, tuple)) and raw:
        return _coerce_value(raw[0])
    return None


def probe_tcp_handshake(
    host: str = RTD_HOST, port: int = RTD_PORT, timeout_s: float = 2.0
) -> dict:
    """Cheap, dependency-free liveness check of thinkorswim's RTD TCP listener.

    Sends the verified ``HELLO 1.1`` handshake and looks for the ``RTD SERVER``
    banner. This proves *the listener that the COM server proxies onto* is up —
    it deliberately does NOT claim anything about subscription framing, which is
    undocumented (see the module docstring).

    Returns ``{"ok": bool, "host", "port", "banner", "error"}``. Never raises.
    Use as a pre-flight: if nothing is listening there is no point paying for COM.
    """
    result: dict = {"ok": False, "host": host, "port": port, "banner": None, "error": None}
    sock = None
    try:
        sock = socket.create_connection((host, port), timeout=timeout_s)
        sock.settimeout(timeout_s)
        sock.sendall(_TCP_HANDSHAKE)
        banner = b""
        deadline = time.time() + timeout_s
        while time.time() < deadline and _TCP_BANNER not in banner:
            chunk = sock.recv(256)
            if not chunk:
                break
            banner += chunk
        result["banner"] = banner.decode("latin-1", "replace").strip() or None
        result["ok"] = _TCP_BANNER in banner
        if not result["ok"]:
            result["error"] = f"unexpected banner: {banner[:64]!r}"
    except Exception as exc:  # noqa: BLE001 — probe must never raise
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
    return result


class _UpdateEventSink:
    """Minimal ``IRTDUpdateEvent`` implementation handed to ``ServerStart``.

    The DLL calls ``UpdateNotify`` when its internal refresher fires. The
    connector does not depend on that push (it polls ``RefreshData`` itself), but
    the interface must be present and callable or ``ServerStart`` will not run.
    """

    _public_methods_ = [
        "UpdateNotify",
        "HeartbeatInterval",
        "Disconnect",
        "get_HeartbeatInterval",
        "put_HeartbeatInterval",
    ]

    def __init__(self, session: "_RtdSession") -> None:
        self._session = session

    def UpdateNotify(self) -> int:
        self._session.note_notify()
        return 0

    def Disconnect(self) -> int:
        return 0

    def get_HeartbeatInterval(self) -> int:
        return 5000

    def put_HeartbeatInterval(self, interval: int) -> int:
        return 0


class _RtdSession:
    """Owns the ``Tos.RTD`` COM object on the calling thread's apartment.

    See the module docstring's THREADING section: this object must live in the
    process's *first* COM apartment, so every method here is meant to be called
    from that thread (the engine's asyncio/uvicorn main thread). Individual calls
    are sub-millisecond; anything that has to wait is provided as an ``async``
    method that sleeps on the event loop rather than blocking it.
    """

    def __init__(
        self,
        *,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        heartbeat_interval_s: float = DEFAULT_HEARTBEAT_INTERVAL_S,
        stale_after_s: float = DEFAULT_STALE_AFTER_S,
        fill_timeout_s: float = DEFAULT_FILL_TIMEOUT_S,
    ) -> None:
        self._poll_interval_s = max(0.1, float(poll_interval_s))
        self._heartbeat_interval_s = max(1.0, float(heartbeat_interval_s))
        self._stale_after_s = max(1.0, float(stale_after_s))
        self._fill_timeout_s = max(0.0, float(fill_timeout_s))

        self._server: Any = None
        self._callback: Any = None
        self._com_ready = False

        self._cache: dict[int, Optional[float]] = {}
        self._observed_at: dict[int, float] = {}
        self._topics: dict[int, tuple[str, str]] = {}
        self._key_to_id: dict[tuple[str, str], int] = {}
        self._next_id = 1

        self._notify_count = 0
        self._last_poll_at = 0.0
        self._last_heartbeat_at = 0.0
        self._last_heartbeat_ok = False
        self._server_started = False
        self._last_error: Optional[str] = None

    # ── state ────────────────────────────────────────────────────────────────
    def note_notify(self) -> None:
        self._notify_count += 1

    @property
    def connected(self) -> bool:
        """Truthful liveness: ServerStart succeeded AND a recent Heartbeat was OK."""
        if not self._server_started or not self._last_heartbeat_ok:
            return False
        age = time.time() - self._last_heartbeat_at
        return age <= max(self._heartbeat_interval_s * 3.0, self._stale_after_s)

    def status(self) -> dict:
        return {
            "source": SOURCE_TOS_RTD,
            "connected": self.connected,
            "server_started": self._server_started,
            "heartbeat_ok": self._last_heartbeat_ok,
            "heartbeat_age_s": (
                round(time.time() - self._last_heartbeat_at, 2)
                if self._last_heartbeat_at
                else None
            ),
            "observed_topics": len(self._topics),
            "priced_topics": sum(1 for v in self._cache.values() if v is not None),
            "notify_count": self._notify_count,
            "last_error": self._last_error,
        }

    # ── COM plumbing (calling thread only) ───────────────────────────────────
    def ensure_com(self) -> bool:
        """``CoInitialize`` this thread. Idempotent; tolerates a prior init."""
        if self._com_ready:
            return True
        try:
            import pythoncom

            try:
                pythoncom.CoInitialize()
            except Exception as exc:  # noqa: BLE001 — RPC_E_CHANGED_MODE == already inited
                # Already initialised with a different model: usable as-is.
                logger.debug("[TOS-RTD] CoInitialize note: %s", exc)
            self._com_ready = True
            return True
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"pywin32/pythoncom unavailable: {exc}"
            logger.warning("[TOS-RTD] COM unavailable — adapter disabled: %s", exc)
            return False

    def start(self) -> bool:
        """Create the RTD object and run ``ServerStart``. Sync; called from the loop thread."""
        if self._server_started:
            return bool(self._last_heartbeat_ok)
        if not self.ensure_com():
            return False
        try:
            import win32com.client
            import win32com.server.util

            server = win32com.client.Dispatch(RTD_PROGID)
            callback = win32com.server.util.wrap(_UpdateEventSink(self))
            pf_res = server._oleobj_.InvokeTypes(
                _DISPID_SERVER_START, 0, _DISPATCH_METHOD, _RET_I4,
                _ARGS_SERVER_START, callback,
            )
            self._server = server
            self._callback = callback
            self._server_started = True
            # pywin32's InvokeTypes does not surface ServerStart's [out,retval]
            # pfRes — it comes back as None even on success (verified). So a
            # non-1 value here is NOT an error; Heartbeat is the liveness proof
            # and is checked immediately below.
            self._heartbeat_once()
            if not self._last_heartbeat_ok:
                self._last_error = "ServerStart ok but Heartbeat failed"
                logger.warning("[TOS-RTD] Heartbeat failed right after ServerStart")
            logger.info(
                "[TOS-RTD] session started (ServerStart pfRes=%r, heartbeat_ok=%s)",
                pf_res,
                self._last_heartbeat_ok,
            )
            return bool(self._last_heartbeat_ok)
        except Exception as exc:  # noqa: BLE001
            self._server_started = False
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("[TOS-RTD] session start failed: %s", exc)
            return False

    def stop(self) -> None:
        """``ServerTerminate`` and drop the object. Never raises."""
        server = self._server
        self._server = None
        self._callback = None
        self._server_started = False
        self._last_heartbeat_ok = False
        if server is None:
            return
        try:
            server._oleobj_.InvokeTypes(
                _DISPID_SERVER_TERMINATE, 0, _DISPATCH_METHOD, _RET_VOID, ()
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("[TOS-RTD] ServerTerminate failed: %s", exc)

    def heartbeat_once(self) -> bool:
        self._heartbeat_once()
        return self._last_heartbeat_ok

    def heartbeat_if_due(self) -> None:
        if time.time() - self._last_heartbeat_at >= self._heartbeat_interval_s:
            self._heartbeat_once()

    def _heartbeat_once(self) -> None:
        if self._server is None:
            return
        try:
            pf_res = self._server._oleobj_.InvokeTypes(
                _DISPID_HEARTBEAT, 0, _DISPATCH_METHOD, _RET_I4, ()
            )
            self._last_heartbeat_at = time.time()
            self._last_heartbeat_ok = bool(int(pf_res or 0))
        except Exception as exc:  # noqa: BLE001
            self._last_heartbeat_ok = False
            self._last_error = f"heartbeat: {type(exc).__name__}: {exc}"
            logger.debug("[TOS-RTD] Heartbeat failed: %s", exc)

    def subscribe(self, field: str, tos_symbol: str) -> Optional[int]:
        """Register (field, symbol) with RTD, reusing an existing topic id."""
        key = (field, tos_symbol)
        existing = self._key_to_id.get(key)
        if existing is not None:
            return existing
        if self._server is None:
            return None
        topic_id = self._next_id
        self._next_id += 1
        try:
            self._server._oleobj_.InvokeTypes(
                _DISPID_CONNECT_DATA, 0, _DISPATCH_METHOD, _RET_SAFEARRAY_VARIANT,
                _ARGS_CONNECT_DATA, topic_id, [field, tos_symbol], 0,
            )
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"ConnectData({field},{tos_symbol}): {exc}"
            logger.debug("[TOS-RTD] ConnectData failed for %s %s: %s", field, tos_symbol, exc)
            return None
        self._topics[topic_id] = (field, tos_symbol)
        self._key_to_id[key] = topic_id
        self._cache.setdefault(topic_id, None)
        return topic_id

    def poll_once(self) -> None:
        """Merge ``RefreshData`` deltas into the value cache.

        RefreshData returns only CHANGED topics, so an empty result is normal and
        must never clear anything.
        """
        if self._server is None:
            return
        try:
            result = self._server._oleobj_.InvokeTypes(
                _DISPID_REFRESH_DATA, 0, _DISPATCH_METHOD, _RET_SAFEARRAY_VARIANT,
                _ARGS_REFRESH_DATA, 0,
            )
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"RefreshData: {type(exc).__name__}: {exc}"
            logger.debug("[TOS-RTD] RefreshData failed: %s", exc)
            return
        self._last_poll_at = time.time()
        if not (isinstance(result, tuple) and len(result) >= 2):
            return
        payload = result[0]
        if not (isinstance(payload, tuple) and len(payload) == 2):
            return
        ids, values = payload
        if not ids:
            return
        now = time.time()
        for topic_id, raw in zip(ids, values, strict=False):
            topic_id = int(topic_id)
            if topic_id in self._topics:
                self._cache[topic_id] = _coerce_value(raw)
                self._observed_at[topic_id] = now

    def read_field(self, field: str, tos_symbol: str) -> tuple[Optional[float], Optional[float]]:
        """Return ``(value, observed_at)`` for a subscribed field."""
        topic_id = self._key_to_id.get((field, tos_symbol))
        if topic_id is None:
            return None, None
        return self._cache.get(topic_id), self._observed_at.get(topic_id)

    # ── waiting (async — never blocks the event loop) ────────────────────────
    async def fill(self, keys: list[tuple[str, str]], timeout_s: Optional[float] = None) -> None:
        """Poll until every key has been observed, or the budget runs out.

        RTD is change-driven: a brand-new subscription usually has no value on
        the first ``RefreshData`` — TOS publishes it a beat later. The waiting is
        done with ``asyncio.sleep`` so the loop stays responsive; each individual
        ``RefreshData`` is a sub-millisecond call.
        """
        budget = self._fill_timeout_s if timeout_s is None else float(timeout_s)
        deadline = time.monotonic() + max(0.0, budget)
        while True:
            self.poll_once()
            if all(self._key_to_id.get(k) in self._observed_at for k in keys):
                return
            if time.monotonic() >= deadline:
                return
            await asyncio.sleep(0.2)


class _LiveFlag(int):
    """``bool``-like flag that is ALSO callable.

    The waterfall reads connection state the same way it does for
    ``IBKRDataConnector`` / ``SchwabConnector`` — as a plain attribute
    (``connector.is_connected``) — while the adapter contract also exposes
    ``is_connected()``. Subclassing ``int`` (rather than ``bool``, which is
    final) satisfies both call styles and, critically, stays **falsy when
    disconnected**, so a missed ``()`` can never read as "connected".
    """

    __slots__ = ()

    def __bool__(self) -> bool:
        return int(self) != 0

    def __call__(self) -> bool:
        return int(self) != 0

    def __repr__(self) -> str:
        return repr(bool(self))


def resolve_tos_symbol(symbol: str) -> Optional[str]:
    """Map an engine symbol to the symbol string thinkorswim's RTD expects.

    Returns ``None`` for anything that is not a plausible TOS symbol, so the
    caller falls through to the next waterfall tier instead of subscribing to
    nonsense.
    """
    if not symbol:
        return None
    key = symbol.strip().upper()
    if key in TOS_RTD_SYMBOLS:
        return TOS_RTD_SYMBOLS[key]
    if key.startswith("^"):
        # Engine convention for an index (e.g. ^VIX) — strip the caret.
        bare = key[1:]
        return TOS_RTD_SYMBOLS.get(bare, bare or None)
    # Already-formed TOS symbol (futures "/ROOT:EXCHANGE" or option ".ROOT...").
    if key.startswith("/") or key.startswith(".") or ":" in key:
        return key
    # Plain equity/ETF ticker.
    if key.replace(".", "").isalpha() and len(key) <= 6:
        return key
    return None


def _option_root(symbol: str) -> Optional[str]:
    """TOS options root for an ETF/index underlying (futures options excluded)."""
    key = (symbol or "").strip().upper().lstrip("^")
    if key in {"SPY", "QQQ", "IWM", "DIA", "VIX"}:
        return key
    return None


def _fmt_strike(strike: float) -> str:
    return str(int(strike)) if float(strike).is_integer() else f"{float(strike):g}"


def default_weekly_expiry(today: Optional[date] = None) -> date:
    """Nearest standard weekly expiry (Friday) on/after ``today``."""
    today = today or datetime.now().date()
    return today + timedelta(days=(4 - today.weekday()) % 7)


class TOSRTDConnector:
    """Thinkorswim RTD quote source for the engine's market-data waterfall.

    Tier-0 source: used only when TOS is actually running and the RTD session is
    heartbeating. Every failure mode — TOS closed, pywin32 missing, COM fault,
    unknown symbol — degrades to ``None`` so the waterfall falls through to
    IBKR/Schwab/Polygon untouched.

    All methods are meant to be awaited from the engine's main event loop; the
    session's COM object is apartment-bound to that thread (see the module
    docstring).
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        host: str = RTD_HOST,
        port: int = RTD_PORT,
        symbols: Optional[Iterable[str]] = None,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        heartbeat_interval_s: float = DEFAULT_HEARTBEAT_INTERVAL_S,
        stale_after_s: float = DEFAULT_STALE_AFTER_S,
        fill_timeout_s: float = DEFAULT_FILL_TIMEOUT_S,
        options_strike_window: int = 4,
        options_strike_step: float = 1.0,
        max_option_topics: int = 120,
    ) -> None:
        self.enabled = bool(enabled)
        self.host = host
        self.port = port
        self.stale_after_s = float(stale_after_s)
        self.options_strike_window = max(0, int(options_strike_window))
        self.options_strike_step = float(options_strike_step)
        self.max_option_topics = max(6, int(max_option_topics))
        self.poll_interval_s = max(0.1, float(poll_interval_s))
        self.watch_symbols = [s.upper() for s in (symbols or ("MES", "SPY", "QQQ", "VIX"))]
        self._session = _RtdSession(
            poll_interval_s=poll_interval_s,
            heartbeat_interval_s=heartbeat_interval_s,
            stale_after_s=stale_after_s,
            fill_timeout_s=fill_timeout_s,
        )
        self._preflight: Optional[dict] = None
        self._last_error: Optional[str] = None
        self._keepwarm_task: Optional[asyncio.Task] = None
        # Indicator engine — computes ATR / Keltner / multi-TF S/R from the
        # live RTD price stream. See data/tos_indicator_engine.py for why these
        # are derived here rather than read as RTD study topics.
        self._indicators = IndicatorRegistry()
        # 1-minute bar builder state, per TOS symbol.
        self._bar_state: dict[str, dict] = {}

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def connect(self) -> bool:
        """Bring up the RTD session. Safe to call when TOS is down.

        Runs a cheap TCP pre-flight first: if nothing is listening on the RTD
        port there is no point paying for COM setup. The COM work itself is done
        inline (sub-millisecond) because the RTD object is apartment-bound to
        this thread — see the module docstring's THREADING section.
        """
        if not self.enabled:
            self._last_error = "disabled"
            return False
        if self.is_connected:
            return True

        preflight = await asyncio.to_thread(probe_tcp_handshake, self.host, self.port)
        self._preflight = preflight
        if not preflight.get("ok"):
            self._last_error = f"pre-flight failed: {preflight.get('error')}"
            logger.info(
                "[TOS-RTD] thinkorswim RTD listener not answering on %s:%s (%s) — "
                "tier inactive",
                self.host,
                self.port,
                preflight.get("error"),
            )
            return False

        ok = self._session.start()
        if ok:
            self._last_error = None
            # Pre-subscribe LAST for every watch symbol so the keepwarm loop has
            # a price stream to feed the indicator engines from the very first
            # tick. Without this the indicator set stays cold until some other
            # caller happens to request a quote.
            self._presubscribe_watchlist()
            self._start_keepwarm()
            logger.info(
                "[TOS-RTD] connected — watchlist %s (banner=%r)",
                self.watch_symbols,
                preflight.get("banner"),
            )
        else:
            self._last_error = self._session.status().get("last_error") or "session start failed"
            logger.warning("[TOS-RTD] RTD session did not start: %s", self._last_error)
        return bool(ok)

    async def close(self) -> None:
        """Tear the RTD session down. Never raises."""
        if self._keepwarm_task is not None:
            self._keepwarm_task.cancel()
            try:
                await self._keepwarm_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._keepwarm_task = None
        try:
            self._session.stop()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[TOS-RTD] close failed: %s", exc)

    def _start_keepwarm(self) -> None:
        """Background poller: keeps the value cache warm and heartbeats fresh."""
        if self._keepwarm_task is not None and not self._keepwarm_task.done():
            return
        self._keepwarm_task = asyncio.create_task(self._keepwarm_loop())

    async def _keepwarm_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.poll_interval_s)
                try:
                    self._session.poll_once()
                    self._session.heartbeat_if_due()
                    self._feed_indicators()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[TOS-RTD] keepwarm tick failed: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("[TOS-RTD] keepwarm loop ended: %s", exc)

    # ── indicators ───────────────────────────────────────────────────────────

    def _presubscribe_watchlist(self) -> None:
        """Subscribe LAST for every watch symbol (best-effort, never raises).

        Gives the indicator engine a continuous price stream independent of
        whatever quote calls the rest of the engine happens to make.
        """
        for engine_symbol in self.watch_symbols:
            tos_symbol = resolve_tos_symbol(engine_symbol)
            if tos_symbol is None:
                continue
            try:
                self._session.subscribe("LAST", tos_symbol)
            except Exception as exc:  # noqa: BLE001
                logger.debug("[TOS-RTD] pre-subscribe %s failed: %s", engine_symbol, exc)

    def _feed_indicators(self) -> None:
        """Push the latest RTD prices into the indicator engines.

        Runs inside the keepwarm loop (same thread as the COM session), so the
        cache read is free. Prices are aggregated into 1-minute bars; every tick
        also updates the day-range gauge, which does not need a bar close.
        """
        for engine_symbol in self.watch_symbols:
            tos_symbol = resolve_tos_symbol(engine_symbol)
            if tos_symbol is None:
                continue
            value, observed = self._session.read_field("LAST", tos_symbol)
            if value is None:
                continue

            engine = self._indicators.get(engine_symbol)

            # Day-range / last-price update on every tick.
            engine.tick(float(value))

            # 1-minute bar aggregation keyed on wall-clock minute.
            minute = int(time.time() // 60)
            state = self._bar_state.get(engine_symbol)
            if state is None:
                self._bar_state[engine_symbol] = {
                    "minute": minute,
                    "open": float(value),
                    "high": float(value),
                    "low": float(value),
                }
                continue

            if minute == state["minute"]:
                state["high"] = max(state["high"], float(value))
                state["low"] = min(state["low"], float(value))
                continue

            # Minute rolled over — close the bar and start the next one.
            engine.ingest(
                Bar(
                    open=state["open"],
                    high=state["high"],
                    low=state["low"],
                    close=float(value),
                )
            )
            self._bar_state[engine_symbol] = {
                "minute": minute,
                "open": float(value),
                "high": float(value),
                "low": float(value),
            }

    async def get_indicators(self, symbol: str) -> Optional[IndicatorSnapshot]:
        """Latest indicator snapshot for ``symbol`` (None when unknown).

        Returns ATR(14), Keltner(20, 3.5), 5/15/30-minute support & resistance,
        and the day-range compression gauge — all derived from the live RTD
        price stream. No RTD study subscription is required.
        """
        if not self.enabled:
            return None
        engine_symbol = (symbol or "").strip().upper()
        if not engine_symbol:
            return None
        if engine_symbol not in self.watch_symbols and resolve_tos_symbol(engine_symbol) is None:
            return None
        return self._indicators.snapshot(engine_symbol)

    def indicators_status(self) -> list[dict]:
        """Per-symbol indicator warm-up state, for observability."""
        out: list[dict] = []
        for symbol in self.watch_symbols:
            snap = self._indicators.snapshot(symbol)
            atr_value = snap.atr.value
            out.append(
                {
                    "symbol": symbol,
                    "last_price": snap.last_price,
                    "atr": atr_value,
                    "atr_bars": snap.atr.bars_used,
                    # `warm` means "ATR has been computed", not "ATR is nonzero".
                    # A flat overnight tape legitimately yields ATR == 0.0, and
                    # `bool(0.0)` would misreport that as cold.
                    "warm": atr_value is not None,
                }
            )
        return out

    # ── state ────────────────────────────────────────────────────────────────
    @property
    def is_connected(self) -> _LiveFlag:
        """Truthful connection state (attribute-first, also callable)."""
        try:
            return _LiveFlag(1 if self.enabled and self._session.connected else 0)
        except Exception:  # noqa: BLE001 — must never raise into the waterfall
            return _LiveFlag(0)

    def status(self) -> dict:
        """Snapshot for /health surfaces. Cheap and non-blocking."""
        base = {
            "enabled": self.enabled,
            "host": self.host,
            "port": self.port,
            "watch_symbols": list(self.watch_symbols),
            "preflight_ok": bool((self._preflight or {}).get("ok")),
            "last_error": self._last_error,
        }
        base.update(self._session.status())
        base["last_error"] = self._last_error or base.get("last_error")
        base["connected"] = bool(self.is_connected)
        # Derived-indicator warm-up state (ATR/Keltner/S-R come from the live
        # price stream, not from RTD study topics — see _feed_indicators).
        try:
            base["indicators"] = self.indicators_status()
        except Exception:  # noqa: BLE001 — status must never raise
            base["indicators"] = []
        return base

    # ── data ─────────────────────────────────────────────────────────────────
    async def get_current_price(self, symbol: str) -> dict:
        """Latest quote for ``symbol``.

        Returns ``{last_price, prev_close, change_pct, bid, ask, source, as_of}``
        where every price is ``None`` when genuinely unavailable — never a
        silent zero.
        """
        fallback = {
            "last_price": None,
            "prev_close": None,
            "change_pct": None,
            "bid": None,
            "ask": None,
            "as_of": None,
            "source": SOURCE_TOS_RTD,
            "tos_symbol": None,
        }
        if not self.enabled or not self.is_connected:
            return fallback
        tos_symbol = resolve_tos_symbol(symbol)
        if tos_symbol is None:
            return fallback
        try:
            keys = [(field, tos_symbol) for field in _QUOTE_FIELDS]
            for field, key_symbol in keys:
                self._session.subscribe(field, key_symbol)
            await self._session.fill(keys)

            out: dict[str, Optional[float]] = {}
            newest: Optional[float] = None
            for field in _QUOTE_FIELDS:
                value, observed = self._session.read_field(field, tos_symbol)
                out[field] = value
                if observed is not None and (newest is None or observed > newest):
                    newest = observed
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.debug("[TOS-RTD] quote failed for %s: %s", symbol, exc)
            return fallback

        last = out["LAST"]
        prev_close = out["CLOSE"]
        change_pct = None
        if last is not None and prev_close:
            try:
                change_pct = ((last - prev_close) / prev_close) * 100.0
            except ZeroDivisionError:
                change_pct = None
        return {
            "last_price": last,
            "prev_close": prev_close,
            "change_pct": change_pct,
            "bid": out["BID"],
            "ask": out["ASK"],
            "as_of": newest,
            "source": SOURCE_TOS_RTD,
            "tos_symbol": tos_symbol,
        }

    async def get_options_chain(
        self,
        symbol: str,
        expiry: Optional[date] = None,
        strikes: Optional[Iterable[float]] = None,
    ) -> list[dict]:
        """Live option quotes for a bounded strike window around spot.

        thinkorswim's RTD has no chain-enumeration call — it only answers for
        option symbols you name — so the window is built explicitly. Pass
        ``expiry``/``strikes`` to pin it; otherwise the nearest weekly expiry and
        a ``±options_strike_window`` band around the underlying's last price are
        used. Rows carry a real quote or are omitted; ``[]`` means unavailable.
        """
        if not self.enabled or not self.is_connected:
            return []
        root = _option_root(symbol)
        if root is None:
            logger.debug("[TOS-RTD] options not supported for %s", symbol)
            return []

        expiry = expiry or default_weekly_expiry()
        strike_list = [float(s) for s in strikes] if strikes is not None else None
        if strike_list is None:
            quote = await self.get_current_price(root)
            spot = quote.get("last_price")
            if not spot:
                logger.debug("[TOS-RTD] no spot for %s — cannot build strike window", root)
                return []
            step = self.options_strike_step
            anchor = round(spot / step) * step
            strike_list = [
                anchor + (i * step)
                for i in range(-self.options_strike_window, self.options_strike_window + 1)
            ]

        # len(_OPTION_FIELDS) topics per contract; keep the subscription bounded.
        per_contract = len(_OPTION_FIELDS)
        max_contracts = max(1, self.max_option_topics // per_contract)
        if len(strike_list) * 2 > max_contracts:
            keep = max(1, max_contracts // 2)
            mid = len(strike_list) // 2
            start = max(0, mid - keep)
            strike_list = strike_list[start : start + (keep * 2)]

        expiry_token = expiry.strftime("%y%m%d")
        pending: list[tuple[tuple[str, str], str, str, float]] = []
        for strike in strike_list:
            for right in ("C", "P"):
                occ = f".{root}{expiry_token}{right}{_fmt_strike(strike)}"
                for field in _OPTION_FIELDS:
                    self._session.subscribe(field, occ)
                    pending.append(((field, occ), occ, right, strike))
        if not pending:
            return []
        await self._session.fill([key for key, _occ, _r, _s in pending])

        rows: dict[tuple[str, float], dict] = {}
        for (field, occ), _occ2, right, strike in pending:
            value, observed = self._session.read_field(field, occ)
            if observed is None:
                continue
            row = rows.setdefault(
                (right, strike),
                {
                    "option_symbol": occ,
                    "underlying": root,
                    "expiry": expiry.isoformat(),
                    "strike": strike,
                    "right": "call" if right == "C" else "put",
                    "last": None,
                    "bid": None,
                    "ask": None,
                    "source": SOURCE_TOS_RTD,
                    "as_of": None,
                },
            )
            row[{"LAST": "last", "BID": "bid", "ASK": "ask"}[field]] = value
            if row["as_of"] is None or observed > row["as_of"]:
                row["as_of"] = observed
        return sorted(rows.values(), key=lambda r: (r["right"], r["strike"]))


# ── module-level singleton (mirrors tradingview_feed / polygon_stream wiring) ─
_default_connector: Optional[TOSRTDConnector] = None


def get_tos_rtd_connector() -> TOSRTDConnector:
    """Process-wide TOS RTD connector (created lazily, not connected).

    NOTE: construction is cheap, but ``connect()`` must be awaited from the
    engine's main event loop — the RTD COM object is bound to that apartment.
    """
    global _default_connector
    if _default_connector is None:
        _default_connector = TOSRTDConnector()
    return _default_connector
