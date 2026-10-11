# policy-mcp

The policy engine. Every real-world action goes through it: **allow**, **ask** (a human decides) or **deny**. It issues the HMAC-signed tokens that action MCPs verify locally, tracks approvals, and owns the kill switch and the audit log. **All data is synthetic.**

Owns: `policy_setting`, `approval`, `audit_log`. It reads `tower_subscribers` and `critical_site` (read-only) so it computes the impact itself instead of trusting the caller.

## Run

```bash
uv run menara-seed
uv run --package policy-mcp python -m policy_mcp                        # stdio
uv run --package policy-mcp python -m policy_mcp --transport streamable-http --port 8109
```

## How an action flows

1. The agent calls `policy_check_action(action, targets, confidence)`.
2. **allow**: the response carries a signed `token`. Pass it to the action MCP.
3. **ask**: an approval is opened (`approval_id`, status PENDING). A human approves with `policy_approve`, which needs the **human approver key** and returns the token.
4. **deny**: stop. Nothing is opened.
5. The action MCP verifies the token locally (never calls policy-mcp). After acting, the agent calls `policy_record_outcome`.

The token is bound to one action and one set of towers: `target` is the sorted, comma-joined tower names (cell ids are normalised to their tower). It expires after `token_ttl_s` (300 s, real time).

## Rules

| Rule | Fails means | Notes |
| --- | --- | --- |
| `known_action` | deny | Unknown actions are denied |
| `kill_switch_off` | deny | Blocks everything, rollbacks included |
| `hourly_action_cap` | deny | Authorisations in the last 60 scenario minutes (default cap 10) |
| `human_decision_required` | ask | `drone_dispatch`, `workforce_create_order`, `comms_send_notice`, `hardware_replace` |
| `human_decision_required` | ask | `drone_dispatch`, `workforce_create_order`, `comms_send_notice`, `hardware_replace`, `exposure_book_qod`, `enterprise_issue_credit` |
| `emergency_coverage` | ask | A target serves a clinic, hospital, police or fire site |
| `subscriber_impact` | ask | Affected subscribers must be below the limit (default 500) |
| `confidence` | ask | Must be at least the minimum (default 0.9) |
| `off_peak` | ask | Peak hours default to 18:00 to 23:00 scenario local time |

`ran_revert_tilt` is a rollback: it skips the `ask` rules (a rollback should never wait for a human) but not the `deny` rules. Actions: `ran_reset_cell`, `ran_tilt_cells`, `ran_revert_tilt`, `drone_dispatch`, `workforce_create_order`, `comms_send_notice`, `hardware_replace`.
`ran_revert_tilt` is a rollback: it skips the `ask` rules (a rollback should never wait for a human) but not the `deny` rules. Actions: `ran_reset_cell`, `ran_tilt_cells`, `ran_revert_tilt`, `drone_dispatch`, `workforce_create_order`, `comms_send_notice`, `hardware_replace`, and for the track servers `energy_sleep_cells` (normal rules, so auto-allowed under the limits), `exposure_book_qod` (always asks: it sells a service) and `enterprise_issue_credit` (always asks: it moves money).

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `policy_check_action` | `action, targets[], confidence, reason?` | `decision`, `reason`, every `rules[]` result, `affected_subscribers`, `touches_emergency`, `approval_id`, `token` (allow only) |
| `policy_get_approval` | `approval_id` | Status, reason, decided by, outcome |
| `policy_list_approvals` | `status?, limit=50` | Approvals, newest first |
| `policy_approve` | `approval_id, approver, approver_key, note?` | **Human only.** `token`, `approved_by` |
| `policy_reject` | `approval_id, approver, approver_key, note?` | **Human only.** The rejected approval |
| `policy_record_outcome` | `approval_id, outcome (SUCCEEDED, FAILED, ROLLED_BACK), detail?` | The approval with its outcome |
| `policy_get_status` | none | Kill switch, settings, peak flag, actions last hour, pending approvals, known actions |
| `policy_set_kill_switch` | `enabled, actor, approver_key?` | Anyone can switch it ON; OFF needs the approver key |
| `policy_update_setting` | `key, value, actor, approver_key` | **Human only.** Changes a threshold |
| `policy_get_audit` | `limit=50` | Audit log, newest first |

## The human approver key

`policy_approve`, `policy_reject`, `policy_update_setting` and turning the kill switch off need `MENARA_APPROVER_KEY`. The command-center UI holds it; **the agent must not**. The dev default is public, so on a shared demo set a private value in `.env`. This keeps an agent from approving its own request, and is not production-grade security.

## Flood scenario

`ran_tilt_cells` on `KKRI-0143` and `KKRI-0144` is **ask** (1,610 subscribers; `KKRI-0144` serves a clinic). `drone_dispatch` is always **ask**. `ran_revert_tilt` is **allow**.

## Tests

```bash
uv run python -m pytest servers/policy-mcp
```