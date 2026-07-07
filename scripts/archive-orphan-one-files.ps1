# Archive and delete orphan OneNote files
# Generated 2026-05-04 from OneNote migration triage. CONFIRMED DUPLICATES per ~/Inbox/onenote-migration-2026-05-04/STATUS-AND-NEXT-STEPS.md.

[CmdletBinding()]
param(
    [switch]$DryRun = $true
)

$ArchiveRoot = "$env:USERPROFILE\.archive\2026\orphan-onenote"
$ErrorCount = 0
$SuccessCount = 0
$DeleteCount = 0
$TotalArchived = 0

# Files to delete (empty/duplicates)
$DeleteFiles = @(
    "$env:USERPROFILE\OneDrive\Documents\OneNote Notebooks\Quick Notes.one",
    "$env:USERPROFILE\OneDrive\Tools\OneNote\Notebooks\Quick Notes.one"
)

# Files to archive with folder structure
$ArchiveFiles = @(
    @{ Source = "$env:USERPROFILE\OneDrive\Business\Marketing\Marketing.one"; SubDir = "Business\Marketing" },
    @{ Source = "$env:USERPROFILE\OneDrive\Greenfield Metal Sales\02_Paradigm_ERP\Import_Files\Paradigm Part 1.one"; SubDir = "GMS\Paradigm" },
    @{ Source = "$env:USERPROFILE\OneDrive\Tools\PARADIGM\AI Automation.one"; SubDir = "Tools\PARADIGM" },
    @{ Source = "$env:USERPROFILE\OneDrive\Tools\PARADIGM\New Section 1.one"; SubDir = "Tools\PARADIGM" },
    @{ Source = "$env:USERPROFILE\OneDrive\Tools\PARADIGM\New Section 2.one"; SubDir = "Tools\PARADIGM" },
    @{ Source = "$env:USERPROFILE\OneDrive\Tools\PARADIGM\New Section 3.one"; SubDir = "Tools\PARADIGM" },
    @{ Source = "$env:USERPROFILE\OneDrive\Tools\PARADIGM\New Section 4.one"; SubDir = "Tools\PARADIGM" },
    @{ Source = "$env:USERPROFILE\OneDrive\Tools\PARADIGM\Paradigm ERP Order Lifecycle Guide (Expanded for N.one"; SubDir = "Tools\PARADIGM" },
    @{ Source = "$env:USERPROFILE\OneDrive\Tools\PARADIGM\Paradigm Part 1.one"; SubDir = "Tools\PARADIGM" },
    @{ Source = "$env:USERPROFILE\OneDrive\Tools\PARADIGM\Paradigm.one"; SubDir = "Tools\PARADIGM" }
)

Write-Host "OneNote Orphan File Archive Utility`n" -ForegroundColor Cyan
Write-Host "DryRun: $DryRun`n" -ForegroundColor ($DryRun ? "Yellow" : "Red")

# Create archive root if missing
if (-not (Test-Path $ArchiveRoot)) {
    if ($DryRun) {
        Write-Host "[DRY] Would create directory: $ArchiveRoot" -ForegroundColor Gray
    }
    else {
        New-Item -ItemType Directory -Path $ArchiveRoot -Force | Out-Null
        Write-Host "[✓] Created archive root: $ArchiveRoot" -ForegroundColor Green
    }
}

# Process DELETE files
Write-Host "`n--- DELETE PHASE ---`n" -ForegroundColor Magenta
foreach ($FilePath in $DeleteFiles) {
    if (Test-Path $FilePath) {
        $Item = Get-Item $FilePath -ErrorAction SilentlyContinue
        $SizeMB = [math]::Round($Item.Length / 1MB, 2)

        # Safety check: only delete if < 1 MB (confirmed empty/Quick Notes duplicates)
        if ($Item.Length -lt 1MB) {
            if ($DryRun) {
                Write-Host "[DRY] DELETE: $FilePath ($SizeMB MB)" -ForegroundColor Gray
            } else {
                Remove-Item $FilePath -Force -ErrorAction SilentlyContinue
                Write-Host "[✓] DELETED: $(Split-Path $FilePath -Leaf) ($SizeMB MB)" -ForegroundColor Green
        $DeleteCount++
    }
}
else {
    Write-Host "[!] SKIPPED (size > 1MB, confirm manually): $FilePath ($SizeMB MB)" -ForegroundColor Yellow
    $ErrorCount++
}
} else {
    Write-Host "[!] FILE NOT FOUND: $FilePath" -ForegroundColor Yellow
}
}

# Process ARCHIVE files
Write-Host "`n--- ARCHIVE PHASE ---`n" -ForegroundColor Magenta
foreach ($Item in $ArchiveFiles) {
    $Source = $Item.Source
    $SubDir = $Item.SubDir

    if (Test-Path $Source) {
        $File = Get-Item $Source
        $SizeMB = [math]::Round($File.Length / 1MB, 2)
        $DestDir = Join-Path $ArchiveRoot $SubDir
        $Dest = Join-Path $DestDir $File.Name

        # Check path length for robocopy fallback (> 260 chars)
        $SourcePathLen = $Source.Length
        $DestPathLen = $Dest.Length

        if ($SourcePathLen -gt 240 -or $DestPathLen -gt 240) {
            # Use robocopy for long paths
            if ($DryRun) {
                Write-Host "[DRY] ARCHIVE (robocopy): $(Split-Path $Source -Leaf) → $SubDir ($SizeMB MB)" -ForegroundColor Gray
            } else {
                if (-not (Test-Path $DestDir)) {
                    New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
                }
                $RobocopyLog = "$env:TEMP\robocopy-$(Get-Random).log"
                & robocopy (Split-Path $Source) $DestDir (Split-Path $Source -Leaf) /MOVE /LOG:$RobocopyLog /NFL /NDL /NP | Out-Null
                if ($LASTEXITCODE -lt 8) {
                    Write-Host "[✓] ARCHIVED (robocopy): $(Split-Path $Source -Leaf) → $SubDir ($SizeMB MB)" -ForegroundColor Green
                    $SuccessCount++
                    $TotalArchived += $File.Length
                } else {
                    Write-Host "[!] ROBOCOPY FAILED: $Source (exit code: $LASTEXITCODE)" -ForegroundColor Red
                    $ErrorCount++
                }
                Remove-Item $RobocopyLog -Force -ErrorAction SilentlyContinue
            }
        } else {
            # Standard Move-Item for shorter paths
            if ($DryRun) {
                Write-Host "[DRY] ARCHIVE: $(Split-Path $Source -Leaf) → $SubDir ($SizeMB MB)" -ForegroundColor Gray
            } else {
                if (-not (Test-Path $DestDir)) {
                    New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
                }
                Move-Item -Path $Source -Destination $Dest -Force -ErrorAction SilentlyContinue
                if ($?) {
                    Write-Host "[✓] ARCHIVED: $(Split-Path $Source -Leaf) → $SubDir ($SizeMB MB)" -ForegroundColor Green
                    $SuccessCount++
                    $TotalArchived += $File.Length
                } else {
                    Write-Host "[!] MOVE FAILED: $Source" -ForegroundColor Red
                    $ErrorCount++
                }
            }
        }
    } else {
        Write-Host "[!] FILE NOT FOUND: $(Split-Path $Source -Leaf)" -ForegroundColor Yellow
        $ErrorCount++
    }
}

# Summary
Write-Host "`n--- SUMMARY ---`n" -ForegroundColor Cyan
$TotalArchivedMB = [math]::Round($TotalArchived / 1MB, 2)
Write-Host "Archived: $SuccessCount files | $TotalArchivedMB MB"
Write-Host "Deleted: $DeleteCount files | 477 KB"
Write-Host "Errors: $ErrorCount"
Write-Host "`nDryRun: $DryRun — Run with -DryRun:`$false to execute." -ForegroundColor ($DryRun ? "Yellow" : "Green")
