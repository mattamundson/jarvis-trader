# load-secrets.ps1 -- pull named secrets from 1Password into env vars
#
# Replacement for ~/jarvis.env / ~/.env. Source of truth is the 1Password
# vault "Amo Personal" (per ~/.claude/rules/secret-hygiene.md).
#
# Modes:
#   . .\load-secrets.ps1            # dot-source: sets env vars in current shell
#   .\load-secrets.ps1 -Spawn       # launches a new pwsh with env loaded
#   .\load-secrets.ps1 -Print       # prints which vars were loaded (no values)
#
# Edit $SecretMap below to add/rename items as your vault evolves.

[CmdletBinding()]
param(
    [switch]$Spawn,
    [switch]$Print
)

$ErrorActionPreference = "Stop"

$VaultName = "Amo Personal"

# Map: env-var-name -> 1Password item path (assumes vault $VaultName, field 'credential')
# Extended 2026-05-04 evening with the 13-service mapping from
# ~/.claude/skills/ralph/projects/home-strategic-plan/PHASE0_ROTATION_PLAYBOOK.md
$SecretMap = @{
    # Original 8
    "ANTHROPIC_API_KEY"      = "op://$VaultName/Anthropic-API/credential"
    "OPENAI_API_KEY"         = "op://$VaultName/OpenAI-API/credential"
    "GOOGLE_API_KEY"         = "op://$VaultName/Google-API/credential"
    "CURSOR_API_KEY"         = "op://$VaultName/Cursor-API/credential"
    "RENDER_API_KEY"         = "op://$VaultName/Render-API/credential"
    "PARADIGM_API_KEY"       = "op://$VaultName/Paradigm-API/credential"
    "OPENROUTER_API_KEY"     = "op://$VaultName/OpenRouter-API/credential"
    "FIRECRAWL_API_KEY"      = "op://$VaultName/Firecrawl-API/credential"

    # Azure AD / Microsoft 365 (Service 8 — multi-field item)
    "AZURE_CLIENT_SECRET"    = "op://$VaultName/Azure-GMS-App/client_secret"
    "AZURE_TENANT_ID"        = "op://$VaultName/Azure-GMS-App/tenant_id"
    "AZURE_CLIENT_ID"        = "op://$VaultName/Azure-GMS-App/client_id"

    # Google AI alias (some code uses this name; same key as GOOGLE_API_KEY)
    "GOOGLE_AI_API_KEY"      = "op://$VaultName/Google-API/credential"

    # Twilio (Service 12 — multi-field)
    "TWILIO_AUTH_TOKEN"      = "op://$VaultName/Twilio/auth_token"
    "TWILIO_ACCOUNT_SID"     = "op://$VaultName/Twilio/account_sid"

    # Telegram bot (Service 13)
    "TELEGRAM_BOT_TOKEN"     = "op://$VaultName/Telegram-Bot-Jarvis/credential"

    # Jarvis internal (Service 11 — generated, not at any issuer)
    "JWT_SECRET_KEY"         = "op://$VaultName/Jarvis-Internal-Keys/jwt_secret_key"
    "AUDIT_HMAC_KEY"         = "op://$VaultName/Jarvis-Internal-Keys/audit_hmac_key"

    # Paradigm bearer (Service 9 — paired with PARADIGM_API_KEY above)
    "PARADIGM_BEARER_TOKEN"  = "op://$VaultName/Paradigm-ERP/bearer_token"

    # Supermemory (Cursor IDE plugin — in Cursor-API item or its own)
    "SUPERMEMORY_CC_API_KEY" = "op://$VaultName/Supermemory-API/credential"
}

function Show-InstallInstructions {
    Write-Host ""
    Write-Host "1Password CLI (op) is required but not installed." -ForegroundColor Red
    Write-Host ""
    Write-Host "Install via winget:" -ForegroundColor Cyan
    Write-Host "  winget install AgileBits.1Password.CLI"
    Write-Host ""
    Write-Host "Or download from:" -ForegroundColor Cyan
    Write-Host "  https://developer.1password.com/docs/cli/get-started/"
    Write-Host ""
    Write-Host "After install, sign in once:" -ForegroundColor Cyan
    Write-Host "  op account add"
    Write-Host "  op signin"
    Write-Host ""
    Write-Host "See ~/.claude/skills/ralph/projects/home-strategic-plan/LOAD_SECRETS_SETUP.md" -ForegroundColor Yellow
    Write-Host ""
}

# ============================================================
# Pre-flight: op CLI installed?
# ============================================================

$op = Get-Command op -ErrorAction SilentlyContinue
if (-not $op) {
    Show-InstallInstructions
    if ($MyInvocation.InvocationName -eq '.') {
        # Dot-sourced; can't exit without killing the parent shell.
        return
    }
    exit 2
}

# ============================================================
# Pre-flight: signed in?
# ============================================================

$accounts = & op account list 2>&1
if ($LASTEXITCODE -ne 0 -or -not $accounts) {
    Write-Host "1Password CLI is installed but no account is configured." -ForegroundColor Red
    Write-Host "Run: op account add" -ForegroundColor Cyan
    Write-Host "Then: op signin" -ForegroundColor Cyan
    if ($MyInvocation.InvocationName -eq '.') { return }
    exit 2
}

# ============================================================
# Load each secret
# ============================================================

$loaded = @()
$missing = @()

foreach ($entry in $SecretMap.GetEnumerator()) {
    $varName = $entry.Key
    $opPath = $entry.Value
    try {
        $val = & op read $opPath 2>$null
        if ($LASTEXITCODE -eq 0 -and $val) {
            # Set process-level env var; also set scope:script for dot-source caller.
            Set-Item -Path "env:$varName" -Value $val
            $loaded += $varName
        }
        else {
            $missing += $varName
        }
    }
    catch {
        $missing += $varName
    }
}

# ============================================================
# Reporting
# ============================================================

if ($Print) {
    Write-Host "Loaded ($($loaded.Count)):" -ForegroundColor Green
    $loaded | ForEach-Object { Write-Host "  $_" }
    if ($missing.Count -gt 0) {
        Write-Host "Missing ($($missing.Count)):" -ForegroundColor Yellow
        $missing | ForEach-Object { Write-Host "  $_  (expected at $($SecretMap[$_]))" }
    }
}
else {
    Write-Host ("Loaded {0} secrets from 1Password vault '{1}'" -f $loaded.Count, $VaultName) -ForegroundColor Green
    if ($missing.Count -gt 0) {
        Write-Host ("Missing: {0}" -f ($missing -join ", ")) -ForegroundColor Yellow
        Write-Host "Add these items to your vault, or remove from `$SecretMap in this script."
    }
}

# ============================================================
# Spawn mode
# ============================================================

if ($Spawn) {
    Write-Host ""
    Write-Host "Spawning new PowerShell with secrets loaded..." -ForegroundColor Cyan
    # Pass loaded env vars to child process via Start-Process.
    $envBlock = @{}
    foreach ($v in $loaded) {
        $envBlock[$v] = [Environment]::GetEnvironmentVariable($v)
    }
    # Note: Start-Process uses current env automatically; this just makes intent explicit.
    Start-Process -FilePath "powershell.exe" -NoNewWindow -Wait
}
