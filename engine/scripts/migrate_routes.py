"""
One-shot route migration: move remaining @app.* inline routes from main.py
into the correct router files, then delete them from main.py.
"""
import re
from pathlib import Path

ENGINE = Path(__file__).parent.parent

def read_lines(path):
    with open(path) as f:
        return f.readlines()

def write_lines(path, lines):
    with open(path, 'w') as f:
        f.writelines(lines)

# ── Step 1: Parse all route ranges from main.py ─────────────────────────────
main_lines = read_lines(ENGINE / 'main.py')

route_starts = []
for i, line in enumerate(main_lines):
    if re.match(r'^@app\.(get|post|put|delete|patch|websocket)\(', line):
        route_starts.append(i)

routes = []
for idx, start in enumerate(route_starts):
    end = route_starts[idx+1] if idx+1 < len(route_starts) else len(main_lines)
    path_match = re.search(r'@app\.\w+\(["\']([^"\']+)', main_lines[start])
    path = path_match.group(1) if path_match else '?'
    method_match = re.match(r'@app\.(\w+)\(', main_lines[start])
    method = method_match.group(1) if method_match else '?'
    body = main_lines[start:end]
    routes.append({'start': start, 'end': end, 'path': path,
                   'method': method, 'body': body})

# ── Step 2: Define routing map ──────────────────────────────────────────────
# Format: (method, path_prefix_or_exact) → router filename
def route_destination(method, path):
    m = method.lower()
    if path.startswith('/safety') or path.startswith('/circuit'):
        return 'safety_router.py'
    if path.startswith('/settings') or path.startswith('/strategy/params'):
        return 'settings_router.py'
    if path.startswith('/strategy-lab'):
        return 'strategy_lab_router.py'
    if path.startswith('/analyze') or path.startswith('/llm'):
        return 'analysis_router.py'
    if path.startswith('/sentiment'):
        return 'sentiment_router.py'
    if path.startswith('/portfolio') or path.startswith('/paper/pending'):
        return 'portfolio_router.py'
    if path.startswith('/analytics'):
        return 'analytics_router.py'
    if path.startswith('/watchlist'):
        return 'watchlist_router.py'
    if path.startswith('/decisions'):
        return 'decisions_router.py'
    if path.startswith('/prices'):
        return 'market_router.py'
    if path.startswith('/market'):
        return 'market_router.py'
    if path.startswith('/pipeline') or path == '/signals/stats':
        return 'pipeline_router.py'
    if path.startswith('/scheduler') or path.startswith('/signals'):
        return 'scheduler_router.py'
    if path.startswith('/notifications'):
        return 'notifications_router.py'
    if path.startswith('/thinkscript'):
        return 'thinkscript_router.py'
    if path.startswith('/macro'):
        return 'macro_router.py'
    if path.startswith('/backtest') or path.startswith('/paper/mgc') or path.startswith('/paper/'):
        return 'backtest_router.py'
    if path.startswith('/ws'):
        return 'websocket_router.py'
    if path.startswith('/reports'):
        return 'reports_router.py'
    if path.startswith('/alerts'):
        return 'alerts_router.py'
    if path.startswith('/position-sizing'):
        return 'market_router.py'
    return None

# ── Step 3: Group routes by destination ────────────────────────────────────
already_in_router = {
    # Confirmed added by subagent — just need deletion from main.py
    ("GET", "/safety/config"),
    ("GET", "/safety/loss-tracker"),
    ("POST", "/portfolio/paper/trade/manual"),
    ("GET", "/portfolio/history/daily-pnl"),
    ("GET", "/portfolio/history/decisions"),
    ("GET", "/portfolio/stats/summary"),
    ("GET", "/portfolio/stats/drawdown"),
    ("GET", "/portfolio/stats/streaks"),
    ("GET", "/portfolio/stats/session-today"),
    ("GET", "/portfolio/stats/weekly"),
    ("GET", "/portfolio/stats/commissions"),
    ("POST", "/portfolio/import/trades"),
    ("GET", "/portfolio/history/trades"),
    ("POST", "/pipeline/run"),
    ("POST", "/pipeline/run/sdk"),
    ("GET", "/pipeline/status"),
    ("GET", "/pipeline/history"),
    ("POST", "/scheduler/scan-now"),
    ("GET", "/reports/performance"),
    ("POST", "/backtest/monte-carlo"),
    ("POST", "/backtest/monte-carlo/chart"),
    ("GET", "/paper/mgc-performance"),
    ("GET", "/position-sizing/calculate"),
    ("GET", "/market/earnings"),
    ("GET", "/analytics/mtf"),
}

dest_map = {}  # router_file → list of route body lines to append
delete_ranges = []  # (start, end) to delete from main.py

for r in routes:
    key = (r['method'].upper(), r['path'])
    if key in already_in_router:
        # Just delete from main.py
        delete_ranges.append((r['start'], r['end']))
        continue
    dest = route_destination(r['method'], r['path'])
    if dest is None:
        print(f"  UNROUTED: {r['method'].upper()} {r['path']}")
        continue
    # Convert @app.METHOD to @router.METHOD
    converted = []
    for line in r['body']:
        converted.append(re.sub(r'^@app\.', '@router.', line))
    if dest not in dest_map:
        dest_map[dest] = []
    dest_map[dest].extend(['\n'] + converted)
    delete_ranges.append((r['start'], r['end']))

# ── Step 4: Append to router files ─────────────────────────────────────────
routers_dir = ENGINE / 'routers'
created = []

for router_file, new_routes in dest_map.items():
    router_path = routers_dir / router_file
    if router_path.exists():
        with open(router_path, 'a') as f:
            f.writelines(new_routes)
        print(f"  APPENDED {len(new_routes)} lines to {router_file}")
    else:
        # Create minimal router stub
        prefix = router_file.replace('_router.py', '').replace('_', '/')
        stub = f'''"""Auto-generated router — {router_file}"""
from fastapi import APIRouter, Depends, HTTPException
from .deps import *

router = APIRouter(prefix="/{prefix}", tags=["{prefix}"])
'''
        with open(router_path, 'w') as f:
            f.write(stub)
            f.writelines(new_routes)
        print(f"  CREATED {router_file} with {len(new_routes)} lines")
        created.append(router_file)

# ── Step 5: Delete ranges from main.py (reverse order) ─────────────────────
delete_ranges.sort(key=lambda x: x[0], reverse=True)
new_main = list(main_lines)

for start, end in delete_ranges:
    # Replace with a single comment
    new_main[start:end] = [f'    # Route moved to router — see chore/b4-route-migration\n']

write_lines(ENGINE / 'main.py', new_main)

# ── Step 6: Report ──────────────────────────────────────────────────────────
import subprocess
result = subprocess.run(['grep', '-c', '@app.', str(ENGINE / 'main.py')], 
                       capture_output=True, text=True)
remaining = int(result.stdout.strip())
print(f"\n@app.* remaining in main.py: {remaining}")
print(f"Routes deleted from main.py: {len(delete_ranges)}")
print(f"New router files created: {created}")
