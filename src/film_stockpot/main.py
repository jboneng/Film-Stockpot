"""Application entry router — GUI by default, CLI when subcommands are used."""

from __future__ import annotations

import sys

_CLI_COMMANDS = frozenset({"export", "presets"})


def is_cli_invocation(argv: list[str] | None = None) -> bool:
    """Return True when the process should run the CLI instead of the GUI."""
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        return False
    if args[0] in _CLI_COMMANDS:
        return True
    return args[0].startswith("-")


def main() -> int:
    """Launch the GUI or CLI depending on argv."""
    if is_cli_invocation():
        from film_stockpot.cli import main as cli_main

        return cli_main()
    from film_stockpot.app import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
