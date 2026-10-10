# tower-mcp

Cell tower status, KPIs, alarms and neighbours. **Synthetic by default**, and the first server with a swappable data source (see *Data sources*). Read-only; it owns no tables.

## Run

```bash
uv run menara-seed                                   # once: creates data/menara.db
uv run --package tower-mcp python -m tower_mcp       # stdio
uv run --package tower-mcp python -m tower_mcp --transport streamable-http --port 8101
```

`tower-mcp` also exists as a console script. Some locked-down Windows machines block `.venv` `.exe` shims, so `python -m tower_mcp` is the portable form and is what `.mcp.json` uses.

Reads `data/menara.db` (override with `MENARA_DB` or `--db`). Responses reflect the scenario clock (`uv run python -m menara_core.scenario_cli show`).

## Tool contract

Every tool returns the shared envelope: `{synthetic: true, as_of, data, evidence[], warnings[]}`. `evidence[]` names the call that produced the answer (`source`, `tool`, `call_id`, `ref`, `confidence`, `as_of`).

| Tool | Arguments | `data` |
| --- | --- | --- |
| `tower_get_status` | `enodeb_name` | Tower attributes, `status` (UP/DEGRADED/DOWN), `battery_pct`, `mains_ok`, `cells[]`, `active_alarm_count`, `latest_kpi`, `neighbours[]` (nearest 4, with status and PRB %) |
| `tower_list_in_bbox` | `min_lat, min_lng, max_lat, max_lng, status?, limit=500` | `towers[]` (id, site, town, state, lat, lng, status), `returned`, `truncated` |
| `tower_get_kpi` | `enodeb_name, window_min=60` (5-1440) | `points[]` (PRB utilisation %, drop rate %, throughput Mbps), `summary` |
| `tower_get_alarms` | `enodeb_name?, severity?, active_only=true, limit=200` | `alarms[]` most severe first, `returned`, `truncated` |

KPIs include the effect of active `ran-mcp` changes (read through `menara_core.kpi_overlay`), so a tilt is visible here and a rollback restores the normal values.

Errors: malformed id or out-of-range argument is `InvalidInputError`; unknown tower is `NotFoundError`.

## Data sources (synthetic today, real tomorrow)

`tools.py` never touches SQL. It calls a `TowerSource` (`source.py`), and a source is chosen at startup:

| Source | Flag | Reads | Responses |
| --- | --- | --- | --- |
| SQLite (default) | `--source sqlite [--db FILE]` | the synthetic `data/menara.db`, with the scenario clock | `synthetic: true` |
| HTTP | `--source http --api-url URL` | a service that follows **Tower API v1** below | `synthetic: false` |

Environment: `MENARA_TOWER_SOURCE`, `MENARA_TOWER_API_URL`, and `MENARA_TOWER_API_TOKEN` (sent as `Authorization: Bearer ...`).

The tool names, arguments and response models do not change between sources. Two fields behave differently on a live source: `KpiPoint.t_min` is `null` (there is no scenario clock), and `as_of` is the time of the call.

**Tower API v1.** This contract is **ours, not any real system's**. A real OSS would need a thin gateway or mapper in front that exposes these endpoints. All responses are JSON; `404` means "no such tower"; any other error status, a timeout, or a response that does not match becomes a `SourceUnavailableError` ("Tower API ...").

| Request | Response |
| --- | --- |
| `GET /towers/{enodeb_name}` | `{enodeb_name, site_id, name, town, state, lat, lng, tower_type, vendor, firmware, cells: [cell_id]}` |
| `GET /towers/{enodeb_name}/status` | `{status: UP\|DEGRADED\|DOWN\|UNKNOWN, battery_pct, mains_ok}` |
| `GET /towers/{enodeb_name}/neighbours` | `[{enodeb_name, distance_km}]`, nearest first |
| `GET /towers/{enodeb_name}/kpi?window_min=N` | `[{at, prb_util, drop_rate, throughput_mbps}]` for the last N minutes |
| `GET /towers?min_lat&min_lng&max_lat&max_lng&status&limit` | `[{enodeb_name, site_id, town, state, lat, lng, status}]` ordered by name, at most `limit` |
| `GET /alarms?enodeb_name&severity&active_only&limit` | `[{alarm_id, enodeb_name, code, severity, message, raised_at, cleared_at, active}]`, most severe first |

`tests/test_sources.py` runs the same behaviour tests against both sources, with a fake Tower API in front of the synthetic data. **Cost to know about:** `tower_get_status` makes about 14 requests on the HTTP source (each neighbour needs its status and KPI). A real API should add a batched endpoint before this is used for real.

## Try it with the flood scenario

At T0, `tower_get_status KKRI-0142` returns DOWN, battery 14%, mains failed, 3 active alarms, and neighbours `KKRI-0143` and `KKRI-0144` at 91% PRB utilisation.

## Tests

```bash
uv run python -m pytest servers/tower-mcp
```