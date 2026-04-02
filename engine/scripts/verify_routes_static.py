#!/usr/bin/env python3
"""
Static Route Verification Script

Parses router files directly without importing the full app.
This allows verification even when there are syntax errors in unrelated modules.

Usage: python scripts/verify_routes_static.py
"""

import re
from collections import defaultdict
from pathlib import Path


def parse_router_file(filepath):
    """Extract all routes from a single router file"""
    routes = []
    try:
        with open(filepath, "r") as f:
            content = f.read()

        # Find router prefix
        prefix_match = re.search(r'router\s*=\s*APIRouter\(prefix="([^"]*)"', content)
        prefix = prefix_match.group(1) if prefix_match else ""

        # Find all @router.{method}(...) decorators
        pattern = r'@router\.(get|post|put|delete|patch|head|options)\("([^"]*)"'
        for method, path in re.findall(pattern, content, re.IGNORECASE):
            method = method.upper()
            full_path = prefix + path if path else prefix
            if not full_path:
                full_path = "/"
            routes.append((full_path, method))

        return routes
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")
        return []


def find_router_files():
    """Find all router files in the routers directory"""
    routers_dir = Path(__file__).parent.parent / "routers"
    router_files = sorted(routers_dir.glob("*_router.py"))
    return [f for f in router_files if f.name != "__init__.py"]


def parse_main_includes():
    """Extract which routers are actually included in main.py with their prefixes"""
    main_py = Path(__file__).parent.parent / "main.py"
    included = {}  # router_name -> extra_prefix
    try:
        with open(main_py, "r") as f:
            content = f.read()
            # Find all include_router calls with optional prefix
            # Handles: app.include_router(name) or app.include_router(name, prefix="/path")
            pattern = r'app\.include_router\((\w+)(?:,\s*prefix="([^"]*)"\s*)?'
            for match in re.finditer(pattern, content):
                router_name = match.group(1)
                extra_prefix = match.group(2) if match.group(2) else ""
                included[router_name] = extra_prefix
        return included
    except Exception as e:
        print(f"Error parsing main.py: {e}")
        return {}


def get_router_name_from_file(filepath):
    """Get the router module name from filepath"""
    return filepath.stem


def main():
    print("JARVIS TRADER — Static Route Verification")
    print("=" * 80)

    # Find all router files
    router_files = find_router_files()
    print(f"\nFound {len(router_files)} router files")

    # Parse all routes from router files
    all_routes = []
    routes_by_router = {}

    for router_file in router_files:
        routes = parse_router_file(router_file)
        router_name = get_router_name_from_file(router_file)
        routes_by_router[router_name] = routes

    # Check which routers are included in main.py and apply their prefixes
    main_includes = parse_main_includes()
    included_routers = set(main_includes.keys())

    # Build final route list with prefixes from main.py includes
    for router_name, extra_prefix in main_includes.items():
        if router_name in routes_by_router:
            for path, method in routes_by_router[router_name]:
                # If router file has prefix and main.py adds another prefix, combine them
                # Usually one or the other, not both
                final_path = extra_prefix + path if extra_prefix else path
                all_routes.append((final_path, method))

    print(f"Found {len(main_includes)} router includes in main.py")

    # Organize by HTTP method
    routes_by_method = defaultdict(list)
    for path, method in all_routes:
        routes_by_method[method].append(path)

    # Print results
    print("\n" + "=" * 80)
    print("ALL ROUTES BY HTTP METHOD")
    print("=" * 80)

    for method in sorted(routes_by_method.keys()):
        paths = sorted(set(routes_by_method[method]))
        print(f"\n{method:8s} ({len(paths):3d} routes):")
        print("-" * 80)
        for path in paths:
            print(f"  {path}")

    # Print by prefix
    routes_by_prefix = defaultdict(list)
    for path, method in all_routes:
        parts = path.strip("/").split("/")
        prefix = "/" + parts[0] if parts and parts[0] else "/"
        routes_by_prefix[prefix].append((path, method))

    print("\n" + "=" * 80)
    print("ROUTES BY PREFIX")
    print("=" * 80)

    for prefix in sorted(routes_by_prefix.keys()):
        routes_list = sorted(set(routes_by_prefix[prefix]))
        print(f"\n{prefix:20s} ({len(routes_list):3d} routes):")
        print("-" * 80)
        for path, method in routes_list:
            print(f"  {method:6s} {path}")

    # Check critical routes
    critical_routes = [
        ("/health", "GET"),
        ("/portfolio/summary", "GET"),
        ("/safety/loss-tracker/status", "GET"),
    ]

    print("\n" + "=" * 80)
    print("CRITICAL ROUTES CHECK")
    print("=" * 80 + "\n")

    found_routes_set = set(all_routes)
    critical_found = 0

    for path, method in critical_routes:
        if (path, method) in found_routes_set:
            print(f"✅ {method:6s} {path}")
            critical_found += 1
        else:
            print(f"❌ {method:6s} {path}")

    print(f"\nCritical routes: {critical_found}/{len(critical_routes)} found")

    # Summary
    unique_paths = len({path for path, _ in all_routes})
    total_routes = len(all_routes)

    print("\n" + "=" * 80)
    print("SUMMARY STATISTICS")
    print("=" * 80)
    print(f"\nRouter files found:         {len(router_files)}")
    print(f"Routers included in main:   {len(main_includes)}")
    print(f"Total route registrations:  {total_routes}")
    print(f"Unique paths:               {unique_paths}")
    print(f"HTTP methods used:          {len(routes_by_method)}")
    print(f"Methods:                    {', '.join(sorted(routes_by_method.keys()))}")

    print("\nRoutes by method:")
    for method in sorted(routes_by_method.keys()):
        print(f"  {method:6s}: {len(set(routes_by_method[method])):3d}")

    # Check for routers not included
    routers_in_files = set(routes_by_router.keys())
    missing_includes = routers_in_files - included_routers

    if missing_includes:
        print("\n⚠️  Routers found but NOT included in main.py:")
        for router in sorted(missing_includes):
            count = len(routes_by_router[router])
            print(f"  - {router:30s} ({count:2d} routes)")

    # Assertions
    print("\n" + "=" * 80)
    if total_routes >= 75:
        print(f"✅ Route count OK: {total_routes} >= 75")
    else:
        print(f"⚠️  Route count LOW: {total_routes} < 75 (expected 75+)")

    if critical_found == len(critical_routes):
        print("✅ All critical routes present")
    else:
        print(f"⚠️  Missing critical routes: {len(critical_routes) - critical_found}")

    if len(routes_by_method) >= 2:
        print("✅ Multiple HTTP methods detected")
    else:
        print("⚠️  Only 1 HTTP method found")

    print("=" * 80)
    return 0 if total_routes >= 75 and critical_found > 0 else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
