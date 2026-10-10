---
name: change-intake-discovery
description: Use when starting a non-trivial Menara change and the current behavior, owning server, contracts, or risks are not yet established. Read-only discovery before any spec, plan, or edit.
---

# Change Intake and Discovery

Establish facts before proposing anything. This skill is read-only: no edits, no branches, no files.

## Required inputs

- `AGENTS.md` and `playbook.md`.
- The README (tool contract) of each server the request could touch.
- `packages/menara-core/` modules involved (envelope, db, clock, ids, privacy, seed).
- `data/scenario/kuala_krai.yaml` when behavior over time matters.

## Establish

1. **Request, restated.** One or two sentences in your own words.
2. **Owner.** Which server or package owns this. New domain means a new server; shared behavior means `menara-core`. If it fits neither, say so.
3. **Current behavior.** What the code does today, with `path:line` references. Run read-only commands (for example `uv run python -m menara_core.scenario_cli show`) when that helps.
4. **Contracts touched.** Tool names and arguments, response models, tables read and written, ports, `.mcp.json` entries, scenario fields.
5. **Dependencies.** Other servers or the golden trace that could be affected. Remember: no MCP calls another.
6. **Risks.** Privacy, synthetic-data labelling, scenario consistency, backward compatibility for teammates' agents.
7. **Open questions.** Only those the developer can resolve. Ask them one at a time with the question tool.

## Exit condition

Report the findings in chat as a short discovery note (owner, current behavior, contracts,
risks, open questions) and wait for the developer's go-ahead. Then continue with
`change-design-spec`, or `implementation-gate` if the developer says the change is small
enough to skip the spec and plan.

## Common mistakes

- Proposing a solution before the owner is known.
- Reading only one server when the change crosses the shared SQLite file or a scenario.
- Treating an assumption as a finding. Mark assumptions as assumptions.
