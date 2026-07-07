# phase0-verify.ps1 -- post-credential-rotation sign-off check
#
# Runs after Amo completes Phase 0 of the audit roadmap (rotate every cred,
# delete forbidden cred files, populate 1Password vault). Verifies the
# round-trip is clean: nothing forbidden remains, op CLI is configured,
# all expected vault items exist, load-secrets.ps1 successfully retrieves them.
#
# Extended 2026-05-04 to cover all 12 services per
# ~/.claude/skills/ralph/projects/home-strategic-plan/PHASE0_ROTATION_PLAYBOOK.md
# Added: Azure-GMS-App, Twilio, Telegram-Bot-Jarvis, Jarvis-Internal-Keys
# (Supermemory-API is verified under Cursor-API entry as Service 12)
#
# Returns:
#   exit 0 = Phase 0 complete and clean
#   exit 2 = something missing or wrong
#
# Usage:
#   .\phase0-verify.ps1

[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"

$results = New-Object System.Collections.ArrayList
function Add-Result {
    param($Check, $Status, $Detail)
    $r = [PSCustomObject]@{ check = $Check; status = $Status; detail = $Detail }
    [void]$results.Add($r)
    $color = switch ($Status) { "OK" { "Green" } "WARN" { "Yellow" } default { "Red" } }
    Write-Host ("[{0,-4}] {1}: {2}" -f $Status, $Check, $Detail) -ForegroundColor $color
}

Write-Host "=== Phase 0 verification ===" -ForegroundColor Cyan
Write-Host ""

# ============================================================
# 1. Forbidden cred files must NOT exist
#    Updated 2026-05-04 evening: added the 2 newly-discovered cred files
#    (career-ops/.env, GMS personal_agent/jarvis.env) per PHASE0_ROTATION_PLAYBOOK.md.
# ============================================================
$forbidden = @(
    "C:\Users\mattm\.env",
    "C:\Users\mattm\jarvis.env",
    "C:\Users\mattm\.secrets\keys.env",
    "C:\Users\mattm\.aider\oauth-keys.env",
    "C:\Users\mattm\career-ops\.env",
    "C:\Users\mattm\OneDrive\Greenfield Metal Sales\AI Agent Team\personal_agent\jarvis.env"
)
$present = $forbidden | Where-Object { Test-Path $_ }
if ($present.Count -eq 0) {
    Add-Result "Forbidden files deleted" "OK" "All $($forbidden.Count) paths gone"
}
else {
    Add-Result "Forbidden files deleted" "FAIL" ("Still present: " + ($present -join ", "))
}

# ============================================================
# 2. 1Password CLI installed
# ============================================================
$op = Get-Command op -ErrorAction SilentlyContinue
if (-not $op) {
    Add-Result "1Password CLI present" "FAIL" "op not on PATH (winget install AgileBits.1Password.CLI)"
}
else {
    $opVer = & op --version 2>&1
    Add-Result "1Password CLI present" "OK" "$opVer at $($op.Source)"
}

# ============================================================
# 3. 1Password account configured + signed in
#    Time-bounded via Start-Job. Without bound, `op whoami` hangs forever
#    if op is waiting for interactive signin (verified 2026-05-04).
# ============================================================
$opSignedIn = $false
if ($op) {
    $accountsJob = Start-Job -ScriptBlock { op account list 2>&1 | Out-String }
    if (Wait-Job -Job $accountsJob -Timeout 5) {
        $accounts = Receive-Job -Job $accountsJob
        Remove-Job -Job $accountsJob -Force -ErrorAction SilentlyContinue
        if ($accounts -match "ERROR" -or -not $accounts.Trim()) {
            Add-Result "1Password account" "FAIL" "No account configured (op account add)"
        }
        else {
            Add-Result "1Password account" "OK" "Account configured"
        }
    }
    else {
        Stop-Job -Job $accountsJob -ErrorAction SilentlyContinue
        Remove-Job -Job $accountsJob -Force -ErrorAction SilentlyContinue
        Add-Result "1Password account" "FAIL" "op account list timed out (5s) -- run 'op signin' interactively first"
    }

    $whoamiJob = Start-Job -ScriptBlock { op whoami 2>&1 | Out-String }
    if (Wait-Job -Job $whoamiJob -Timeout 5) {
        $whoami = Receive-Job -Job $whoamiJob
        Remove-Job -Job $whoamiJob -Force -ErrorAction SilentlyContinue
        if ($whoami -match "ERROR|not currently signed in") {
            Add-Result "1Password signed in" "FAIL" "Not signed in (op signin)"
        }
        else {
            Add-Result "1Password signed in" "OK" ($whoami.Trim())
            $opSignedIn = $true
        }
    }
    else {
        Stop-Job -Job $whoamiJob -ErrorAction SilentlyContinue
        Remove-Job -Job $whoamiJob -Force -ErrorAction SilentlyContinue
        Add-Result "1Password signed in" "FAIL" "op whoami timed out (5s) -- run 'op signin' interactively first"
    }
}

if (-not $opSignedIn) {
    Write-Host ""
    Write-Host "Skipping vault-item checks (op not signed in). Run 'op signin' and re-run." -ForegroundColor Yellow
    Write-Host ""
}

# ============================================================
# 4. Expected vault items exist
# ============================================================
$expectedItems = @(
    "Anthropic-API",
    "OpenAI-API",
    "Google-API",
    "Cursor-API",
    "Render-API",
    "Paradigm-API",
    "OpenRouter-API",
    "Firecrawl-API",
    # --- Extended 2026-05-04: 4 services from PHASE0_ROTATION_PLAYBOOK.md ---
    "Azure-GMS-App",        # Service 3:  Azure AD (AZURE_CLIENT_SECRET / TENANT_ID / CLIENT_ID)
    "Twilio",               # Service 9:  Twilio WhatsApp alerts (TWILIO_AUTH_TOKEN)
    "Telegram-Bot-Jarvis",  # Service 10: Telegram bot (TELEGRAM_BOT_TOKEN)
    "Jarvis-Internal-Keys"  # Service 11: JWT_SECRET_KEY, AUDIT_HMAC_KEY, API_KEY, ADMIN_PASSWORD
)
$Vault = "Amo Personal"

if ($op -and $opSignedIn) {
    $missing = @()
    $found = @()
    foreach ($item in $expectedItems) {
        $check = & op item get $item --vault $Vault --format json 2>&1 | Out-String
        if ($check -match "isn't an item|not found|ERROR") {
            $missing += $item
        }
        else {
            $found += $item
        }
    }
    if ($missing.Count -eq 0) {
        Add-Result "Vault items complete" "OK" "$($found.Count)/$($expectedItems.Count) items in '$Vault'"
    }
    else {
        Add-Result "Vault items complete" "FAIL" ("Missing: " + ($missing -join ", "))
    }

    # ----------------------------------------------------------
    # 4b. Verify key fields are non-empty for the 4 new services
    #     (Extended 2026-05-04 per PHASE0_ROTATION_PLAYBOOK.md)
    # ----------------------------------------------------------
    $fieldChecks = @(
        @{ Item = "Azure-GMS-App"; Field = "client_secret"; Label = "Azure client_secret" },
        @{ Item = "Azure-GMS-App"; Field = "tenant_id"; Label = "Azure tenant_id" },
        @{ Item = "Azure-GMS-App"; Field = "client_id"; Label = "Azure client_id" },
        @{ Item = "Twilio"; Field = "auth_token"; Label = "Twilio auth_token" },
        @{ Item = "Twilio"; Field = "account_sid"; Label = "Twilio account_sid" },
        @{ Item = "Telegram-Bot-Jarvis"; Field = "credential"; Label = "Telegram bot token" },
        @{ Item = "Jarvis-Internal-Keys"; Field = "jwt_secret_key"; Label = "JWT secret key" },
        @{ Item = "Jarvis-Internal-Keys"; Field = "audit_hmac_key"; Label = "HMAC audit key" },
        @{ Item = "Jarvis-Internal-Keys"; Field = "api_key"; Label = "Jarvis API key" },
        @{ Item = "Jarvis-Internal-Keys"; Field = "admin_password"; Label = "Admin password" }
    )
    foreach ($fc in $fieldChecks) {
        $val = & op item get $fc.Item --vault $Vault --fields $fc.Field 2>&1 | Out-String
        $val = $val.Trim()
        if ($val -match "isn't an item|not found|ERROR" -or $val.Length -eq 0) {
            Add-Result "Field: $($fc.Label)" "FAIL" "Item '$($fc.Item)' field '$($fc.Field)' missing or empty"
        }
        else {
            Add-Result "Field: $($fc.Label)" "OK" "Present ($($val.Length) chars)"
        }
    }
}

# ============================================================
# 5. load-secrets.ps1 actually loads secrets
# ============================================================
$loader = Join-Path $PSScriptRoot "load-secrets.ps1"
if (-not (Test-Path $loader)) {
    Add-Result "load-secrets.ps1 present" "FAIL" "Missing at $loader"
}
elseif ($op -and $opSignedIn) {
    # Run loader -Print and check it reports loaded items.
    $loaderOut = & $loader -Print 2>&1 | Out-String
    if ($loaderOut -match "Loaded \(([0-9]+)\)") {
        $loadedCount = [int]$Matches[1]
        if ($loadedCount -ge $expectedItems.Count) {
            Add-Result "load-secrets.ps1 works" "OK" "Loaded $loadedCount/$($expectedItems.Count) secrets"
        }
        else {
            Add-Result "load-secrets.ps1 works" "WARN" "Only $loadedCount of $($expectedItems.Count) loaded"
        }
    }
    else {
        Add-Result "load-secrets.ps1 works" "FAIL" "Loader did not report any loaded secrets"
    }
}

# ============================================================
# 6. credential-guard hook is wired in settings.json
# ============================================================
$settings = "C:\Users\mattm\.claude\settings.json"
if (Test-Path $settings) {
    $cfgRaw = Get-Content $settings -Raw
    if ($cfgRaw -match "credential-guard\.sh") {
        Add-Result "credential-guard wired" "OK" "Hook referenced in settings.json"
    }
    else {
        Add-Result "credential-guard wired" "WARN" "Hook script exists but not in settings.json (apply SETTINGS_PATCH.md)"
    }
}
else {
    Add-Result "credential-guard wired" "FAIL" "settings.json not found"
}

# ============================================================
# 7. Re-run scan-credentials to confirm no HIGH findings
# ============================================================
$scanner = Join-Path $PSScriptRoot "scan-credentials.ps1"
if (Test-Path $scanner) {
    Write-Host ""
    Write-Host "Running scan-credentials (Quiet mode)..." -ForegroundColor DarkGray
    & $scanner -Quiet 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Add-Result "scan-credentials clean" "OK" "Zero HIGH findings"
    }
    elseif ($LASTEXITCODE -eq 2) {
        Add-Result "scan-credentials clean" "FAIL" "Scanner reported HIGH findings -- run with -Quiet:`$false to inspect"
    }
    else {
        Add-Result "scan-credentials clean" "WARN" "Scanner exit $LASTEXITCODE (unexpected)"
    }
}

# ============================================================
# Summary
# ============================================================
Write-Host ""
Write-Host "=== PHASE 0 VERIFICATION SUMMARY ===" -ForegroundColor Cyan
$failed = ($results | Where-Object status -EQ "FAIL").Count
$warned = ($results | Where-Object status -EQ "WARN").Count
$ok = ($results | Where-Object status -EQ "OK").Count
Write-Host ("  OK   : {0}" -f $ok) -ForegroundColor Green
Write-Host ("  WARN : {0}" -f $warned) -ForegroundColor Yellow
Write-Host ("  FAIL : {0}" -f $failed) -ForegroundColor Red

if ($failed -eq 0) {
    Write-Host ""
    Write-Host "Phase 0 COMPLETE. Credential rotation verified." -ForegroundColor Green
    exit 0
}
else {
    Write-Host ""
    Write-Host "Phase 0 INCOMPLETE. Address the FAIL items above before considering the rotation done." -ForegroundColor Red
    exit 2
}
