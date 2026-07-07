# Anthropic API Key Rotation Helper
# ------------------------------------------------------------------------------
# Safely updates engine/.env with a new ANTHROPIC_API_KEY, verifies it works,
# and restarts the engine. Reverts to the prior key on verification failure.
#
# Usage:
#     .\scripts\rotate_anthropic_key.ps1
#
# NEVER writes the plaintext key to logs or stdout. The key exists in memory
# only for as long as the script is running.
# ------------------------------------------------------------------------------

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$envPath  = Join-Path $repoRoot "engine\.env"
$venvPy   = Join-Path $repoRoot "engine\.venv\Scripts\python.exe"
$restart  = Join-Path $repoRoot "restart_engine.ps1"

if (-not (Test-Path $envPath)) {
    Write-Host "ERROR: $envPath not found" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $venvPy)) {
    Write-Host "ERROR: venv python not found at $venvPy" -ForegroundColor Red
    exit 1
}

Write-Host "Anthropic API Key Rotation" -ForegroundColor Cyan
Write-Host "---------------------------" -ForegroundColor Cyan
Write-Host "1. Go to https://console.anthropic.com/settings/keys"
Write-Host "2. Create a new API key"
Write-Host "3. Paste it below (input is hidden)"
Write-Host ""

$secureKey = Read-Host -Prompt "New ANTHROPIC_API_KEY" -AsSecureString
$bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $newKey = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
} finally {
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

if ([string]::IsNullOrWhiteSpace($newKey) -or $newKey.Length -lt 20) {
    Write-Host "ERROR: key looks invalid (too short or empty)" -ForegroundColor Red
    exit 1
}
if (-not $newKey.StartsWith("sk-ant-")) {
    Write-Host "WARNING: key does not start with 'sk-ant-'. Continue anyway? [y/N]" -ForegroundColor Yellow
    $confirm = Read-Host
    if ($confirm -ne "y" -and $confirm -ne "Y") { exit 1 }
}

# Backup the .env
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupPath = "$envPath.bak-$timestamp"
Copy-Item $envPath $backupPath
Write-Host "Backup: $backupPath" -ForegroundColor Gray

# Read, replace (or insert), write
$lines = Get-Content $envPath
$replaced = $false
$newLines = foreach ($line in $lines) {
    if ($line -match "^ANTHROPIC_API_KEY\s*=") {
        $replaced = $true
        "ANTHROPIC_API_KEY=$newKey"
    } else {
        $line
    }
}
if (-not $replaced) {
    $newLines += "ANTHROPIC_API_KEY=$newKey"
}
# Write without trailing prompts in stdout
Set-Content -Path $envPath -Value $newLines -Encoding UTF8 -NoNewline:$false
Write-Host ".env updated" -ForegroundColor Green

# Verify the key with a tiny Haiku round-trip
Write-Host "Verifying key (Haiku ping)..." -ForegroundColor Cyan
$verifyScript = @'
import os, sys
from pathlib import Path
# Load .env manually (no python-dotenv dependency required here)
env_path = Path(sys.argv[1])
for raw in env_path.read_text(encoding="utf-8").splitlines():
    if raw.startswith("ANTHROPIC_API_KEY="):
        os.environ["ANTHROPIC_API_KEY"] = raw.split("=", 1)[1].strip()
        break
try:
    import anthropic
    c = anthropic.Anthropic()
    r = c.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
        messages=[{"role": "user", "content": "reply 'ok' only"}],
    )
    text = r.content[0].text if r.content else ""
    print("VERIFY_OK:" + text.strip()[:20])
except Exception as e:
    print("VERIFY_FAIL:" + str(e)[:120])
    sys.exit(2)
'@

$verifyFile = Join-Path $env:TEMP "jarvis_verify_$timestamp.py"
$verifyScript | Set-Content -Path $verifyFile -Encoding UTF8
try {
    $result = & $venvPy $verifyFile $envPath 2>&1
    $exit = $LASTEXITCODE
} finally {
    Remove-Item $verifyFile -Force -ErrorAction SilentlyContinue
}

Write-Host $result -ForegroundColor Gray
if ($exit -ne 0 -or ($result -join "`n") -notmatch "VERIFY_OK") {
    Write-Host "VERIFICATION FAILED — reverting from backup" -ForegroundColor Red
    Copy-Item $backupPath $envPath -Force
    Write-Host "Restored $envPath from $backupPath" -ForegroundColor Yellow
    exit 2
}

Write-Host "Key verified successfully." -ForegroundColor Green

# Restart the engine
if (Test-Path $restart) {
    Write-Host "Restarting engine via $restart ..." -ForegroundColor Cyan
    & $restart
} else {
    Write-Host "WARNING: $restart not found — restart engine manually" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Rotation complete." -ForegroundColor Green
Write-Host "Remember to:" -ForegroundColor Cyan
Write-Host "  1. Revoke the OLD key at https://console.anthropic.com/settings/keys" -ForegroundColor Cyan
Write-Host "  2. Check engine logs for 401 errors" -ForegroundColor Cyan
Write-Host "  3. Keep or delete the backup at: $backupPath" -ForegroundColor Cyan
