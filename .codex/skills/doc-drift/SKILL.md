---
name: doc-drift
description: Use when Menara code or behavior diverges from CLAUDE.md, AGENTS.md, playbook.md or a server README, and after any change that alters layout, rules, contracts, ports, status, tech stack, or process. Keeps the docs and skills current.
---

# Doc Drift

Docs that disagree with the code mislead teammates and agents. After a change, and whenever you
notice a mismatch, reconcile them.

## What to check

| If the change alters | Update |
| --- | --- |
| A server's tools, arguments, models, errors | That server's `README.md` contract table |
| A server's existence or state | The status table in `CLAUDE.md` and `AGENTS.md`; `.mcp.json`; root `pyproject.toml` |
| Ports, transports | The port table in `CLAUDE.md` and `AGENTS.md`, and the server README |
| Layout, commands, rules | `CLAUDE.md` and `AGENTS.md` (they must say the same) |
| Process, gates, validation commands | `playbook.md`, and the lifecycle skills that mention them |
| A skill | Run `uv run python scripts/sync_codex_skills.py`, then `uv run python scripts/check_skill_parity.py` |
| Scenario or seed behavior | The scenario section of `AGENTS.md` and affected READMEs |

## Procedure

1. List the statements in the docs that the change makes untrue or incomplete.
2. Fix them in the same change, not a follow-up.
3. Keep facts in the handbooks and README files. Skills point to them; they do not copy them.
4. Keep `CLAUDE.md` and `AGENTS.md` consistent: the same project, rules, and commands.
5. Update the "Last updated" line if the handbook has one.
6. If a doc statement is wrong and you cannot tell which side is right, ask the developer.

## Common mistakes

- Updating `CLAUDE.md` but not `AGENTS.md`.
- Adding a server but not its `.mcp.json` entry or port.
- Copying a command into three skills so they drift apart.
