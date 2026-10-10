# grid-mcp

Power feeder status and outages for tower sites. **All data is synthetic.** Read-only; owns no tables.

Every tower is supplied by exactly one feeder. A feeder is `ENERGISED`, `AT_RISK` (for example a substation close to a flood), or `TRIPPED`.

## Run

```bash
uv run menara-seed
uv run --package grid-mcp python -m grid_mcp                            # stdio
uv run --package grid-mcp python -m grid_mcp --transport streamable-http --port 8106
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `grid_get_tower_power` | `enodeb_name` | `feeder` (id, name, `status`, `since`, `note`, `restoration_eta`, `customers`, `customers_affected`) and `mains_expected` (false only when TRIPPED) |
| `grid_get_feeder_status` | `feeder_id` | `feeder` and `towers[]` it supplies |
| `grid_list_outages` | `include_at_risk=true` | `feeders[]` tripped first, `returned`, total `customers_affected` |

`customers_affected` equals `customers` only for a `TRIPPED` feeder. `since` and `restoration_eta` are ISO times; `restoration_eta` is null when unknown.

Errors: malformed id is `InvalidInputError`; unknown tower, tower with no feeder, or unknown feeder is `NotFoundError`.

## Flood scenario

- `FDR-KKRI-01` powers `KKRI-0142` and has been TRIPPED since 03:00 (earth fault, flooded substation, ETA unknown), 3,200 customers.
- `FDR-KKRI-02` (`KKRI-0148`, `KKRI-0151`, `KKRI-0153`) is AT_RISK from 06:30.
- `FDR-KKRI-03` powers the other eight towers and stays energised.

## Tests

```bash
uv run python -m pytest servers/grid-mcp
```
