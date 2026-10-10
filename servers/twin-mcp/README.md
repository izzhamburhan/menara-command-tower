# twin-mcp

A digital twin: simulate a tower failure or a tilt change **before acting**. **All data is synthetic**, and the model is deliberately simple (demo formulas in `menara_core.network_model`, not RF engineering).

Owns: `twin_simulation` (every run is stored with an id you can cite). Reads KPIs, neighbours, subscribers and critical sites read-only.

## Run

```bash
uv run menara-seed
uv run --package twin-mcp python -m twin_mcp                            # stdio
uv run --package twin-mcp python -m twin_mcp --transport streamable-http --port 8108
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`. `site` is an `enodeb_name` or `site_id`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `twin_simulate_failure` | `site` | `sim_id`, `already_down`, `load_before_prb`, `subscribers_impacted`, `emergency_sites_affected`, `critical_sites_affected[]`, `neighbours[]` (current and predicted PRB, `overloaded`), `overloaded_count`, `subscribers_at_overload_risk`, `recommendation` |
| `twin_simulate_tilt` | `changes[]` of `{enodeb_name, tilt_delta_deg}` (max 20, within +/-8, positive = more downtilt) | `sim_id`, `tilted[]` (current and predicted PRB), `coverage_loss_pct`, `receivers[]` (neighbours that pick up shed traffic), `recommended`, `reasons[]` |
| `twin_get_simulation` | `simulation_id` | The stored parameters and result |

## The model

- **Tilt.** A downtilt of 1 degree sheds 7.7 % of a tower's load (capped at 40 %), so 4 degrees takes 91 % PRB to 63 %. Coverage loss is 3.5 % per degree; more than 15 % is not recommended. Half the shed load lands on live neighbours, weighted by inverse distance. Uptilt adds load.
- **Failure.** 60 % of the failed tower's last loaded PRB moves to live neighbours (inverse distance, doubled for overlapping coverage). A neighbour at 85 % PRB or more is `overloaded`. If the tower is already DOWN, predictions equal the observed KPIs, which already include the failover.
- Current loads include the effect of any active RAN changes, so a second simulation sees what the first change did.

Errors: malformed input is `InvalidInputError`; unknown tower or simulation is `NotFoundError`.

## Flood scenario

Tilting `KKRI-0143` and `KKRI-0144` by +4 degrees: 91 % to 63 %, coverage loss 14 %, recommended. Tilting only one of them is not recommended: its neighbour is already at 91 % and would take more load.

## Tests

```bash
uv run python -m pytest servers/twin-mcp
```
