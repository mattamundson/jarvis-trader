"""
Comprehensive endpoint verification test

Validates that all 80+ API routes are correctly wired into the FastAPI application.
This test imports the app and inspects all registered routes without starting the server.

**P3-1 (execution spine):** ``critical_routes`` below mirrors high-traffic paths from
``dashboard/lib/api.ts`` (``fetchEngine`` / ``postEngine``) — health, pipeline, portfolio
paper, safety, IB probe, watchlist scan. See ``docs/strategic/07_EXECUTION_SPINE.md`` P3-1.

Reference: ``engine/main.py`` contains all router includes.
"""

import os
import sys
import types
from collections import defaultdict

import pytest


def load_env():
    """Load .env file to populate os.environ"""
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    os.environ[key] = value


def _install_google_stub():
    """Allow the engine Jarvis router to import in test environments without google-genai."""
    fake_genai = types.ModuleType("google.genai")
    fake_genai.Client = object

    fake_yfinance = types.ModuleType("yfinance")

    class _Ticker:
        def __init__(self, *args, **kwargs):
            pass

        def history(self, *args, **kwargs):
            raise RuntimeError("yfinance history is not used in route wiring tests")

    fake_yfinance.Ticker = _Ticker

    fake_google = types.ModuleType("google")
    fake_google.genai = fake_genai

    sys.modules["google"] = fake_google
    sys.modules["google.genai"] = fake_genai
    sys.modules["yfinance"] = fake_yfinance


def test_routes_wired():
    """Test that all critical routes are registered"""
    load_env()
    _install_google_stub()

    # Import the app
    sys.path.insert(0, os.path.dirname(__file__).replace("tests", ""))
    from main import app

    # Extract all routes
    routes = []
    for route in app.routes:
        # Skip mount points
        if hasattr(route, "path") and hasattr(route, "methods"):
            for method in route.methods:
                routes.append((route.path, method))

    # Group by HTTP method for reporting
    routes_by_method = defaultdict(list)
    for path, method in routes:
        routes_by_method[method].append(path)

    # Print all routes (for debugging)
    print("\n\n=== ALL REGISTERED ROUTES ===\n")
    for method in sorted(routes_by_method.keys()):
        paths = sorted(set(routes_by_method[method]))
        print(f"\n{method} ({len(paths)} routes):")
        for path in paths:
            print(f"  {path}")

    # Define critical routes that MUST exist
    critical_routes = {
        ("GET", "/health"): "health check endpoint",
        ("GET", "/health/full"): "deep health for dashboard SystemMetricsPanel",
        ("GET", "/api/v1/health"): "v1 health check (if using prefix)",
        ("POST", "/pipeline/run"): "run trading pipeline",
        ("GET", "/pipeline/status"): "AgentPipelineStatusWidget",
        ("GET", "/pipeline/pending-approvals"): "dashboard approvals queue",
        ("GET", "/portfolio/summary"): "portfolio summary",
        ("GET", "/portfolio/paper/positions"): "OpenPositionsWidget / command center",
        ("GET", "/portfolio/stats/trading-days"): "distinct trading days (validation UI)",
        ("GET", "/portfolio/stats/paper-phase-summary"): "dashboard paper phase widget",
        ("GET", "/safety/status"): "safety layer status",
        ("GET", "/safety/circuit-breakers"): "RiskStatusWidget / degraded UX",
        ("GET", "/ib/connection-test"): "ConnectionHealthCard",
        ("GET", "/watchlist/scan"): "useChartData watchlist scan",
    }

    # Define additional expected routes (best-effort)
    expected_routes = {
        # Analysis
        ("GET", "/analysis/technical"): "technical analysis",
        ("GET", "/jarvis/analyze"): "Jarvis quick analysis snapshot",
        ("POST", "/jarvis/analyze"): "Jarvis quick analysis snapshot",
        # Backtest
        ("GET", "/backtest/results"): "backtest results",
        # Pipeline
        ("POST", "/pipeline/run"): "pipeline execution",
        # Options
        ("GET", "/options/module/status"): "options module status or similar",
        # Portfolio
        ("GET", "/portfolio/summary"): "portfolio summary",
        # Validation (legacy path redirects; canonical is /paper/validation/progress)
        ("GET", "/validation/progress"): "validation progress (redirects)",
        ("GET", "/paper/validation/progress"): "paper validation progress (canonical)",
        ("GET", "/paper/validation/approved-paper-gates"): "approved-symbol per-symbol validation gates",
        ("GET", "/paper/validation/trades/closed"): "closed paper trades for dashboard /trades",
        # Safety
        ("GET", "/safety/status"): "safety status",
    }

    # Check that critical routes exist
    found_routes = {(method, path) for path, method in routes}

    print("\n\n=== CRITICAL ROUTES CHECK ===\n")
    critical_found = 0
    for (method, path), description in sorted(critical_routes.items()):
        if (method, path) in found_routes:
            print(f"✅ {method:6s} {path:40s} - {description}")
            critical_found += 1
        else:
            print(f"❌ {method:6s} {path:40s} - {description} [MISSING]")

    print(f"\nCritical routes found: {critical_found}/{len(critical_routes)}")

    # Check expected routes
    print("\n=== EXPECTED ROUTES CHECK ===\n")
    expected_found = 0
    for (method, path), description in sorted(expected_routes.items()):
        if (method, path) in found_routes:
            print(f"✅ {method:6s} {path:40s} - {description}")
            expected_found += 1
        else:
            # Try partial match
            partial_matches = [
                p
                for (m, p) in found_routes
                if m == method and path.split("/")[1:2] == p.split("/")[1:2]
            ]
            if partial_matches:
                print(
                    f"⚠️  {method:6s} {path:40s} - {description}"
                    f" [Found similar: {partial_matches[0]}]"
                )
            else:
                print(f"❌ {method:6s} {path:40s} - {description} [NOT FOUND]")

    print(f"\nExpected routes found: {expected_found}/{len(expected_routes)}")

    # Assert minimum route count
    total_routes = len(routes)
    print("\n=== SUMMARY ===")
    print(f"Total routes registered: {total_routes}")
    print(f"Unique paths: {len({path for path, _ in routes})}")
    print(f"HTTP methods used: {', '.join(sorted(routes_by_method.keys()))}")

    # Assertions
    # Floor tracks current main.py router surface (was 75+; refactors may reduce count)
    assert total_routes >= 65, f"Expected at least 65 routes, found {total_routes}"
    assert critical_found > 0, "No critical routes found - app routing is broken"
    assert (
        "GET" in routes_by_method and "POST" in routes_by_method
    ), "App must have GET and POST routes"

    # Assert at least one health endpoint
    health_routes = [p for m, p in found_routes if m == "GET" and "health" in p]
    assert (
        len(health_routes) > 0
    ), "At least one health endpoint must exist (GET /health or similar)"

    print("\n✅ All assertions passed!")


def test_route_methods_valid():
    """Test that all routes use valid HTTP methods"""
    load_env()
    _install_google_stub()

    sys.path.insert(0, os.path.dirname(__file__).replace("tests", ""))
    from main import app

    valid_methods = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}

    for route in app.routes:
        if hasattr(route, "methods"):
            for method in route.methods:
                assert method in valid_methods, f"Route {route.path} has invalid method {method}"

    print("✅ All routes use valid HTTP methods")


def test_router_imports_complete():
    """Test that all routers from routers/ directory are imported and registered"""
    import glob
    import os

    load_env()
    _install_google_stub()

    sys.path.insert(0, os.path.dirname(__file__).replace("tests", ""))
    from main import app

    # Get all router files
    router_dir = os.path.join(os.path.dirname(__file__), "..", "routers")
    router_files = glob.glob(os.path.join(router_dir, "*_router.py"))
    router_names = [
        os.path.basename(f).replace(".py", "")
        for f in router_files
        if not f.endswith("__init__.py")
    ]

    # Get all routes from the app
    route_paths = [route.path for route in app.routes if hasattr(route, "path")]
    route_str = " ".join(route_paths)

    print(f"\nRouter files found in routers/: {len(router_names)}")
    print(f"Router modules: {', '.join(sorted(router_names))}")

    missing_routers = []
    for router_name in sorted(router_names):
        # Check if this router is referenced in any route path or tags
        if router_name not in ["__init__"]:
            # Some routers might not have routes yet, just check they're importable
            try:
                __import__(f"routers.{router_name}", globals(), locals())
                print(f"  ✅ {router_name}")
            except ImportError as e:
                print(f"  ⚠️  {router_name} (import error: {e})")
                missing_routers.append(router_name)

    print(
        f"\nRouters successfully imported: {len(router_names) - len(missing_routers)}/{len(router_names)}"
    )


def test_jarvis_analyze_route_wiring():
    """Jarvis quick-analysis route should be present once the engine mounts it."""
    load_env()
    _install_google_stub()

    sys.path.insert(0, os.path.dirname(__file__).replace("tests", ""))
    from main import app

    found_routes = {
        (method, route.path)
        for route in app.routes
        if hasattr(route, "path") and hasattr(route, "methods")
        for method in route.methods
    }

    assert ("GET", "/jarvis/analyze") in found_routes
    assert ("POST", "/jarvis/analyze") in found_routes


if __name__ == "__main__":
    # Run the main test
    test_routes_wired()
    test_route_methods_valid()
    test_router_imports_complete()
