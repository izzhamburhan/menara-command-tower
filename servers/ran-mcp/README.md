# ran-mcp

Sandboxed RAN changes: tilt, cell reset, and rollback. **All data is synthetic and nothing real is changed.** Every change needs a signed policy token that this server verifies locally; it never calls policy-mcp.

Owns: `ran_change`, `ran_change_item`, `ran_kpi_effect`. Reads `cell`, `tower` and `ran_script`.

## Run

```bash
uv run menara-seed
uv run --package ran-mcp python -m ran_mcp                              # stdio
uv run --package ran-mcp python -m ran_mcp --transport streamable-http --port 8111
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `ran_get_config` | `enodeb_name` | Cells with `base_tilt_deg`, `applied_delta_deg`, `tilt_deg`, and `active_changes[]` |
| `ran_tilt_cells` | `changes[], policy_token, reason?` | The change (`ACTIVE`): items, towers, approver. Each change is `{enodeb_name or cell_id, tilt_delta_deg}`; a tower name tilts all its cells |
| `ran_reset_cell` | `cell_id, policy_token, reason?` | The change (`COMPLETED`) |
| `ran_revert_change` | `change_id, policy_token, reason?` | The change (`REVERTED`); KPIs return to normal from now |
| `ran_get_change` | `change_id` | One change |
| `ran_list_changes` | `status?, enodeb_name?, limit=50` | Changes, newest first |

**Tokens.** `ran_tilt_cells` needs action `ran_tilt_cells`, `ran_reset_cell` needs `ran_reset_cell`, and `ran_revert_change` needs `ran_revert_tilt`. The token target is the sorted, comma-joined tower names of the change, so a token for two towers does not cover one of them. Forged, expired, or mismatched tokens raise `TokenError` and change nothing.

**Limits.** `tilt_delta_deg` within +/-8, a cell's resulting tilt within 0 to 15 degrees, at most 30 cells per change.

## The effect, and how to verify it

A tilt writes a KPI effect from the moment it is applied. `tower-mcp` and `ontology-mcp` read it through `menara_core.kpi_overlay`, so `tower_get_kpi` shows the result and a rollback restores the normal KPIs. A change on a tower with several cells scales by the mean tilt change over its cells. The realised effect is not returned by this server: **verify it with tower KPIs** and compare with the twin's prediction.

**Scripted failure (demo twist).** The first tilt on `KKRI-0143` has only 10 % efficacy (`ran_script` table, from the scenario), so its load goes from 91 % to about 88 %, not the predicted 63 %. A second attempt works. The agent must notice, roll back, and try the next option.

## Flood scenario

Tilt `KKRI-0143` and `KKRI-0144` by +4 degrees: `KKRI-0144` goes 91 % to 63 %, `KKRI-0143` 91 % to 88.2 % (first attempt). Roll back, ask policy again, retry: both reach 63 %.

## Tests

```bash
uv run python -m pytest servers/ran-mcp
```
