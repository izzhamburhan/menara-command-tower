# TDD plan: self-heal view, reset, and usage-mcp

Spec: `docs/specs/usage-heal-reset.md` (approved). Branch `feat/usage-heal-reset`, worktree `.worktrees/feat/usage-heal-reset`.
Every slice: write the named test first, run it and see the stated red, write the minimum code, see green, run the slice validation. Each slice leaves the whole suite green. `T` = `uv run python -m pytest`.

Edits to large files that are open in the IDE have been merged with stale lines before. After each edit of an existing file, check the changed region and run the tests again after a short pause. A whole-file rewrite goes through a copy from outside the repo.

## Spec clarifications found while planning

- **Criterion 2 (heal events).** The event is appended by `RunManager._on_event` after the `result` event (and after the `map` event), using the full result text kept by `_Mapper`, so a long result does not lose the stage.
- **Criterion 9 (policy defaults).** The seed's policy defaults move into one function `policy_settings(scenario)` in `seed/actions.py`, called by the seed and by the reset.
- **Criterion 3 (heal state).** `tower_get_kpi` allows at most 1440 minutes, so the window is `min(1440, clock + 240)`.
- **Visual polish (new, requested after approval).** The page gets a design pass (hierarchy, type, spacing, color, motion) on top of the new tab, card and button. The developer asked for the Impeccable design skill to be used. Installing third-party skill code into the repo was blocked in this session, so slice 8 states the fallback: the same pass done by hand against the same checks (guard tests, screenshots at desktop and mobile width, contrast), and the skill is run if the developer installs or allows it.

## Global constraints

- Tables written: no MCP gains a write table. `usage-mcp` owns none. The three usage tables are written by the seed only. The reset helper is the one maintenance writer and is never an MCP tool.
- No MCP calls another MCP; the demo composes calls.
- Privacy: no per-subscriber usage; areas under 5 estimated users are withheld; every usage answer says it is a synthetic estimate; no logos.
- `mcp[cli]>=1.9,<2`; Python via `python -m`; ruff and mypy strict.
- New code uses its own random stream so every older table is unchanged.

**Scope boundary.** May change: `packages/menara-core/**` (seed, reset, scenario_cli), `servers/usage-mcp/**` (new), `packages/menara-agent/tests/test_servers.py`, `tests/test_run_mcp.py`, `packages/menara-demo/**`, `.mcp.json`, root `pyproject.toml` and `uv.lock` (only what `new_mcp.py` and `uv sync` change), `docs/**`, root README, `CLAUDE.md`, `AGENTS.md`. Must not change: `data/scenario/kuala_krai.yaml`, the other 12 servers' source, `tests/golden_trace` (must pass unchanged), `.github`, `packages/menara-agent/src`.

---

## Slice 1: reset in menara-core

**Files.** Modify `seed/actions.py` (extract `policy_settings(scenario) -> dict[str, str]`, used by `build_actions`), `scenario_cli.py` (`reset-state [--yes]`). Create `packages/menara-core/src/menara_core/reset.py`, `packages/menara-core/tests/test_reset.py`.

**Interface produced.**
`RUNTIME_TABLES: tuple[str, ...]` (the 11 tables of spec item 7), `reset_runtime_state(db_path: Path, scenario: Scenario) -> dict[str, int]`. It connects with `connect(db_path, owned_tables=set(RUNTIME_TABLES) | {"policy_setting", "scenario_state"})`, deletes in one transaction, deletes the matching `sqlite_sequence` rows, rewrites `policy_setting` from `policy_settings(scenario)`, sets the clock to `scenario.default_now_min`.

**Tests first (`test_reset.py`, using `build_test_db`, dirtying the copy by inserting rows through the same owned connections the servers use).**
- `test_reset_clears_every_runtime_table_and_reports_the_counts`
- `test_the_next_ids_start_again_from_one` (insert an incident and an approval, reset, insert again, expect `seq` 1)
- `test_policy_settings_go_back_to_the_scenario_defaults` (flip `kill_switch` to 1 and change a threshold first)
- `test_the_clock_goes_back_to_the_default`
- `test_base_tables_are_untouched` (row counts and a hash of `tower`, `subscriber`, `subscriber_cell_visit`, `ticket`, `critical_site`, plus `seed_meta`)
- `test_a_failure_leaves_everything_as_it_was` (monkeypatch one delete to raise; the other tables keep their rows)
- `test_reset_of_a_missing_database_says_not_seeded` (`DatabaseNotSeededError`)
- `test_cli_reset_state_needs_yes_and_prints_the_counts` (`main(["reset-state"])` returns 2 without `--yes` on a non-tty; with `--yes --db` it returns 0)
- `test_the_seed_and_the_reset_use_the_same_policy_defaults`

**Expected red.** `ModuleNotFoundError: menara_core.reset`; `argparse` rejects `reset-state`.

**Green.** Implement as described. The CLI refuses without `--yes` when stdin is not a terminal (and asks `[y/N]` when it is).

**Validate.** `T packages/menara-core -q`, ruff, mypy. **Checkpoint:** core green, the seed's policy rows unchanged (the existing seed tests).

## Slice 2: usage seed in menara-core

**Files.** Modify `seed/schema.py` (three base tables), `seed/build.py` (call `build_usage`, add the tables to the summary counts). Create `seed/usage.py`, `packages/menara-core/tests/test_usage_seed.py`.

**Interface produced.** `build_usage(conn, seed, towers)`; module constants `APPS` (14 rows of `(app_id, name, category)`), `CATEGORIES`, per-app hourly curves, per-profile base reach. Random stream `random.Random(f"{seed}:usage")`.

**Tests first.**
- `test_the_catalogue_has_14_apps_in_8_categories_and_real_names_without_logos`
- `test_every_tower_has_a_share_for_every_app` (rows = towers x 14)
- `test_data_shares_of_a_tower_sum_to_one`
- `test_user_shares_are_between_0_and_1`
- `test_hour_factors_exist_for_24_hours_and_peak_in_the_evening` (evening video and social above 04:00 for every app of those categories)
- `test_towns_have_different_favourite_apps` (the top app by `user_share` differs between at least 4 towns)
- `test_old_tables_are_unchanged` (the BASELINE hashes from `test_movement.py` are re-asserted)
- `test_same_seed_same_usage`
- `test_default_seed_size_grows_by_under_10_mb_and_5_seconds` (a loose bound: count rows under 25,000)

**Expected red.** `sqlite3.OperationalError: no such table: app`.

**Green.** Implement the generator: reach per app by tower profile (urban or not), a per-town favourite boost, small per-tower noise; data share derived from reach and a per-app weight (video heavy, messaging light), normalised.

**Validate.** `T packages/menara-core -q`; a full default seed timed in a scratch folder (record seconds and size). **Checkpoint:** every other server's suite still green (`T servers -q`).

## Slice 3: scaffold usage-mcp and the 13-server counts

**Files.** Run `uv run python scripts/new_mcp.py usage --port 8113 --description "What people use on the internet, by area and tower"` (creates `servers/usage-mcp/**`, `.mcp.json` entry, root `pyproject.toml` entries). Modify `packages/menara-agent/tests/test_servers.py`, `tests/test_run_mcp.py`, `packages/menara-demo/src/menara_demo/__main__.py` (help text "all thirteen").

**Tests first (edit the existing ones before scaffolding, see them fail).**
- `test_servers.py::test_load_config_reads_all_thirteen_servers_from_mcp_json` (13 and `"usage"` present)
- `tests/test_run_mcp.py`: 13 servers, 13 distinct ports, `servers["usage"].port == 8113`, 13 `--transport streamable-http` flags.

**Expected red.** `assert 12 == 13` in the three places.

**Green.** Run the scaffold; check `git diff` of `.mcp.json` and `pyproject.toml` is only the usage lines.

**Validate.** `T packages/menara-agent tests -q`, `uv sync`, ruff, mypy. **Checkpoint:** the placeholder tool `usage_info` still passes its scaffold tests.

## Slice 4: usage-mcp tools

**Files.** Replace the placeholder in `servers/usage-mcp/src/usage_mcp/{tools,models,server}.py`; tests in `servers/usage-mcp/tests/{conftest,test_tools,test_server}.py`; `servers/usage-mcp/README.md`.

**Interfaces.**
- `models.py`: `AppUsage(rank, app_id, name, category, users_est, reach_pct, data_share_pct)`, `CategoryShare`, `AreaUsage`, `TrendPoint`, `AppTrend`.
- `tools.py`: `top_apps_in_area(conn, lat, lng, radius_km=10.0, rank_by="users", hour=None, limit=10)`, `get_tower_apps(conn, enodeb_name, rank_by="users", hour=None, limit=10)`, `app_trend(conn, lat, lng, radius_km=10.0, app="")`. The hour defaults from the scenario clock (`menara_core.clock`). `OWNED_TABLES = frozenset()`.

**Tests first (`test_tools.py`).**
- `test_the_top_apps_are_ranked_by_users_and_by_data`
- `test_the_category_shares_sum_to_100`
- `test_users_and_reach_follow_the_hour` (evening reach of video above 04:00)
- `test_the_default_hour_comes_from_the_scenario_clock` (uses the `set_clock` fixture)
- `test_two_towns_have_different_top_apps` (circles over Tawau and Kuala Krai)
- `test_an_area_with_fewer_than_5_estimated_users_is_withheld`
- `test_an_empty_circle_gives_zero_towers_and_a_warning`
- `test_tower_apps_for_one_tower_and_an_unknown_tower_is_not_found`
- `test_app_trend_has_24_points_and_a_peak_hour_and_accepts_id_or_name_in_any_case`
- `test_an_unknown_app_lists_the_valid_ids`
- `test_bad_numbers_are_invalid_input` (radius 0 and 101, hour 24, limit 0 and 21, `rank_by="x"`)
- `test_every_answer_is_synthetic_and_has_evidence`
- `test_no_response_contains_a_subscriber_hash` (no `msisdn` anywhere in the serialised answer)
- `test_the_server_registers_three_usage_tools_with_envelopes` (`test_server.py`, using the repo's existing server-test helper pattern from `sites-mcp`).

**Expected red.** `AttributeError: module 'usage_mcp.tools' has no attribute 'top_apps_in_area'`.

**Green.** Query towers in a bounding box then filter by `haversine_km` (`menara_core.geo`), join `tower_subscribers`, `tower_app_share`, `app_hour_factor`; cap each tower's app users at its users.

**Validate.** `T servers/usage-mcp -q`, ruff, mypy; a real stdio call (`scripts/run_mcp.py usage --stdio` or the `McpHub` smoke script) against a freshly seeded database. **Checkpoint:** three tools return sensible numbers for a Tawau circle and a Kuala Krai circle; read them.

## Slice 5: demo reset route

**Files.** Modify `packages/menara-demo/src/menara_demo/{app,runs}.py`; tests in `packages/menara-demo/tests/test_reset.py`.

**Interfaces.** `RunManager.clear()` (status `idle`, events empty, pending cleared; refuses while running), `POST /api/reset` calling `menara_core.reset.reset_runtime_state(db_file, load_scenario(settings.default_scenario_path()))`.

**Tests first.**
- `test_reset_while_a_run_is_in_progress_is_409`
- `test_reset_clears_events_status_and_returns_the_counts_and_the_clock`
- `test_reset_clears_a_finished_run_so_the_page_starts_empty` (`/api/agent/events` has no `run_id` after)
- `test_reset_is_not_an_mcp_tool_and_not_in_the_console` (`/api/tools` has no name containing `reset`; `/api/call` of such a name is 404)
- `test_replay_twice_with_a_reset_between_gives_the_same_ids` (real stdio servers, the existing replay fixture: first run creates `INC-0001`, second run after reset creates `INC-0001` again, same `CHG-0001`, `APR-0001`, `MIS-0001`) in `test_replay.py`.

**Expected red.** `404` on `/api/reset`; `AttributeError: clear`.

**Green.** Implement the route and `clear()`.

**Validate.** `T packages/menara-demo -q`, ruff, mypy. **Checkpoint:** the replay-reset-replay test is the proof for spec item 11.

## Slice 6: heal backend

**Files.** Create `packages/menara-demo/src/menara_demo/heal.py`, `packages/menara-demo/tests/test_heal.py`. Modify `runs.py` (heal events), `app.py` (`GET /api/heal/state`).

**Interfaces.**
- `STAGES = ("detect", "diagnose", "simulate", "approve", "apply", "verify", "rollback", "recover")`.
- `stage_for(name: str, arguments: dict, result_text: str) -> str | None`.
- `async def heal_state(hub: Hub, clock_min: int) -> dict[str, Any]` returning `{clock, failed_tower, watched[], series{tower: [{t_min, prb}]}, threshold, changes[], incident, stages_done[]}`.
- In `RunManager._on_event`: after a successful `result` (and the `map` event), if `stage_for` is not None, append `{"type": "heal", "step", "stage", "attempt", "label"}`; `attempt` counts tilt applications in the run.

**Tests first (`test_heal.py`).**
- `test_each_tool_maps_to_its_stage` (parametrised over spec item 1, including `ontology_update_incident` with `RESOLVED` giving `recover` and with `MITIGATING` giving none)
- `test_unknown_tools_and_failed_calls_have_no_stage`
- `test_runs.py::test_a_heal_event_follows_the_result_and_map_events`
- `test_runs.py::test_the_second_tilt_is_attempt_2`
- `test_runs.py::test_a_failing_stage_builder_does_not_break_the_run`
- `test_heal_state_before_any_run_has_series_no_changes_and_no_incident` (fake hub with canned tool results)
- `test_heal_state_uses_the_incident_tower_and_falls_back_to_the_anchor`
- `test_heal_state_watches_neighbours_over_85_and_every_changed_tower`
- `test_heal_state_window_is_capped_at_1440`
- `test_replay.py::test_heal_state_after_the_replay_shows_the_failed_then_the_good_tilt` (real servers: two changes, the first with efficacy 0.1 on KKRI-0143, `REVERTED`; PRB at or above 85 before the first tilt and below 85 after the second)
- `test_replay.py::test_replay_emits_the_eight_stages_in_order` (a stage list with every stage present, `rollback` before the second `apply`).

**Expected red.** `ModuleNotFoundError: menara_demo.heal`; `404` on `/api/heal/state`.

**Green.** Implement with the hub only (`tower_get_status`, `tower_get_kpi`, `ran_list_changes`, `ontology_list_incidents`).

**Validate.** `T packages/menara-demo -q`, ruff, mypy. **Checkpoint:** read the real heal state JSON after a Replay and check it against the screen.

## Slice 7: page guards and the usage card

**Files.** Modify `packages/menara-demo/src/menara_demo/static/index.html`, `tests/test_page.py`.

**Tests first (page guards).**
- `test_the_page_has_the_heal_reset_and_usage_hooks` (`tabHeal`, `paneHeal`, `healStages`, `healChart`, `resetDemo`, `usageCard`, `usageToggle`, the strings `/api/heal/state`, `/api/reset`, `usage_top_apps_in_area`, `event.type === "heal"`)
- `test_the_usage_card_says_it_is_a_synthetic_estimate`
- the existing guards stay (hosts, contrast, no duplicate function, valid JS, no brand names). The brand deny-list does **not** include the app names in the usage seed, because they are shown as labels; the test asserts the page has no logo images (`<img` count 0 and no `url(` to an app asset).

**Expected red.** The new hooks are missing.

**Green (steps, each checked by hand with a headless screenshot).**
1. Usage card in the Map & area panel: top 5 with bars, Users/Data toggle, category split, busiest hour, "synthetic estimate" caption; calls `usage_top_apps_in_area` through `/api/call` when the circle changes (and quietly shows nothing if the call fails).
2. Console example for the three usage tools.

**Validate.** `T packages/menara-demo -q`; screenshots of Tawau and Kuala Krai circles showing different top apps. **Checkpoint:** developer sees the card.

## Slice 8: Self-heal tab, Reset button and the visual pass

**Files.** `index.html` (and nothing else; the guards from slice 7 already name the hooks).

**Steps.**
1. **Self-heal tab**: stage tracker driven by `heal` events (pulse on the active stage, tick when done, attempt numbers, red rollback), SVG chart of the watched towers' PRB from `/api/heal/state` with the 85% line and a marker per change applied or reverted, a result line, and the two run buttons that call the same `startRun`. The chart refreshes after each `result` and `heal` event, and works with reduced motion.
2. **Reset demo** button in the header: confirm dialog, `POST /api/reset`, then clear the timeline, heal tab, map effects, replay and trail layers, reload towers and stats, and show what was removed; a `409` shows "A run is in progress: cancel it first."
3. **Design pass**: critique then fix, one batch each, at desktop and 390 px width: type scale and hierarchy, spacing rhythm, color and contrast, empty states, focus states, motion kept purposeful and off under reduced motion. The Impeccable skill is used if it is installed (`/impeccable critique` then `polish` on `packages/menara-demo/src/menara_demo/static/index.html`); otherwise the same passes are done by hand against its published checklist (hierarchy, color, type, layout, motion, accessibility, responsive) and the result is shown as before and after screenshots.

**Validate.** `T packages/menara-demo -q` (guards); headless screenshots (CDP script from the previous change) of: the Self-heal tab mid-Replay and after, the Reset flow, the usage card, desktop and 390 px; no JS errors in the console. **Checkpoint:** the developer sees screenshots and a short list of what the design pass changed.

## Slice 9: docs (doc-drift)

**Files.** `servers/usage-mcp/README.md` (done in slice 4; re-read), `packages/menara-demo/README.md` (Self-heal tab, Reset, usage card, routes, scene links), root `README.md` (thirteen servers, the table row for `usage`, the reset command), `CLAUDE.md` and `AGENTS.md` (ports table row 8113, status row, "All 13", commands `menara-scenario reset-state`), `docs/specs/usage-heal-reset.md` (as-built notes).

**Validate.** `uv run python scripts/check_skill_parity.py`; grep for stale "twelve", "12 servers", "52 tools". **Checkpoint:** `CLAUDE.md` and `AGENTS.md` agree.

## Slice 10: verification

Fresh run and read: `uv run python -m ruff check .`, `uv run python -m mypy`, `uv run python -m pytest` (full, golden trace and the replay tests included), the skill parity check, a default seed (seconds, size), the stdio smoke calls of slice 4, Replay in a real browser with the Self-heal tab and a reset between two runs, and, if the key is present, one live run. Then `completion-checkpoint`.

## Risks

- **Seed size and time:** measured in slice 2; the usage tables are small.
- **Reset while servers run:** every server opens the database per call, and slice 5 proves it with real servers.
- **IDE merges into open files:** the guard tests catch broken pages; whole-file rewrites go through a copy.
- **Design pass depends on the skill install:** the fallback is defined in slice 8, so the plan does not block.