---
name: verification-review
description: Use when Menara implementation or a test-only slice is complete and the change may be claimed fixed, complete, or ready for review. Produces fresh evidence before any completion claim.
---

# Verification and Review

Produce fresh evidence that the change matches the approved artifacts and adds no contract,
privacy, ownership, or compatibility regressions. Evidence from earlier in the session does not
count; run the commands again.

## Required checks

1. Compare the diff with the approved spec and plan. Note any difference.
2. Run, from the repo root, and read the output:
   ```bash
   uv run python -m ruff check .
   uv run python -m mypy
   uv run python -m pytest
   ```
3. For a new or changed tool, model, or server, make a real stdio call against a seeded DB, not only unit tests:
   ```bash
   uv run python - <<'PY'
   import asyncio
   from mcp import ClientSession, StdioServerParameters
   from mcp.client.stdio import stdio_client
   async def go():
       p = StdioServerParameters(command="uv", args=["run", "--package", "<server>", "python", "-m", "<module>"])
       async with stdio_client(p) as (r, w), ClientSession(r, w) as s:
           await s.initialize()
           print([t.name for t in (await s.list_tools()).tools])
   asyncio.run(go())
   PY
   ```
4. Seed, schema, or scenario change: `uv run menara-seed` completes (all servers stopped) and `tests/golden_trace` passes.
5. Skill change: `uv run python scripts/check_skill_parity.py`.
6. Review the diff for: wrong table writes, one MCP calling another, missing `Envelope` or `synthetic: true`, unprefixed tool names, privacy leaks, missing tests (happy path, error, boundary), stale README or status tables.

## Required output

- Each command run and its fresh result (pass, fail, counts).
- Tests added or updated.
- Findings by severity with `path:line`, or an explicit "no findings".
- Fixes made, residual risks, and anything skipped with the reason.
- Whether the change is ready for human review.

If any check fails or cannot run, say so plainly and stop short of a completion claim.

## Common mistakes

- Reporting "tests pass" from a run before the last edit.
- Running only the touched server's tests when the seed or `menara-core` changed.
- Skipping the stdio call because unit tests passed.
