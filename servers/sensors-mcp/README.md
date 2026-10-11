# sensors-mcp

Smart-city sensors (water level, rain, air quality) and early-warning alerts with the time left before a danger level. **All data is synthetic**: fictional sensors and owners (names end in "(synthetic)") and invented readings. Track 5 (sustainability and smart nation). The same alerts could be sold to a council as a flood early-warning service (track 6).

Read-only; owns no tables. Reads `iot_sensor`, `iot_reading`.

## Run

```bash
uv run python -m menara_core.seed.cli                                 # re-seed: the sensor tables are new
uv run --package sensors-mcp python -m sensors_mcp                    # stdio
uv run --package sensors-mcp python -m sensors_mcp --transport streamable-http --port 8120
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `sensors_list_in_area` | `lat, lng, radius_km=20` (0.1 to 100), `kind?` (`WATER_LEVEL`, `RAIN`, `AIR_QUALITY`) | `sensors[]` nearest first: `sensor_id`, `kind`, `name`, `owner`, `town`, `enodeb_name` (the tower that carries it), `unit`, `value` (latest), `status` (`OK`, `WARNING`, `DANGER`), `distance_km` |
| `sensors_get_readings` | `sensor_id`, `window_min=360` (5 to 1440) | `points[]` (a reading every 15 minutes, up to the clock), `latest`, `min_value`, `max_value` |
| `sensors_get_alerts` | `lat, lng, radius_km=20`, `kind?` | `alerts[]` most urgent first: the sensor, `value`, `warn_value`, `danger_value`, `status`, `trend_per_hour`, `projected_min_to_danger` (0 when already past danger, null when steady or falling) |

Errors: a bad radius, kind or window is `InvalidInputError`; an unknown sensor is `NotFoundError`. An empty circle is not an error.

## The model

- Each town has **two water-level sensors** that follow the local river gauge (they share its warning and danger levels): one at the gauge, one upstream that lags it by two hours, so it can warn first. Plus a rain gauge and an air-quality sensor. Readings every 15 minutes from minute -1440 to 720.
- Rain is heavy in Kelantan (the flood region) around T0 and light elsewhere.
- **Trend** is the change over the last hour. **Projected minutes to danger** = the distance to the danger level over that trend (a straight line), so it is a warning, not a forecast.

## Flood scenario

At T0 the Kuala Krai water sensors are over their danger level, and `sensors_get_alerts` for Kuala Krai lists them first. A Kuala Lumpur circle has no alerts. As the river falls after its peak the alerts lose their projected time.

## Tests

```bash
uv run python -m pytest servers/sensors-mcp
```
