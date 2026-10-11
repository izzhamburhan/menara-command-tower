# enterprise-mcp

Business customers on a tower, the revenue and SLA penalty an outage puts at risk, and issuing a service credit. **All data is synthetic**: fictional companies (names end in "(synthetic)") and invented values, rates and penalties. Track 6 (revenue) and track 1 (operations).

Owns `sla_credit` (credits that were approved and issued). Reads, read-only: `enterprise_account`, `tower`, `tower_state`.

## Run

```bash
uv run python -m menara_core.seed.cli                                 # re-seed: the enterprise tables are new
uv run --package enterprise-mcp python -m enterprise_mcp              # stdio
uv run --package enterprise-mcp python -m enterprise_mcp --transport streamable-http --port 8116
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `enterprise_get_revenue_at_risk` | `enodeb_names` (up to 50), or `lat, lng, radius_km=15` | `accounts[]` on towers that are DOWN or DEGRADED (`account_id`, `name`, `sector`, `enodeb_name`, `status`, `outage_min`, `revenue_per_hour_rm`, `penalty_rm_per_hour`, `penalty_accrued_rm`, `projected_penalty_2h_rm`, `credits_rm`, `net_exposure_rm`), and the totals. Accounts on healthy towers are not listed |
| `enterprise_list_accounts` | `lat, lng, radius_km=15`, `limit=50` (1 to 200) | `accounts[]` nearest first with their current `status` (`UP`, `DEGRADED`, `DOWN`), plan, monthly value, SLA availability, penalty rate |
| `enterprise_issue_credit` | `account_id`, `hours` (0.5 to 72), `policy_token`, `reason` | `credit_id` (`CRD-0001`...), `amount_rm`, `from_min`, `hours`, `approved_by` |

`enterprise_issue_credit` moves money: it needs a signed `policy_token` for action `enterprise_issue_credit` on the account's tower, and policy always asks a human for it. A wrong or missing token is `TokenError`.

Errors: no selector, a half centre, a bad radius or hours, a credit for an account whose tower was never affected, or a credit that overlaps an earlier one are `InvalidInputError`; an unknown tower or account is `NotFoundError`.

## The model

- An account accrues its **penalty rate per hour** while its tower is DOWN, and a quarter of it while DEGRADED. The penalty rate is 1% of the monthly value per hour.
- **Revenue at risk per hour** is the monthly value over 720 hours.
- **Projected penalty** is the next 2 hours at the current rate; **net exposure** = accrued + projected - credits.
- A **credit** is hours x the penalty rate, capped at the monthly value, and covers the hours from now; it shows against the account in `enterprise_get_revenue_at_risk`.

## Flood scenario

`KKRI-0142` is down and serves two fictional accounts (a cold storage and a timber mill): `enterprise_get_revenue_at_risk(["KKRI-0142"])` shows the penalty building, and a credit brings the net exposure down.

## Tests

```bash
uv run python -m pytest servers/enterprise-mcp
```
