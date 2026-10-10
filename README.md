# Menara Command Center (MCP side)

Synthetic-data MCP servers for a Malaysia network command center (TM AI Elevate hackathon). Every domain is its own installable MCP server.

```bash
uv sync
uv run menara-seed                                  # creates data/menara.db
uv run --package tower-mcp python -m tower_mcp      # run one server over stdio
uv run python -m pytest
```

## Getting started (for the team)

1. `uv sync`, then `uv run menara-seed` to create the synthetic database.
2. Try it with a model: put your own `DEEPSEEK_API_KEY` in a `.env` file at the repo root (gitignored; copy `.env.example`), then
   `uv run python -m menara_agent "Ticket TK-88213 just arrived. Find the cause and blast radius, and record an Incident."`
   When policy asks for a human, the runner prompts you in the terminal. See `packages/menara-agent/README.md`.
3. Or use the 12 servers from any MCP client (Claude Code, Codex): `.mcp.json` already registers them. To run them yourself: `uv run python scripts/run_mcp.py list`, then `uv run python scripts/run_mcp.py tower` (HTTP on its port, endpoint `http://127.0.0.1:8101/mcp`) or `... all`.
4. Move the scenario clock with `uv run python -m menara_core.scenario_cli set 12` (0 = first ticket, 12 = storm complete, 360 = power back).

Notes: `menara_agent` is a small test driver, not the real agent. Everyone's runs write to their own local `data/menara.db`; re-seed (with servers stopped) for a clean start. Use your own API key and never commit `.env`.

See `CLAUDE.md` for the layout, rules and status. Each server's contract is in `servers/<name>-mcp/README.md`.

All data is synthetic.
