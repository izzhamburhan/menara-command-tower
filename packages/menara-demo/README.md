# menara-demo

A simple local web page that shows what the Menara MCP servers return, for demos. **Not the real command-center UI** (your team builds that) and not a product: no login, no state of its own. **All data is synthetic.**

## Run

```bash
uv run python -m menara_core.seed.cli     # once, if data/menara.db does not exist
uv run python -m menara_demo              # starts the 12 MCP servers, then the page
```

Open http://127.0.0.1:8200. Options: `--port 8200`, `--host 127.0.0.1` (keep it local; there is no login), `--servers tower,user` (a subset). Stop it with Ctrl+C so the server processes shut down cleanly. Stop other things that hold `data/menara.db` open (Claude Code's MCP servers, `run_mcp.py`) only if you plan to re-seed.

The map needs internet for its tiles (OpenStreetMap, via Leaflet from a CDN). The towers still draw without it, and the Console tab never needs it.

## What you see

- **Map of Malaysia**, every tower coloured by status (green up, amber degraded, red down). **Click the map** to circle a place and move the radius slider (1 to 50 km).
- **Side panel**: the towers inside the circle (distance, status, sampled and estimated subscribers), then the sampled subscribers with their service label and how many cells they changed in 24 h. **Click a subscriber** to draw their trail on the map and list the cells with arrival and leave times.
- **Presets**: "Kuala Krai (flood)" jumps to clock 12 (the flooded tower is red, its subscribers detached); "Tawau (commuters)" jumps to clock 150 (after the morning commute), where trails have movement.
- **Clock bar**: the scenario time, a minute box, and shortcuts 0, 12, 150, 360 (first ticket, storm complete, after the commute, power restored). It writes the same clock as `scenario_cli`.
- **Console tab**: pick any of the 52 tools, edit the JSON arguments, press Run, read the raw response. The four human-only tools (`policy_approve`, `policy_reject`, `policy_update_setting`, `policy_set_kill_switch`) are not offered and the server refuses them.
- **Scene links** for demos: `#kk`, `#tawau`, `#tawau-trail` (opens a commuter's trail) and `#console`, for example http://127.0.0.1:8200/#tawau-trail.

A banner says DEMO and SYNTHETIC DATA at all times.

## How it works

`menara_demo.app` is a small Starlette app. It starts the servers from `.mcp.json` through `menara_agent.servers.McpHub` (real stdio MCP processes, the same as the DeepSeek test driver) and offers four routes: `GET /` (the page), `GET /api/tools`, `POST /api/call` and `GET`/`POST /api/clock`. The page composes the calls itself (circle search, subscriber lists, trail), so the servers are still never called by each other. The app holds no approver key and no model key; the servers get only the shared dev settings from `.env`, never `DEEPSEEK_API_KEY` or `MENARA_APPROVER_KEY`.

A tool error comes back as `{ok: false, error}` and the page shows it; a malformed request is a 400, a human-only tool a 403, an unknown tool a 404.

## Tests

```bash
uv run python -m pytest packages/menara-demo
```

They use a fake hub for the routes and one end-to-end test against real stdio servers (a circle search, an area list and a trail through the app).