from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_SKILLS = {
    "menara-workflow",
    "change-intake-discovery",
    "change-design-spec",
    "tdd-plan",
    "implementation-gate",
    "verification-review",
    "completion-checkpoint",
    "handoff-summary",
    "mcp-contract-guard",
    "synthetic-data-guard",
    "doc-drift",
}


def _load(name: str) -> ModuleType:
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parity = _load("check_skill_parity")
sync = _load("sync_codex_skills")


def test_repo_skills_are_in_sync() -> None:
    assert parity.check(ROOT) == []


def test_the_lean_skill_set_is_present_on_both_platforms() -> None:
    claude = {p.name for p in (ROOT / ".claude" / "skills").iterdir() if p.is_dir()}
    codex = {p.name for p in (ROOT / ".codex" / "skills").iterdir() if p.is_dir()}
    assert claude == codex == EXPECTED_SKILLS


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / ".claude", tmp_path / ".claude")
    shutil.copytree(ROOT / ".codex", tmp_path / ".codex")
    return tmp_path


def test_a_one_sided_edit_is_reported(sandbox: Path) -> None:
    skill = sandbox / ".claude" / "skills" / "tdd-plan" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nExtra line.\n", encoding="utf-8")
    problems = parity.check(sandbox)
    assert len(problems) == 1 and "tdd-plan" in problems[0]


def test_sync_repairs_drift_and_removes_orphans(sandbox: Path) -> None:
    skill = sandbox / ".claude" / "skills" / "tdd-plan" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nExtra line.\n", encoding="utf-8")
    orphan = sandbox / ".codex" / "skills" / "gone"
    orphan.mkdir()
    (orphan / "SKILL.md").write_text("x", encoding="utf-8")
    sync.sync(sandbox)
    assert parity.check(sandbox) == []
    assert not orphan.exists()


def test_missing_codex_twin_is_reported(sandbox: Path) -> None:
    shutil.rmtree(sandbox / ".codex" / "skills" / "doc-drift")
    assert any("doc-drift" in p for p in parity.check(sandbox))


def test_claude_md_is_renamed_for_codex_except_on_lines_naming_both() -> None:
    to_codex = parity.to_codex
    assert to_codex("Read `CLAUDE.md`.") == "Read `AGENTS.md`."
    both = "Keep `CLAUDE.md` and `AGENTS.md` consistent."
    assert to_codex(both) == both