# flood-mcp

River gauges and flood extent. **All data is synthetic.** Gauge levels and thresholds are invented for the demo, not real hydrology or warning criteria. Read-only; owns no tables.

## Run

```bash
uv run menara-seed
uv run --package flood-mcp python -m flood_mcp                          # stdio
uv run --package flood-mcp python -m flood_mcp --transport streamable-http --port 8107
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `flood_get_gauge` | `gauge_id` | River, station, `level_m`, `warning_m`, `danger_m`, `status` (NORMAL, WARNING, DANGER), `trend` over 3 h (RISING, FALLING, STEADY), `above_danger_by_m` |
| `flood_list_gauges` | `min_lat, min_lng, max_lat, max_lng, status?, limit=100` | `gauges[]` with level and status, `returned`, `truncated` |
| `flood_check_point` | `lat, lng` | `inside_flood`, `extent_id`, `depth_m`, `distance_to_edge_km`, `extent_radius_km` |

The flood extent is a circle that grows over time; the latest extent with `from_min <= now` applies. Depth falls linearly from the centre to zero at the edge. Before the first extent exists, `flood_check_point` returns `inside_flood: false` with a warning.

Errors: malformed id or out-of-range input is `InvalidInputError`; unknown gauge is `NotFoundError`.

## Flood scenario

`GAUGE-KKRI-01` (Sungai Kelantan, synthetic): 26.4 m at T0, 1.4 m above danger (25.0 m), RISING; peaks at 27.1 m around +3 h. The extent covers `KKRI-0142`: 4.5 km radius at T0, about 1.1 m deep at the tower.

## Tests

```bash
uv run python -m pytest servers/flood-mcp
```
