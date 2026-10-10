# TDD plan: towers and subscribers around a point, and a subscriber's trail

Spec: `docs/specs/map-subscribers.md` (criteria are cited as C1 to C21). Every slice leaves the suite green. Run a slice's tests with `uv run python -m pytest <path>`.

## Global constraints

- Allowed to change: `packages/menara-core/src/menara_core/seed/{schema,movement,build}.py` (new `movement.py`), `packages/menara-core/tests/`, `servers/tower-mcp/**`, `servers/user-mcp/**`, `CLAUDE.md`, `AGENTS.md`, `.claude/skills/mcp-contract-guard/SKILL.md` (plus its Codex twin via the sync script), `docs/**`.
- Must not change: `data/scenario/kuala_krai.yaml`, any other server, `.mcp.json`, root `pyproject.toml`, ports, `tests/golden_trace/` (it must still pass untouched).
- Tables written: none by the servers (all new tools are read-only); the seed writes the new `subscriber_cell_visit` table only.
- Privacy: hashed MSISDN, cell-level coordinates, small-group rule from `menara_core.privacy`. `mcp[cli]>=1.9,<2`. mypy strict.

## Slice 1: the seed generates trails (C19, C20, C21, C17 data half)

- Files: `seed/schema.py` (new table and index), `seed/movement.py` (new), `seed/build.py` (call it last, add its count to the summary), `packages/menara-core/tests/test_movement.py` (new).
- Interface produced: `build_movement(conn, seed, scenario) -> None`, using `random.Random(f"{seed}:movement")`.
- Failing tests first, in `test_movement.py` (expected red: `no such table: subscriber_cell_visit`):
  - `test_every_subscriber_is_where_the_subscriber_table_says_at_minute_0`
  - `test_cluster_subscribers_never_move`
  - `test_at_least_30_percent_of_the_other_subscribers_move_between_existing_towers`
  - `test_visits_are_ordered_and_in_the_seeded_period` (rows from -1440, strictly increasing `start_min`, none after 480)
  - `test_the_same_seed_gives_the_same_trails_and_leaves_old_tables_unchanged` (build twice, compare; compare the pre-existing table row counts with fixed numbers taken from the baseline run)
  - `test_commuters_stop_at_a_tower_between_home_and_work`
- Green: schema, generator, wiring. Baseline numbers (for the "unchanged" check) are recorded from `main` before editing.
- Refactor: none expected. Checkpoint: `uv run python -m pytest packages` and the whole suite (other servers' tests prove they are unaffected).

## Slice 2: `tower_list_in_radius` (C1 to C7)

- Files: `servers/tower-mcp/src/tower_mcp/{models,tools,server}.py`, tests in `servers/tower-mcp/tests/test_tools.py`, `test_sources.py`, `test_server.py`.
- Produced: `TowerNearby` (pin fields plus `distance_km`), `TowerRadiusList`, `tools.list_in_radius(source, lat, lng, radius_km, status=None, limit=500)`, registration in `server.py` (tool count 5).
- Failing tests first (expected red: `AttributeError: module 'tower_mcp.tools' has no attribute 'list_in_radius'`):
  - `test_radius_returns_towers_nearest_first_with_distance`
  - `test_a_tower_in_the_box_corner_but_outside_the_circle_is_excluded` (builds a fake source with a tower at the corner)
  - `test_radius_status_filter_and_limit_truncation`
  - `test_radius_warns_when_the_box_prefetch_overflows` (fake source returning more than the maximum)
  - `test_radius_validation`
  - `test_radius_is_the_same_on_both_sources` (in `test_sources.py`, uses the `any_source` fixture)
  - `test_server_registers_the_radius_tool`
- Green: box prefilter with `bbox_around`, exact filter with `haversine_km`, sort, truncate. No source change.

## Slice 3: `user_list_in_area` and `user_list_on_tower` (C8 to C14)

- Files: `servers/user-mcp/src/user_mcp/{models,tools,server}.py`, tests in `servers/user-mcp/tests/test_tools.py`, `test_server.py`.
- Produced: `AreaSubscriber`, `TowerSubscribers`, `SubscriberList`, `tools.list_in_area`, `tools.list_on_tower`. The cell at the current clock is `SELECT ... FROM subscriber_cell_visit WHERE start_min <= now ORDER BY start_min DESC LIMIT 1` per subscriber (a window query in SQL); `subscribers_est` comes from `tower_subscribers`.
- Failing tests first (expected red: `AttributeError ... list_on_tower`):
  - `test_list_on_tower_returns_sampled_and_estimated_counts`
  - `test_flooded_tower_subscribers_are_detached_and_no_service` and `test_overloaded_neighbour_subscribers_are_degraded` (C13, clock 12)
  - `test_area_around_a_town_lists_its_towers_and_subscribers`
  - `test_fewer_than_five_matches_are_withheld` and `test_five_or_more_are_returned`
  - `test_limit_truncates_but_the_total_is_kept`
  - `test_a_mover_appears_on_the_new_tower_after_they_move` (C14, moves the clock)
  - `test_list_validation_and_unknown_tower`
  - `test_server_registers_the_list_tools`
- Green: the two functions sharing one helper.

## Slice 4: `user_get_trail` and the serving cell follows the trail (C15 to C18)

- Files: `servers/user-mcp/src/user_mcp/{models,tools,server}.py`, tests in `test_tools.py`, `test_server.py`.
- Produced: `TrailSegment`, `Trail`, `tools.get_trail`. `get_serving_cell` reads the latest visit at or before the clock and falls back to the `subscriber` row.
- Failing tests first (expected red: `AttributeError ... get_trail`):
  - `test_a_stationary_subscriber_has_one_current_segment`
  - `test_a_commuter_has_home_transit_and_work_segments_with_times`
  - `test_the_trail_never_extends_past_the_clock`
  - `test_window_selects_overlapping_segments_and_clips_durations`
  - `test_serving_cell_follows_the_trail_and_matches_the_table_at_minute_0` (C17)
  - `test_trail_validation_and_unknown_subscriber`
  - `test_server_registers_the_trail_tool`
- Green: segment builder over `subscriber_cell_visit`. Existing `user_get_serving_cell` tests and the golden trace stay unchanged and green.

## Slice 5: docs, guard skill, and smoke

- Files: `servers/tower-mcp/README.md`, `servers/user-mcp/README.md` (contract rows, privacy line, the experience limitation, PDPA sentence), `CLAUDE.md` and `AGENTS.md` (status table counts, rule 2 read exceptions), `.claude/skills/mcp-contract-guard/SKILL.md` then `uv run python scripts/sync_codex_skills.py`.
- Real checks: start `user-mcp` and `tower-mcp` over stdio and call each new tool once against a freshly seeded database; run `uv run menara-seed` equivalent and confirm the summary lists the new table; run `doc-drift`.
- Validation for the whole change: `uv run python -m pytest`, `uv run python -m ruff check .`, `uv run python -m mypy`, `uv run python scripts/check_skill_parity.py`.

## Review checkpoints

After slice 1 (the data is right and nothing old changed), and after slice 5 (full validation).