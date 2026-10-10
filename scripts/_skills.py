"""Shared helpers for the Claude/Codex skill twins. The Claude copy is the source of truth."""

from __future__ import annotations

import json
import re
from pathlib import Path

CLAUDE_DIR = Path(".claude") / "skills"
CODEX_DIR = Path(".codex") / "skills"
SKILL_FILE = "SKILL.md"
OPENAI_YAML = Path("agents") / "openai.yaml"
SHORT_DESCRIPTION_MAX = 110


def to_codex(text: str) -> str:
    """Codex reads AGENTS.md. Lines that already name AGENTS.md are left alone."""
    return "\n".join(
        line if "AGENTS.md" in line else line.replace("CLAUDE.md", "AGENTS.md") for line in text.split("\n")
    )


def frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group(1).split("\n"):
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def _short(description: str) -> str:
    first = re.split(r"(?<=[.!?])\s", description, maxsplit=1)[0].rstrip(".")
    return first if len(first) <= SHORT_DESCRIPTION_MAX else first[: SHORT_DESCRIPTION_MAX - 3].rstrip() + "..."


def openai_yaml(name: str, description: str) -> str:
    acronyms = {"tdd": "TDD", "mcp": "MCP"}
    title = " ".join(acronyms.get(word, word.capitalize()) for word in name.split("-"))
    short = _short(description)
    prompt = f"Use ${name} to handle this Menara task."
    return (
        "interface:\n"
        f"  display_name: {json.dumps(title, ensure_ascii=False)}\n"
        f"  short_description: {json.dumps(short, ensure_ascii=False)}\n"
        f"  default_prompt: {json.dumps(prompt, ensure_ascii=False)}\n"
        "\n"
        "policy:\n"
        "  allow_implicit_invocation: true\n"
    )


def skill_names(root: Path, base: Path) -> list[str]:
    folder = root / base
    return sorted(p.name for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else []


def expected_twin(root: Path, name: str) -> tuple[str, str]:
    """(SKILL.md text, openai.yaml text) the Codex twin must have for a Claude skill."""
    source = (root / CLAUDE_DIR / name / SKILL_FILE).read_text(encoding="utf-8")
    meta = frontmatter(source)
    return to_codex(source), openai_yaml(name, meta.get("description", ""))