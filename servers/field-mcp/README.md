# field-mcp

Which technician to send to a tower, by road or by boat, what parts they carry, whether it is safe, and dispatching them. **All data is synthetic**: a fictional crew (names end in "(synthetic)") and invented speeds, work times and stock. Track 2 (workforce productivity) and track 1 (operations).

Owns `field_job` (work orders that were approved and dispatched). Reads, read-only: `technician`, `spare_part`, `tower`, `flood_extent`.

## Run

```bash
uv run python -m menara_core.seed.cli                                 # re-seed: the field tables are new
uv run --package field-mcp python -m field_mcp                        # stdio
uv run --package field-mcp python -m field_mcp --transport streamable-http --port 8118
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `field_find_crew` | `enodeb_name`, `skill` (`POWER`, `RAN`, `FIBRE`, `CIVIL`) | `access` (`ROAD` or `BOAT`), `flood_depth_m`, `road_safe`, `safe_to_dispatch`, `safety_note`, `candidates[]` (up to 5, on shift and free, by ETA): `tech_id`, `name`, `depot_id`, `distance_km`, `eta_min`, `access`, `parts[]` in stock at their depot |
| `field_dispatch` | `enodeb_name`, `tech_id`, `task` (3 to 200 characters), `policy_token`, `reason`, `skill="POWER"`, `access="AUTO"` (`AUTO`, `ROAD`, `BOAT`) | `job_id` (`JOB-0001`...), `eta_min`, `access`, `status`, `approved_by` |
| `field_list_jobs` | `status?` (`EN_ROUTE`, `ON_SITE`, `DONE`), `limit=50` (1 to 200) | `jobs[]` newest first, with a status that follows the scenario clock and `eta_left_min` |

`field_dispatch` commits staff: it needs a signed `policy_token` for action `workforce_create_order` on that tower, and policy always asks a human for it. A wrong or missing token is `TokenError`.

Errors: a bad skill, task length, access or status; a technician who is off shift, busy or lacks the skill; or `ROAD` into a tower under floodwater (send the crew by boat) are `InvalidInputError`; an unknown tower or technician is `NotFoundError`.

## The model

- A technician drives from their depot (the same depots as the drones) at 55 km/h. 30 technicians, five per depot: two work 06:00 to 18:00, one 08:00 to 20:00, two 18:00 to 06:00.
- Water depth at a tower is the flood extent's maximum depth, deepest at its centre. From **0.3 m** the road is not safe: the crew go by **boat**, which adds 25 minutes.
- A job is `EN_ROUTE` until its ETA, `ON_SITE` for 90 minutes of work, then `DONE`. A busy technician is not offered.
- Parts: POWER needs a generator, rectifier or battery; RAN an antenna. Stock is invented per depot; the Kota Bharu depot has a generator and batteries.

## Flood scenario

`field_find_crew("KKRI-0142", "POWER")` returns `BOAT` with the extra time and a safety note about fast-flowing water, matching the drone's finding that the access road is flooded and the generator is reachable only by boat. A dry tower in Kota Bharu returns `ROAD`.

## Tests

```bash
uv run python -m pytest servers/field-mcp
```
