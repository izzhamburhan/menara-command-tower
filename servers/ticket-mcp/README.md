# ticket-mcp

UniFi Mobile support tickets. **All data is synthetic.** Owns `ticket_note` and `ticket_resolution`; everything else is read-only.

## Run

```bash
uv run menara-seed
uv run --package ticket-mcp python -m ticket_mcp                      # stdio
uv run --package ticket-mcp python -m ticket_mcp --transport streamable-http --port 8102
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `ticket_get_ticket` | `ticket_id` | Ticket: category, status, `location_text`, geocoded `lat`/`lng`, `customer_ref` (hashed MSISDN), summary, language, `notes[]` |
| `ticket_cluster_by_location` | `ticket_id, radius_km=15, window_min=60, limit=100` | Tickets within `radius_km` and +/- `window_min` of the anchor: `count` (full total), `span_min`, `centroid`, `top_locations[]`, `tickets[]`, `truncated` |
| `ticket_add_note` | `ticket_id, text (max 1000), author="agent"` | The stored note |
| `ticket_resolve` | `ticket_ids[] (max 200), note, resolved_by="agent"` | `resolved[]`, `already_resolved[]`, `count`. Closes the tickets (status becomes RESOLVED, `resolved_at` set) and adds a "Resolved" note to each |

A ticket is invisible until the scenario clock reaches its creation time (`NotFoundError`). `customer_ref` is the key for `user-mcp`.

## Flood scenario

TK-88213 ("No data since 7am, banjir kat Kuala Krai") exists at T0. Advance the clock to 12 minutes and `ticket_cluster_by_location TK-88213` returns 37 tickets:

```bash
uv run python -m menara_core.scenario_cli set 12
```

## Tests

```bash
uv run python -m pytest servers/ticket-mcp
```