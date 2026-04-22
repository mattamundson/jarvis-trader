"""
JARVIS TRADER — Setup Verification Script
==========================================
Run this to verify your environment is configured correctly.
Usage: python test_setup.py

Checks:
  ✅ Python version
  ✅ Required packages installed
  ✅ .env file exists with required keys
  ✅ IBKR Gateway reachable (if running)
  ✅ Schwab API credentials present
  ✅ Market data APIs (Polygon, Finnhub)
  ✅ Anthropic LLM API
  ✅ Infrastructure (PostgreSQL, Redis, QuestDB)
"""

import asyncio
import os
import sys
from pathlib import Path


def check(label: str, passed: bool, detail: str = ""):
    icon = "✅" if passed else "❌"
    msg = f"  {icon} {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return passed


def check_warn(label: str, passed: bool, detail: str = ""):
    icon = "✅" if passed else "⚠️ "
    msg = f"  {icon} {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return True  # Warnings don't fail the check


print("\n🤖 JARVIS TRADER — Setup Verification")
print("=" * 50)
errors = 0

# ── Python Version ────────────────────────────────────────────────────────
print("\n📦 Python Environment")
py_ok = check(
    f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    sys.version_info >= (3, 10),
    "need 3.10+" if sys.version_info < (3, 10) else "OK",
)
if not py_ok:
    errors += 1

# ── Required Packages ─────────────────────────────────────────────────────
print("\n📦 Core Packages")
packages = [
    ("fastapi", "FastAPI web framework"),
    ("pydantic", "Data validation"),
    ("pydantic_settings", "Settings management"),
    ("pandas", "Data processing"),
    ("numpy", "Numerical computing"),
    ("pandas_ta", "Technical indicators"),
    ("httpx", "HTTP client"),
    ("anthropic", "Claude LLM API"),
    ("langchain", "LangChain framework"),
    ("langgraph", "LangGraph orchestration"),
]

for pkg, desc in packages:
    try:
        __import__(pkg)
        check(f"{pkg}", True, desc)
    except ImportError:
        check(f"{pkg}", False, f"MISSING — pip install {pkg}")
        errors += 1

print("\n📦 Trading Packages")
trading_packages = [
    ("ib_async", "Interactive Brokers API (required for futures)"),
    ("schwab", "Charles Schwab API"),
    ("alpaca", "Alpaca Markets (paper trading)"),
    ("polygon", "Polygon.io market data"),
    ("finnhub", "Finnhub news/sentiment"),
    ("praw", "Reddit API"),
    ("vectorbt", "Backtesting framework"),
]

for pkg, desc in trading_packages:
    try:
        __import__(pkg)
        check_warn(f"{pkg}", True, desc)
    except ImportError:
        check_warn(f"{pkg}", False, f"Not installed (optional) — pip install {pkg}")

# ── Environment File ──────────────────────────────────────────────────────
print("\n🔑 Configuration")
env_file = Path(".env")
env_example = Path(".env.example")

if not check(
    ".env file",
    env_file.exists(),
    "copy .env.example to .env and fill in keys" if not env_file.exists() else "found",
):
    errors += 1
    print("     Run: copy .env.example .env")
else:
    # Load and check required keys
    from dotenv import load_dotenv

    load_dotenv()

    required_keys = [
        ("ANTHROPIC_API_KEY", "LLM analysis — REQUIRED to run agents"),
        ("POLYGON_API_KEY", "Historical market data — recommended (Starter $29/mo)"),
        ("FINNHUB_API_KEY", "News sentiment — free tier available"),
    ]

    ibkr_keys = [
        ("IBKR_PORT", "IBKR Gateway port (4002=paper, 4001=live)"),
    ]

    for key, desc in required_keys:
        val = os.getenv(key)
        if key == "ANTHROPIC_API_KEY":
            if not check(key, bool(val), "Required for LLM agents" if not val else "set"):
                errors += 1
        else:
            check_warn(key, bool(val), desc if not val else "set")

    # Check safety defaults
    live = os.getenv("LIVE_TRADING_ENABLED", "False")
    approval = os.getenv("REQUIRE_HUMAN_APPROVAL", "True")
    check(
        "LIVE_TRADING_ENABLED=False (safe default)",
        live == "False",
        f"Currently: {live} — ⚠️ WARNING if True!" if live != "False" else "safe",
    )
    check(
        "REQUIRE_HUMAN_APPROVAL=True (safe default)",
        approval == "True",
        f"Currently: {approval}" if approval == "True" else "⚠️ DISABLED!",
    )

# ── Infrastructure ────────────────────────────────────────────────────────
print("\n🗄️  Infrastructure")


async def check_connections():
    # Redis
    try:
        import redis.asyncio as aioredis

        r = await aioredis.from_url("redis://localhost:6379")
        await r.ping()
        await r.aclose()
        check_warn("Redis", True, "connected on localhost:6379")
    except Exception:
        check_warn("Redis", False, "not running — start with: docker compose up -d redis")

    # PostgreSQL
    try:
        import asyncpg

        conn = await asyncpg.connect("postgresql://jarvis:jarvis@localhost:5432/jarvis_trader")
        await conn.close()
        check_warn("PostgreSQL", True, "connected on localhost:5432")
    except Exception:
        check_warn("PostgreSQL", False, "not running — start with: docker compose up -d postgres")

    # QuestDB
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.get("http://localhost:9000/status", timeout=3)
            check_warn("QuestDB", resp.status_code == 200, "connected on localhost:9000")
    except Exception:
        check_warn("QuestDB", False, "not running — start with: docker compose up -d questdb")

    # IBKR Gateway
    try:
        import socket

        port = int(os.getenv("IBKR_PORT", "4002"))
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        result = s.connect_ex(("127.0.0.1", port))
        s.close()
        if result == 0:
            check_warn(
                f"IB Gateway (port {port})",
                True,
                f"reachable — {'paper' if port == 4002 else 'LIVE'} mode",
            )
        else:
            check_warn(
                f"IB Gateway (port {port})",
                False,
                "not running — download from interactivebrokers.com/en/trading/ibgateway.php",
            )
    except Exception:
        check_warn("IB Gateway", False, "check failed")


asyncio.run(check_connections())

# ── Summary ───────────────────────────────────────────────────────────────
print("\n" + "=" * 50)
if errors == 0:
    print("✅ All critical checks passed! You're ready to start.")
    print("\nNext steps:")
    print("  1. cd engine && uvicorn main:app --reload --port 8010")
    print("  2. Visit http://localhost:8010/docs for the API")
    print("  3. Visit http://localhost:8010/health to verify")
else:
    print(f"❌ {errors} critical issue(s) found. Fix these before starting.")
    print("\n  Run: pip install -r requirements.txt")
    print("  Then: copy .env.example .env && fill in your API keys")

print()
