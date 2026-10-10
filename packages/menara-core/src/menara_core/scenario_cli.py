"""`uv run menara-scenario show|set N|advance N|reset` moves the shared scenario clock."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from menara_core import clock, settings
from menara_core.db import connect
from menara_core.errors import MenaraError
from menara_core.scenario import load_scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="menara-scenario", description=__doc__)
    parser.add_argument("command", choices=["show", "set", "advance", "reset"])
    parser.add_argument("minutes", nargs="?", type=int, help="minutes for set/advance")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.command in {"set", "advance"} and args.minutes is None:
        parser.error(f"{args.command} needs a minutes value")

    try:
        conn = connect(args.db or settings.db_path(), owned_tables={"scenario_state"})
        current = clock.now_min(conn)
        if args.command == "set":
            clock.set_now(conn, args.minutes)
        elif args.command == "advance":
            clock.set_now(conn, current + args.minutes)
        elif args.command == "reset":
            clock.set_now(conn, load_scenario(settings.default_scenario_path()).default_now_min)
        print(f"t_min={clock.now_min(conn)}  as_of={clock.as_of(conn)}  (synthetic)")
    except MenaraError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
