#Requires -Version 5.1
<#
.SYNOPSIS
    Build and publish a Windows x64 release to GitHub.

.DESCRIPTION
    End-to-end release automation:

    1. Verifies pyproject.toml and __init__.py share the same version (shown in the app).
    2. Builds FilmStockPot_x64_<version>.exe with PyInstaller + Inno Setup.
    3. Tags the current commit as v<version>, pushes the tag, and creates a GitHub
       release with the installer attached.
    4. Bumps the minor version for the next development cycle and pushes main.

    Requires: uv, Inno Setup 6, GitHub CLI (gh), and git push access to origin.

    If PowerShell blocks unsigned scripts, run release_windows.cmd instead.

.EXAMPLE
    .\scripts\release_windows.cmd
    .\scripts\release_windows.cmd -SkipBump
    .\scripts\release_windows.cmd -Draft
#>
param(
    [switch]$SkipBump,
    [switch]$Draft,
    [string]$NotesFile = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        if ($Name -eq "gh") {
            throw @"
Required command not found on PATH: gh (GitHub CLI)

Install it, then open a new terminal:
  winget install --id GitHub.cli -e

Authenticate:
  gh auth login
"@
        }
        throw "Required command not found on PATH: $Name"
    }
}

function Ensure-GhAuthenticated {
    if (-not $env:GH_TOKEN -and $env:GITHUB_TOKEN) {
        $env:GH_TOKEN = $env:GITHUB_TOKEN
    }
    if ($env:GH_TOKEN) {
        return
    }
    gh auth status 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub CLI is not authenticated. Run: gh auth login"
    }
}

Write-Host "==> Checking prerequisites" -ForegroundColor Cyan
Require-Command "uv"
Require-Command "git"
Require-Command "gh"
Ensure-GhAuthenticated

$Branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($Branch -ne "main" -and $Branch -ne "master") {
    throw "Release must be run from main/master (current branch: $Branch)."
}

if ((git status --porcelain).Length -gt 0) {
    throw "Working tree has uncommitted changes. Commit or stash them before releasing."
}

Write-Host "==> Verifying version metadata" -ForegroundColor Cyan
$Version = (uv run python scripts/bump_version.py --verify).Trim()
$Tag = "v$Version"
Write-Host "    Release version: $Version (tag $Tag)" -ForegroundColor Green

if (git tag --list $Tag) {
    throw "Git tag $Tag already exists. Bump the version before releasing again."
}

$RemoteTag = git ls-remote --tags origin "refs/tags/$Tag"
if ($RemoteTag) {
    throw "Remote tag $Tag already exists on origin."
}

Write-Host "==> Building Windows installer" -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "build_windows.ps1")

$InstallerPath = Join-Path $Root "dist/installer/FilmStockPot_x64_$Version.exe"
if (-not (Test-Path $InstallerPath)) {
    throw "Installer was not created at $InstallerPath"
}

Write-Host "==> Pushing current branch" -ForegroundColor Cyan
git push origin $Branch

Write-Host "==> Creating tag $Tag" -ForegroundColor Cyan
git tag -a $Tag -m "Film Stockpot $Version"
git push origin $Tag

Write-Host "==> Publishing GitHub release $Tag" -ForegroundColor Cyan
$NotesPath = $NotesFile
if (-not $NotesPath) {
    $DefaultNotes = Join-Path $Root "scripts/release_notes/v$Version.md"
    if (Test-Path $DefaultNotes) {
        $NotesPath = $DefaultNotes
    }
}

$ReleaseArgs = @(
    "release", "create", $Tag,
    "--title", "Film Stockpot $Version"
)
if ($NotesPath) {
    Write-Host "    Release notes: $NotesPath" -ForegroundColor Green
    $ReleaseArgs += @("--notes-file", $NotesPath)
} else {
    $ReleaseArgs += @("--notes", "Windows x64 installer for Film Stockpot $Version.")
}
$ReleaseArgs += $InstallerPath
if ($Draft) {
    $ReleaseArgs += "--draft"
}

& gh @ReleaseArgs
if ($LASTEXITCODE -ne 0) {
    throw "gh release create failed."
}

$ReleaseUrl = (gh release view $Tag --json url -q .url).Trim()
Write-Host "    Release URL: $ReleaseUrl" -ForegroundColor Green

if (-not $SkipBump) {
    Write-Host "==> Bumping minor version for next development cycle" -ForegroundColor Cyan
    $NextVersion = (uv run python scripts/bump_version.py --minor).Trim()
    git add pyproject.toml src/film_stockpot/__init__.py
    git commit -m "chore: bump minor to $NextVersion for next development [skip ci]"
    git push origin $Branch
    Write-Host "    Next development version: $NextVersion" -ForegroundColor Green
}

Write-Host ""
Write-Host "Release complete." -ForegroundColor Green
Write-Host "  Version:   $Version"
Write-Host "  Tag:       $Tag"
Write-Host "  Installer: $InstallerPath"
Write-Host "  Release:   $ReleaseUrl"
