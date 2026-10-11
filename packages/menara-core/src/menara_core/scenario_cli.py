"""`uv run menara-scenario show|set N|advance N|reset` moves the shared scenario clock.

`reset-state [--yes]` goes further: it removes everything agents and people created (incidents, approvals, tilts,
drone missions, notes, the audit log), restarts the id counters and restores the policy defaults and the clock.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from menara_core import clock, settings
from menara_core.db import connect
from menara_core.errors import MenaraError
from menara_core.reset import reset_runtime_state
from menara_core.scenario import load_scenario


def _reset_state(db_path: Path, *, assume_yes: bool) -> int:
    if not assume_yes:
        if not sys.stdin.isatty():
            print("error: reset-state removes incidents, approvals, tilts and notes; pass --yes to confirm", file=sys.stderr)
            return 2
        if input("Remove everything created while playing and restore the defaults? [y/N] ").strip().lower() != "y":
            print("nothing changed")
            return 1
    try:
        deleted = reset_runtime_state(db_path, load_scenario(settings.default_scenario_path()))
    except MenaraError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for table, rows in deleted.items():
        print(f"{table}: {rows} removed")
    print("policy settings and the clock are back to their defaults (synthetic)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="menara-scenario", description=__doc__)
    parser.add_argument("command", choices=["show", "set", "advance", "reset", "reset-state"])
    parser.add_argument("minutes", nargs="?", type=int, help="minutes for set/advance")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--yes", action="store_true", help="reset-state: do not ask first")
    args = parser.parse_args(argv)
    if args.command in {"set", "advance"} and args.minutes is None:
        parser.error(f"{args.command} needs a minutes value")

    if args.command == "reset-state":
        return _reset_state(args.db or settings.db_path(), assume_yes=args.yes)
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
