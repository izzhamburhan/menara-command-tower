"""Fail when .codex/skills is not an exact regeneration of .claude/skills.

Usage: uv run python scripts/check_skill_parity.py
Fix:   uv run python scripts/sync_codex_skills.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _skills import (  # noqa: E402
    CLAUDE_DIR,
    CODEX_DIR,
    OPENAI_YAML,
    SKILL_FILE,
    expected_twin,
    frontmatter,
    skill_names,
    to_codex,
)

__all__ = ["check", "main", "to_codex"]


def check(root: Path) -> list[str]:
    problems: list[str] = []
    claude = skill_names(root, CLAUDE_DIR)
    codex = skill_names(root, CODEX_DIR)
    problems += [f"{n}: missing under {CODEX_DIR}" for n in claude if n not in codex]
    problems += [f"{n}: exists under {CODEX_DIR} but not under {CLAUDE_DIR}" for n in codex if n not in claude]
    for name in claude:
        source = root / CLAUDE_DIR / name / SKILL_FILE
        if not source.is_file():
            problems.append(f"{name}: no {SKILL_FILE} under {CLAUDE_DIR}")
            continue
        meta = frontmatter(source.read_text(encoding="utf-8"))
        if meta.get("name") != name:
            problems.append(f"{name}: frontmatter name is {meta.get('name')!r}, expected {name!r}")
        if not meta.get("description"):
            problems.append(f"{name}: frontmatter description is missing")
        if name not in codex:
            continue
        skill_text, yaml_text = expected_twin(root, name)
        twin = root / CODEX_DIR / name
        for rel, expected in ((Path(SKILL_FILE), skill_text), (OPENAI_YAML, yaml_text)):
            path = twin / rel
            if not path.is_file():
                problems.append(f"{name}: missing {CODEX_DIR / name / rel}")
            elif path.read_text(encoding="utf-8") != expected:
                problems.append(f"{name}: {rel} differs from the Claude skill (run scripts/sync_codex_skills.py)")
    return problems


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    problems = check(root)
    for problem in problems:
        print(f"skill-parity: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"skill-parity: {len(skill_names(root, CLAUDE_DIR))} skills in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
