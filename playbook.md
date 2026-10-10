# Menara AI-First TDD Playbook

Owner: Izzham Burhan, TMRND. Applies to every change in this repo, by a human or an AI agent.
The root handbook is `CLAUDE.md` (Claude Code) or `AGENTS.md` (Codex and others). This
playbook is the process; the handbook is the facts (layout, rules, commands, ports).

## 1. Purpose

Several people and several agents build MCP servers in one repo, in parallel, against a
fixed demo date. The process exists so that:

- each MCP stays an independent server with a stable, typed contract;
- the shared SQLite file and scenario stay consistent for everyone;
- AI-written code is test-first, verified with fresh evidence, and reviewed by a person;
- all demo data stays synthetic and privacy-safe.

## 2. Core principle

Write the test first, make the smallest change that passes, then prove it with fresh
command output. No claim of "done" without evidence from this session.

## 3. The gates

Every non-trivial change passes these gates in order. Each gate has a skill.

| Gate | What happens | Skill |
| --- | --- | --- |
| 0. Route | Classify the task, pick guards | `menara-workflow` |
| 1. Discovery | Read-only: owner, current behavior, contracts, risks | `change-intake-discovery` |
| 1.5. Workspace | Worktree under `.worktrees/` (default) or a plain branch | `implementation-gate` (setup part) |
| 2. Design spec | Requirements, acceptance criteria, contract, tables, scenario impact. Developer approves | `change-design-spec` |
| 3. TDD plan | Test-first slices with exact failing tests and commands. Developer approves | `tdd-plan` |
| 4. Implementation gate | Workspace clean, baseline green, edit boundary declared | `implementation-gate` |
| 5. Implementation | Red, green, refactor, one slice at a time | guards below |
| 6. Verification | Fresh pytest, ruff, mypy, smoke or golden trace | `verification-review` |
| 6.5. Completion | Developer picks: commit, push, PR, or leave | `completion-checkpoint` |
| 7. Handoff | Honest end-of-task summary | `handoff-summary` |

Guards, used whenever their trigger applies:

- `mcp-contract-guard`: any change under `servers/` or `packages/menara-core/`, any tool, model, table, port or `.mcp.json` change.
- `synthetic-data-guard`: any change to seed data, scenario files, responses that carry subscriber or location data, UI copy, or anything that could read as a claim about real TM systems.
- `doc-drift`: any change that alters layout, rules, contracts, ports, status, or this process.

### Red flags: you are about to violate a gate

| Thought | Reality |
| --- | --- |
| "It is small, I will just edit." | Only a typo, comment or doc-wording change may skip gates. Everything else is classified first. |
| "I know this code already." | Re-read it in this session. Ownership and contracts change fast with several people working. |
| "The tests will pass, I will skip the run." | Claims need fresh output from this session. |
| "I will fix the test to match my change." | Changing a test to go green hides a regression. Change a test only when the approved contract changed. |
| "I will call tower-mcp from ticket-mcp, it is simpler." | MCPs never call each other. The agent orchestrates. Redesign. |
| "I will add one real-looking phone number to the seed." | Seed data is generated and hashed. No real or real-looking personal data. |

## 4. Task buckets

Classify before acting. If more than one applies, start at the earliest stage.

- trivial doc, comment or wording change (the only bucket that may shorten the flow)
- question or clarification
- discovery or code inspection
- requirements, design or planning
- review
- bug investigation or fix
- implementation or refactor
- handoff or delivery summary

The developer may explicitly shorten a named gate ("skip the design spec, it is a one-line
fix"). Never assume it.

## 5. Context to read before any change

1. `CLAUDE.md` or `AGENTS.md`.
2. This playbook, for anything beyond a trivial change.
3. The README (tool contract) of every server the change touches.
4. `packages/menara-core/` modules the change depends on.
5. `data/scenario/kuala_krai.yaml` when behavior over time matters.
6. Existing tests for the area.

## 6. Git and branches

- Base branch: `main`. Work happens on a branch, never directly on `main`.
- Branch names: `feat/<server>-<slug>`, `fix/<server>-<slug>`, `docs/<slug>`, `chore/<slug>`.
- Worktrees: `sh scripts/worktree-add.sh <branch> [--base main]` creates `.worktrees/<branch>`. Several agents can then work in parallel without sharing a checkout. Clean up with `sh scripts/worktree-cleanup.sh`.
- Commits: Conventional Commits with the server as scope, for example `feat(tower-mcp): add tower_get_neighbours`. Do not commit or push unless the developer asked or approved.
- Pull requests: open with `gh pr create`; the body follows `.github/pull_request_template.md`.
- If a git command fails inside an agent sandbox (lock file, permission, network), retry once outside the sandbox; never delete lock files or edit git config to work around it.
- Spec and plan files live in the branch: `docs/specs/<slug>.md`, `docs/plans/<slug>.md`.

## 7. Minimum validation

Run from the repo root. All must pass before a completion claim.

```bash
uv run python -m ruff check .
uv run python -m mypy
uv run python -m pytest
```

Plus, when relevant:

| Change | Extra evidence |
| --- | --- |
| New or changed tool, model or server | A real stdio smoke call (see `verification-review`) |
| Changed seed, schema or scenario | `uv run menara-seed` runs clean; golden trace passes |
| Changed contract between servers | `tests/golden_trace` updated and passing |
| Changed skills | `uv run python scripts/check_skill_parity.py` |

## 8. Definition of Ready

- Owner server or package is named.
- Acceptance criteria are written and testable.
- The tool contract (arguments, `data` shape, errors) is stated.
- Table ownership is clear: which tables are read, which are written, by whom.
- Scenario impact is known (does it change `kuala_krai.yaml` or the clock?).
- Privacy impact is known.

## 9. Definition of Done

- Failing test was written first and seen failing.
- ruff, mypy strict, and pytest pass, shown with fresh output.
- Server README contract, `CLAUDE.md` and `AGENTS.md` status and port tables are current.
- `.mcp.json` and the root `pyproject.toml` register any new server.
- No MCP calls another MCP; each writes only its own tables.
- All data synthetic and labelled; no real personal or TM data.
- The developer chose the completion option and received the handoff summary.

## 10. Review checklist

- Does the diff match the approved spec and plan?
- Is each new tool covered by a happy-path, an error, and a boundary test?
- Is the response wrapped in `Envelope` with `evidence[]` and `synthetic: true`?
- Do tool names carry the domain prefix? Are errors `menara_core.errors` types?
- Are writes limited to tables the server owns?
- Could any field identify a real person? Is location cell-level at most?
- Does a seed or scenario change keep the golden trace and the demo story intact?
- Are docs and skills in sync with the code?

## 11. Enforcement

- CI (`.github/workflows/ci.yml`) runs ruff, mypy, pytest and the skill-parity check on every push and pull request.
- Skills exist for Claude Code (`.claude/skills/`) and Codex (`.codex/skills/`). Edit the Claude copy, then run `uv run python scripts/sync_codex_skills.py`. CI fails if the twins differ.
- `CLAUDE.md` and `AGENTS.md` must describe the same project and rules.