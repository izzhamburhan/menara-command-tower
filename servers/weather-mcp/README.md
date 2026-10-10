# weather-mcp

Rainfall and lightning near a location. **All data is synthetic.** Read-only; owns no tables.

Observations come from the weather station nearest to the `lat`/`lng` you pass (one synthetic station per town, plus `WX-KKRI-01` for the flood scenario). Pass a tower's coordinates from `tower-mcp`.

## Run

```bash
uv run menara-seed
uv run --package weather-mcp python -m weather_mcp                      # stdio
uv run --package weather-mcp python -m weather_mcp --transport streamable-http --port 8105
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `weather_get_rainfall` | `lat, lng, window_min=1440 (60-1440), radius_km=30 (1-100)` | `station` (id, name, distance), `total_mm` over the window, `last_hour_mm`, `peak_mm_per_hour`, `rain_24h_mm`, `intensity`, hourly `points[]` |
| `weather_get_lightning` | `lat, lng, window_min=60 (60-1440), radius_km=30` | `station`, `total_strikes`, `last_hour_strikes`, `peak_strikes_per_hour`, `activity` |

Observations are hourly; a point at `t_min` is the hour ending then. `intensity` uses the 24 h total and `activity` the last hour. **Thresholds are invented for the demo, not real warning criteria:**

| `intensity` | 24 h rainfall | `activity` | last-hour strikes |
| --- | --- | --- | --- |
| NORMAL | under 60 mm | NONE / LOW / HIGH / SEVERE | 0 / 1-19 / 20-99 / 100+ |
| HEAVY | 60 mm | | |
| VERY_HEAVY | 120 mm | | |
| EXTREME | 180 mm | | |

Errors: coordinates or ranges out of bounds is `InvalidInputError`; no station within `radius_km` is `NotFoundError`.

## Flood scenario

At T0 near Kuala Krai (5.531, 102.197): 148 mm in 24 h (VERY_HEAVY), 25 mm in the last hour, 150 lightning strikes in the last hour (SEVERE).

## Tests

```bash
uv run python -m pytest servers/weather-mcp
```
