"""
Market data endpoints
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["market"])

# Global references (injected from main.py)


def inject_dependencies():
    """Inject dependencies from main.py"""
    pass


@router.get("/market/earnings")
async def get_upcoming_earnings(days: int = 7):
    """Check for upcoming earnings near our watched symbols."""
    WATCHED = {
        "SPY": "S&P 500 ETF",
        "QQQ": "Nasdaq ETF",
        "AAPL": "Apple (QQQ weight)",
        "MSFT": "Microsoft (QQQ weight)",
        "NVDA": "Nvidia (QQQ weight)",
        "AMZN": "Amazon",
        "META": "Meta",
        "GOOGL": "Alphabet",
    }

    from datetime import timedelta

    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days)
    upcoming = []

    try:
        import yfinance as yf

        for symbol, name in WATCHED.items():
            try:
                ticker = yf.Ticker(symbol)
                cal = ticker.calendar
                if cal is None:
                    continue
                if hasattr(cal, "columns"):
                    dates = (
                        cal["Earnings Date"].dropna().tolist()
                        if "Earnings Date" in cal.columns
                        else []
                    )
                elif isinstance(cal, dict):
                    dates = cal.get("Earnings Date", [])
                    if not isinstance(dates, list):
                        dates = [dates]
                else:
                    continue
                for d in dates:
                    if d is None:
                        continue
                    if hasattr(d, "to_pydatetime"):
                        d = d.to_pydatetime()
                    if not hasattr(d, "tzinfo"):
                        continue
                    if d.tzinfo is None:
                        import pytz

                        d = pytz.utc.localize(d)
                    if now <= d <= cutoff:
                        upcoming.append(
                            {
                                "symbol": symbol,
                                "name": name,
                                "date": d.strftime("%Y-%m-%d"),
                                "days_away": (d - now).days,
                            }
                        )
            except Exception:
                continue

        upcoming.sort(key=lambda x: x["days_away"])
        return {
            "upcoming_earnings": upcoming,
            "count": len(upcoming),
            "days_lookahead": days,
            "note": "High-impact earnings can increase volatility on MES/MNQ",
            "source": "yfinance",
        }

    except ImportError:
        return {
            "upcoming_earnings": [],
            "count": 0,
            "days_lookahead": days,
            "note": "yfinance not installed",
            "source": "unavailable",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/market/session")
async def get_market_session():
    """Return current market session status (pre-market, regular, after-hours, closed)."""
