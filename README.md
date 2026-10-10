# Menara Command Center (MCP side)

Synthetic-data MCP servers for a Malaysia network command center (TM AI Elevate hackathon). Every domain is its own installable MCP server.

```bash
uv sync
uv run menara-seed                                  # creates data/menara.db
uv run --package tower-mcp python -m tower_mcp      # run one server over stdio
uv run python -m pytest
```

See `CLAUDE.md` for the layout, rules and status. Each server's contract is in `servers/<name>-mcp/README.md`.

All data is synthetic.
