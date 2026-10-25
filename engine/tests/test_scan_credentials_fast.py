from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.scan_credentials_fast import scan_roots


def _git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)


def test_env_reference_assignments_are_not_literal_secret_findings(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    src = tmp_path / "app.ts"
    src.write_text(
        "const apiKey = process.env.ENGINE_API_KEY || '';\n"
        "const url = `${base}/ws?api_key=${encodeURIComponent(apiKey)}`;\n"
        "client = Anthropic(api_key=direct_anthropic_key, timeout=30)\n"
        "token = response.get('access_token')\n"
        "self.password = password\n"
        "password = os.getenv('DASHBOARD_PASSWORD')\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "app.ts"], cwd=tmp_path, check=True)

    assert scan_roots([tmp_path]) == []


def test_literal_secret_like_assignments_are_still_high_findings(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    src = tmp_path / "bad.md"
    src.write_text("API_KEY=abcdefghijklmnop1234567890\n", encoding="utf-8")
    subprocess.run(["git", "add", "bad.md"], cwd=tmp_path, check=True)

    findings = scan_roots([tmp_path])

    assert len(findings) == 1
    assert findings[0].severity == "HIGH"
    assert findings[0].rule == "generic_secret_assignment"
