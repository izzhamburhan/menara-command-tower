# Spec: self-heal view, reset, and usage-mcp

Owner: Izzham Burhan, TMRND. Branch `feat/usage-heal-reset`. All data is synthetic.

Three requests after the demo-wow merge:

- **A. Self-heal view**: make the closed loop (detect, diagnose, simulate, approve, apply, verify, roll back, retry, recover) visible in the UI.
- **B. Reset**: put the demo back to a clean state after playing, without stopping the servers or re-seeding.
- **C. usage-mcp**: a 13th MCP that says what people in a circle use on the internet (apps, categories, busiest hour).

## 1. Goal and non-goals

**Goals.**
- A: a "Self-heal" tab showing the loop's stages lighting up, a KPI chart of the overloaded neighbours with the tilt and rollback marked on it, and buttons to run it (Replay with no key, or live).
- B: a "Reset demo" button, a core helper, and a CLI command that clear everything an agent or a person created and put the clock and policy settings back, with the servers still running.
- C: a new server `usage-mcp` (port 8113) with three read-only tools, a small seeded dataset, and a "What people use here" card in the Map & area panel.

**Non-goals.**
- No new MCP tools for A or B (A reads existing tools; B is a maintenance helper that an agent can never call).
- No per-subscriber app profile: usage is only per tower and per circle (decided with the developer).
- No flood-time shift in usage, no change to `kuala_krai.yaml`, no logos, no real traffic claims.
- No change to the golden trace flow.

## 2. Acceptance criteria

### A. Self-heal view (menara-demo)

1. `heal.py` maps a finished tool call to a loop stage, in Python: `detect` (`ticket_get_ticket`, `ticket_cluster_by_location`, `tower_get_status`, `tower_get_alarms`), `diagnose` (`grid_*`, `flood_*`, `weather_*`, `ontology_blast_radius`, `ontology_create_incident`), `simulate` (`twin_*`), `approve` (`policy_check_action`, an approval event), `apply` (`ran_tilt_cells`, `drone_dispatch`), `verify` (`tower_get_kpi`), `rollback` (`ran_revert_change`), `recover` (`ontology_update_incident` with status `RESOLVED`). Anything else maps to no stage.
2. During a run, each mapped result adds `{"type": "heal", "step": N, "stage": ..., "attempt": n, "label": ...}` after the `result` event (and after the `map` event, if any). `attempt` counts how many times `apply` (tilt only) has happened in this run, so the second tilt is attempt 2. A failing or unmapped call adds no event.
3. `GET /api/heal/state` returns the loop state built from the real servers: for each watched tower a PRB series from `tower_get_kpi` (window `min(1440, clock + 240)` minutes), the list of RAN changes from `ran_list_changes` (`change_id`, `status`, `applied_min`, `reverted_min`, `efficacy` per item), the incident status from `ontology_list_incidents`, and the current clock. The failed tower is the tower of the latest incident, or `KKRI-0142` (the scenario's flood anchor, as the stats strip uses `TK-88213`) before any incident exists. The watched towers are its neighbours (from `tower_get_status`) whose PRB reached 85% in the window, plus every tower that a RAN change touched. The 85% line and the neighbour list come from the data, not from a fixed list.
4. With nothing run yet, the state has the neighbour series, no changes, and incident `none`. After the Replay, it has two changes (the first `REVERTED` with efficacy 0.1 on KKRI-0143, the second `ACTIVE` then `REVERTED` after power returns), and the neighbours' PRB at or above 85 before the first tilt and below 85 after the second.
5. The page has a 4th tab "Self-heal" with: a stage tracker (8 stages, the active one pulses, a done one is ticked, `apply` and `verify` show their attempt number, `rollback` shows red when it happened); an SVG chart of the neighbours' PRB over scenario time with an 85% "overload" line and a vertical marker for each change applied or reverted; a short result line ("KKRI-0143: 91% to 63%, healed on attempt 2"); and buttons "Run self-heal (Replay)" and "Run live" that start the same run as the Story tab. Events from `heal` update the tracker immediately, and the chart refreshes from `/api/heal/state` after each result.
6. The Self-heal tab works with a Replay and no model key. If the server is an old copy, the existing "Restart the demo" message shows.

### B. Reset (menara-core and menara-demo)

7. `menara_core.reset.reset_runtime_state(db_path, scenario) -> dict[str, int]` deletes every row of the runtime tables and returns the rows deleted per table. The runtime tables are `incident`, `incident_ticket`, `twin_simulation`, `ran_change`, `ran_change_item`, `ran_kpi_effect`, `drone_mission`, `approval`, `audit_log`, `ticket_note`, `ticket_resolution`. It is one transaction: all or nothing.
8. It resets the autoincrement counters of those tables (`sqlite_sequence`), so the next incident is `INC-0001`, the next change `CHG-0001`, the next approval `APR-0001`, and the next mission `MIS-0001`.
9. It puts `policy_setting` back to the scenario defaults (the same values the seed writes; the seed and the reset share one function) and the scenario clock back to `default_now_min`.
10. It never touches base tables: row counts and a hash of `tower`, `subscriber`, `subscriber_cell_visit`, `ticket`, `critical_site` are the same before and after. It leaves `seed_meta` alone. A database that is not seeded gives `DatabaseNotSeededError`.
11. It works while the MCP servers are running (they open the database per call). A test plays the Replay on real stdio servers, resets, plays it again, and gets the same ids as the first time.
12. `menara-scenario reset-state` runs it and prints the counts; without `--yes` it asks first (a non-interactive run without `--yes` refuses).
13. `POST /api/reset` (demo): `409` while a run is in progress; otherwise it cancels nothing, runs the reset, clears the run manager (events empty, status idle, no pending approval) and returns `{ok, deleted: {...}, clock}`. It is not an MCP tool, so an agent cannot call it, and the Console does not offer it.
14. The page has a "Reset demo" button (header). It asks for confirmation, calls the route, and then clears the Story timeline, the Self-heal tab, the map effects, the replay and the trail layers, reloads the towers and the stats, and says what was removed ("Removed 1 incident, 3 approvals, ..."). A `409` shows "A run is in progress: cancel it first."

### C. usage-mcp

15. A new server `servers/usage-mcp/` (`usage_mcp`), registered in `.mcp.json` and the root `pyproject.toml`, port 8113, depending only on `menara-core`. It owns no tables (`OWNED_TABLES = frozenset()`).
16. Seed: three base tables written only by the seed. `app` (14 apps: `app_id`, `name`, `category`), `app_hour_factor` (`app_id`, `hour` 0 to 23, `factor`), `tower_app_share` (`enodeb_name`, `app_id`, `user_share` 0 to 1 = the share of a tower's active users that use the app in a day, `data_share` = the share of its data volume; the data shares of a tower sum to 1). One random stream `f"{seed}:usage"`, so every older table is unchanged. Each town has its own favourite app, so different places have a different number one.
17. The apps use real names with no logos: TikTok, Facebook, Instagram, Threads, WhatsApp, Telegram, YouTube, Netflix, Spotify, X, Mobile Legends, Shopee, Grab, Google Maps. Categories: `SHORT_VIDEO`, `SOCIAL`, `MESSAGING`, `VIDEO_STREAMING`, `MUSIC`, `GAMING`, `COMMERCE`, `MOBILITY`. Every response says the numbers are synthetic.
18. `usage_top_apps_in_area(lat, lng, radius_km=10, rank_by="users", hour=None, limit=10)`: towers inside the circle (`radius_km` 0.1 to 100, `limit` 1 to 20, `rank_by` `users` or `data`, `hour` 0 to 23, default the scenario clock's hour). `data`: `center`, `radius_km`, `hour`, `towers_counted`, `total_users_est`, `apps[]` ranked (`rank`, `app_id`, `name`, `category`, `users_est`, `reach_pct`, `data_share_pct`), `categories[]` (`category`, `data_share_pct`, sums to 100), `busiest_hour`, `withheld`.
19. The figures are worked out as: users of an app at an hour = sum over the towers of `tower_subscribers` times `user_share` times `factor` of that hour (capped at the tower's users), `reach_pct` = that over the total, `data_share_pct` = the data-weighted share of the area at that hour. If the area's estimated users are under 5 the answer is withheld (`withheld: true`, no `apps`), as in `user_list_in_area`. No towers in the circle gives `towers_counted: 0` and a warning, not an error.
20. `usage_get_tower_apps(enodeb_name, rank_by="users", hour=None, limit=10)`: the same `data` for one tower. An unknown tower is `NotFoundError`.
21. `usage_app_trend(lat, lng, radius_km=10, app)`: for one app, 24 points (`hour`, `users_est`, `reach_pct`) and `peak_hour`. `app` is an `app_id` or a name (case-insensitive); an unknown app is `InvalidInputError` that lists the valid ids.
22. Every response is an `Envelope` with `synthetic: true` and `evidence[]`. Tool names are `usage_*`. Bad numbers (radius 0, hour 24, limit 0) are `InvalidInputError`.
23. Reads (read-only, base tables): `tower`, `tower_subscribers`, `app`, `app_hour_factor`, `tower_app_share`. The README says so.
24. The seed has a clear shape: Tawau and Kuala Krai circles have different top apps; the evening hours have more video and social use than 04:00; the category shares sum to 100 for any circle.
25. Demo: the Map & area panel gets a "What people use here" card for the circle (top 5 by users with bars, a Users/Data toggle, the category split, the busiest hour, and "synthetic estimate" wording). It composes `usage_top_apps_in_area` through `/api/call`. The Console lists the new tools with an example.
26. The hard-coded counts change from 12 to 13 servers (`packages/menara-agent/tests/test_servers.py`, `tests/test_run_mcp.py`, docs). The demo says 55 tools.

### D. Regression

27. The golden trace, the Replay end-to-end test and all other existing tests pass, except the ones named in section 4. ruff, mypy strict, pytest and the skill parity check are clean.

## 3. Tool contract

New tools (all on `usage-mcp`, read-only):

| Tool | Arguments | `data` |
| --- | --- | --- |
| `usage_top_apps_in_area` | `lat, lng, radius_km=10, rank_by="users", hour?, limit=10` | `hour`, `towers_counted`, `total_users_est`, `apps[]`, `categories[]`, `busiest_hour`, `withheld` |
| `usage_get_tower_apps` | `enodeb_name, rank_by="users", hour?, limit=10` | the same for one tower |
| `usage_app_trend` | `lat, lng, radius_km=10, app` | `app`, `points[24]`, `peak_hour` |

Errors are `menara_core.errors` types. `evidence[]` names the tool, the area or tower, and the hour.

New demo routes (not MCP): `GET /api/heal/state`, `POST /api/reset`. New event type `heal`.

New core API: `menara_core.reset.reset_runtime_state`, `menara-scenario reset-state [--yes]`.

## 4. Data

| Table | Read by | Written by | Change |
| --- | --- | --- | --- |
| `app`, `app_hour_factor`, `tower_app_share` | usage-mcp | seed only | new |
| runtime tables (section 2, item 7), `policy_setting`, `scenario_state` | their servers | reset helper (maintenance, not an MCP) | rows cleared and defaults restored |

The seed adds about 17,000 rows (a few MB). Other servers are unaffected. The reset is the one exception to "an MCP writes only its own tables": it is a developer maintenance tool like the seed, lives in `menara-core`, is never exposed as a tool, and only runs when a person presses the button or runs the CLI.

**Existing tests that change (approved contract change):**
- `packages/menara-agent/tests/test_servers.py`: 12 servers becomes 13.
- `tests/test_run_mcp.py`: 12 servers, 12 distinct ports, 12 streamable-http flags become 13.
- `packages/menara-core/tests/test_movement.py`: the old-tables hashes are unchanged; the new tables are listed as new.
- The seed `counts` summary in `seed/build.py` lists the new tables.

## 5. Scenario impact

None. `kuala_krai.yaml` is not touched. The clock sets the hour for usage (`07:00 + t_min`). Reset moves the clock to `default_now_min` (0).

## 6. Privacy

- Usage is aggregated per tower and per circle. There is no per-subscriber profile and no hashed subscriber in any usage response.
- Areas with fewer than 5 estimated users are withheld.
- App names are real brands used only as labels for invented numbers, with no logos and no claim about real traffic; every usage response and the card say "synthetic estimate".
- Reset removes agent-created data (incidents, approvals, audit entries); the audit log is a demo log, not a record to keep. The button asks first.

## 7. Ports and registration

Port 8113 for `usage-mcp`. Created with `uv run python scripts/new_mcp.py usage --port 8113 --description "..."`, which adds the `.mcp.json` entry and the root `pyproject.toml` entries; the CLAUDE.md and AGENTS.md port and status tables get a `usage` row.

## 8. Alternatives considered

- **Reset by re-seeding.** Needs every MCP server stopped, which breaks the demo mid-session. Rejected.
- **Reset as an MCP tool (policy-gated).** An agent could wipe its own audit trail. Rejected; it is a person-only button.
- **A per-subscriber usage profile.** More striking but profiling one person; declined by the developer.
- **Hourly usage stored per tower per app (345k rows).** Needlessly big. A per-tower share plus an hourly curve per app gives the same answers in 17k rows.
- **Heal view as a new MCP.** Everything it needs is already in `tower_get_kpi` and `ran_list_changes`. Rejected.

## 9. Rollout

After merging, teammates stop the servers, run `uv run python -m menara_core.seed.cli` (new tables), and restart. `usage` appears in `.mcp.json`, so agents and the demo see 13 servers and 55 tools. From then on, "Reset demo" (or `menara-scenario reset-state --yes`) puts the data back without a re-seed.