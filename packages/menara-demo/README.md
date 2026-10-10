# menara-demo

A simple local web page that shows what the Menara MCP servers return, for demos. **Not the real command-center UI** (your team builds that) and not a product: no login, no state of its own. **All data is synthetic.**
A simple local web page that shows what the Menara MCP servers return, and lets an agent work the flood incident while you watch, for demos. **Not the real command-center UI** (your team builds that) and not a product: no login, no state of its own. **All data is synthetic.**

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
- **Story tab**: watch an agent work the whole flood incident through the real servers: investigate, record the Incident, request a drone, simulate and apply a tilt, verify with KPIs, roll back a failed fix, recover. **Run live** lets DeepSeek decide each step (needs `DEEPSEEK_API_KEY` in `.env`); **Replay** follows a fixed script with no model and no key. Each tool call and result appears in a timeline (click a result to expand it), together with the model's own commentary. When policy needs a human, **Approve** and **Reject** buttons appear in the timeline; only your click triggers the approval. Pick a preset task or edit it, set the start minute, and **Cancel** any time. A run changes the demo data (an Incident, a drone mission, tilts), so re-seed with the servers stopped for a clean start.
- **Explain this trail**: under a subscriber's trail, a button asks the model to write a short story of their day. The backend gives the model only facts: each stop with its time, and the known sites (from `sites-mcp`) within about 2.5 km of each tower, with distances. The model must use only those places, say "near" never "at", call a long overnight stay "probably home", and say so when no known site is near a tower. It cannot know real places such as a mall or a named school: the sites in the demo data are synthetic (hospital, clinic, police, school, enterprise), and a trail is only cell level, accurate to about a kilometre or more. The facts are shown under the story so you can check it. Real place names would need an external map-data lookup, which is a separate decision.
- **Scene links** for demos: `#kk`, `#tawau`, `#tawau-trail` (opens a commuter's trail), `#story` and `#console`, for example http://127.0.0.1:8200/#tawau-trail.

A banner says DEMO and SYNTHETIC DATA at all times.

## How it works

`menara_demo.app` is a small Starlette app. It starts the servers from `.mcp.json` through `menara_agent.servers.McpHub` (real stdio MCP processes, the same as the DeepSeek test driver) and offers four routes: `GET /` (the page), `GET /api/tools`, `POST /api/call` and `GET`/`POST /api/clock`. The page composes the calls itself (circle search, subscriber lists, trail), so the servers are still never called by each other. The app holds no approver key and no model key; the servers get only the shared dev settings from `.env`, never `DEEPSEEK_API_KEY` or `MENARA_APPROVER_KEY`.
`menara_demo.app` is a small Starlette app. It starts the servers from `.mcp.json` through `menara_agent.servers.McpHub` (real stdio MCP processes, the same as the DeepSeek test driver) and offers `GET /` (the page), `GET /api/tools`, `POST /api/call`, `GET`/`POST /api/clock`, the Story routes (`/api/agent/status`, `run`, `events`, `decision`, `cancel`) and `POST /api/trail/story`. The page composes the map calls itself (circle search, subscriber lists, trail), so the servers are still never called by each other.

**Keys.** The demo app itself holds the model key and the approver key, server-side only. They are never sent to the browser, and the MCP servers get only the shared dev settings from `.env`, never `DEEPSEEK_API_KEY` or `MENARA_APPROVER_KEY`. The model cannot call `policy_approve`, `policy_reject`, `policy_update_setting` or `policy_set_kill_switch`; the runner calls `policy_approve` only after you press Approve. A run goes through the same gate and demo-clock tool as the terminal driver (`menara_agent`). One run at a time.

A tool error comes back as `{ok: false, error}` and the page shows it; a malformed request is a 400, a human-only tool a 403, an unknown tool a 404.

## Tests

```bash
uv run python -m pytest packages/menara-demo
```

They use a fake hub for the routes and one end-to-end test against real stdio servers (a circle search, an area list and a trail through the app).
They use a fake hub and a fake model for the routes, runs, approvals, cancel and trail narration (no network, no key), plus end-to-end tests of **Replay** against real stdio servers on a scratch database, with the approvals pressed by the test.