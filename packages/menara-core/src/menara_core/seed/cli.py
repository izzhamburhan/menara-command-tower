"""`uv run menara-seed` writes data/menara.db. Stop all MCP servers first."""

from __future__ import annotations

import argparse
from pathlib import Path

from menara_core import settings
from menara_core.scenario import load_scenario
from menara_core.seed.build import DEFAULT_SEED, DEFAULT_TOWER_COUNT, build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="menara-seed", description=__doc__)
    parser.add_argument("--db", type=Path, default=None, help="output file (default: data/menara.db)")
    parser.add_argument("--scenario", type=Path, default=None, help="scenario YAML")
    parser.add_argument("--towers", type=int, default=DEFAULT_TOWER_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)

    db_path = args.db or settings.db_path()
    scenario = load_scenario(args.scenario or settings.default_scenario_path())
    counts = build(db_path, scenario, towers=args.towers, seed=args.seed)
    print(f"Seeded {db_path} (synthetic, seed={args.seed}, scenario={scenario.name})")
    for table, count in counts.items():
        print(f"  {table}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
