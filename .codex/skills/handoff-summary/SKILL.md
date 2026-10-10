---
name: handoff-summary
description: Use at the end of any AI-assisted implementation task in the Menara repo to produce the required honest handoff summary: what changed, tests and results, compatibility, risks, and what still needs the developer.
---

# Handoff Summary

Every AI-assisted task ends with a concise, honest summary. Use this shape.

## Cover

- **Summary.** The behavior change, in plain language, then the technical change.
- **Files changed.** Path and reason for each.
- **Tests.** Added or updated tests, the commands run, and pass, fail, or blocked for each. Include counts from the fresh run.
- **Verification evidence.** ruff, mypy, pytest, stdio smoke, golden trace: which ran, which were skipped, and why.
- **Git status.** Branch or worktree, whether the work is committed, whether it is pushed, PR status, and any approval still needed from the developer.
- **Compatibility and rollout.** What teammates must do after merging: re-seed, restart servers, update `.mcp.json`. Changes to tool names, arguments, `data` models, tables, ports, or scenario content.
- **Docs and skills.** Which docs and skills were updated, or "none needed".
- **Risks and follow-ups.** Known risks, or "none known".

## Rules

- Be specific. Do not hide failed or skipped validation; say what was skipped and why.
- Say plainly whether commit and push are pending the developer's approval.
- If another developer continues the work (for example a teammate building the agent that consumes the tools), give actionable notes: tool names, example calls, error cases, known gaps.
- Mention that all data is synthetic only when the change touches data or UI copy.
