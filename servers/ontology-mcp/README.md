# ontology-mcp

Links towers to everything around them (neighbours, power feeder, river gauge, critical sites, subscribers) and owns the **Incident** object the agent creates. **All data is synthetic.**

It reads other domains' base tables read-only. It writes only `incident` and `incident_ticket`. It calls no other MCP.

## Run

```bash
uv run menara-seed
uv run --package ontology-mcp python -m ontology_mcp                    # stdio
uv run --package ontology-mcp python -m ontology_mcp --transport streamable-http --port 8104
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`. `site` accepts an `enodeb_name` (`KKRI-0142`) or a `site_id` (`SITE-KKRI-0142`).

| Tool | Arguments | `data` |
| --- | --- | --- |
| `ontology_blast_radius` | `site, radius_km=20 (1-100), limit=200` | `origin`, `at_risk_towers[]` by distance, `towers_at_risk`, `subscribers_in_radius`, `subscribers_at_risk`, `critical_sites[]`, `counts_by_kind`, `emergency_sites`, `sla_customers`, `feeders[]` tripped first, `truncated` |
| `ontology_neighbours` | `site` | Nearest and reverse neighbours with distance, status, PRB %, and which direction the link runs |
| `ontology_upstream_of` | `site` | `dependencies[]`: power feeder and nearest river gauge (status and detail), and `shares_feeder_with[]` |
| `ontology_create_incident` | `enodeb_name, cause, cause_confidence, summary, ticket_ids?, evidence?` | The new Incident, status OPEN |
| `ontology_create_incident` | `enodeb_name, cause, cause_confidence, summary, ticket_ids?, evidence?` | The new Incident, status OPEN. `summary` is 5-500 characters |
| `ontology_get_incident` | `incident_id` | One incident with tickets, evidence and notes |
| `ontology_list_incidents` | `status?, enodeb_name?, limit=50` | Incidents, newest first |
| `ontology_update_incident` | `incident_id, status, note?` | The updated incident |
| `ontology_update_incident` | `incident_id, status, note?` | The updated incident. The status must move forward; a rejected move lists the allowed statuses |

**Incident rules.** `cause` is FLOOD, POWER, TRANSPORT, HARDWARE, CONFIG or UNKNOWN; `cause_confidence` is 0 to 1; `summary` is 5 to 500 characters. `ticket_ids` must already exist at the scenario time (up to 200). `evidence` entries are `{source, tool, call_id, ref?}` copied from earlier tool responses, so every claim links to the call that produced it (up to 30). Only one open incident per tower. Status moves forward only: OPEN, MITIGATING, RESOLVED (OPEN may go straight to RESOLVED).

**Blast radius.** Everything within `radius_km` of the tower, by distance. Subscriber figures are estimates from `tower_subscribers` (synthetic). Lists are capped by `limit`; counts and totals always cover everything in range.

Errors: malformed id or out-of-range input is `InvalidInputError`; unknown tower, ticket or incident is `NotFoundError`.

## Flood scenario

`ontology_blast_radius KKRI-0142` at T0: 11 towers at risk, 8,420 subscribers in the area (7,440 on the at-risk towers), 2 clinics, 1 police station, 2 schools, 1 SLA customer, and three feeders (one tripped, one at risk, one energised).

## Tests

```bash
uv run python -m pytest servers/ontology-mcp
```