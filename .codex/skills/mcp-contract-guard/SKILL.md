---
name: mcp-contract-guard
description: Use when a Menara change touches servers/, packages/menara-core/, a tool or response model, a SQLite table, a port, or .mcp.json. Verifies each MCP stays an independent server with a typed, documented, tested contract and owns only its own tables.
---

# MCP Contract Guard

Each MCP is a separate, independently installable server. Teammates and agents depend on the
contract. Check every item before design approval, before edits, and again at verification.

## Independence

- The server depends only on `menara-core`, plus `mcp[cli]>=1.9,<2`. No import of another server.
- No MCP calls another MCP, over the network or in process. The agent orchestrates.
- Cross-domain reads are read-only and limited: `ontology-mcp`, `twin-mcp` and `policy-mcp` read base tables to compute impact themselves; `ran-mcp` reads `cell` and `tower`; `drone-mcp` reads `tower`; `user-mcp` reads `tower_subscribers` for the population estimate; `tower-mcp` and `ontology-mcp` apply `ran_kpi_effect` via `menara_core.kpi_overlay`. List what a new server reads in its README, and do not widen the list without the developer's approval.
- Entry points: `python -m <module>` works, stdio by default, `--transport streamable-http` with the port from the `AGENTS.md` port table. `.mcp.json` uses `python -m`, never the console-script `.exe`.

## Data ownership

- Everyone reads the shared `data/menara.db`. Writes go through `menara_core.db.connect(path, owned_tables={...})`, so the SQLite authorizer enforces ownership.
- A table has exactly one owning server. A server with no owned tables opens read-only.
- Base tables are written only by the seed. Changing the schema or seed means: update `seed/schema.py`, re-run `uv run menara-seed`, run every server's tests and the golden trace.
- State that changes over time lives in the scenario clock and timeline tables, not in memory.

## Tool contract

- Tool names are domain-prefixed (`tower_get_status`, `ticket_add_note`).
- Every tool returns `Envelope` dumped as JSON: `synthetic: true`, `as_of`, `data`, `evidence[]`, `warnings[]`. Evidence names source, tool, call id, ref, confidence, as_of.
- Real data readiness: `tower-mcp` is the pattern (tools call a `TowerSource` interface; SQLite and HTTP implementations). A server that gets a real source must set `synthetic: false` on its envelopes (`wrap_at(..., synthetic=False)`) and document its upstream contract.
- Logic lives in `tools.py` as plain functions; `server.py` only registers and wraps them. Models live in `models.py`, fully typed (mypy strict).
- Validate inputs with `menara_core.ids` parsers and range checks; raise `InvalidInputError`, `NotFoundError`, or another `menara_core.errors` type.
- Time-dependent results respect the scenario clock: nothing appears before the clock reaches it.
- Large results have a `limit`, a `truncated` flag, and a warning, while keeping full totals where that matters.
- Real-world write actions (action MCPs) must verify an HMAC policy token locally with `menara_core.tokens` (action and `target_key` of the towers); they never call policy-mcp. Anything that approves, rejects, or switches the kill switch off needs `MENARA_APPROVER_KEY`, which an agent must never hold.

## Documentation and registration

- The server README holds the tool contract table and a run section, and stays current.
- `.mcp.json`, root `pyproject.toml` (`dev` group and `tool.uv.sources`), and the status and port tables in `CLAUDE.md` and `AGENTS.md` list the server.
- A contract change is communicated in the handoff summary, since teammates' agents depend on it.

## Tests

- Tool-level tests for happy path, error, and boundary cases; a server-level test that the tools are registered and an envelope comes back.
- `tests/golden_trace` updated whenever a cross-server flow or the seed changes.
- Tests were written first and seen failing.

## Common mistakes

- Adding a convenience import from a sibling server.
- Writing to a base table "just for the demo".
- Returning raw dicts or skipping the envelope.
- Calling the console script in `.mcp.json`.
- Using the folder name `mcp` for a directory: it shadows the real `mcp` library under pytest.