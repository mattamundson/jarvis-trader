"""
FreqtradeBridge — HTTP API bridge to a running Freqtrade instance.

Architecture: Freqtrade runs as a SEPARATE process (not embedded).
jarvis-trader talks to it via Freqtrade's REST API (default: localhost:8080).
This keeps Freqtrade's battle-tested exchange connectors independent.

Freqtrade setup:
  pip install freqtrade
  freqtrade new-config --config infrastructure/freqtrade/config.json
  freqtrade trade --config infrastructure/freqtrade/config.json
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger("jarvis_trader.markets.crypto.bridge")


class FreqtradeBridge:
    """
    Communicates with a running Freqtrade instance via its REST API.
    Freqtrade docs: https://www.freqtrade.io/en/stable/rest-api/
    """

    def __init__(self, base_url: str = "http://localhost:8080/api/v1", password: str = ""):
        self.base_url = base_url.rstrip("/")
        self._password = password
        self._token: Optional[str] = None
        self._client = httpx.AsyncClient(timeout=10.0)

    async def authenticate(self) -> bool:
        """Get JWT token from Freqtrade API."""
        try:
            resp = await self._client.post(
                f"{self.base_url}/token/login",
                json={"password": self._password},
            )
            if resp.status_code == 200:
                self._token = resp.json().get("access_token")
                logger.info("Freqtrade: authenticated")
                return True
            logger.warning(f"Freqtrade auth failed: {resp.status_code}")
            return False
        except Exception as exc:
            logger.error(f"Freqtrade auth error: {exc}")
            return False

    def _headers(self) -> dict:
        if self._token:
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    async def is_running(self) -> bool:
        """Check if Freqtrade instance is alive."""
        try:
            resp = await self._client.get(f"{self.base_url}/ping", headers=self._headers())
            return resp.status_code == 200
        except Exception:
            return False

    async def get_status(self) -> dict:
        """Get Freqtrade status (running state, active trades)."""
        try:
            resp = await self._client.get(f"{self.base_url}/status", headers=self._headers())
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.error(f"get_status error: {exc}")
        return {}

    async def get_trades(self) -> list[dict]:
        """Get list of open trades."""
        try:
            resp = await self._client.get(f"{self.base_url}/trades", headers=self._headers())
            if resp.status_code == 200:
                return resp.json().get("trades", [])
        except Exception as exc:
            logger.error(f"get_trades error: {exc}")
        return []

    async def get_profit(self) -> dict:
        """Get profit statistics."""
        try:
            resp = await self._client.get(f"{self.base_url}/profit", headers=self._headers())
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.error(f"get_profit error: {exc}")
        return {}

    async def get_balance(self) -> dict:
        """Get wallet balance."""
        try:
            resp = await self._client.get(f"{self.base_url}/balance", headers=self._headers())
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.error(f"get_balance error: {exc}")
        return {}

    async def get_config(self) -> dict:
        """Get Freqtrade bot config summary (version, state, dry_run, bot_name)."""
        try:
            resp = await self._client.get(f"{self.base_url}/show_config", headers=self._headers())
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.error(f"get_config error: {exc}")
        return {}

    async def start_trading(self) -> bool:
        """Start Freqtrade trading loop."""
        try:
            resp = await self._client.post(f"{self.base_url}/start", headers=self._headers())
            return resp.status_code == 200
        except Exception:
            return False

    async def stop_trading(self) -> bool:
        """Stop Freqtrade trading loop."""
        try:
            resp = await self._client.post(f"{self.base_url}/stop", headers=self._headers())
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.aclose()
