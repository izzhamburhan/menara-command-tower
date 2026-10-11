approve# Spec: demo wow (live map, bolder UI, weekly routines)

Owner: Izzham Burhan, TMRND. Branch `feat/demo-wow`. All data is synthetic.

## 1. Goal and non-goals

**Goal.** Three changes requested after the first live runs:

1. **The map follows the story.** While an agent runs (live or replay), the Map shows what it is looking at: the tower it checks, the blast radius, the drone, the flood point, the tilted neighbours. The Story panel is no longer the only place where anything happens.
2. **A bolder look.** A dark command-center theme with glow, pulsing alarms, animated trails and a stats strip, so the demo lands in the first ten seconds.
3. **Routines in a trail story.** For one subscriber, show *which places they go and how often*: weekday school/hospital/work stops, and a weekend habit such as "near Mall X on 4 of the last 4 weekends". This needs a synthetic `MALL` site kind and four weeks of synthetic movement.

**Non-goals.**
- No real place names, no real malls or schools. The model may only use sites that come from `sites-mcp`.
- No change to the scenario (`kuala_krai.yaml`), the clock, policy, or any write tool.
- No new MCP, port or `.mcp.json` entry.
- The last two days of every mover's movement (from minute -1440 on) stay exactly as they are today. The new history only comes before them.
- No WebSocket, no new JS framework, no build step. The page stays one HTML file.
- No browser automation framework (no Playwright) in this change.

## 2. Acceptance criteria

### A. Seed (menara-core)

1. `critical_site.kind` accepts `MALL`. Every town that has sites gets exactly one `MALL`, named `<Town> Mall <n> (synthetic)`, with priority 4, `emergency_service = 0`, serving the nearest non-cluster tower of that town. Existing site ids and names do not change (the mall is appended after the existing kinds).
2. Adding malls does not change any older table: the "old tables unchanged" hashes in `test_movement.py` and the seed tests still match (malls draw from their own random stream).
3. History start: every subscriber's first `subscriber_cell_visit` row is at minute `-40320` (28 days before T0, Saturday 2026-10-17 07:00). Stayers keep a single row there; they were already one row.
4. For every mover, the rows with `start_min >= -1440` are identical to today's seed (same towers, same minutes, same cells).
5. Weekdays (Mon to Fri) in the history follow the existing commute shape (home, tower on the way if any, work, and back), with their own jitter.
6. Weekends (Sat and Sun, four weekends: 4 x 2 days) in the history: a mover with a mall tower 3 to 25 km from home is a *mall regular* with probability 0.4. A mall regular visits the mall's serving tower on one of the two weekend days, on about 80% of weekends, for 2 to 4 hours. Other movers stay home on weekends, with a 10% chance per weekend of one mall visit. Movers with no mall in range always stay home.
7. No two consecutive visits of one subscriber are on the same tower (the history ends with the existing `-1440` home row, so the evening return of day -2 is not duplicated).
8. Same seed gives the same history. In a default-size seed, at least 25% of the movers who have a mall in range have at least one weekend mall visit, and no row has `start_min > 480` (unchanged).
9. `uv run menara-seed` finishes clean. The seed time and the database size increase are measured and reported. If the database would exceed 100 MB, the history shortens to 21 days (3 weekends) and the spec is updated.

### B. sites-mcp

10. `MALL` is a valid `kind` in `sites_list_in_bbox` and in the `SiteKind` model. `sites_get_site` and `sites_for_tower` return it with priority 4, `emergency_service: false`, `sla_customer: false`.
11. An unknown kind (for example `ZOO`) is still `InvalidInputError`. The README, the tool descriptions and the sites table in `CLAUDE.md` and `AGENTS.md` say `MALL` exists.

### C. user-mcp

12. `user_get_trail` accepts `window_min` from 5 to 40320 (was 2880). Over 40320 is `InvalidInputError("window_min must be between 5 and 40320")`. The default stays 1440.
13. With `window_min=40320` at the T0 clock, a mover's trail spans four weekends and `segments` stay oldest first, contiguous (`left_at` of one equals `arrived_at` of the next), with exactly one `current` segment.
14. `user_get_experience`, `user_list_in_area`, `user_list_on_tower` and the "current cell" logic return the same results as before (the latest visit that has started).

### D. Demo backend (menara-demo)

15. **Map effects.** Each tool result in a run produces, in addition to the existing `call` and `result` events, at most one `{"type": "map", "step": N, "effects": [...]}` event. An effect is `{kind, lat, lng, label, tone}` where `kind` is `focus`, `pin`, `ring`, `link` or `area`, and `tone` is `ok`, `warn`, `bad` or `info`. Coordinates come from the demo's read-only database (tower and site coordinates), never from the model.
16. The effects table:
    - Any tool whose arguments or result name a tower (`enodeb_name`, `site`, `targets[]`, `changes[].enodeb_name`): `focus` on that tower. A DOWN tower is `bad`, a tower above 85% PRB or degraded is `warn`, otherwise `ok`.
    - `ontology_blast_radius`: a `ring` around the failed tower, and a `pin` for each affected tower and critical site (capped at 40).
    - `flood_get_gauge`, `flood_check_point`: an `area` (circle) at the gauge or point, `warn` or `bad` by level.
    - `drone_dispatch`, `drone_get_mission`: a `pin` at the tower with `info` tone, and a `link` from the drone base to the tower when the mission data has one.
    - `ran_tilt_cells`, `ran_revert_change`: `focus` on each changed tower.
    - `ticket_cluster_by_location`: a `pin` per ticket location (capped at 40).
    - Unknown tools, errors, and results the code cannot parse produce no `map` event and never crash the run.
17. A map event never carries a subscriber hash or MSISDN.
18. **Habit facts.** `POST /api/trail/story` fetches `user_get_trail` with `window_min = 40320`. The backend computes the facts, not the model: for each tower where the subscriber stayed at least 30 minutes, `weekday_days`, `weekend_days`, `weekend_days_in_window`, `typical_arrival_hour`, `typical_minutes`, and the nearby sites with distances and coordinates (as now, plus lat/lng and the new `MALL` kind). A `routines[]` list holds one deterministic sentence per regular place, for example `Weekends: near Tawau Mall 3 (synthetic) on 4 of 4 weekends, usually about 2 h 30 min from about 11:00`.
19. A routine is only produced when the pattern is backed by the numbers: a weekend routine needs the tower visited on at least 3 weekend days in the window and at least 2 distinct weekends; a weekday routine needs at least 5 weekdays. Otherwise the place is listed as an occasional stop, not a habit.
20. The model prompt keeps the existing rules and adds: use only `routines[]` and `nearby_sites` for habits; never state a frequency that is not in the facts; say "near", not "at"; mention that the subscriber is synthetic. The facts and the deterministic routines are returned with the story so they can be checked.
21. The story endpoint's `window_min` validation is 5 to 40320 and the default is 40320. Errors map as before (400 bad input, 404 unknown subscriber, 503 no key, 502 model failure).
22. `GET /api/trail/routines` (no model, no key): returns the same facts and `routines[]` without calling the model, so the page shows the routine table even when there is no key. Same errors except 503.

### E. Demo page (menara-demo, `index.html`)

23. **Story drives the map.** On a `map` event the page switches the left side to the incident view and: flies to the first effect (once per step, with a duration of at most 1.2 s), draws the effects with a fade-in, and keeps them until the run ends or a new run starts. Replay and live both do this. The timeline cards keep working as today, and clicking a card focuses its effects on the map.
24. The map is never blank for lack of tiles: if the tile server fails, the dark background and all markers still show.
25. **Look.** A dark command-center theme (map tiles, panels and timeline), a header stats strip (towers up, down, degraded, open tickets, incident status, clock) that refreshes when the clock changes, glow and a pulse on DOWN towers, a legend, and a prominent `DEMO · SYNTHETIC DATA` badge. Colors come from CSS variables; body text contrast is at least 4.5:1. `prefers-reduced-motion` turns off the pulse and fly animations.
26. **Trail replay.** A subscriber's trail is drawn with an animated dashed line and a moving dot that replays the day with the time shown, with Play/Pause and a speed control.
27. **Routine panel.** Under a trail, a "Routine" table lists each regular place (icon by kind, name, weekday or weekend pattern, typical time) from `/api/trail/routines`, and the regular places are drawn on the map with the kind icon. The `Explain this trail (LLM)` button stays and gets the same facts. All of it says "synthetic subscriber, cell-level, inferred pattern".
28. The page loads no script or style from any host other than the ones listed in section 7. A test fails if a new host appears.

### F. Regression

29. The golden trace passes unchanged. The Replay end-to-end test passes unchanged. 423 existing tests pass, except the ones named in section 4.
30. ruff, mypy strict, pytest, skill parity: clean.

## 3. Tool contract

No new MCP tool. Changes to existing tools:

| Tool | Change |
| --- | --- |
| `sites_list_in_bbox` | `kind` filter accepts `MALL` |
| `sites_get_site`, `sites_for_tower` | may return `kind: "MALL"`, `priority: 4`; `counts_by_kind` may include `MALL` |
| `user_get_trail` | `window_min` range 5 to 40320 (was 5 to 2880); response shape unchanged |

Errors stay `menara_core.errors` types (`InvalidInputError`). `evidence[]` is unchanged.

New demo-only routes (not MCP):

| Route | Request | Response |
| --- | --- | --- |
| `GET /api/trail/routines?msisdn_hash=&window_min=` | hash (16 hex), window 5 to 40320 | `{ok, facts, routines[]}` |
| `POST /api/trail/story` | as before, window default 40320 | `{ok, story, model, facts, routines[]}` |
| `GET /api/agent/events` | as before | adds events `{type: "map", step, effects[]}` |

## 4. Data

| Table | Read by | Written by | Change |
| --- | --- | --- | --- |
| `critical_site` | sites-mcp, ontology, twin, policy, demo (read-only) | seed only | new kind `MALL` (CHECK), one per town |
| `subscriber_cell_visit` | user-mcp, demo (read-only, through MCP) | seed only | history from minute -40320; ~12x more rows for movers |

No new tables, and no server gains a write table. The demo reads tower and site coordinates through its own read-only SQLite connection, as it does for the clock today.

**Other servers affected by the seed change:** sites-mcp (kind list, counts), user-mcp (trail window, tests), ontology/twin/policy (read `critical_site`: blast-radius counts must not change; malls are not emergency sites and are not in the Kuala Krai cluster, so the impact numbers should not move, and a test proves it), tower-mcp and ran-mcp (unchanged).

**Existing tests that change with the approved contract (and why):**
- `packages/menara-core/tests/test_movement.py`: "visits start at -1440" becomes "-40320"; the old tables hash test stays.
- `servers/sites-mcp/tests/test_tools.py`: `kind="MALL"` is no longer invalid; the invalid kind becomes `ZOO`.
- `servers/user-mcp/tests/test_trail.py`: tests that use `window_min=2880` to mean "everything" use 40320; the stayer test (`duration_min == 1440`, arrived 2026-11-13T07:00) now expects the 28-day stay.
- `packages/menara-demo/src/menara_demo/app.py` and its tests: the story window range.

No other test changes.

## 5. Scenario impact

None. `kuala_krai.yaml` and the clock are not touched. At T0 only history before T0 is visible; the future rows (minute 0 to 480) are unchanged. Today (Saturday 2026-11-14) keeps its existing work-bound commute for movers (it is a quirk of the original seed and out of scope). Weekday and weekend labels in routines use the real calendar dates of the scenario clock.

## 6. Privacy

- Subscribers are still hashed; location is still cell level; no MSISDN, name or address.
- A routine is a pattern on **one synthetic subscriber**. The page and the story say so, and say the pattern is inferred from cell-level data and is only "near", never "at".
- Malls and all places are fictional (`(synthetic)` in the name). No real organisation or brand appears anywhere, including the page theme.
- Map events carry tower and site coordinates only.
- Aggregates under 5 stay suppressed in the area tools; routines are per subscriber and are not aggregates.

## 7. Ports and registration

None. External hosts the page may use: `unpkg.com` (Leaflet, as today) and the map-tile host. Tiles: the dark basemap from `basemaps.cartocdn.com` (free, no key, needs attribution which the page shows). If that is not acceptable, fall back to the current OSM tiles with a CSS filter; this is the only open choice and has no effect on the contract.

## 8. Alternatives considered

- **Separate `subscriber_habit_visit` table + new `user_get_habits` tool.** Cleaner for the old tests, but it makes two sources of truth for where a subscriber was, and adds a tool teammates' agents must learn. Rejected; one longer trail is simpler.
- **Let the model find the habit from the raw 28-day trail.** It would invent frequencies. Rejected; the backend computes counts and the model only words them.
- **Browser tests with Playwright.** Heavy for a hackathon repo. Instead the map logic lives in Python (`map_effects`) where pytest covers it, and the page is checked by a host-allowlist test, an HTML smoke test, and a manual screenshot pass.
- **Mall as a tower attribute.** Malls are places with a location and a serving tower, exactly what `critical_site` models. Reusing it needs no new server.

## 9. Rollout

After merging, teammates must stop all MCP servers, run `uv run menara-seed`, and restart the servers and the demo. The database grows (measured value goes in the PR). Agents that call `user_get_trail` with the default window see no change; agents that need more history can ask for up to 40320 minutes. Sites lists now contain `MALL` entries, which agents that filter by kind will see only when they ask for it.
## 10. As built (changes found while implementing; the intent is unchanged)

- **Map tiles.** The free CARTO dark tiles now answer "API key required", so the page uses the OpenStreetMap tiles (`tile.openstreetmap.org`, the fallback named in section 7) with a CSS filter that turns them dark. Allowed hosts: `unpkg.com`, `tile.openstreetmap.org`.
- **Mall ids.** `critical_site_id` allows two digits after the area code, so a mall is `CS-<area>-90` (not `-M01`). Criterion 2 became: every `critical_site` row that is not a `MALL` is unchanged.
- **Stops.** A stay under 45 minutes is transit (a commute spends 30 minutes on the tower on the way), not 30. Weekday and weekend typical times are counted separately.
- **Effects.** Tower and site positions come from the database; flood and ticket positions come from the server's own result (never from the model). Only `tower_get_status` and `tower_get_kpi` give a tower a status tone; other tools mark a tower `info`. The stats strip shows `Tickets (cluster)` from `ticket_cluster_by_location` on TK-88213 (0 before T0), since there is no ticket-listing tool. Effects are built from the full result text, not the shortened text shown in the timeline.
- **Seed history.** For a commuter, the original home row at minute -1440 is replaced by the evening return home of the day before (the same tower and cell, earlier), so no tower repeats back to back and nobody sits at work overnight. Rows after minute -1440 are identical to before. The full-size seed takes about 6 seconds and the database is about 95 MB (under the 100 MB limit, so the history stays at 28 days).
- **Page.** `#replay` is a new scene link that starts a Replay. The page names a clear fix ("Restart the demo") when the server answers with a non-JSON page, which is what an old copy of the server does for a route it does not have.
