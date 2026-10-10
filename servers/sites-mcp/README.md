# sites-mcp

Critical sites (hospitals, clinics, police, schools, SLA enterprise customers) and the tower that serves each. **All data is synthetic**; names are fictional. Read-only; owns no tables.

`emergency_service` sites (HOSPITAL, CLINIC, POLICE, FIRE) must never be changed without human approval. policy-mcp relies on this flag.

## Run

```bash
uv run menara-seed
uv run --package sites-mcp python -m sites_mcp                          # stdio
uv run --package sites-mcp python -m sites_mcp --transport streamable-http --port 8112
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `sites_get_site` | `critical_site_id` (for example `CS-KKRI-01`) | `name`, `kind`, location, `priority` (1 emergency, 2 SLA, 3 school), `emergency_service`, `sla_customer`, `serving_enodeb` |
| `sites_list_in_bbox` | `min_lat, min_lng, max_lat, max_lng, kind?, limit=200` | `sites[]` highest priority first, `returned`, `truncated` |
| `sites_for_tower` | `enodeb_name` | `sites[]` served by the tower, `counts_by_kind`, `emergency_sites`, `sla_customers` |

`critical_site_id` (`CS-<area>-<nn>`) is different from a tower's `site_id` (`SITE-<enodeb>`).

Errors: malformed id or out-of-range input is `InvalidInputError`; unknown site or tower is `NotFoundError`.

## Flood scenario

Six sites around Kuala Krai: two clinics, a police station, two schools and one SLA logistics customer. `KKRI-0142` serves a clinic and the police station.

## Tests

```bash
uv run python -m pytest servers/sites-mcp
```
