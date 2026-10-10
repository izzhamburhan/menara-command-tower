# user-mcp

Subscriber serving cell and experience. **All data is synthetic and PII-masked.** Read-only; owns no tables.

Subscribers are identified only by `msisdn_hash` (a salted 16-hex-char hash; raw numbers are never stored). Location is cell-level, never individual.

## Run

```bash
uv run menara-seed
uv run --package user-mcp python -m user_mcp                          # stdio
uv run --package user-mcp python -m user_mcp --transport streamable-http --port 8103
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `user_get_serving_cell` | `msisdn_hash` | `serving_cell`, `enodeb_name`, `attached`, `detached_since`, cell-level `cell_lat`/`cell_lng`, plan, segment, `home_fibre`. If not attached, `serving_cell` is the last known cell and a warning says so |
| `user_get_experience` | `msisdn_hash, window_min=120` (5-1440) | `points[]` (score 0-100, label GOOD/FAIR/POOR/NO_SERVICE, throughput, drop events, RSRP), `latest`, `summary` |

Get the hash from a ticket's `customer_ref` (ticket-mcp).

## Flood scenario

At clock 12, the TK-88213 customer is on `KKRI-0142-B1`, not attached since 06:55, experience `NO_SERVICE`. Subscribers on the overloaded neighbours `KKRI-0143` and `KKRI-0144` are degraded, not silent.

## Tests

```bash
uv run python -m pytest servers/user-mcp
```
