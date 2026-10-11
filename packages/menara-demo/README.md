# menara-demo

A simple local web page that shows what the Menara MCP servers return, and lets an agent work the flood incident while you watch, for demos. **Not the real command-center UI** (your team builds that) and not a product: no login, no state of its own. **All data is synthetic.**

## Run

```bash
uv run python -m menara_core.seed.cli     # once, if data/menara.db does not exist (re-seed after pulling: the data changed)
uv run python -m menara_demo              # starts the 13 MCP servers, then the page
```

Open http://127.0.0.1:8200. Options: `--port 8200`, `--host 127.0.0.1` (keep it local; there is no login), `--servers tower,user` (a subset). Stop it with Ctrl+C so the server processes shut down cleanly, and **restart it after pulling new code**: an old copy keeps serving the old routes, and the page then says so ("probably an old copy. Restart the demo"). Stop other things that hold `data/menara.db` open (Claude Code's MCP servers, `run_mcp.py`) only if you plan to re-seed.

The map needs internet for its tiles (OpenStreetMap, shown dark with a CSS filter, and Leaflet from a CDN). If the tiles cannot load, the dark background, the towers and every story effect still draw, and the Console tab never needs the internet.

## What you see

A dark command-center page: a full-screen map, a stats strip (towers up, degraded and down, tickets in the cluster, incident status), the scenario clock, a legend, a **Reset demo** button, and a side panel with four tabs.

- **Map of Malaysia**, every tower glowing in its status colour (green up, amber degraded, red down, a pulse on the down ones). **Click the map** to circle a place and move the radius slider (1 to 50 km).
- **Map & area tab**: the towers inside the circle (distance, status, sampled and estimated subscribers), then the sampled subscribers with their service label and how many cells they changed in 24 h.
  - **What people use here**: the top 5 apps for the circle (from `usage-mcp`), with a Users/Data toggle, the category split and the busiest hour. Different places have a different leader. It is a **synthetic estimate**: invented numbers, aggregated, never per person, and the app names are only labels (no logos).
  - **Click a subscriber** to draw their last 24 hours on the map and list the cells with arrival and leave times. A bar at the bottom **replays the trail** (Play, Pause, speed, scrubber) with a moving dot and the time.
  - **Routine (last 4 weeks)**: a table of the places this synthetic subscriber returns to, worked out by the backend from four weeks of trail: where they probably live, the weekday places (at least 5 weekdays) and the weekend places (at least 3 weekend days across at least 2 completed weekends), for example `Weekends: near Tawau Mall 1 (synthetic) on 4 of 4 weekends, usually about 2 h 58 min from about 11:00`. A stay under 45 minutes is transit, not a stop. The places are drawn on the map with a letter for their kind. It needs no model key.
  - **Explain this trail (LLM)**: asks the model to write the story from those facts (below).
- **Story tab**: watch an agent work the whole flood incident through the real servers: investigate, record the Incident, request a drone, simulate and apply a tilt, verify with KPIs, roll back a failed fix, recover. **Run live** lets DeepSeek decide each step (needs `DEEPSEEK_API_KEY` in `.env`); **Replay** follows a fixed script with no model and no key (it waits 10 minutes after each tilt before judging it, as a real loop would). Each tool call and result appears in a timeline (click a result to expand it), together with the model's own commentary. When policy needs a human, **Approve** and **Reject** buttons appear in the timeline; only your click triggers the approval. Pick a preset task or edit it, set the start minute, and **Cancel** any time.
  - **The map follows the run.** As each result arrives the map shows it: the tower being checked (red if down, amber if busy), the blast radius ring with at-risk towers and critical sites, the flood area, the drone and its link from the depot, the towers that were tilted, the ticket cluster. The camera flies to it (untick *Camera follows the run* to stop that). Cards marked *on the map* can be clicked to fly back to them. All positions come from the database or the server's own result, never from the model's words.
- **Self-heal tab**: the same run, shown as the self-healing loop. Eight stages light up as the loop goes: **detect, diagnose, simulate, approve, apply, verify, roll back, recover**, with the tilt attempt number on *apply* and *verify*. A chart shows the load (PRB %) of the overloaded neighbour towers against the 85% overload line, with each tilt marked: in the Replay the first tilt does not help and is rolled back, the second brings the load from 91% down to 63%. Tiles show the peak load, the load now, how many tilts were tried and the incident status. **Run self-heal (Replay)** needs no key; **Run live** lets the model drive. Approvals are pressed in the Story tab.
- **Console tab**: pick any of the 55 tools, edit the JSON arguments, press Run, read the raw response. The four human-only tools (`policy_approve`, `policy_reject`, `policy_update_setting`, `policy_set_kill_switch`) are not offered and the server refuses them.
- **Clock bar**: the scenario time, a minute box, and shortcuts 0, 12, 150, 360 (first ticket, storm complete, after the commute, power restored). It writes the same clock as `scenario_cli`.
- **Reset demo** (header): after playing, one click (and a confirmation) removes everything created while playing (incidents, approvals, tilts, drone missions, simulations, notes and the audit log), restarts the id counters (the next incident is `INC-0001` again), restores the policy settings and puts the clock back at T0. The map data is not touched and the servers keep running. It refuses while a run is in progress. The same thing from a terminal: `uv run python -m menara_core.scenario_cli reset-state --yes`.
- **Presets**: "Kuala Krai (flood)" jumps to clock 12 (the flooded tower is red, its subscribers detached); "Tawau (commuters)" jumps to clock 150 (after the morning commute), where trails have movement.
- **Scene links** for demos: `#kk`, `#tawau`, `#tawau-trail` (opens a commuter's trail and routine), `#story`, `#replay` (opens the Story tab and starts a Replay), `#heal` (opens the Self-heal tab and starts a Replay) and `#console`, for example http://127.0.0.1:8200/#heal.

A banner says DEMO and SYNTHETIC DATA at all times.

### How the trail story stays honest

The backend gathers the facts and a model only words them. It gives the model the last day's stops (with their times), the routines it counted over four weeks, and the known sites (from `sites-mcp`) within about 2.5 km of each tower, with distances. The model must use only those places, say "near" never "at", use only the counted routines for habits and never state a frequency that is not in the facts, call a long overnight stay "probably home", say so when no known site is near a tower, and say that the subscriber is synthetic and the routine is inferred from cell-level data. It cannot know real places such as a named school or a real mall: the sites in the demo data are synthetic (hospital, clinic, police, school, enterprise, mall), and a trail is only cell level, accurate to about a kilometre or more. The facts are shown under the story so you can check it. Real place names would need an external map-data lookup, which is a separate decision.

## How it works

`menara_demo.app` is a small Starlette app. It starts the servers from `.mcp.json` through `menara_agent.servers.McpHub` (real stdio MCP processes, the same as the DeepSeek test driver) and offers:

| Route | What |
| --- | --- |
| `GET /` | the page |
| `GET /api/tools`, `POST /api/call` | the tool console |
| `GET`/`POST /api/clock` | the scenario clock |
| `/api/agent/status`, `run`, `events`, `decision`, `cancel` | the Story runs. The events include `{type: "map", step, effects[]}` after a tool result that has something to draw, and `{type: "heal", step, stage, attempt, label}` for each stage of the self-healing loop |
| `GET /api/heal/state` | the loop's state at the scenario clock, read from the servers: the overloaded neighbours' PRB series, the RAN changes (tilts and rollbacks), the incident. Only what has happened by the clock is shown |
| `POST /api/reset` | clear a session (see Reset demo); `409` while a run is in progress. Not an MCP tool, so an agent cannot call it |
| `GET /api/trail/routines?msisdn_hash=&window_min=` | the counted routines and the facts, no model, no key (`window_min` 5 to 40320, default 40320) |
| `POST /api/trail/story` | the same facts, written up by the model |

The page composes the map calls itself (circle search, subscriber lists, trail, usage), so the servers are still never called by each other. The map effects are worked out in `map_effects.py` from the full tool result and the database (read-only), the stages and the loop state in `heal.py`, and the routines in `routines.py`; all plain Python covered by tests.

**Keys.** The demo app itself holds the model key and the approver key, server-side only. They are never sent to the browser, and the MCP servers get only the shared dev settings from `.env`, never `DEEPSEEK_API_KEY` or `MENARA_APPROVER_KEY`. The model cannot call `policy_approve`, `policy_reject`, `policy_update_setting` or `policy_set_kill_switch`; the runner calls `policy_approve` only after you press Approve. A run goes through the same gate and demo-clock tool as the terminal driver (`menara_agent`). One run at a time.

A tool error comes back as `{ok: false, error}` and the page shows it; a malformed request is a 400, a human-only tool a 403, an unknown tool a 404.

## Tests

```bash
uv run python -m pytest packages/menara-demo
```

They use a fake hub and a fake model for the routes, runs, approvals, cancel, reset, map effects, heal stages and state, routines and trail narration (no network, no key), plus end-to-end tests of **Replay** against real stdio servers on a scratch database (the eight stages in order, the failed then the good tilt on the KPI series, and a reset between two runs giving the same ids), with the approvals pressed by the test. `test_page.py` guards the single-file page: it may only load from `unpkg.com` and `tile.openstreetmap.org`, it must keep the hooks the story needs, its text must be readable, it names no real brand and has no logos, and its script must be valid JavaScript (`node` is needed for that one).
