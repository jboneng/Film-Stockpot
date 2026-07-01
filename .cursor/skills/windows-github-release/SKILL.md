---
name: windows-github-release
description: >-
  Build Film Stockpot Windows x64 installers (PyInstaller + Inno Setup), verify
  bundled and installed apps launch, write release notes, and publish GitHub
  releases with the correct version. Use when the user asks to release, ship,
  build an installer, re-upload a hotfix, bump version for release, or publish
  vX.Y.Z on GitHub.
---

# Windows GitHub Release (Film Stockpot)

End-to-end workflow for shipping `FilmStockPot_x64_<version>.exe` to GitHub.

## Prerequisites

Confirm before starting:

- Windows x64 build machine
- `uv`, `git`, `gh` (authenticated), Inno Setup 6
- Branch `main`, **clean working tree**
- Version to ship is committed on `main`

```powershell
uv run python scripts/bump_version.py --verify
git status --porcelain   # must be empty
gh auth status
```

## Version rules

Single source of truth: `pyproject.toml` **and** `src/film_stockpot/__init__.py` (must match).

| Action | Command |
|--------|---------|
| Verify sync | `uv run python scripts/bump_version.py --verify` |
| Set release version | `uv run python scripts/bump_version.py --set X.Y.Z` |
| After release (automatic) | `release_windows.ps1` bumps minor → next dev cycle |

**Before a new release**, pin the ship version and commit with `[skip ci]` so CI does not bump the build number first:

```powershell
uv run python scripts/bump_version.py --set X.Y.Z
git add pyproject.toml src/film_stockpot/__init__.py uv.lock
git commit -m "chore: set release version to X.Y.Z [skip ci]"
git push origin main
```

Outputs use this version everywhere: app title bar, installer filename, Git tag (`vX.Y.Z`).

## Release checklist

Copy and track progress:

```
Release X.Y.Z:
- [ ] Release notes drafted: scripts/release_notes/vX.Y.Z.md
- [ ] Version pinned and committed on main ([skip ci])
- [ ] bump_version.py --verify passes
- [ ] Working tree clean
- [ ] Build + smoke test passed (build_windows.ps1)
- [ ] Silent install test passed (installed exe launches)
- [ ] Tag vX.Y.Z created and pushed (or hotfix re-upload)
- [ ] GitHub release published with installer attached
- [ ] Post-release minor bump pushed (unless -SkipBump)
```

## Standard release (new version)

1. **Write release notes** — create `scripts/release_notes/vX.Y.Z.md` before publishing. See [reference.md](reference.md) for structure.

2. **Pin version** (if not already on `main` at `X.Y.Z`).

3. **Run full release**:

```powershell
.\scripts\release_windows.cmd
```

Or: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\release_windows.ps1`

The script:
- Verifies version metadata
- Runs `build_windows.ps1` (PyInstaller → Inno Setup)
- Smoke-tests `dist/FilmStockpot/FilmStockpot.exe`
- Tags `vX.Y.Z`, pushes, creates GitHub release with notes + installer
- Bumps minor for next dev cycle (unless `-SkipBump`)

Options: `-Draft`, `-SkipBump`, `-NotesFile path\to\notes.md`

4. **Confirm** release URL and installer asset on GitHub.

## Build-only (no publish)

```powershell
.\scripts\build_windows.cmd
```

Outputs:
- `dist/FilmStockpot/FilmStockpot.exe` — PyInstaller bundle
- `dist/installer/FilmStockPot_x64_<version>.exe` — installer

Includes bundled-exe smoke test (minimal `PATH`). **Always run the silent install test too** before publishing — see [reference.md](reference.md).

## Hotfix re-upload (same tag/version)

When fixing a broken installer without a new version number:

1. Fix packaging on `main`, commit, push.
2. Temporarily set version to the release being fixed:

```powershell
uv run python scripts/bump_version.py --set X.Y.Z
```

3. Rebuild and verify (build + silent install tests).
4. Re-upload and refresh notes:

```powershell
gh release upload vX.Y.Z dist/installer/FilmStockPot_x64_X.Y.Z.exe --clobber
gh release edit vX.Y.Z --notes-file scripts/release_notes/vX.Y.Z.md
```

5. Restore dev version: `uv run python scripts/bump_version.py --set <next-dev>` and commit.

6. Record new installer SHA256 in release notes; tell users to **uninstall first** then re-download.

## PyQt6 packaging (do not skip)

Frozen Windows builds fail with `DLL load failed while importing QtWidgets` if Qt paths or versions are wrong.

**Required in this repo:**

| File | Purpose |
|------|---------|
| `packaging/pyqt6_bootstrap.py` | Runtime hook: `os.add_dll_directory` for `PyQt6/Qt6/bin`, set `QT_PLUGIN_PATH` |
| `packaging/film_stockpot.spec` | Wire runtime hook; collect Qt modules via `pyqt6_library_info.collect_module`; exclude unused PyQt6 modules; `upx=False` |
| `pyproject.toml` | Pin **matching** `pyqt6==X.Y.Z` and `pyqt6-qt6==X.Y.Z` |

After changing PyQt6 or spec: rebuild, smoke-test bundled exe, silent-install test. Dev-machine success alone is not enough.

**Do not** use `collect_all("PyQt6")` — it pulls optional Qt DLLs and can mismatch bindings.

## Agent responsibilities

When the user requests a release:

1. Read this skill and [reference.md](reference.md).
2. Inspect git log/diff since last tag; draft release notes from actual changes.
3. Ensure version is correct and committed before running release script.
4. Run build and **both** verification tests; do not publish if either fails.
5. Use `gh` for all GitHub release operations.
6. Return release URL, installer path, and SHA256 hash.
7. Only commit when the user asks; release script commits post-release bump automatically.

## Key paths

| Path | Role |
|------|------|
| `scripts/build_windows.ps1` | Build + bundled smoke test |
| `scripts/release_windows.ps1` | Full publish pipeline |
| `scripts/bump_version.py` | Version read/write/verify |
| `scripts/release_notes/vX.Y.Z.md` | GitHub release body |
| `packaging/film_stockpot.spec` | PyInstaller spec |
| `packaging/pyqt6_bootstrap.py` | Qt DLL runtime hook |
| `installer/film_stockpot.iss` | Inno Setup script |

## Additional resources

- Release notes template and verification commands: [reference.md](reference.md)
- Human docs: `README.md` → **Windows release**
