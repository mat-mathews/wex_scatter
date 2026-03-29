# Copy scatter Claude Code skills into the project's .claude/skills/ directory.
# Run from the repo root: pwsh tools/setup-claude-skills.ps1
#
# Uses directory copies instead of symlinks (symlinks on Windows require
# Developer Mode or admin privileges).

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$SkillsDir = Join-Path $RepoRoot "tools/claude-skills"
$TargetDir = Join-Path $RepoRoot ".claude/skills"

if (-not (Test-Path $TargetDir)) {
    New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
}

Get-ChildItem -Path $SkillsDir -Directory -Filter "scatter-*" | ForEach-Object {
    $skillName = $_.Name
    $linkPath = Join-Path $TargetDir $skillName

    if (Test-Path $linkPath) {
        # Remove and re-copy to pick up changes
        Remove-Item -Recurse -Force $linkPath
    }

    Copy-Item -Recurse -Path $_.FullName -Destination $linkPath
    Write-Host "  copied: $skillName"
}

Write-Host ""
Write-Host "Done. Skills available in Claude Code:"
Write-Host "  /scatter-graph       - dependency health, coupling, cycles"
Write-Host "  /scatter-consumers   - find who uses a project"
Write-Host "  /scatter-impact      - SOW/change blast radius"
Write-Host "  /scatter-sproc       - stored procedure consumers"
Write-Host "  /scatter-branch      - git branch impact analysis"
