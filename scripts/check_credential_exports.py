#!/usr/bin/env python3
"""Fail when tracked files look like credential EXPORTS, regardless of filename.

Why this exists
---------------
The existing CI guard (`Check for secret-shaped filenames` in .github/workflows/ci.yml)
matches on FILE NAMES only (`*secret*.csv`, `*credential*.csv`, `*.pem`, ...). A credential
export that is merely renamed -- e.g. `Secret-Value.csv` -> `value-export-root.archived` --
therefore passes CI while its plaintext contents stay committed. That is evasion, not
remediation, and it happened (archive/security-filename-quarantine/2026-09-24/).

Filename denylists cannot work: the attacker only has to change the name. This check looks
at CONTENT instead, matching the shape of an export/settings dump -- a credential-shaped
NAME paired with a long opaque VALUE -- which is what a 1Password/Perforce/Perplexity-style
CSV export looks like no matter what it is called.

It reports the key NAME and location only. It never prints the value.

Usage:
    python scripts/check_credential_exports.py            # scan `git ls-files`
    python scripts/check_credential_exports.py --paths f1 f2
    python scripts/check_credential_exports.py --self-test
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# A credential-ish NAME (must end in / contain a known sensitive suffix) followed by a
# separator and a long opaque value. Deliberately requires BOTH halves so that prose,
# tables and prose docs do not trip it.
NAME = r"[A-Z][A-Z0-9_]*?(?:TOKEN|APIKEY|API_KEY|SECRET|PASSWORD|PASS|WEBHOOK|CREDENTIAL|SERVICE_ID|PROJECT_ID|TEAM_ID|PRIVATE_KEY|ACCESS_KEY)[A-Z0-9_]*"
PAIR_RE = re.compile(
    rf'"?\b({NAME})\b"?\s*[,=:]\s*"?([A-Za-z0-9_\-\.\+/=:@\?&]{{20,}})"?',
)

# Documentation, examples, templates and the test tree legitimately contain credential-shaped
# prose and placeholders. They are not credential *exports*; scanning them produces noise that
# gets the gate disabled, which is worse than not having it.
SKIP_PATH_RE = re.compile(
    r"(^|/)(docs|\.github|scripts|node_modules|tests?)/"
    r"|\.md$|\.mdx$|\.example$|\.template$|\.sample$|\.lock$|\.baseline$|\.svg$",
    re.IGNORECASE,
)


def _looks_opaque(value: str) -> bool:
    """True when a value looks like a real token rather than an English placeholder."""
    if len(value) < 24:
        return False
    if value.lower().startswith(("http://", "https://")):
        return True
    has_digit = any(c.isdigit() for c in value)
    has_upper = any(c.isupper() for c in value)
    has_lower = any(c.islower() for c in value)
    # Real tokens are random: they mix case or carry digits. Placeholder prose does not.
    return has_digit or (has_upper and has_lower)

# Placeholder / public-by-design markers. Keep this list to unambiguous English placeholder
# words only: a substring test on short digit runs (e.g. "1234", "xxxx") creates FALSE
# NEGATIVES, because real random tokens frequently contain those runs. An early version of
# this list silently skipped a Discord webhook URL that contained "/1234567890/".
ALLOW_SUBSTRINGS = (
    "change-me",
    "changeme",
    "changethis",
    "placeholder",
    "redacted",
    "your-",
    "process.env",
    "os.environ",
    "example",
    "dummy",
    "notreal",
)

BINARY_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".pdf", ".zip", ".gz", ".tgz",
    ".whl", ".so", ".dll", ".exe", ".bin", ".db", ".sqlite", ".woff", ".woff2", ".ttf",
    ".mp4", ".mov", ".parquet", ".npy", ".pkl", ".jar", ".class",
)
MAX_BYTES = 2_000_000


def _iter_tracked() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], capture_output=True, text=True, check=True
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [Path(p) for p in out.split("\0") if p]


def scan(paths: list[Path]) -> list[tuple[str, int, str]]:
    """Return (path, lineno, key_name) findings. Never returns values."""
    findings: list[tuple[str, int, str]] = []
    for path in paths:
        posix = path.as_posix()
        if path.suffix.lower() in BINARY_SUFFIXES or SKIP_PATH_RE.search(posix):
            continue
        try:
            if not path.is_file() or path.stat().st_size > MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, value in PAIR_RE.findall(line):
                low = value.lower()
                if any(allowed.lower() in low for allowed in ALLOW_SUBSTRINGS):
                    continue
                if not _looks_opaque(value):
                    continue
                findings.append((posix, lineno, name))
    return findings


def _self_test() -> int:
    import tempfile

    cases = [
        # (label, content, should_flag)
        ("csv export row", '"VERCEL_TOKEN","zQ9vXn2mLp4rT7wB1cY6kD3sA8fG5hJ0kL2mN4pQr6"\n', True),
        ("equals form", "RAILWAY_TOKEN=9f2c7b1e4a6d8f0b3c5e7a9d1f2b4c6e8a0d\n", True),
        ("discord webhook", '"DISCORD_WEBHOOK_URL","https://discord.com/api/webhooks/1234567890/AbCdEfGhIjKlMnOpQrStUvWxYz"\n', True),
        ("placeholder", "API_KEY=change-me-please\n", False),
        ("example value", "ENGINE_API_KEY=your-example-key-value-here-ok\n", False),
        ("env reference", "ENGINE_API_KEY=process.env.ENGINE_API_KEY\n", False),
        ("prose", "The API_KEY should be a long random value; never commit it.\n", False),
        ("short value", "API_KEY=abc\n", False),
        ("ordinary var", "SOME_COUNT=125000000000000000000000\n", False),
    ]
    passed = 0
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for i, (label, content, should_flag) in enumerate(cases):
            f = root / f"case_{i}.txt"
            f.write_text(content, encoding="utf-8")
            hits = scan([f])
            got = bool(hits)
            ok = got == should_flag
            passed += int(ok)
            print(f"{'PASS' if ok else 'FAIL'}  {label:18s} flagged={got} expected={should_flag}")
    print(f"\nself-test: {passed}/{len(cases)}")
    return 0 if passed == len(cases) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Detect credential exports by content")
    ap.add_argument("--paths", nargs="*", help="files to scan (default: git ls-files)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return _self_test()

    paths = [Path(p) for p in args.paths] if args.paths else _iter_tracked()
    findings = scan(paths)

    if findings:
        print("ERROR: credential-shaped exports found in TRACKED files.", file=sys.stderr)
        print("A credential-shaped NAME paired with a long opaque VALUE was found.", file=sys.stderr)
        print("Renaming such a file does NOT make it safe -- the bytes must be removed.", file=sys.stderr)
        print("", file=sys.stderr)
        for path, lineno, name in findings:
            print(f"  {path}:{lineno}  key={name}", file=sys.stderr)
        print("", file=sys.stderr)
        print(f"{len(findings)} finding(s). Values are deliberately not printed.", file=sys.stderr)
        return 1

    print(f"No credential-shaped exports found in {len(paths)} tracked file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
