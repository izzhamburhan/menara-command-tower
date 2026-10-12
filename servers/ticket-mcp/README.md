# ticket-mcp

UniFi Mobile support tickets and Network Trouble Tickets (NTT). **All data is synthetic.** Owns `ticket_note`, `ticket_resolution`, `ntt`, `ntt_ctt_link`, and `ntt_note`; everything else is read-only.

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
| `ticket_create_ntt` | `network_element_id, fault_type, severity, summary, ctt_ticket_ids?` | Create NTT bound to Network Element (tower/feeder). Deduplicates active NE NTTs. Returns `NttDetail` |
| `ticket_get_ntt` | `ntt_id` | Single NTT with root NE, severity, linked CTTs, count, notes, and resolution info |
| `ticket_list_ntts` | `status?, network_element_id?, limit=50` | List NTTs, newest first, with linked CTT counts |
| `ticket_link_ctts` | `ntt_id, ctt_ticket_ids[]` | Link Customer Trouble Tickets (CTTs) to parent NTT |
| `ticket_unlink_ctt` | `ntt_id, ctt_ticket_id` | Unlink a CTT from NTT |
| `ticket_resolve_ntt` | `ntt_id, resolution_note, resolved_by="agent"` | Resolves NTT; cascades resolution to all linked CTTs and evaluates MCMC closure email / report requirement |
| `ticket_check_mcmc` | `ntt_id` | Evaluates MCMC regulatory notification eligibility based on outage duration (>= 120 min), severity (CRITICAL/MAJOR), and root NE |

A ticket is invisible until the scenario clock reaches its creation time (`NotFoundError`). `customer_ref` is the key for `user-mcp`.

### MCMC regulatory conditions (TM iNTT standard)
- **Lifecycle Closure Email**: Outage duration >= 120 mins, service-impacting severity (`CRITICAL`/`MAJOR`), root NE. Auto-dispatched on `ticket_resolve_ntt`.
- **Comprehensive Report**: Flagged when closure email sends; regulatory deadline is 3 days post-resolution.

## Flood scenario

TK-88213 ("No data since 7am, banjir kat Kuala Krai") exists at T0. Advance the clock to 12 minutes and `ticket_cluster_by_location TK-88213` returns 37 tickets:

```bash
uv run python -m menara_core.scenario_cli set 12
```

## Tests

```bash
uv run python -m pytest servers/ticket-mcp
```