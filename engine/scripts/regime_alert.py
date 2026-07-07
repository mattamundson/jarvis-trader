"""Regime detector alert — fetches daily bars, evaluates regime, fires Discord/WhatsApp alert.

Designed to run as a scheduled task (daily, after market close).

Usage:
    python engine/scripts/regime_alert.py
    python engine/scripts/regime_alert.py --engine-url http://127.0.0.1:8010
    python engine/scripts/regime_alert.py --dry-run     # evaluate without sending alert

Exit codes:
    0 — regime OK (no alert)
    1 — REGIME ALERT fired (or an unrecoverable error)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

# Allow running from project root or engine/ subdir
_engine_dir = Path(__file__).parent.parent
if str(_engine_dir) not in sys.path:
    sys.path.insert(0, str(_engine_dir))

from risk.regime_detector import RegimeStatus, evaluate_regime  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("regime_alert")

_ENGINE_URL = "http://127.0.0.1:8010"
_LOOKBACK_DAYS = 40  # need enough bars for RSI(14) + 5-day window


def _fetch_daily_bars(
    symbol: str, engine_url: str, futures: bool = False
) -> Optional[pd.DataFrame]:
    """Hit /analyze/bars/{symbol}?timeframe=1D and return a DataFrame with 'close' column."""
    futures_param = "true" if futures else "false"
    url = (
        f"{engine_url}/analyze/bars/{symbol}"
        f"?timeframe=1D&days={_LOOKBACK_DAYS}&futures={futures_param}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "JarvisRegimeAlert/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        logger.warning(f"HTTP {exc.code} fetching {symbol} bars: {exc.reason}")
        return None
    except Exception as exc:
        logger.warning(f"Failed to fetch {symbol} bars: {exc}")
        return None

    bars = data.get("bars") or []
    if not bars:
        logger.warning(f"No bars returned for {symbol}")
        return None

    df = pd.DataFrame(bars)
    if "close" not in df.columns:
        logger.warning(f"{symbol} bars missing 'close' column (got: {list(df.columns)})")
        return None

    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    logger.info(f"Fetched {len(df)} daily bars for {symbol}")
    return df


def _send_alert(message: str, engine_url: str) -> bool:
    """POST alert message to engine /safety/alerts/manual endpoint (if it exists)."""
    url = f"{engine_url}/safety/alerts/manual"
    payload = json.dumps({"message": message, "source": "regime_detector"}).encode()
    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "JarvisRegimeAlert/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info(f"Alert sent, engine responded: {resp.status}")
            return True
    except Exception as exc:
        logger.warning(f"Could not POST alert to engine ({exc}); alert logged locally only")
        return False


def _write_state_file(status: RegimeStatus, state_path: Path) -> None:
    """Write machine-readable regime state JSON for other tools to read."""
    state = {
        "evaluated_at": datetime.now(tz=timezone.utc).isoformat(),
        "alert": status.alert,
        "triggers": status.triggers,
        "mes_rsi": status.mes_rsi,
        "vix_level": status.vix_level,
        "message": status.message,
    }
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    logger.info(f"State written to {state_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Regime detector alert")
    parser.add_argument("--engine-url", default=_ENGINE_URL)
    parser.add_argument("--dry-run", action="store_true", help="Evaluate but do not send alert")
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path(__file__).parent.parent / "data" / "regime_state.json",
        help="Path to write machine-readable regime state JSON",
    )
    args = parser.parse_args()

    logger.info(f"Regime detector starting — engine: {args.engine_url}")

    # Fetch MES daily bars
    mes_df = _fetch_daily_bars("MES", args.engine_url, futures=True)

    # Fetch VIX daily bars (VIX is an index, not a futures contract)
    vix_df = _fetch_daily_bars("VIX", args.engine_url, futures=False)

    # Evaluate regime conditions
    status = evaluate_regime(mes_daily_df=mes_df, vix_daily_df=vix_df)

    logger.info(status.message)
    _write_state_file(status, args.state_file)

    if status.alert:
        if args.dry_run:
            logger.info("[DRY RUN] Alert suppressed.")
        else:
            _send_alert(status.message, args.engine_url)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
