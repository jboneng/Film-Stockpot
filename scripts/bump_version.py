"""Bump the Film Stockpot major.minor.build version.

Updates ``pyproject.toml`` and ``src/film_stockpot/__init__.py`` together so they
stay in sync. Used by GitHub Actions to auto-increment build numbers on pushes to
main and minor numbers when a release is published.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _ROOT / "pyproject.toml"
_INIT = _ROOT / "src" / "film_stockpot" / "__init__.py"
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _read_pyproject_version() -> tuple[int, int, int]:
    text = _PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version = "(\d+)\.(\d+)\.(\d+)"$', text, re.MULTILINE)
    if not match:
        raise SystemExit(f"Could not find version in {_PYPROJECT}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _format_version(major: int, minor: int, build: int) -> str:
    return f"{major}.{minor}.{build}"


def _write_version(major: int, minor: int, build: int) -> str:
    version = _format_version(major, minor, build)

    pyproject = _PYPROJECT.read_text(encoding="utf-8")
    updated_pyproject, count = re.subn(
        r'^version = "\d+\.\d+\.\d+"$',
        f'version = "{version}"',
        pyproject,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise SystemExit("Failed to update pyproject.toml version")
    _PYPROJECT.write_text(updated_pyproject, encoding="utf-8")

    init_text = _INIT.read_text(encoding="utf-8")
    updated_init, count = re.subn(
        r'^__version__ = "\d+\.\d+\.\d+"$',
        f'__version__ = "{version}"',
        init_text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise SystemExit("Failed to update __init__.py version")
    _INIT.write_text(updated_init, encoding="utf-8")

    return version


def _read_init_version() -> str | None:
    match = re.search(r'^__version__ = "(\d+\.\d+\.\d+)"$', _INIT.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else None


def verify_version_sync() -> str:
    """Return the current version after verifying pyproject.toml and __init__.py match."""
    version = _format_version(*_read_pyproject_version())
    init_version = _read_init_version()
    if init_version != version:
        raise SystemExit(
            f"Version mismatch: pyproject.toml has {version}, "
            f"__init__.py has {init_version or 'missing'}."
        )
    return version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", help="Print the current version and exit")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify pyproject.toml and __init__.py versions match, then print the version",
    )
    parser.add_argument("--build", action="store_true", help="Increment the build number")
    parser.add_argument(
        "--minor",
        action="store_true",
        help="Increment the minor number and reset build to 1",
    )
    parser.add_argument(
        "--major",
        action="store_true",
        help="Increment the major number, reset minor and build to 0 and 1",
    )
    parser.add_argument("--set", metavar="X.Y.Z", help="Set an exact version")
    args = parser.parse_args()

    major, minor, build = _read_pyproject_version()

    if args.verify:
        print(verify_version_sync())
        return

    if args.print:
        print(_format_version(major, minor, build))
        return

    actions = sum(bool(flag) for flag in (args.build, args.minor, args.major, bool(args.set)))
    if actions != 1:
        raise SystemExit("Specify exactly one of --build, --minor, --major, or --set")

    if args.set:
        match = _VERSION_RE.fullmatch(args.set)
        if not match:
            raise SystemExit(f"Invalid version {args.set!r}; expected major.minor.build")
        major, minor, build = int(match.group(1)), int(match.group(2)), int(match.group(3))
    elif args.build:
        build += 1
    elif args.minor:
        minor += 1
        build = 1
    elif args.major:
        major += 1
        minor = 0
        build = 1

    print(_write_version(major, minor, build))


if __name__ == "__main__":
    main()
