<#
.SYNOPSIS
  Safely write the DiscordChatExporter user token to C:\Users\mattm\discord-export\.token.

.DESCRIPTION
  Prompts with masked input, writes a single-line token file, and never prints
  the token. This token is for DiscordChatExporter (DCE) and is separate from
  DISCORD_PERSONAL_BOT_TOKEN used by the Jarvis-Trader bot/reaction watcher.

  DCE expects a Discord USER token, not a bot token. Do not paste this token in
  chat, command arguments, PR bodies, or logs.
#>
[CmdletBinding()]
param(
    [string]$TokenPath = 'C:\Users\mattm\discord-export\.token'
)

$ErrorActionPreference = 'Stop'

function ConvertTo-PlainText {
    param([Security.SecureString]$Secure)
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    } finally {
        if ($ptr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    }
}

$dir = Split-Path -Parent $TokenPath
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

Write-Host 'Paste the DiscordChatExporter USER token. Input is masked; token will not be printed.'
$secure = Read-Host -AsSecureString 'DCE user token'
$token = (ConvertTo-PlainText $secure).Trim()

if ([string]::IsNullOrWhiteSpace($token)) {
    Write-Error 'No token entered; token file was not changed.'
    exit 3
}

# DCE user tokens vary by auth state. Avoid over-validating format here; DCE is
# the validator. Only reject obvious bot-token confusion.
if ($token -match '^Bot\s+') {
    Write-Error 'This looks like a bot Authorization header. DCE needs a Discord USER token only.'
    exit 4
}

Set-Content -Path $TokenPath -Value $token -NoNewline -Encoding ASCII
$length = (Get-Item $TokenPath).Length
if ($length -le 0) {
    Write-Error 'Token file write failed or is empty.'
    exit 5
}

Write-Host ("DCE_TOKEN_FILE_WRITTEN path={0} bytes={1}" -f $TokenPath, $length)
Write-Host 'Next: run scripts\dce-nightly.ps1 to validate/export/ingest.'
exit 0
