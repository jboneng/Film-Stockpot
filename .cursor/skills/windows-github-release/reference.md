# Windows Release Reference

## Release notes template

Create `scripts/release_notes/vX.Y.Z.md`:

```markdown
## Film Stockpot X.Y.Z

One-line summary of what this release is for.

### Download

- **FilmStockPot_x64_X.Y.Z.exe** — full installer (recommended)
- Requires Windows 10/11 x64

---

## Highlights

### Feature area 1

- User-facing bullet
- Another bullet with concrete behavior

### Feature area 2

- ...

---

## Existing features (unchanged)

- Short reminder of core app capabilities (3–6 bullets)

---

## Upgrade notes

- Breaking changes, migration steps, or hotfix reinstall instructions
- Sidecar / preset format changes if any

---

## Development / source

- Repository link
- License
```

**Quality bar:** write for users, not developers. Lead with highlights; group by feature; include upgrade notes for anything that affects installed users.

For hotfixes, add an explicit upgrade note:

```markdown
- **X.Y.Z installer (re-uploaded):** fixes … Uninstall any previous X.Y.Z install first, then download the latest `FilmStockPot_x64_X.Y.Z.exe`.
```

---

## Verification tests

Run both after every build. Do not publish if either fails.

### 1. Bundled exe smoke test

`build_windows.ps1` runs this automatically. To run manually:

```powershell
$ExePath = "dist/FilmStockpot/FilmStockpot.exe"
$SavedPath = $env:PATH
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
try {
    $Proc = Start-Process -FilePath $ExePath -PassThru -WorkingDirectory (Split-Path $ExePath)
    Start-Sleep -Seconds 5
    if ($Proc.HasExited) { throw "Exited with code $($Proc.ExitCode)" }
    Stop-Process -Id $Proc.Id -Force
    Write-Host "OK"
} finally {
    $env:PATH = $SavedPath
}
```

Minimal `PATH` catches DLL issues that hide when dev tools (Qt, Python venv) are on `PATH`.

### 2. Silent install test

Simulates a clean user install:

```powershell
$installDir = Join-Path $env:TEMP "FilmStockpotTestInstall"
if (Test-Path $installDir) { Remove-Item -Recurse -Force $installDir }
New-Item -ItemType Directory -Path $installDir | Out-Null

$installer = "dist/installer/FilmStockPot_x64_X.Y.Z.exe"
Start-Process -FilePath $installer -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/DIR=`"$installDir`"" -Wait

$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
$exe = Join-Path $installDir "FilmStockpot.exe"
$Proc = Start-Process -FilePath $exe -PassThru -WorkingDirectory $installDir
Start-Sleep -Seconds 6
if ($Proc.HasExited) { throw "Installed app failed: exit $($Proc.ExitCode)" }
Stop-Process -Id $Proc.Id -Force
Write-Host "Install test OK"
```

### 3. Confirm GitHub asset (after upload)

```powershell
$local = Get-FileHash "dist/installer/FilmStockPot_x64_X.Y.Z.exe" -Algorithm SHA256
$tmp = Join-Path $env:TEMP "verify_installer.exe"
gh release download vX.Y.Z -O $tmp --clobber
$remote = Get-FileHash $tmp -Algorithm SHA256
if ($local.Hash -ne $remote.Hash) { throw "GitHub asset hash mismatch" }
Write-Host "SHA256: $($local.Hash)"
```

---

## PyInstaller spec essentials

`packaging/film_stockpot.spec` should:

```python
from PyInstaller.utils.hooks.qt import pyqt6_library_info

binaries += pyqt6_library_info.collect_extra_binaries()

for mod in ("PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "PyQt6.QtSvg"):
    hi, bins, datas = pyqt6_library_info.collect_module(mod)
    hiddenimports += hi
    binaries += bins
    datas += datas

runtime_hooks = [str(root / "packaging" / "pyqt6_bootstrap.py")]
```

Also: exclude unused `PyQt6.*` modules, `upx=False`, bundle `FilmPresets/` and app assets as datas.

---

## Common failures

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `QtWidgets` DLL load failed | PyQt6 / pyqt6-qt6 version mismatch | Pin matching versions in `pyproject.toml`, `uv lock` |
| Same error after pin | Qt6/bin not on DLL search path in frozen app | Ensure `packaging/pyqt6_bootstrap.py` is in spec `runtime_hooks` |
| Works in `dist/` but not installed | Stale install or old GitHub asset | Uninstall, verify SHA256, re-upload with `--clobber` |
| `git tag already exists` | Tag `vX.Y.Z` on remote | Hotfix flow (re-upload) or bump to new version |
| Release script aborts on dirty tree | Uncommitted changes | Commit or stash first |
| Version mismatch error | `pyproject.toml` ≠ `__init__.py` | `bump_version.py --set X.Y.Z` updates both |

---

## gh commands quick reference

```powershell
# New release (prefer release_windows.ps1)
gh release create vX.Y.Z --title "Film Stockpot X.Y.Z" --notes-file scripts/release_notes/vX.Y.Z.md dist/installer/FilmStockPot_x64_X.Y.Z.exe

# Hotfix re-upload
gh release upload vX.Y.Z dist/installer/FilmStockPot_x64_X.Y.Z.exe --clobber
gh release edit vX.Y.Z --notes-file scripts/release_notes/vX.Y.Z.md

# Inspect
gh release view vX.Y.Z --json url,assets
```
