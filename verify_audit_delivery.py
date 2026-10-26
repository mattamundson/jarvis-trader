#!/usr/bin/env python3
"""Verify all audit backlog items are delivered.

Run from jarvis-trader/ root.
"""
import json, os, subprocess, sys

def gh(*args):
    r = subprocess.run(["gh"] + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        return f"ERR({r.returncode}): {r.stderr.strip()[:200]}"
    return r.stdout.strip()

def gh_json(*args):
    """Run gh with --json and return parsed JSON or error string."""
    r = subprocess.run(["gh"] + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        return {"error": f"ERR({r.returncode}): {r.stderr.strip()[:200]}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"raw": r.stdout.strip()[:200]}

def cmd(*args):
    r = subprocess.run(list(args), capture_output=True, text=True)
    return r.stdout.strip()

print("=" * 70)
print("JARVIS TRADER consolidation — delivery verification")
print("=" * 70)

# 1. PRs merged
print("\n--- 1. Consolidation PRs (must all be MERGED) ---")
expected = {
    816: "jarvis-trader Wave 1 imports",
    6: "master-jarvis REPO_AUTHORITY.md",
    949: "critique item 1",
    950: "critique item 3",
    951: "wave3 mining distillations",
    953: "critique item 2",
    954: "critique item 4",
    955: "critique item 5",
}
all_merged = True
for n, desc in expected.items():
    repo = "mattamundson/master-jarvis" if n == 6 else "mattamundson/jarvis-trader"
    j = gh_json("pr", "view", str(n), "--json", "state,mergedAt", "--repo", repo)
    if isinstance(j, dict) and "error" in j:
        state, merged_at = "ERR", j["error"]
    else:
        state = j.get("state", "UNKNOWN")
        merged_at = j.get("mergedAt", "UNKNOWN")
    status = "OK" if state == "MERGED" else "FAIL"
    if state != "MERGED":
        all_merged = False
    print(f"  PR #{n:3} {desc:40} [{status}] state={state} mergedAt={merged_at}")

# 2. Source repos archived
print("\n--- 2. Source repos (must be archived) ---")
source_repos = [
    "jarvis-positions-check",
    "jarvis-quant",
    "autotrade",
    "Polymarket-Trading-Bot",
    "prediction-market-backtesting",
    "polybot",
]
for r in source_repos:
    archived = gh("api", "repos/mattamundson/" + r, "--jq", ".archived")
    print(f"  {r:35} archived={archived}")

# 3. Reference forks topic-tagged
print("\n--- 3. Reference forks (must carry reference/trading-research/vendor-fork) ---")
ref_forks = [
    "claude-trading-skills",
    "awesome-quant",
    "TradingAgents",
    "Vibe-Trading",
    "tradingview-mcp",
    "sunday-quant-scientist",
    "fredapi",
    "lightweight-charts",
    "LLM-Trading-Lab",
    "atlas-gic",
]
for r in ref_forks:
    topics = gh("api", "repos/mattamundson/" + r, "--jq", ".topics // []")
    print(f"  {r:35} topics={topics}")

# 4. Strategy registry entries
print("\n--- 4. Strategy registry entries ---")
entries_dir = "docs/research/strategy-registry/entries"
for fn in sorted(os.listdir(entries_dir)):
    if not fn.endswith(".json"):
        continue
    d = json.load(open(os.path.join(entries_dir, fn)))
    print(f"  {fn:45} state={d['promotion_state']:15} gate={d.get('gate_verdict',{}).get('verdict','NO_GATE')}")

# 5. Mining artifacts
print("\n--- 5. Mining artifacts (must exist) ---")
artifacts = [
    "docs/research/backtest-critique-checklist.md",
    "docs/research/chart-review-runbook.md",
    "docs/research/macro-regime-context-spec.md",
    "docs/research/tradingagents-schema-note.md",
    "docs/research/sentinel-observability-runbook.md",
    "docs/research/claude-trading-skills-intake-gate.md",
    "docs/research/awesome-quant-tool-intake-gate.md",
    "docs/research/fredapi-transport-resilience-checklist.md",
    "docs/research/lightweight-charts-dashboard-integration-contract.md",
    "docs/research/tradingview-mcp-chart-control-checklist.md",
    "docs/research/sunday-quant-scientist-regime-feature-checklist.md",
    "docs/research/reference-repo-mining/consolidation-disposition.md",
]
for a in artifacts:
    exists = os.path.exists(a)
    lines = cmd("wc", "-l", a).split()[0] if exists else "N/A"
    status = "OK" if exists else "MISSING"
    print(f"  {a:60} [{status}] {lines} lines")

# 6. Registry schema validation
print("\n--- 6. Registry schema validation ---")
try:
    import jsonschema
    schema = json.load(open("docs/research/strategy-registry/schema.json"))
    all_ok = True
    for fn in sorted(os.listdir(entries_dir)):
        if not fn.endswith(".json"):
            continue
        entry = json.load(open(os.path.join(entries_dir, fn)))
        try:
            jsonschema.validate(entry, schema)
        except jsonschema.ValidationError as e:
            print(f"  FAIL {fn}: {e.message}")
            all_ok = False
    if all_ok:
        print("  ALL ENTRIES VALID")
except ImportError:
    print("  jsonschema not available — skipping")

print("\n" + "=" * 70)
print("VERIFICATION COMPLETE")
print("=" * 70)
