# events-mcp

Crowd events ahead (festivals, matches, concerts, the balik kampung rush) and the load they will put on the towers around the venue. **All data is synthetic**: fictional events (names end in "(synthetic)") and invented crowd sizes and load figures. Track 4 (networks and infrastructure).

Read-only; owns no tables. Reads `crowd_event`, `tower`, `tower_kpi`, `tower_subscribers`. The crowd model is shared with exposure-mcp in `menara_core.crowd`.

## Run

```bash
uv run python -m menara_core.seed.cli                                 # re-seed: the crowd_event table is new
uv run --package events-mcp python -m events_mcp                      # stdio
uv run --package events-mcp python -m events_mcp --transport streamable-http --port 8119
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `events_list_upcoming` | `lat, lng, radius_km=30` (0.1 to 100), `within_min=4320` (5 to 14400) | `events[]` soonest first, those on now (`ONGOING`) or starting within the window (`UPCOMING`): `event_id`, `name`, `kind`, `town`, `starts_in_min`, `duration_min`, `attendance`, `distance_km`, `serving_towers[]` |
| `events_forecast_load` | `event_id` | `towers[]` (the 5 nearest to the venue: `baseline_prb`, `uplift_prb`, `predicted_prb`, `risk`, `subscribers_est`), `overall_risk`, `subscribers_affected`, `starts_in_min`, `peak_in_min` |
| `events_capacity_plan` | `event_id` | `recommendations[]` ordered by `priority` (1 first): `towers`, `advice`, `next_tool` (`twin_simulate_tilt`, `exposure_quote`, `care_draft_notice`, `energy_find_savings`) and `arguments` ready to use. **Advice as data: nothing is executed** |

Errors: bad ranges are `InvalidInputError`; an unknown event is `NotFoundError`. An empty result is not an error.

## The model

- A crowd of N people adds `N x 0.004` PRB points in total, spread over the 5 nearest towers by inverse distance (the closest takes the most). A tower's baseline is its average PRB.
- Risk: `LOW` under 70% predicted PRB, `MEDIUM` from 70%, `HIGH` from 85%.
- The plan recommends a downtilt simulation for each busy tower, broadcast-quality uplift on demand for crowds of 20,000 or more, a notice to customers around the venue, and keeping the busy towers out of the night sleep list.

## Flood scenario

The scripted `Kota Bharu Derby Football Match (synthetic)` is 42,000 people at 18:00 the day after T0, close to the flood region: `events_forecast_load` shows which Kota Bharu towers go over 85%, and the plan tells an agent what to simulate, sell and tell customers.

## Tests

```bash
uv run python -m pytest servers/events-mcp
```
