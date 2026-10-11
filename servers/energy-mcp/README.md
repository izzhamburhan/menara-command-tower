# energy-mcp

How much power a tower uses, how long its battery or generator lasts, and where night-time "sleep" modes save energy and CO2. **All data is synthetic**: invented power, fuel and carbon figures for a demo, not real measurements. Track 5 (sustainability) and track 4 (networks).

Owns `energy_action` (the sleep modes that were approved and applied). Reads, read-only: `tower`, `cell`, `tower_state`, `tower_kpi`, `tower_neighbour`, `tower_energy`, `critical_site`, `flood_extent`.

## Run

```bash
uv run python -m menara_core.seed.cli                                 # re-seed: the energy tables are new
uv run --package energy-mcp python -m energy_mcp                      # stdio
uv run --package energy-mcp python -m energy_mcp --transport streamable-http --port 8114
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `energy_get_tower` | `enodeb_name` | `status`, `supply` (`MAINS`, `BATTERY`, `GENERATOR`, `NONE`), `mains_ok`, `battery_pct`, `load_pct`, `base_kw`, `draw_kw`, `sleeping`, `active_action`, `hours_left` (null on mains), `has_generator`, `generator_fuel_l`, `generator_hours_left` |
| `energy_find_savings` | `lat, lng, radius_km=15` (0.1 to 100), `hour?` (0 to 23, default the scenario clock) | `window_open`, `window` (`00:00 to 06:00`), `co2_kg_per_kwh`, `candidates[]` (`enodeb_name`, `cells`, `night_load_pct`, `kwh_saved`, `co2_kg_saved`, `risk`), totals |
| `energy_apply_sleep` | `enodeb_names` (1 to 20), `policy_token`, `reason` | `actions[]` (`action_id` `ENA-0001`..., `from_min`, `to_min`, `kwh_saved`, `co2_kg_saved`, `approved_by`), totals |

`energy_apply_sleep` is a real-world action: it needs a signed `policy_token` for action `energy_sleep_cells` on exactly those towers (from `policy_check_action`; it auto-allows off-peak for a small, confident request, and asks a human in the peak window). A wrong or missing token is `TokenError`.

Errors: out-of-range numbers, an empty or oversized tower list, a tower that cannot sleep now (the message says why), or a second action on a tower that is already sleeping are `InvalidInputError`; an unknown tower is `NotFoundError`.

## The model

- **Draw** = `base_kw x (0.65 + 0.5 x load)`; a down tower idles at 35% of base. A sleeping tower draws 35% less until its action ends.
- **Night load** is taken to be 40% of a tower's average load. A tower can sleep between 00:00 and 06:00 when that is under 25% PRB, it has at least 2 cells, every neighbour is up, it serves no emergency site, it is not in a flood extent and it is not already sleeping.
- **Saving** = the night draw x 35% x the hours left in the window; CO2 = kWh x 0.585 kg (a stated synthetic grid factor).
- **Backup time**: without mains, the battery lasts `battery kWh x charge / draw`; a generator lasts `fuel / burn rate`.

## Flood scenario

`KKRI-0142` is down with no mains: `energy_get_tower` shows it on battery with a few hours left and a generator with about 9 hours of fuel (reachable only by boat, see field-mcp). It, and the emergency-site tower beside it, are never sleep candidates. At 03:00 on a quiet town the savings list is long.

## Tests

```bash
uv run python -m pytest servers/energy-mcp
```
