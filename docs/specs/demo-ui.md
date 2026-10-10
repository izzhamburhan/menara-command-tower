# Spec and plan: a simple demo interface

Status: approved in chat ("Lets do some interface to see the output, just for demo. Just simple one only"). The developer left the shape open; this takes the map vision from earlier in the conversation, plus a console for raw output.

## Goal

A single local web page that shows what the MCP servers return, for demos. Not a product UI, not the team's real UI, and it adds no MCP tool.

## What it shows

1. **Map of Malaysia** with every tower coloured by status. Click the map to place a circle (radius slider 1 to 50 km). The side panel lists the towers inside (distance, status, sampled and estimated subscribers), then the sampled subscribers (experience label, attached, recent cell changes). Click a subscriber to draw their trail on the map and list the cells with arrival and leave times.
2. **Presets**: "Kuala Krai (flood)" at clock 12 and "Tawau (commuters)" at clock 150.
3. **Clock bar**: shows the scenario time and sets it (minute number, with the usual presets).
4. **Console tab**: pick any tool, edit the JSON arguments, run, see the raw response. The four human-only tools are not offered.
5. A permanent banner: DEMO, SYNTHETIC DATA.

## Design

- New workspace package `packages/menara-demo` (`python -m menara_demo [--port 8200] [--host 127.0.0.1]`). A Starlette app served by uvicorn, both already installed with `mcp`. The page is one static HTML file; the map is Leaflet from a CDN (tiles need internet; towers still draw without it).
- The backend starts all twelve servers through the existing `menara_agent.servers.McpHub` (real stdio MCP processes, the same as the agent uses) and exposes four routes: `GET /`, `GET /api/tools`, `POST /api/call`, `GET`/`POST /api/clock`. The browser composes the calls (radius, lists, trail); the servers are still never called by each other.
- `POST /api/call` refuses `policy_approve`, `policy_reject`, `policy_update_setting` and `policy_set_kill_switch` (403) and unknown tools (404). A tool error comes back as `{ok: false, error}` with status 200 so the page can show it. The backend holds no approver key and no model key.
- The clock route writes only `scenario_state`, like `scenario_cli`.
- Binds to `127.0.0.1` by default. It is a demo tool, with no login.

## Acceptance

1. `GET /` serves the page and it says SYNTHETIC.
2. `/api/tools` lists tools with description and schema and never lists the four human-only tools.
3. `/api/call` returns parsed JSON and a timing; plain-text results come back as text; human-only and unknown tools are refused; a tool error is reported as `ok: false`; a malformed body is 400.
4. `/api/clock` reads and sets the minute; out-of-range or non-integer values are 400.
5. End to end against real stdio servers: a circle search, an area list and a trail all work through the app.
6. Full suite, ruff and mypy stay green. Nothing under `servers/` or `menara-core` changes.

## Out of scope

Authentication, real-time updates, mobile layout polish, the agent chat, approvals in the page, and any write flow beyond what the console already allows.

## Rollout

`uv sync` once, seed the database, then `uv run python -m menara_demo` and open http://127.0.0.1:8200.