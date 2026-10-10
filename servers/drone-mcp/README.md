# drone-mcp

Simulated drones that inspect towers. **All data is synthetic; vision findings are canned, not from a real model.** A dispatch needs a signed policy token (action `drone_dispatch`) that this server verifies locally.

Owns: `drone_mission`. Reads `drone`, `drone_finding`, `tower`, `seed_meta`.

## Run

```bash
uv run menara-seed
uv run --package drone-mcp python -m drone_mcp                          # stdio
uv run --package drone-mcp python -m drone_mcp --transport streamable-http --port 8110
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `drone_list_drones` | none | 12 drones at 6 depots: `IDLE` or `ON_MISSION`, and when each is free |
| `drone_dispatch` | `enodeb_name, policy_token, reason?` | The mission: drone, depot, distance, arrival and completion times, `EN_ROUTE` |
| `drone_get_mission` | `mission_id` | Status (`EN_ROUTE`, `ON_SITE`, `COMPLETE`), progress, and once complete the `findings` |
| `drone_list_missions` | `status?, enodeb_name?, limit=50` | Missions, newest first |

**Dispatch rules.** The nearest idle drone within 150 km flies at 90 km/h and inspects for 15 minutes; it is busy until it has flown back. One active mission per tower. No idle drone in range is an `InvalidInputError`. The brief's `run_inspection` is part of the mission: findings appear when the inspection ends.

**The clock decides.** Progress follows the scenario clock, so findings appear only after it passes the end of the inspection. Move it with `uv run python -m menara_core.scenario_cli advance 60`.

**Findings.** `access_road` (status, water depth, passable by), `tower_structure`, `antenna_alignment`, `power_cabinet`, `genset` (status, access), `hazards[]`, `summary`, `confidence`. Every tower has them; only the flooded tower's are dramatic.

## Flood scenario

Dispatch to `KKRI-0142` sends a drone from the Kota Bharu depot, about 66 km and 45 minutes. At the end of the inspection: access road flooded 0.6 m (passable by boat), tower intact, antenna aligned, genset unreachable by road.

## Tests

```bash
uv run python -m pytest servers/drone-mcp
```
