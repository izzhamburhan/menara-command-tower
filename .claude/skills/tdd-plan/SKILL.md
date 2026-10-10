---
name: tdd-plan
description: Use when a Menara design spec is approved and a feature, bug fix, refactor, or test-only change needs a test-first implementation plan before editing.
---

# TDD Implementation Plan

Convert the approved spec into small, independently testable, test-first slices. Do not edit
production code while writing the plan.

## Required inputs

- The approved spec in `docs/specs/<slug>.md`.
- `CLAUDE.md`, `playbook.md` §7 (minimum validation), and the existing tests for the area.

## Plan contents

Write `docs/plans/<slug>.md`. For every slice give:

1. exact files to create, modify, and test;
2. interfaces consumed and produced (function signatures, models);
3. the failing test to write first, by file and test name;
4. the command and the expected red result, for example
   `uv run python -m pytest servers/tower-mcp/tests/test_tools.py::test_x` failing with `AttributeError`;
5. the minimal implementation to turn it green;
6. the refactor after green, if any;
7. validation commands for the slice and a review checkpoint.

Order slices so each leaves the suite green: `menara-core` and seed first, then tool logic in
`tools.py`, then `server.py` registration, then README, `.mcp.json`, and docs. Put the
server-level test (tool registered, envelope returned) and the golden-trace change in the plan
whenever the contract changes.

Include the global constraints: tables each server may write, privacy rules, `mcp[cli]>=1.9,<2`,
and the scope boundary (files that must not change).

## Exit condition

Self-review for spec coverage, placeholders, signature consistency, and unbounded scope. Get
explicit developer approval of the plan, then continue with `implementation-gate`.

## Common mistakes

- Writing "add tests" without naming the test and its expected failure.
- Slices that leave the suite red between steps.
- Planning the implementation before the spec is approved.
- Forgetting the real stdio smoke call and the golden trace when a contract changes.
