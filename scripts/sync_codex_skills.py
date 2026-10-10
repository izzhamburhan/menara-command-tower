"""Regenerate .codex/skills from .claude/skills. Edit the Claude copy, then run this.

Usage: uv run python scripts/sync_codex_skills.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _skills import CODEX_DIR, OPENAI_YAML, SKILL_FILE, expected_twin, skill_names  # noqa: E402


def sync(root: Path) -> list[str]:
    written: list[str] = []
    claude = skill_names(root, Path(".claude") / "skills")
    for name in claude:
        skill_text, yaml_text = expected_twin(root, name)
        target = root / CODEX_DIR / name
        (target / OPENAI_YAML).parent.mkdir(parents=True, exist_ok=True)
        (target / SKILL_FILE).write_text(skill_text, encoding="utf-8", newline="\n")
        (target / OPENAI_YAML).write_text(yaml_text, encoding="utf-8", newline="\n")
        written.append(name)
    for name in skill_names(root, CODEX_DIR):
        if name not in claude:
            shutil.rmtree(root / CODEX_DIR / name)
            print(f"removed orphan Codex skill: {name}")
    return written


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    written = sync(root)
    print(f"Synced {len(written)} skills to {CODEX_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
