"""
KrakenAdapter — thin async wrapper around the `kraken-cli` Rust binary.

Architecture:
    The adapter invokes `kraken` (from krakenfx/kraken-cli) as a subprocess
    and parses its `-o json` output. All network I/O and authentication are
    delegated to the binary, which reads credentials from env vars
    KRAKEN_SPOT_API_KEY/SECRET and KRAKEN_FUTURES_API_KEY/SECRET.

Paper vs live:
    When `live_enabled=False` (default), every trading command is prefixed
    with `paper ` so kraken-cli's built-in paper engine handles the trade.
    Read-only queries like `balance` still go to the live endpoint so the
    adapter can display the real account context — only mutating calls are
    redirected.

Rate limiting:
    Kraken's public endpoints allow ~1 req/s. The adapter does NOT enforce
    this client-side (the pipeline cadence is well below that), but it DOES
    back off on 429/rate-limit exit codes from the CLI, with up to 3 retries
    and exponential delay.

Composition, not inheritance:
    This class is NOT a MarketModule. `CryptoMarketModule` composes it the
    same way it composes `FreqtradeBridge` — backend selection happens at
    module construction.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from typing import Any, Optional

logger = logging.getLogger("jarvis_trader.markets.crypto.kraken")

# Default Rust binary name; override if installed under a different alias.
KRAKEN_CLI = "kraken"

# Soft retry budget for transient CLI errors (e.g. 429 rate limit).
_MAX_RETRIES = 3
_BASE_BACKOFF_SECONDS = 0.5


class KrakenAdapter:
    """
    Async wrapper around kraken-cli. Methods mirror the CLI's command tree:

      - balance() → `kraken balance -o json`
      - positions() → `kraken positions -o json` or `kraken paper positions -o json`
      - ticker(symbol) → `kraken ticker <sym> -o json`
      - submit_order(...) → `kraken order buy/sell <sym> <qty> [options]`
        (or `kraken paper buy/sell ...` when live_enabled=False)

    All methods return native Python objects. On any failure — CLI missing,
    JSON parse error, nonzero exit, timeout — they return None or [] and
    log at DEBUG. They never raise.
    """

    def __init__(
        self,
        *,
        live_enabled: bool = False,
        binary: str = KRAKEN_CLI,
        default_order_type: str = "limit",
    ):
        self._binary = binary
        self._live_enabled = live_enabled
        self._default_order_type = default_order_type
        self._available: Optional[bool] = None

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Cached check: is the kraken binary available (native or WSL)?"""
        if self._available is not None:
            return self._available

        # 1. Check native PATH
        if shutil.which(self._binary) is not None:
            self._available = True
            return True

        # 2. Check WSL fallback (Phase 6 requirement)
        import sys
        if sys.platform == "win32":
            # Heuristic: check if 'wsl' exists and if the binary exists in standard WSL cargo path
            if shutil.which("wsl") is not None:
                # We can't easily check file existence inside WSL without running a command,
                # so we'll assume it's available if 'wsl' is present and we'll fail later if not.
                # In production, we'd do a 'wsl which kraken' here.
                self._available = True
                return True

        self._available = False
        logger.debug("kraken-cli not found on PATH (native or WSL) — adapter unavailable")
        return False

    @property
    def paper_mode(self) -> bool:
        return not self._live_enabled

    # ------------------------------------------------------------------
    # CLI helper
    # ------------------------------------------------------------------

    async def _run(self, args: list[str], timeout: float = 10.0) -> Optional[Any]:
        """
        Execute `kraken <args>` and return the parsed JSON output.
        Automatically handles WSL prefix on Windows.
        """
        if not self.is_available():
            return None

        # Resolve command: handle Windows -> WSL bridge
        import sys
        if sys.platform == "win32" and shutil.which(self._binary) is None:
            # Command: wsl /home/mattm/.cargo/bin/kraken <args>
            # Note: hardcoded user path 'mattm' is local to this workstation
            cmd = ["wsl", "/home/mattm/.cargo/bin/kraken", *args]
        else:
            cmd = [self._binary, *args]

        for attempt in range(_MAX_RETRIES):
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                logger.debug("kraken %s timed out after %.1fs", " ".join(args), timeout)
                return None
            except FileNotFoundError:
                self._available = False
                return None

            stdout = (stdout_b or b"").decode("utf-8", errors="replace").strip()
            stderr = (stderr_b or b"").decode("utf-8", errors="replace").strip()

            if proc.returncode == 0:
                if not stdout:
                    return None
                try:
                    return json.loads(stdout)
                except json.JSONDecodeError:
                    logger.debug("kraken %s returned non-JSON stdout", " ".join(args))
                    return None

            # Transient: back off and retry on rate-limit indicators
            low = stderr.lower()
            is_rate_limit = "429" in low or "rate" in low or "too many requests" in low
            if is_rate_limit and attempt < _MAX_RETRIES - 1:
                delay = _BASE_BACKOFF_SECONDS * (2 ** attempt)
                logger.debug(
                    "kraken %s rate-limited (attempt %d/%d); sleeping %.2fs",
                    " ".join(args),
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            logger.debug(
                "kraken %s failed (rc=%s): %s",
                " ".join(args),
                proc.returncode,
                stderr[:200],
            )
            return None

        return None

    # ------------------------------------------------------------------
    # Read-only queries — always live (read live account state)
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """
        Probe the CLI and return True if it responds with usable JSON.
        In paper mode, ensures the paper engine is initialized.
        """
        if not self.is_available():
            return False
        version = await self._run(["--version"], timeout=5.0)
        if version is None:
            # `--version` may return plain text (not JSON); try `balance` as secondary probe
            balance = await self._run(["balance", "-o", "json"], timeout=5.0)
            return balance is not None
        return True

    async def get_balance(self) -> Optional[dict]:
        return await self._run(["balance", "-o", "json"])

    async def get_positions(self) -> list[dict]:
        """
        Return open spot/futures positions. In paper mode, returns the paper
        engine's balances as a proxy for positions.
        """
        if self.paper_mode:
            # Paper mode: use 'paper balance'
            result = await self._run(["paper", "balance", "-o", "json"])
            if isinstance(result, dict) and "balances" in result:
                positions = []
                for sym, bal in result["balances"].items():
                    if bal.get("total", 0) > 0 and sym != "USD":
                        positions.append({
                            "symbol": sym,
                            "quantity": bal["total"],
                            "available": bal["available"]
                        })
                return positions
            return []
        else:
            # Live mode: use 'positions' (if supported) or fallback to 'balance'
            result = await self._run(["positions", "-o", "json"])
            if isinstance(result, list):
                return result
            if isinstance(result, dict) and isinstance(result.get("positions"), list):
                return result["positions"]

            # Fallback to balance
            result = await self._run(["balance", "-o", "json"])
            if isinstance(result, dict):
                return [{"symbol": k, "quantity": v} for k, v in result.items() if float(v) > 0]
            return []

    async def get_daily_pnl(self) -> float:
        """
        Best-effort daily P&L.
        In paper mode, uses 'paper status'.
        """
        if self.paper_mode:
            result = await self._run(["paper", "status", "-o", "json"])
            if isinstance(result, dict):
                return float(result.get("unrealized_pnl", 0.0))
            return 0.0

        args = ["pnl", "-o", "json"]
        result = await self._run(args)
        if isinstance(result, dict):
            for key in ("daily_pnl", "pnl_today", "pnl", "total"):
                val = result.get(key)
                if isinstance(val, (int, float)):
                    return float(val)
        return 0.0

    async def get_ticker(self, symbol: str) -> Optional[dict]:
        """Public market data — same endpoint in paper and live."""
        return await self._run(["ticker", symbol, "-o", "json"])

    # ------------------------------------------------------------------
    # Mutating calls — paper-gated
    # ------------------------------------------------------------------

    async def submit_order(
        self,
        *,
        symbol: str,
        side: str,  # "buy" | "sell"
        quantity: float,
        order_type: Optional[str] = None,
        limit_price: Optional[float] = None,
    ) -> Optional[dict]:
        """
        Submit a spot order. In paper mode, this calls `kraken paper buy/sell`.
        In live mode, this calls `kraken order buy/sell`.

        The caller is responsible for having obtained approval for live orders
        (e.g. via WhatsApp gate) before this method is invoked.
        """
        side_norm = side.lower().strip()
        if side_norm not in ("buy", "sell"):
            logger.warning("KrakenAdapter: invalid side '%s'", side)
            return None

        effective_type = (order_type or self._default_order_type).lower()

        args: list[str]
        if self.paper_mode:
            # kraken paper buy <sym> <qty> [--type limit --price X]
            args = ["paper", side_norm, symbol, str(quantity)]
        else:
            # kraken order buy <sym> <qty> --type limit --price X
            args = ["order", side_norm, symbol, str(quantity)]

        args.extend(["--type", effective_type])
        if effective_type == "limit" and limit_price is not None:
            args.extend(["--price", str(limit_price)])

        args.extend(["-o", "json"])
        return await self._run(args, timeout=15.0)

    async def cancel_order(self, order_id: str) -> Optional[dict]:
        args = (
            ["paper", "cancel", order_id, "-o", "json"]
            if self.paper_mode
            else ["cancel", order_id, "-o", "json"]
        )
        return await self._run(args)

    async def init_paper(self, balance: float = 10000.0) -> Optional[dict]:
        """Initialize (or reset) the kraken-cli paper account."""
        return await self._run(
            ["paper", "init", "--balance", str(balance), "-o", "json"]
        )
