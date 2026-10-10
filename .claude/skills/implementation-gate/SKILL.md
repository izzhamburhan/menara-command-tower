---
name: implementation-gate
description: Use when Menara code edits are imminent, and also at Gate 1.5 to set up the ticket workspace. Confirms the workspace, a green baseline, and the exact edit boundary before any file is changed.
---

# Implementation Gate

No file is edited until this gate passes. It has two parts: set up the workspace, then confirm readiness.

<HARD-GATE>
Do not edit code until the workspace is ready, the baseline is known, and the edit boundary
below is declared and accepted.
</HARD-GATE>

## Part 1: Workspace (Gate 1.5, right after discovery and before the first file is written)

1. Ask once per task, with the question tool, which workspace the developer wants. First option: **Worktree under `.worktrees/` (Recommended)**, because agents often run in parallel. Alternative: a plain branch in the current checkout.
2. Pick the branch name from `playbook.md` §6 (`feat/<server>-<slug>`, and so on). Base is `main`.
3. Worktree: `sh scripts/worktree-add.sh <branch> --base main`. Work only inside the path it prints. Do not hand-roll `git worktree add`.
4. Plain branch: a dirty checkout is a blocker. Stop and ask, offering the worktree instead.
5. Reuse an existing branch or worktree for the same task instead of creating a second one.
6. Every later write, command, and commit for the task happens inside that workspace.

## Part 2: Readiness (immediately before edits)

1. `git status --short` in the workspace is clean, or the dirt is the declared task. Report whether the base branch has moved on.
2. `uv sync`, then baseline validation from `playbook.md` §7. Report any failure that exists **before** your change; do not fix unrelated failures silently.
3. Declare the **edit boundary**: the exact files you will create or modify, the tables each server may write, and the files that must not change. Compare it with the approved plan.
4. If the work needs `data/menara.db`, check it exists and was seeded from the current scenario; re-seed only with all MCP servers stopped.

## Output

Report: workspace path and branch, base state, baseline result, and the edit boundary. Then
start the first red test from the plan.

## Common mistakes

- Editing in the shared checkout because "it is quick".
- Skipping the baseline, then being unable to tell which failures are new.
- Letting the boundary grow during implementation without updating the plan.
