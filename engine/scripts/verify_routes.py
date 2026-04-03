#!/usr/bin/env python3
"""
Standalone Route Verification Script

Prints all registered API routes organized by HTTP method and prefix.
Can be run directly without pytest: python scripts/verify_routes.py

Output:
  - All routes grouped by HTTP method
  - Route count summary
  - Critical route validation
  - Route prefix analysis
"""

import os
import sys
from collections import defaultdict
from pathlib import Path


def load_env():
    """Load .env file to populate os.environ for app startup"""
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    os.environ[key] = value
        print(f"Loaded .env from {env_path}")
    else:
        print(f"Warning: .env not found at {env_path}")


def import_app():
    """Import FastAPI app from main.py"""
    # Add engine directory to path
    engine_dir = Path(__file__).parent.parent
    sys.path.insert(0, str(engine_dir))

    try:
        from main import app

        return app
    except ImportError as e:
        print(f"Error importing app: {e}")
        sys.exit(1)


def analyze_routes(app):
    """Extract and analyze all routes from the FastAPI app"""
    routes = []
    route_details = []

    for route in app.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            for method in route.methods:
                routes.append((route.path, method))
                route_details.append(
                    {
                        "path": route.path,
                        "method": method,
                        "name": getattr(route, "name", "unknown"),
                        "tags": getattr(route, "tags", []),
                    }
                )

    return routes, route_details


def print_routes_by_method(routes):
    """Print routes organized by HTTP method"""
    routes_by_method = defaultdict(list)

    for path, method in routes:
        routes_by_method[method].append(path)

    print("\n" + "=" * 80)
    print("ROUTES ORGANIZED BY HTTP METHOD")
    print("=" * 80)

    for method in sorted(routes_by_method.keys()):
        paths = sorted(set(routes_by_method[method]))
        print(f"\n{method:8s} ({len(paths):3d} routes):")
        print("-" * 80)

        for path in paths:
            print(f"  {path}")

    return routes_by_method


def print_routes_by_prefix(routes):
    """Print routes organized by path prefix"""
    routes_by_prefix = defaultdict(list)

    for path, method in routes:
        # Extract prefix (first part of path)
        parts = path.strip("/").split("/")
        prefix = "/" + parts[0] if parts and parts[0] else "/"

        routes_by_prefix[prefix].append((path, method))

    print("\n" + "=" * 80)
    print("ROUTES ORGANIZED BY PREFIX")
    print("=" * 80)

    for prefix in sorted(routes_by_prefix.keys()):
        routes_list = sorted(set(routes_by_prefix[prefix]))
        print(f"\n{prefix:20s} ({len(routes_list):3d} routes):")
        print("-" * 80)

        for path, method in routes_list:
            print(f"  {method:6s} {path}")


def check_critical_routes(routes):
    """Validate that critical routes exist"""
    found_routes = {(method, path) for path, method in routes}

    critical_routes = [
        ("GET", "/health"),
        ("POST", "/pipeline/run"),
        ("GET", "/portfolio/summary"),
        ("GET", "/safety/status"),
    ]

    print("\n" + "=" * 80)
    print("CRITICAL ROUTES CHECK")
    print("=" * 80 + "\n")

    found_count = 0
    for method, path in critical_routes:
        status = "✅" if (method, path) in found_routes else "❌"
        print(f"{status} {method:6s} {path}")
        if (method, path) in found_routes:
            found_count += 1

    print(f"\nCritical routes: {found_count}/{len(critical_routes)} found")

    return found_count == len(critical_routes)


def print_summary(routes, route_details):
    """Print summary statistics"""
    routes_by_method = defaultdict(list)
    for path, method in routes:
        routes_by_method[method].append(path)

    unique_paths = len({path for path, _ in routes})
    total_routes = len(routes)

    print("\n" + "=" * 80)
    print("SUMMARY STATISTICS")
    print("=" * 80)
    print(f"\nTotal route registrations:  {total_routes}")
    print(f"Unique paths:               {unique_paths}")
    print(f"HTTP methods used:          {len(routes_by_method)}")
    print(f"Methods:                    {', '.join(sorted(routes_by_method.keys()))}")

    print("\nRoutes by method:")
    for method in sorted(routes_by_method.keys()):
        print(f"  {method:6s}: {len(routes_by_method[method]):3d}")

    # Check for routes that might be duplicated
    path_counts = defaultdict(int)
    for path, _ in routes:
        path_counts[path] += 1

    duplicates = {p: c for p, c in path_counts.items() if c > 1}
    if duplicates:
        print("\nWarning: Duplicate path registrations found:")
        for path, count in sorted(duplicates.items()):
            print(f"  {path}: {count} times")
    else:
        print("\nNo duplicate paths found ✅")


def main():
    """Main entry point"""
    print("JARVIS TRADER — Route Verification Script")
    print("=" * 80)

    load_env()
    print("\nImporting FastAPI app...")

    app = import_app()
    print(f"App imported successfully: {app.title}")

    print("\nAnalyzing routes...")
    routes, route_details = analyze_routes(app)

    # Print organized output
    print_routes_by_method(routes)
    print_routes_by_prefix(routes)

    # Validate critical routes
    critical_ok = check_critical_routes(routes)

    # Print summary
    print_summary(routes, route_details)

    # Exit with proper code
    print("\n" + "=" * 80)
    if critical_ok and len(routes) >= 75:
        print("✅ Route verification PASSED")
        print("=" * 80)
        return 0
    else:
        print("❌ Route verification FAILED")
        print("=" * 80)
        return 1


if __name__ == "__main__":
    sys.exit(main())
