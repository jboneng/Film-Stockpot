# Running Film Stockpot from the Command Line

This guide covers how to set up and run Film Stockpot using [uv](https://docs.astral.sh/uv/) from a terminal.

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) installed and on your `PATH`
- A terminal opened in the project root (`FilmStockpot/`)

Film Stockpot uses **Python 3.12+**. On first run, `uv` will download and use the version pinned in `.python-version` if it is not already installed.

## First-time setup

From the project root, install dependencies and create the virtual environment:

```powershell
uv sync
```

To include development tools (pytest):

```powershell
uv sync --dev
```

## Run the application

Recommended — use the installed CLI entry point:

```powershell
uv run film-stockpot
```

Alternative — run as a Python module:

```powershell
uv run python -m film_stockpot
```

Both commands start the PyQt6 desktop window. Close the window or press `Ctrl+C` in the terminal if the process does not exit on its own.

## Run without `uv run`

You can activate the project virtual environment and run commands directly.

**PowerShell (Windows):**

```powershell
.\.venv\Scripts\Activate.ps1
film-stockpot
```

**bash / zsh (macOS / Linux):**

```bash
source .venv/bin/activate
film-stockpot
```

Deactivate when finished:

```powershell
deactivate
```

## Run tests

From the project root:

```powershell
uv run pytest
```

Verbose output:

```powershell
uv run pytest -v
```

## Common commands

| Task | Command |
|------|---------|
| Install / update dependencies | `uv sync` |
| Run the app | `uv run film-stockpot` |
| Run tests | `uv run pytest` |
| Add a dependency | `uv add <package>` |
| Add a dev dependency | `uv add --dev <package>` |

## Troubleshooting

**`uv` is not recognized**

Install uv and restart your terminal. See the [uv installation docs](https://docs.astral.sh/uv/getting-started/installation/).

**PyQt6 import or DLL errors**

Ensure you are using the project environment, not a system Python:

```powershell
uv sync
uv run film-stockpot
```

If problems persist, remove the local environment and sync again:

```powershell
Remove-Item -Recurse -Force .venv
uv sync
```

**Execution policy blocks venv activation (Windows)**

Run the app with `uv run film-stockpot` instead of activating `.venv`, or adjust PowerShell execution policy for your user account.
