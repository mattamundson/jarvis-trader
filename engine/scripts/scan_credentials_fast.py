"""Fast tracked-file credential scan for local readiness gates.

This is intentionally narrower than the full PowerShell home-directory scanner:
- scans only git-tracked files in the selected repository roots;
- skips binary/heavy dependency/build paths;
- never writes matched secret values, only path/line/rule metadata;
- emits the summary JSON shape accepted by backtest.live_readiness C3.

It is a CI/agent-safe fast path for C3 when the full home scanner exceeds the
runtime cap. A clean result means "no HIGH findings in tracked source files",
not "the entire workstation has no secrets".
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ROOTS = [
    Path(r"C:\Users\mattm\ThinkorSwim\jarvis-trader"),
    Path(r"C:\Users\mattm\master-jarvis"),
]
DEFAULT_OUT = Path.home() / ".claude" / "logs" / "scan-credentials-latest.json"
SKIP_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    ".next",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
TEXT_SUFFIXES = {
    ".bat",
    ".cmd",
    ".cfg",
    ".conf",
    ".css",
    ".csv",
    ".env",
    ".example",
    ".gitignore",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
ALLOWLIST_VALUE_MARKERS = (
    "example",
    "dummy",
    "placeholder",
    "redacted",
    "changeme",
    "fakekeyfortesting",
    "not-a-real",
    "not_a_real",
    "your_",
    "test_",
    "local-research-sandbox-dummy-not-a-credential",
)
REFERENCE_VALUE_MARKERS = (
    "process.env",
    "import.meta.env",
    "os.getenv",
    "os.environ",
    "getattr(settings",
    "settings.",
    "config.",
    "localstorage",
    "sessionstorage",
    "get-content",
    "select-string",
    "${",
    "%env",
)
RULES: list[tuple[str, str, re.Pattern[str]]] = [
    ("HIGH", "generic_secret_assignment", re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd)\b\s*[:=]\s*['\"]?([^'\"\s#]{16,})")),
    ("HIGH", "aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("HIGH", "github_pat", re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b")),
    ("HIGH", "openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("HIGH", "anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("HIGH", "private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
]


@dataclass
class Finding:
    severity: str
    rule: str
    path: str
    line: int


def _tracked_files(root: Path) -> list[Path]:
    if not (root / ".git").exists():
        return []
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        return []
    files: list[Path] = []
    for rel in proc.stdout.splitlines():
        path = root / rel
        parts = set(path.parts)
        if SKIP_PARTS & parts:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and "." + path.name.lower() not in TEXT_SUFFIXES:
            continue
        files.append(path)
    return files


def _allowlisted(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ALLOWLIST_VALUE_MARKERS)


def _is_reference_assignment(rule: str, text: str, match: re.Match[str] | None = None) -> bool:
    """Return True for env/config references that are not literal credentials.

    The fast scanner is intended to find tracked literal secrets, not safe source
    expressions such as ``apiKey = process.env.ENGINE_API_KEY`` or docs showing
    how to read a key from `.env`. Those were dominating C3 with false positives.
    """
    if rule != "generic_secret_assignment":
        return False
    lowered = text.lower()
    if any(marker in lowered for marker in REFERENCE_VALUE_MARKERS):
        return True
    if match is None:
        return False
    value = match.group(2).strip().strip("'\"`;,)")
    value_lower = value.lower()
    # Expressions/references frequently include punctuation or identifier names
    # and are not tracked literals: api_key=direct_anthropic_key,
    # token=response.get('access_token'), password=password, etc.
    if any(ch in value for ch in ".()[]{}"):
        return True
    if "_" in value and not value_lower.startswith(("sk_", "ghp_")):
        return True
    if value_lower in {
        "apikey",
        "api_key",
        "secret",
        "token",
        "password",
        "auth_token",
        "direct_anthropic_key",
        "directanthropickey",
    }:
        return True
    return False


def scan_roots(roots: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for root in roots:
        for path in _tracked_files(root):
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "\x00" in content[:4096]:
                continue
            for lineno, line in enumerate(content.splitlines(), start=1):
                if _allowlisted(line):
                    continue
                for severity, rule, pattern in RULES:
                    match = pattern.search(line)
                    if match:
                        if _is_reference_assignment(rule, line, match):
                            continue
                        findings.append(
                            Finding(
                                severity=severity,
                                rule=rule,
                                path=str(path),
                                line=lineno,
                            )
                        )
                        break
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast tracked-file credential scanner")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--root", type=Path, action="append", dest="roots")
    args = parser.parse_args()

    roots = args.roots or DEFAULT_ROOTS
    findings = scan_roots(roots)
    n_high = sum(1 for finding in findings if finding.severity.upper() == "HIGH")
    summary = {
        "scanner": "scan_credentials_fast.py",
        "scope": "git-tracked files only; secret stores and untracked .env files are out of scope",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "roots": [str(root) for root in roots],
        "n_high": n_high,
        "n_findings": len(findings),
        "findings": [asdict(finding) for finding in findings],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(args.out), "n_high": n_high, "n_findings": len(findings)}))
    return 1 if n_high else 0


if __name__ == "__main__":
    raise SystemExit(main())
