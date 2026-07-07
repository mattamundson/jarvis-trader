#!/usr/bin/env python3
"""Pre-commit validation for JARVIS TRADER. Usage: python scripts/pre_commit_check.py [--skip-dashboard] [--skip-tests]"""

import subprocess, sys, os, re
from pathlib import Path

COLORS = {'green': '\033[92m', 'red': '\033[91m', 'yellow': '\033[93m', 'reset': '\033[0m'}

def colored(text, color):
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"

def run_check(cmd, cwd=None, skip=False):
    if skip: return None, "Skipped"
    try:
        result = subprocess.run(cmd, shell=isinstance(cmd, str), cwd=cwd, capture_output=True, text=True, timeout=120)
        return result.returncode == 0, result.stdout + result.stderr if result.returncode else result.stdout
    except subprocess.TimeoutExpired: return False, "Timeout"
    except Exception as e: return False, str(e)

def check_env_files():
    try:
        result = subprocess.run("git diff --cached --name-only", shell=True, capture_output=True, text=True)
        env_files = [f for f in result.stdout.strip().split('\n') if '.env' in f and f]
        return len(env_files) == 0, env_files
    except: return False, ["Error checking git"]

def check_secrets(cwd):
    patterns = [r'sk-ant-api[0-9]*-[A-Za-z0-9_\-]*', r'AKIA[0-9A-Z]{16}', r'aws_secret_access_key\s*[=:]\s*[A-Za-z0-9/+=]{40,}', r'password\s*[=:]\s*["\'][^\s]+["\']', r'secret\s*[=:]\s*["\'][^\s]+["\']', r'client_secret.*\.json']
    try:
        result = subprocess.run("git diff --cached --name-only", shell=True, capture_output=True, text=True)
        found = []
        for f in [x.strip() for x in result.stdout.split('\n') if x.strip()]:
            if os.path.exists(f):
                try:
                    with open(f, 'r', errors='ignore') as file:
                        if any(re.search(p, file.read(), re.IGNORECASE) for p in patterns):
                            found.append(f)
                except: pass
        return len(found) == 0, found
    except: return False, ["Error checking secrets"]

def main():
    skip_dashboard, skip_tests = '--skip-dashboard' in sys.argv, '--skip-tests' in sys.argv
    root = Path(__file__).parent.parent
    os.chdir(root)

    print(colored("\n=== JARVIS TRADER Pre-Commit Validation ===\n", 'yellow'))

    results = []
    passed, files = check_env_files()
    results.append((passed, ".env file check" if passed else f".env: {', '.join(files[:2])}"))

    passed, files = check_secrets(root)
    results.append((passed, "Secret detection" if passed else f"Secrets in: {', '.join(files[:2])}"))

    passed, _ = run_check("ruff check engine", cwd=root)
    if passed is not None: results.append((passed, "Ruff lint" if passed else "Ruff failed"))

    passed, _ = run_check([sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"], cwd=str(root / "engine"), skip=skip_tests)
    if passed is not None: results.append((passed, "Engine tests" if passed else "Tests failed"))

    passed, _ = run_check([sys.executable, "-m", "pytest", "tests/test_safety_layer.py", "-v"], cwd=str(root / "engine"), skip=skip_tests)
    if passed is not None: results.append((passed, "Safety layer" if passed else "Safety failed"))

    passed, _ = run_check("pnpm run build", cwd=str(root / "dashboard"), skip=skip_dashboard)
    if passed is not None: results.append((passed, "Dashboard build" if passed else "Build failed"))

    print("\n" + colored("=== Summary ===\n", 'yellow'))
    for p, name in results:
        sym = colored('+', 'green') if p else (colored('~', 'yellow') if p is None else colored('X', 'red'))
        print(f"  {sym} {name}")

    passed_count = sum(1 for p, _ in results if p is True)
    print(f"\n{passed_count}/{len(results)} checks passed")
    print(colored("\nReady to commit." if passed_count == len(results) else f"\nFix {len(results) - passed_count} issue(s).", 'green' if passed_count == len(results) else 'red'))
    return 0 if passed_count == len(results) else 1

if __name__ == "__main__": sys.exit(main())
