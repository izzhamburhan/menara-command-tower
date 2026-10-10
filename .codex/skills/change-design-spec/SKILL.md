---
name: change-design-spec
description: Use when Menara discovery is done and requirements, acceptance criteria, the tool contract, table ownership, or scenario impact need to be decided and approved before planning.
---

# Requirements and Design Spec

Turn discovery into one reviewable spec. Do not edit production code while writing it.

## Required inputs

- The discovery note from `change-intake-discovery`.
- `AGENTS.md`, `playbook.md` (§8 Definition of Ready), and the touched servers' READMEs.

## Spec contents

Write `docs/specs/<slug>.md` in the ticket workspace (create `docs/specs/` if needed):

1. **Goal and non-goals.**
2. **Acceptance criteria.** Numbered, each one testable. Include error and boundary cases.
3. **Tool contract.** For each new or changed tool: name (domain-prefixed), arguments with types and ranges, `data` model, error types from `menara_core.errors`, and what goes into `evidence[]`.
4. **Data.** Tables read, tables written, and the owning server for each. Schema or seed changes, with their effect on every other server. New tables are owned by exactly one server.
5. **Scenario impact.** Changes to `kuala_krai.yaml`, the clock, or what is visible at T0 versus later.
6. **Privacy.** Any identifier or location in the response. Must be hashed MSISDN, cell-level at most, with aggregates under 5 suppressed.
7. **Ports and registration.** Port from the table in `AGENTS.md`, the `.mcp.json` entry, root `pyproject.toml` entries.
8. **Alternatives considered** and why the chosen design wins, briefly.
9. **Rollout.** What teammates must do after merging (re-seed, restart servers).

## Exit condition

Self-review for placeholders, contradictions, and untestable criteria. Show the spec to the
developer, get explicit approval, and only then continue with `tdd-plan`. Commit the spec
only when the developer approves committing.

## Common mistakes

- Acceptance criteria that cannot fail.
- Letting two servers write the same table.
- Changing the seed without listing which other servers' tests it affects.
- Leaving the port or `.mcp.json` registration for later.
