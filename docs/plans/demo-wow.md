# TDD plan: demo wow

Spec: `docs/specs/demo-wow.md` (approved). Branch `feat/demo-wow`, worktree `.worktrees/feat/demo-wow`.
Every slice: write the named test first, run it, see the stated red, write the minimum code, see green, run the slice validation. Each slice leaves the whole suite green.

## Spec clarifications (found while planning; they refine, not change, the approved spec)

- **Criterion 2.** `critical_site` gains MALL rows, so its baseline row count and hash in `test_movement.py` change. The rule becomes: every `critical_site` row whose kind is not `MALL` is identical (count and hash) to the baseline, and all other baseline tables are untouched.
- **Criterion 25, "open tickets".** There is no ticket-listing tool. The stats strip shows `Tickets (cluster)` from `ticket_cluster_by_location` on `TK-88213` (radius 15 km, window 30 min), and 0 when the clock is before T0.
- **Malls draw from their own stream.** `build_malls(conn, seed, scenario, towers)` is a new function in `seed/sites.py` called from `build.py` after `build_sites`. `build_sites` itself is not changed, so its random draws are unchanged.

## Global constraints

- Tables written: no server gains a write table. `critical_site` and `subscriber_cell_visit` are written by the seed only. The demo reads its database read-only.
- No MCP calls another MCP. The demo composes calls; it never imports a server package.
- Privacy: hashed MSISDN only, cell-level location, no real names, `(synthetic)` in every new place name. Map events carry no subscriber hash.
- `mcp[cli]>=1.9,<2` stays pinned; `pyproject.toml` and `uv.lock` are not touched.
- ruff, mypy strict, and the line style of the file being edited.
- Python through `python -m` (shims are blocked on Windows).

**Scope boundary.** May change: `packages/menara-core/src/menara_core/seed/{schema,sites,movement,build}.py` and their tests, `servers/sites-mcp/**`, `servers/user-mcp/**`, `packages/menara-demo/**`, `docs/**`, root README, `CLAUDE.md`, `AGENTS.md`. Must not change: `data/scenario/kuala_krai.yaml`, `policy-mcp`, `ran-mcp`, `drone-mcp`, `twin-mcp`, `ontology-mcp`, `tower-mcp`, `ticket-mcp`, `.mcp.json`, `.claude/skills`, `.github`, `packages/menara-agent` (read-only here), `tests/golden_trace` (must pass unchanged).

Run commands from the worktree root. `T` below is `uv run python -m pytest`.

---

## Slice 1: MALL site kind in the seed (menara-core)

**Files.** Modify `seed/schema.py` (CHECK adds `'MALL'`), `seed/sites.py` (`PRIORITY["MALL"] = 4`, new `build_malls`), `seed/build.py` (call it). Tests: create `packages/menara-core/tests/test_malls.py`; modify `packages/menara-core/tests/test_movement.py` (BASELINE `critical_site` check).

**Interface produced.** `build_malls(conn: sqlite3.Connection, seed: int, scenario: Scenario, towers: list[TowerRow]) -> None`. For each town with non-cluster towers: one row `CS-<code>-M01`, name `<Town> Mall 1 (synthetic)`, kind `MALL`, priority 4, `emergency_service 0`, position within 0.01 degrees of a local tower, serving the nearest local non-cluster tower, drawn from `random.Random(f"{seed}:malls")`.

**Tests first (in `test_malls.py`).**
- `test_every_town_with_sites_has_exactly_one_mall`
- `test_a_mall_is_not_an_emergency_site_and_has_priority_4`
- `test_a_mall_is_served_by_a_non_cluster_tower_of_its_own_town`
- `test_mall_names_say_synthetic`
- `test_the_other_site_rows_are_unchanged` (count and hash of rows with `kind != 'MALL'` equal the old BASELINE values `(214, "90b0ddb4172c")`)
- `test_malls_are_the_same_for_the_same_seed`

In `test_movement.py`: change the `critical_site` entry so the check excludes MALL rows (the helper filters `WHERE kind != 'MALL'` for that table).

**Expected red.** `uv run python -m pytest packages/menara-core/tests/test_malls.py` fails: no MALL rows (`assert 0 == 1` style) and the CHECK would reject MALL.

**Green.** Schema CHECK, `PRIORITY`, `build_malls`, call in `build`.

**Validate.** `T packages/menara-core -q`, ruff, mypy. **Checkpoint:** all menara-core tests green; every other server's suite still green (`T servers -q`), because malls are new rows only.

## Slice 2: sites-mcp knows MALL

**Files.** Modify `servers/sites-mcp/src/sites_mcp/{tools,models,server}.py`, `servers/sites-mcp/README.md`. Tests: modify `servers/sites-mcp/tests/test_tools.py`; add to `test_server.py` if the description is asserted.

**Tests first.**
- `test_tools.py::test_a_mall_can_be_listed_by_kind` (`kind="MALL"` returns malls with priority 4, `emergency_service` false, `sla_customer` false)
- `test_tools.py::test_get_site_returns_a_mall`
- `test_tools.py::test_for_tower_counts_include_mall_when_the_tower_serves_one`
- change the existing invalid-kind test from `kind="MALL"` to `kind="ZOO"` (approved contract change).

**Expected red.** `InvalidInputError: kind must be one of ...` for `MALL`, and pydantic validation error on `SiteKind`.

**Green.** Add `MALL` to `KINDS`, `SiteKind`, and the tool description; README sentence.

**Validate.** `T servers/sites-mcp -q`, ruff, mypy. **Checkpoint:** sites suite green.

## Slice 3: four weeks of movement history (menara-core)

**Files.** Modify `seed/movement.py`. Tests: modify `packages/menara-core/tests/test_movement.py`; create `packages/menara-core/tests/test_history.py`.

**Interfaces.**
- `PERIOD_START = -40320`; the commute constants for the last two days stay.
- `_history(rng, home, work, mid, mall_tower, habit) -> list[Visit]`: visits strictly before minute -1440, oldest first, ending without the day -2 evening return (the existing `-1440` home row stands in for it).
- Habit: `"MALL"` (40% of movers with a mall tower 3 to 25 km from home) or `"HOME"`; mall regulars visit on about 80% of weekends on Saturday or Sunday for 120 to 240 min starting 10:00 to 14:00; others have a 10% chance per weekend of one mall visit; movers with no mall in range never leave home on weekends.
- Mall towers are read from `critical_site` (kind MALL) so malls must exist first (Slice 1).
- Weekday and weekend are computed from the real date of `scenario.t0`.
- Stayers get a single row at `PERIOD_START` (instead of at -1440).
- Rows for movers with `start_min >= -1440` stay identical; the generator for those rows keeps its random draws in the same order (history uses its own stream `f"{seed}:history"`).

**Tests first (`test_history.py`, plus edits).**
- `test_movers_tail_from_minus_1440_is_unchanged` (pinned hash of mover rows with `start_min >= -1440`, recorded now from `main`; run once before coding to record the value with `git stash`-free means: build the seed on `main` in a temp dir and hash it, then paste)
- `test_every_subscriber_starts_at_minus_40320`
- `test_no_two_consecutive_visits_share_a_tower`
- `test_weekday_history_commutes_and_weekend_history_stays_home_or_goes_to_a_mall`
- `test_weekend_mall_visits_only_go_to_mall_serving_towers`
- `test_a_mall_regular_visits_most_weekends` (movers with at least 3 weekend mall days out of 4 exist)
- `test_movers_without_a_mall_in_range_never_move_on_weekends`
- `test_the_same_seed_gives_the_same_history`
- `test_the_default_seed_has_at_least_25_percent_weekend_mall_visitors_among_movers_with_a_mall_in_range` (default-size seed, as the existing default test does)
- `test_the_seed_has_no_row_after_minute_480`
- In `test_movement.py`: `test_visits_start_at_the_beginning...` expects `-40320`; the commuters-stop-on-the-way test keeps using "today" rows (`start_min >= 0`) and the last-two-days trail; the "stay in the seeded period" test keeps `MAX <= 480`.

**Expected red.** `AssertionError: {-1440} != {-40320}`; `assert 0 > 0` for weekend mall visitors.

**Green.** Implement `_history`, habit assignment, stayer start, dedupe rule.

**Validate.** `T packages/menara-core -q`, then `uv run menara-seed --help` equivalent: run the real default seed into a temp file and report seconds and size (criterion 9). If over 100 MB, switch `HISTORY_DAYS` to 21 and update the spec. **Checkpoint:** the measured size and time are in the notes; menara-core green.

## Slice 4: longer trail window (user-mcp)

**Files.** Modify `servers/user-mcp/src/user_mcp/{tools,server}.py`, `servers/user-mcp/README.md`. Tests: modify `servers/user-mcp/tests/test_trail.py`; add `test_trail_history.py`.

**Interface.** `MAX_TRAIL_WINDOW_MIN = 40320`; error text `window_min must be between 5 and 40320`.

**Tests first.**
- `test_a_28_day_window_returns_four_weekends_of_segments_oldest_first_and_contiguous`
- `test_exactly_one_segment_is_current_and_left_at_matches_next_arrival`
- `test_a_window_over_40320_is_rejected_with_the_range_in_the_message`
- `test_default_window_is_still_one_day` (default trail equals the 1440 window of before for a mover)
- `test_area_lists_and_experience_are_unchanged_by_history` (list on a tower at clock 12 gives the same hashes as the visit's latest-started rule)
- Existing tests: windows of 2880 meant "everything", so they change to 40320; the stayer test now expects arrival `2026-10-17T07:00` and `duration_min == 40320` at clock 12 with the default window of 1440 giving `1440`.

**Expected red.** `InvalidInputError: window_min must be between 5 and 2880`.

**Green.** Raise the constant; README, server description.

**Validate.** `T servers/user-mcp -q`, ruff, mypy. **Checkpoint:** user suite green; `T tests/golden_trace -q` green (the golden trace uses the trail of the commuter, so run it here).

## Slice 5: cross-server regression and a real stdio smoke call

**Files.** None to edit unless a test breaks. Create `packages/menara-demo/tests/test_history_e2e.py` only if no existing test already walks a real server for it.

**Tests (written first, expected to pass if slices 1 to 4 are right; a red here means a regression to fix before going on).**
- `test_the_blast_radius_numbers_for_kkri_0142_do_not_change_with_malls` (ontology `ontology_blast_radius` site counts equal the pre-change recorded numbers).
- Real stdio smoke: with a freshly seeded temp database, call `user_get_trail` (window 40320) and `sites_list_in_bbox` (kind MALL) via `scripts/run_mcp.py --stdio` or the menara-agent hub, and read the envelopes.

**Validate.** `T -q` (all), ruff, mypy. **Checkpoint:** whole suite green before any demo work. Review point with the developer: report the seed size and time.

## Slice 6: map effects (menara-demo backend)

**Files.** Create `packages/menara-demo/src/menara_demo/map_effects.py`, `packages/menara-demo/tests/test_map_effects.py`. Modify `runs.py`, `tests/test_runs.py`.

**Step 0 (read only).** Print the real result shapes of `tower_get_status`, `ontology_blast_radius`, `flood_get_gauge`, `flood_check_point`, `drone_dispatch`, `drone_get_mission`, `ran_tilt_cells`, `ticket_cluster_by_location` from the golden trace or a stdio call, and use them as the fixtures in the tests. No guessing of shapes.

**Interfaces.**
- `Effect = TypedDict` with `kind, lat, lng, label, tone` (`kind` in focus, pin, ring, link, area).
- `effects_for(db_file: Path, name: str, arguments: dict[str, Any], result_text: str) -> list[Effect]` (pure given the database; never raises).
- In `RunManager._run`, wrap `on_event`: remember `call` arguments by step; on a `result` event with `ok`, compute effects and append `{"type": "map", "step": n, "effects": [...]}` after the result event when the list is non-empty.

**Tests first.**
- `test_a_tower_tool_focuses_the_tower_with_the_right_tone` (DOWN is `bad`, high PRB `warn`, else `ok`)
- `test_blast_radius_gives_a_ring_and_pins_capped_at_40`
- `test_flood_tools_give_an_area`
- `test_drone_tools_give_an_info_pin`
- `test_tilt_tools_focus_every_changed_tower`
- `test_ticket_cluster_gives_pins_capped_at_40`
- `test_coordinates_come_from_the_database_not_from_the_result` (a fake result with wrong lat/lng still yields the database position)
- `test_unknown_tool_garbage_json_and_unknown_tower_give_no_effects_and_do_not_raise`
- `test_no_effect_carries_a_subscriber_hash`
- `test_runs.py::test_a_map_event_follows_a_result_event_with_the_same_step`
- `test_runs.py::test_a_failing_effect_builder_does_not_break_the_run`
- `test_replay.py` (existing end-to-end on real stdio servers): add `test_replay_emits_map_events_for_tower_and_blast_radius`

**Expected red.** `ModuleNotFoundError: menara_demo.map_effects`; no `map` events in a run.

**Green.** Implement the table in spec 16 against the fixtures from Step 0; wire the wrapper.

**Validate.** `T packages/menara-demo -q`, ruff, mypy. **Checkpoint:** demo suite green, existing events unchanged.

## Slice 7: routines and the routines route (menara-demo backend)

**Files.** Create `packages/menara-demo/src/menara_demo/routines.py`, `tests/test_routines.py`. Modify `trail_story.py`, `app.py`, `tests/test_story.py`.

**Interfaces.**
- `build_routines(segments: list[dict], towers: list[dict]) -> list[dict]` and helpers: `weekend_days_in_window(window_start_iso, now_iso) -> int`, `routine_sentence(...) -> str`.
- Per-tower fact fields: `weekday_days`, `weekend_days`, `weekend_weekends` (distinct weekends), `weekend_days_in_window`, `typical_arrival_hour`, `typical_minutes`. A stop under 30 minutes is not counted.
- `nearby_sites` entries gain `lat`, `lng`.
- Rules: weekend habit needs at least 3 weekend days and at least 2 distinct weekends; weekday habit needs at least 5 weekdays; otherwise the place is an occasional stop with no habit sentence.
- Routes: `GET /api/trail/routines?msisdn_hash=&window_min=`; `POST /api/trail/story` default window 40320 and range 5 to 40320; both return `routines`.

**Tests first.**
- `test_routines.py::test_counts_weekday_and_weekend_days_with_real_dates` (the scenario T0 is a Saturday: the window starting 2026-10-17 has 4 weekends, 8 weekend days)
- `test_a_weekend_habit_needs_three_days_across_two_weekends`
- `test_a_weekday_habit_needs_five_weekdays`
- `test_a_stop_under_30_minutes_is_ignored`
- `test_the_sentence_names_the_site_and_the_counts` (`Weekends: near Tawau Mall 3 (synthetic) on 4 of 4 weekends, usually about 2 h 30 min from about 11:00`)
- `test_a_place_with_no_known_site_nearby_says_so`
- `test_story.py::test_story_uses_a_28_day_window_and_returns_routines`
- `test_story.py::test_routines_route_works_without_a_model_key` (200 with `llm=None`)
- `test_story.py::test_routines_route_maps_errors` (400, 404; window 40321 is 400)
- `test_story.py::test_prompt_tells_the_model_to_use_only_routines_and_never_invent_a_frequency`
- Existing story tests: the fake trail gets weekend timestamps; the hub fake accepts the longer window.

**Expected red.** `ModuleNotFoundError: menara_demo.routines`; `404` for the new route.

**Green.** Implement; rules text in `RULES`.

**Validate.** `T packages/menara-demo -q`, ruff, mypy. **Checkpoint:** a real-server check: call `/api/trail/routines` on a real seeded database for a known mall-regular (found with a read-only SQL query) and read the sentences.

## Slice 8: the page (menara-demo, `index.html`)

The page is plain JS without a test runner, so the logic that matters is already in Python (slices 6 and 7). This slice adds three guards and then the visual work, in small steps, each checked by hand.

**Tests first (`packages/menara-demo/tests/test_page.py`, pure file checks).**
- `test_the_page_loads_only_from_allowed_hosts` (parses every `src` and `href` and CSS `url(...)`; allowed: unpkg.com, basemaps.cartocdn.com, same origin)
- `test_the_page_has_the_hooks_the_story_needs` (ids for the stats strip, the map-effect layer, the routine panel, the replay controls, the legend; the string `prefers-reduced-motion`; the handler name for `"map"` events)
- `test_the_demo_badge_and_synthetic_wording_are_present`
- `test_no_real_brand_names_in_the_page` (a small deny-list)

**Expected red.** The ids and the map handler do not exist yet.

**Steps (each is a commit-sized edit; after each one, run the demo and look at it).**
1. Theme: CSS variables, dark panels, dark tiles with an offline fallback background, legend, badge. Contrast checked against 4.5:1 by computing it in the test for the main text and background pair.
2. Stats strip: towers up, down and degraded from the loaded tower list, `Tickets (cluster)`, incident status, clock; refreshes on clock change and after each map event.
3. Map effects: a `mapEffects` layer; `renderMapEvent(event)`: fly once per step (max 1.2 s), fade-in, pulse on `bad`; kept until the run ends or a new run starts; click on a timeline card refocuses its effects; reduced-motion disables fly and pulse.
4. Trail replay: dashed animated line, moving dot, time label, Play, Pause, speed.
5. Routine panel: fetch `/api/trail/routines`, table with kind icons, regular places drawn on the map; Explain button reuses the facts.

**Validate.** `T packages/menara-demo -q`; then a manual pass in the browser: Replay with the map visible, one DOWN tower pulse, blast radius, a trail with Play, a routine table for a mall regular; a screenshot of each saved to the scratchpad and looked at. **Checkpoint:** developer sees the live demo (Replay is enough; Live if the key is present).

## Slice 9: docs (doc-drift)

**Files.** `servers/sites-mcp/README.md`, `servers/user-mcp/README.md` (done in slices 2 and 4; re-read), `packages/menara-demo/README.md` (map events, routines, new route, tiles host), root `README.md`, `CLAUDE.md` and `AGENTS.md` (sites and user rows, demo row; re-seed note), `docs/specs/demo-wow.md` (apply the three clarifications above).

**Validate.** `uv run python scripts/check_skill_parity.py` (should still pass); a read-through that `CLAUDE.md` and `AGENTS.md` still agree. **Checkpoint:** no stale numbers (2880, "six kinds").

## Slice 10: verification (fresh evidence, nothing assumed)

Run and report: `uv run python -m ruff check .`, `uv run python -m mypy`, `uv run python -m pytest` (full, including golden trace and Replay e2e), `uv run python scripts/check_skill_parity.py`, a fresh default `menara-seed` (time and size), the stdio smoke calls from Slice 5, the Replay run in the browser with screenshots, and, if the key is present, one live run. Then `completion-checkpoint`: the developer chooses commit, push, PR or leave. Re-seeding the developer's own `data/menara.db` is only done with their say-so (servers must be stopped).

## Risks and how the plan handles them

- Seed size and time: measured in Slice 3, with a stated fallback to 21 days.
- Hidden coupling to `-1440` as the first visit: found by the full test suite in Slices 3 to 5; each failure is judged against the spec (approved change) or fixed (regression).
- Real result shapes unknown for map effects: Step 0 of Slice 6 reads them first.
- The tile host is external: offline fallback is tested in the hooks test and checked by hand.
- The IDE has previously re-inserted stale lines into files that were open: after each edit of a large file, re-read the changed region.