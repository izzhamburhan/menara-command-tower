# TDD plan: eight new MCPs and a six-track story

Spec: `docs/specs/tracks-mcps.md` (approved). Branch `feat/tracks-mcps`, worktree `.worktrees/feat/tracks-mcps`.
Every slice: write the named tests first, run them and see the stated red, write the minimum code, see green, run the slice validation, commit locally. Each slice leaves the whole suite green. `T` = `uv run python -m pytest`. Nothing is pushed or merged without the developer's say-so.

Large files that are open in the IDE have been merged with stale lines before. After editing an existing file, check the changed region and re-run the tests after a pause. New files are written with the Write tool; a big rewrite of an existing file goes through a copy from outside the repo.

## The template every server slice follows (so each slice below says only what differs)

For a server `X` with port `P`, tables and tools as in the spec:

1. **Seed (menara-core).** Add the tables to `seed/schema.py` (base tables seed-only; owned tables created empty), a module `seed/<domain>.py` with `build_<domain>(conn, seed, towers, scenario)` on its own stream `f"{seed}:<domain>"`, a call in `seed/build.py`, and the new tables in the summary counts. Tests in `packages/menara-core/tests/test_<domain>_seed.py` (shape, counts, ranges, same seed gives the same rows, older tables unchanged because `test_movement.py`'s BASELINE still matches). Red: `sqlite3.OperationalError: no such table`.
2. **Scaffold.** `uv run python scripts/new_mcp.py X --port P --description "..." [--owns tables]`, `uv sync`. Update the three server-count tests (`packages/menara-agent/tests/test_servers.py`, `tests/test_run_mcp.py`) before scaffolding and see them fail (`assert 13 == 14` and so on); after the scaffold they pass.
3. **Tools, tests first.** `servers/X-mcp/tests/test_tools.py` (happy path, error, boundary, clock, privacy, token cases for writes, the placeholder test replaced) and `tests/test_server.py` (tools registered, an envelope returned), then `models.py`, `tools.py`, `server.py`. Red: `AttributeError: module 'x_mcp.tools' has no attribute ...`.
4. **README contract**, with the tables read and written, ranges, errors and a flood-scenario section.
5. **Runtime tables to reset.** Add each owned table to `RUNTIME_TABLES` in `menara_core/reset.py`, and the expected list in `test_reset.py` (red first: the list assertion fails).
6. **Validate.** `T servers/X-mcp packages/menara-core -q`, ruff, mypy, a real stdio call against a fresh full seed (print the answers for a Kuala Krai and a Tawau example and read them), then the whole suite. Commit.

Constants and models stay small. Money, rates and factors are named module constants with a comment "synthetic". Every `data` model has a `note` field that says it is synthetic. No file contains a real phone number, brand or person.

## Global constraints

- Tables written: only the owned ones listed in the spec; the demo reads through the hub, never the database (except the existing read-only position lookups).
- Write tools verify `verify_token(settings.signing_key(), token, action=..., target=target_key(towers))` (a single tower uses `target_key([name])`), exactly as `ran-mcp` and `drone-mcp` do.
- Privacy: no subscriber hash or message recipient anywhere; groups under 5 are withheld.
- `mcp[cli]>=1.9,<2`; `python -m` on Windows; ruff and mypy strict.

**Scope boundary.** May change: `packages/menara-core/**`, `servers/<new>-mcp/**` (new), `servers/policy-mcp/**` (three action names and tests), `packages/menara-agent/tests/test_servers.py`, `tests/test_run_mcp.py`, `packages/menara-demo/**`, `.mcp.json`, root `pyproject.toml` and `uv.lock` (only what `new_mcp.py` and `uv sync` change), `docs/**`, README, `CLAUDE.md`, `AGENTS.md`. Must not change: `data/scenario/kuala_krai.yaml`, the other servers' source, `tests/golden_trace` (passes unchanged), `.github`, `.claude/skills`, `packages/menara-agent/src`.

---

## Slice 0: policy knows the three new actions

**Files.** `servers/policy-mcp/src/policy_mcp/tools.py` (`ACTIONS`), `servers/policy-mcp/tests/` (the existing known-actions and always-ask tests), `servers/policy-mcp/README.md`.

**Tests first.** `test_the_new_actions_are_known` (`energy_sleep_cells`, `exposure_book_qod`, `enterprise_issue_credit` in `known_actions`), `test_exposure_and_credit_always_ask_a_human` (decision `ask` even at confidence 1.0 and a tiny audience), `test_energy_sleep_follows_the_normal_rules` (small audience, high confidence, off-peak gives `allow` with a token; in the peak window gives `ask`), `test_the_kill_switch_and_the_hourly_cap_apply_to_the_new_actions`.

**Expected red.** `known_actions` lacks the names; `check_action` treats them as an unknown profile (normal rules), so the always-ask tests fail.

**Green.** Add three `ActionProfile` entries (`energy_sleep_cells` plain, the other two with `always_ask`).

**Validate.** `T servers/policy-mcp -q`, ruff, mypy. **Checkpoint:** policy suite green.

## Slice 1: energy-mcp (port 8114, owns `energy_action`)

**Seed.** `tower_energy(enodeb_name PK, base_kw, battery_kwh, has_genset, genset_fuel_l, genset_l_per_h)`, `energy_action(seq PK AUTOINCREMENT, action_id UNIQUE, enodeb_name, kind CHECK ('SLEEP'), from_min, to_min, kwh_saved, co2_kg_saved, approved_by, reason)`. `seed/energy.py`: base kW by tower type (macro 3.2, rooftop 1.6, plus urban 15%), battery kWh by type, generator on ~40% of towers, `KKRI-0142` has a generator with about 9 hours of fuel. Tests (`test_energy_seed.py`): `test_every_tower_has_an_energy_row`, `test_ranges_are_sane`, `test_the_flooded_tower_has_a_generator_with_limited_fuel`, `test_same_seed_same_energy`.

**Tools (`tools.py`).** `get_tower(conn, enodeb_name)`, `find_savings(conn, lat, lng, radius_km=15.0, hour=None)`, `apply_sleep(conn, enodeb_names, policy_token, reason)`. Constants: `CO2_KG_PER_KWH = 0.585`, `SLEEP_WINDOW = (0, 6)`, `SLEEPABLE_SHARE = 0.35`, `MAX_TOWERS = 20`, `PRB_QUIET = 25.0`.

**Tests first (`test_tools.py`).**
- `test_the_flooded_tower_runs_on_battery_or_generator_with_a_finite_time_left_and_a_warning`
- `test_a_healthy_tower_is_on_mains_and_has_no_hours_warning`
- `test_draw_rises_with_load`
- `test_savings_only_in_the_sleep_window` (empty at 07:00, non-empty at 03:00 from the `set_clock` fixture)
- `test_candidates_need_two_cells_quiet_load_up_neighbours_and_no_emergency_site`
- `test_a_tower_in_a_flood_extent_is_never_a_candidate`
- `test_apply_sleep_writes_one_action_per_tower_and_returns_totals` (with a real token from `issue_token` for `energy_sleep_cells` and `target_key`)
- `test_apply_sleep_rejects_a_missing_or_wrong_token` (`TokenError`)
- `test_a_non_candidate_or_a_repeat_is_invalid_input`
- `test_the_draw_drops_after_an_action_until_its_end_and_the_saving_is_capped`
- `test_energy_actions_get_ids_ena_0001_and_up`
- `test_bad_ranges_are_invalid_input` (radius, hour, 0 or 21 towers)

**Reset.** Add `energy_action` to `RUNTIME_TABLES` and the expected set in `test_reset.py`.

**Validate and checkpoint.** As in the template. Stdio smoke: Kuala Krai tower (battery or generator hours), savings at 03:00 for Kuala Lumpur, one approved sleep through a token.

## Slice 2: care-mcp (port 8115, owns `care_notice`)

**Seed.** `care_template(kind CHECK, language CHECK, body)`: 3 kinds x 4 languages = 12 rows with placeholders `{area}`, `{cause}`, `{eta}`, `{care_line}`; `care_notice(seq, notice_id UNIQUE, towers, language, recipients_est, message, sent_min, sent_at, approved_by, tickets_deflected_est)`. Language mix per town as a function in `seed/care.py` (stored as `seed_meta` keys or a small table `care_language_mix(town, language, share)`; use the table so it is data).

**Tools.** `get_impact`, `draft_notice`, `send_notice`, `list_notices`. Constants: `SMS_COST_RM = 0.06`, `EXTRA_TICKET_RATE = {"FLOOD": 0.045, "POWER": 0.03, "DEFAULT": 0.02}`, `DEFLECTION = 0.55`, `DEDUPE_MIN = 30`, `MIN_RECIPIENTS = 5`.

**Tests first.**
- `test_impact_counts_only_towers_that_are_down_or_degraded` (at T0 the flood cluster; a healthy tower alone gives zero)
- `test_impact_predicts_extra_tickets_and_the_open_tickets_and_the_language_mix`
- `test_impact_is_withheld_under_5_customers`
- `test_the_draft_fills_the_template_in_each_language_and_is_not_sent` (nothing written; `care_notice` stays empty)
- `test_the_draft_has_cost_recipients_and_expected_deflection_and_no_real_phone_number`
- `test_send_needs_a_comms_send_notice_token_for_those_towers` (and `TokenError` otherwise)
- `test_send_writes_a_notice_with_an_id_ntc_0001_and_the_deflection`
- `test_send_validates_message_length_and_an_empty_audience`
- `test_the_same_message_to_the_same_towers_within_30_minutes_is_invalid_input`
- `test_after_a_notice_the_predicted_extra_tickets_fall`
- `test_list_notices_newest_first_and_has_counts_only` (no recipient anywhere in the serialised answer)

**Reset.** `care_notice`.

## Slice 3: enterprise-mcp (port 8116, owns `sla_credit`)

**Seed.** `enterprise_account(account_id PK, name, sector, enodeb_name, plan, monthly_value_rm, sla_availability_pct, penalty_rm_per_hour)`: one per `ENTERPRISE` critical site, plus five fictional accounts on the cluster towers (`KKRI-0142` has two, so the DOWN tower has revenue at risk), plus up to three per town; names end `(synthetic)`. `sla_credit(seq, credit_id UNIQUE, account_id, from_min, hours, amount_rm, issued_min, issued_at, approved_by, reason)`.

**Tools.** `get_revenue_at_risk(conn, enodeb_names=None, lat=None, lng=None, radius_km=15.0)`, `list_accounts(conn, lat, lng, radius_km=15.0, limit=50)`, `issue_credit(conn, account_id, hours, policy_token, reason)`. Outage minutes come from `tower_state` (the time since the tower went DOWN, or DEGRADED since). Projection: next 2 hours at the penalty rate.

**Tests first.**
- `test_every_enterprise_site_has_an_account_and_names_say_synthetic`
- `test_accounts_on_the_down_tower_are_at_risk_with_outage_minutes_from_tower_state`
- `test_a_healthy_tower_has_no_accounts_at_risk`
- `test_revenue_per_hour_penalty_so_far_and_two_hour_projection_add_up`
- `test_area_and_tower_selectors_and_neither_given_is_invalid_input`
- `test_list_accounts_in_a_circle_with_service_state`
- `test_issue_credit_needs_the_token_for_the_accounts_tower` (`TokenError` otherwise)
- `test_issue_credit_amount_is_hours_times_penalty_capped_at_monthly_value`
- `test_a_credit_for_an_unaffected_account_is_invalid_input`
- `test_overlapping_credit_hours_are_invalid_input`
- `test_after_a_credit_the_net_exposure_falls_and_the_credit_is_listed`
- `test_credit_ids_crd_0001_and_up`

**Reset.** `sla_credit`.

## Slice 4: exposure-mcp (port 8117, owns `qod_booking`)

**Seed.** `qod_profile(profile_id PK, name, kind, guaranteed, unit, headroom_prb, price_rm_per_hour_per_tower)` with 4 rows; `qod_booking(seq, booking_id UNIQUE, profile_id, towers, customer, from_min, to_min, price_rm, approved_by, reason)`. `crowd_event` is created in slice 6; this server reads it only if present, so quote tests do not depend on it before then (a `table_exists` guard returns zero uplift).

**Tools.** `list_profiles`, `quote(conn, profile_id, enodeb_names, duration_min, start_in_min=0)`, `book(conn, profile_id, enodeb_names, duration_min, customer, policy_token, reason)`. Headroom = `100 - PRB` now minus reservations from active bookings and minus a forecast uplift when a crowd event touches the tower.

**Tests first.**
- `test_four_profiles_with_prices_and_headroom_needs`
- `test_a_quiet_tower_is_feasible_and_the_quote_adds_up`
- `test_an_overloaded_tower_is_not_feasible_with_the_reason` (the flood neighbours at 91% PRB)
- `test_duration_start_and_tower_limits_are_validated`
- `test_book_needs_the_exposure_book_qod_token_and_writes_a_booking_bkg_0001`
- `test_booking_an_infeasible_tower_or_a_bad_customer_name_is_invalid_input`
- `test_reserved_headroom_shows_in_the_next_quote_for_the_same_window`
- `test_the_quote_includes_event_uplift_when_an_event_is_present` (added in slice 6, marked then)

**Reset.** `qod_booking`.

## Slice 5: field-mcp (port 8118, owns `field_job`)

**Seed.** `technician(tech_id PK, name, depot_id, lat, lng, skills, shift_start_hour, shift_end_hour)` (about 30, 2 to 4 per depot using the drone depots, fictional names), `spare_part(depot_id, part, qty)`; `field_job(seq, job_id UNIQUE, tech_id, enodeb_name, task, skill, dispatched_min, dispatched_at, eta_min, access CHECK ('ROAD','BOAT'), approved_by, reason)`.

**Tools.** `find_crew(conn, enodeb_name, skill)`, `dispatch(conn, enodeb_name, tech_id, task, policy_token, reason)`, `list_jobs(conn, status=None, limit=50)`. Constants: `ROAD_KMH = 55`, `BOAT_KMH = 18`, `BOAT_EXTRA_MIN = 25`, `UNSAFE_DEPTH_M = 0.5`. Status from the clock like drone missions.

**Tests first.**
- `test_crew_are_ranked_by_eta_and_must_have_the_skill_and_be_on_shift`
- `test_a_tower_in_the_flood_extent_gets_boat_access_with_extra_time_and_a_safety_note`
- `test_road_into_deep_water_is_not_safe_to_dispatch_but_boat_is`
- `test_parts_for_the_skill_are_reported_per_depot`
- `test_dispatch_needs_the_workforce_create_order_token_and_writes_a_job_job_0001`
- `test_dispatch_rejects_a_busy_or_off_shift_or_unskilled_technician`
- `test_dispatching_road_into_unsafe_water_is_invalid_input`
- `test_job_status_follows_the_clock_en_route_on_site_done`
- `test_list_jobs_filters_by_status`

**Reset.** `field_job`.

## Slice 6: events-mcp (port 8119, read-only)

**Seed.** `crowd_event(event_id PK, name, kind, town, lat, lng, radius_km, start_min, end_min, attendance)`: about 25 fictional events (names end `(synthetic)`), spread over the first 4 days after T0 and across states; `seed/events.py` picks venues near existing towers.

**Tools.** `list_upcoming`, `forecast_load(event_id)`, `capacity_plan(event_id)`. Model constants: `KB_PER_ATTENDEE_MIN`-style load per attendee turned into PRB points with a stated formula, spread by inverse distance to the 5 nearest towers; risk `LOW`/`MEDIUM`/`HIGH` at 70% and 85%.

**Tests first.** `test_events_exist_in_the_future_and_are_synthetic_named`, `test_list_upcoming_by_circle_and_window_soonest_first`, `test_an_event_in_the_past_is_not_listed`, `test_forecast_adds_load_to_the_nearest_towers_and_labels_the_risk`, `test_a_bigger_crowd_gives_a_higher_risk`, `test_the_capacity_plan_names_towers_the_exposure_profile_and_the_next_tool` (as data, nothing executed), `test_an_unknown_event_is_not_found`, `test_bad_ranges_are_invalid_input`.

**Follow-up in exposure.** Turn on `test_the_quote_includes_event_uplift_when_an_event_is_present` and wire the uplift (red then green).

## Slice 7: sensors-mcp (port 8120, read-only)

**Seed.** `iot_sensor(sensor_id PK, kind CHECK, name, lat, lng, owner, enodeb_name, warn_value, danger_value, unit)`, `iot_reading(sensor_id, t_min, value, PRIMARY KEY (sensor_id, t_min))`: a sensor set per town (2 to 4: rain, air quality, and water level near rivers); near Kuala Krai, the water sensors follow `flood_reading` (scaled to the sensor's unit and thresholds); readings every 15 minutes from -1440 to the end of the scenario.

**Tools.** `list_in_area`, `get_readings`, `get_alerts` (projected time to danger by a linear fit on the last hour; `null` when falling).

**Tests first.** `test_each_town_has_sensors_and_the_flood_ones_follow_the_gauge`, `test_readings_have_a_value_every_15_minutes_and_stop_at_the_clock`, `test_readings_window_is_validated`, `test_alerts_at_t0_include_the_kuala_krai_water_sensors_and_exclude_quiet_places`, `test_a_rising_sensor_has_a_projected_time_to_danger_and_a_falling_one_has_none`, `test_alerts_are_sorted_most_urgent_first`, `test_kind_filter_and_unknown_sensor`.

## Slice 8: scam-mcp (port 8121, read-only)

**Seed.** `scam_pattern(pattern_id PK, name, kind CHECK, severity, example, advice)` (10 fictional, generic wording, no real brand), `scam_signal(pattern_id, town, t_min, reports, blocked, PRIMARY KEY (pattern_id, town, t_min))` (hourly, 3 patterns trend up in a couple of towns around T0).

**Tools.** `get_hotspots`, `get_pattern`, `estimate_protection` (constants `AVG_LOSS_RM`, `PROTECTED_SHARE` stated and synthetic).

**Tests first.** `test_patterns_are_generic_and_synthetic_and_carry_no_number_or_brand`, `test_hotspots_rank_patterns_by_reports_with_a_trend`, `test_groups_under_5_reports_are_withheld`, `test_window_and_radius_are_validated`, `test_pattern_lookup_and_unknown_pattern`, `test_protection_estimate_is_labelled_an_estimate_and_scales_with_the_circle`, `test_no_response_contains_a_phone_number_pattern` (a regex over the serialised answer for digit runs that look like numbers).

## Slice 9: the Tracks backend in menara-demo

**Files.** Create `packages/menara-demo/src/menara_demo/tracks.py` and `scripted_tracks.py`; modify `runs.py`, `app.py`, `map_effects.py`; tests `test_tracks.py`, additions to `test_runs.py`, `test_replay.py`, `test_map_effects.py`.

**Interfaces.**
- `TRACKS = {1: "Industry and Operations", ..., 6: "Revenue Streams"}`; `track_for(name) -> int | None` from the tool-to-track table in spec item 47; `TrackTracker.observe(name, arguments, text, ok=True) -> dict | None` returning `{"track", "name", "label"}`.
- `async def tracks_state(hub, clock_min, as_of) -> dict` with the six cards (spec item 45), from the hub only (`care_list_notices`, `care_get_impact`, `enterprise_get_revenue_at_risk`, `field_list_jobs`, `energy_get_tower`, `exposure_list_profiles`? no: bookings come from a read tool on exposure: add `exposure_list_bookings` if the state needs it; otherwise the booking total comes from the quote/booking results kept by the page, so the state includes bookings via the `exposure_book` events: decide in the first red test and keep it in the exposure slice if needed).
- `TracksReplayModel(ChatClient)`: the incident script followed by the track steps; selected by `"script": "tracks"` in `POST /api/agent/run`; ids and tokens are read out of earlier results.

**Tests first.**
- `test_every_new_tool_belongs_to_one_track_and_unknown_tools_have_none`
- `test_a_track_event_follows_the_result_and_heal_events`
- `test_tracks_state_before_anything_is_done_says_what_is_waiting` (fake hub)
- `test_tracks_state_sums_notices_credits_and_energy_saved` (fake hub)
- `test_tracks_state_shows_only_what_has_happened_by_the_clock`
- `test_the_tracks_script_extends_the_incident_script_and_stops_cleanly_on_a_rejection`
- `test_run_script_must_be_incident_or_tracks` (400 otherwise)
- `test_map_effects_for_field_energy_exposure_sensors_events` (shapes copied from real output)
- `test_replay.py::test_the_tracks_replay_reaches_all_six_tracks_with_five_approvals_more` (real stdio servers: all 21 needed servers; every track appears in the `track` events; ids `NTC-0001`, `CRD-0001`, `JOB-0001`, `ENA-0001`, `BKG-0001` exist; the state shows non-zero kWh, RM credited and tickets deflected)
- `test_replay.py::test_reset_after_the_tracks_replay_clears_the_new_tables_and_a_second_run_gives_the_same_ids`

**Expected red.** `ModuleNotFoundError: menara_demo.tracks`; `400` or ignored `script`.

**Green.** Implement; extend `NEEDED` servers in the replay fixture.

**Validate.** `T packages/menara-demo -q`, ruff, mypy. **Checkpoint:** read the real tracks state JSON after the Replay.

## Slice 10: the Tracks tab and Console examples

**Files.** `packages/menara-demo/src/menara_demo/static/index.html` (via a copy from outside the repo), `tests/test_page.py`.

**Tests first (page guards).** `test_the_page_has_the_tracks_hooks` (`tabTracks`, `paneTracks`, `trackCards`, `tracksReplay`, `/api/tracks/state`, `event.type === "track"`, `"script": "tracks"` or `script: "tracks"`), `test_all_six_tracks_are_named_on_the_page`, `test_every_new_tool_has_a_console_example` (the new tool names appear in the `EXAMPLES` block), existing guards stay.

**Steps (each checked with a headless screenshot).** (1) Tab and six-card layout with idle states; (2) cards fill from `/api/tracks/state` and light up on `track` events; (3) "Run six-track Replay" button and `#tracks` scene; (4) Console examples; (5) a design check at desktop and 390 px.

**Validate.** Guards green; screenshots of the idle tab, the tab mid-run and after the run; no JS errors. **Checkpoint:** developer sees the screenshots.

## Slice 11: docs (doc-drift)

Each server README is done in its slice (re-read). Update `packages/menara-demo/README.md` (Tracks tab, six-track Replay, new routes and event, scene link), root `README.md` (twenty-one servers, eight table rows, tool totals, the Tracks story), `CLAUDE.md` and `AGENTS.md` (ports 8114 to 8121, status rows, "All 21", layout), `docs/specs/tracks-mcps.md` (as-built notes). Grep for stale `thirteen`, `13`, `55 tools`, `59 tools`.

## Slice 12: verification

Fresh run and read: `uv run python -m ruff check .`, `uv run python -m mypy`, `uv run python -m pytest` (full, golden trace and replays included), the skill parity check, a default seed (seconds and size), the stdio smoke calls of each server, the six-track Replay in a real browser with screenshots and a reset between two runs, and, if a key is present, one live run. Then `completion-checkpoint`.

## Risks

- **Size.** Eight servers in one branch. The slices are independent, each commit leaves the suite green, and the developer can stop or merge after any slice group.
- **Seed size and time.** Sensors and scam signals are the largest tables; their sizes are measured in their slices, with a stated cap (under 30 MB added in total).
- **Replay length and approvals.** The tracks script adds five approvals; the page tells the user to press Approve in the Story tab, and the heal view already shows "waiting for your decision".
- **IDE merges** into open files: guard tests and whole-file copies, as before.