#Requires -Version 5.1
<#
.SYNOPSIS
    Build a standalone Windows x64 installer for Film Stockpot.

.DESCRIPTION
    Creates dist/FilmStockpot/ via PyInstaller, then packages it into
    dist/installer/FilmStockPot_x64_<version>.exe using Inno Setup 6.

    Requires Inno Setup 6: https://jrsoftware.org/isinfo.php

.PARAMETER SkipInstaller
    Only build the PyInstaller bundle; skip Inno Setup.

.EXAMPLE
    .\scripts\build_windows.ps1
    .\scripts\build_windows.ps1 -SkipInstaller
#>
param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Find-InnoSetupCompiler {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) {
            return $path
        }
    }
    return $null
}

Write-Host "==> Syncing dependencies" -ForegroundColor Cyan
uv sync --dev

$Version = (uv run python scripts/bump_version.py --verify).Trim()
Write-Host "==> Building Film Stockpot $Version for Windows x64" -ForegroundColor Cyan

Write-Host "==> Running PyInstaller" -ForegroundColor Cyan
if (Test-Path "dist/FilmStockpot") {
    Remove-Item -Recurse -Force "dist/FilmStockpot"
}
if (Test-Path "build/film_stockpot") {
    Remove-Item -Recurse -Force "build/film_stockpot"
}

$SavedBuildPath = $env:PATH
$UvBin = Split-Path (Get-Command uv).Source -Parent
$VenvScripts = Join-Path $Root ".venv\Scripts"
$env:PATH = @(
    "$env:SystemRoot\System32",
    $env:SystemRoot,
    $UvBin,
    $VenvScripts
) -join ';'
try {
    uv run pyinstaller packaging/film_stockpot.spec --noconfirm --clean
} finally {
    $env:PATH = $SavedBuildPath
}

Write-Host "==> Copying FilmPresets beside executable" -ForegroundColor Cyan
$TargetPresets = Join-Path $Root "dist/FilmStockpot/FilmPresets"
if (Test-Path $TargetPresets) {
    Remove-Item -Recurse -Force $TargetPresets
}
Copy-Item -Recurse -Force (Join-Path $Root "FilmPresets") $TargetPresets

Write-Host "==> Smoke-testing bundled executable" -ForegroundColor Cyan
$ExePath = Join-Path $Root "dist/FilmStockpot/FilmStockpot.exe"
if (-not (Test-Path $ExePath)) {
    throw "Bundled executable was not created at $ExePath"
}
$SavedPath = $env:PATH
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
try {
    $Proc = Start-Process -FilePath $ExePath -PassThru -WorkingDirectory (Split-Path $ExePath)
    Start-Sleep -Seconds 5
    if ($Proc.HasExited) {
        throw "FilmStockpot.exe exited immediately with code $($Proc.ExitCode). Qt/DLL startup failed."
    }
    $Proc.Refresh()
    if ($Proc.MainWindowTitle -match "Unhandled exception|Error") {
        throw "FilmStockpot.exe showed a startup error dialog: $($Proc.MainWindowTitle)"
    }
    Stop-Process -Id $Proc.Id -Force
    Write-Host "    Smoke test passed" -ForegroundColor Green
} finally {
    $env:PATH = $SavedPath
}

if ($SkipInstaller) {
    Write-Host "Skipping Inno Setup (--SkipInstaller)." -ForegroundColor Yellow
    Write-Host "Bundle: dist/FilmStockpot/FilmStockpot.exe" -ForegroundColor Green
    return $null
}

$Iscc = Find-InnoSetupCompiler
if (-not $Iscc) {
    throw @"
Inno Setup 6 was not found. Install it from https://jrsoftware.org/isinfo.php
or re-run with -SkipInstaller to build only the PyInstaller bundle.
"@
}

Write-Host "==> Creating installer with Inno Setup" -ForegroundColor Cyan
$InstallerDir = Join-Path $Root "dist/installer"
New-Item -ItemType Directory -Force -Path $InstallerDir | Out-Null

& $Iscc "installer/film_stockpot.iss" "/DMyAppVersion=$Version"

$InstallerPath = Join-Path $InstallerDir "FilmStockPot_x64_$Version.exe"
if (-not (Test-Path $InstallerPath)) {
    throw "Installer was not created at $InstallerPath"
}

Write-Host ""
Write-Host "Build complete:" -ForegroundColor Green
Write-Host "  Installer: $InstallerPath"
Write-Host "  Bundle:    $(Join-Path $Root 'dist/FilmStockpot/FilmStockpot.exe')"

return $InstallerPath
