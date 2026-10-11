# care-mcp

Customer care for an outage: who is affected, how many tickets will follow, a drafted notice in four languages, and sending it. **All data is synthetic**: invented rates and wording for a demo. Track 3 (customer experience).

**Counts only.** There is no recipient list, no phone number and no subscriber hash anywhere, in the tables or in any answer. The care line in a notice is a placeholder ("the Help page in the app"), never a real number.

Owns `care_notice` (notices that were approved and sent). Reads, read-only: `tower`, `tower_state`, `tower_subscribers`, `ticket`, `ticket_resolution`, `grid_feeder_tower`, `grid_feeder_state`, `flood_extent`, `care_template`, `care_language_mix`.

## Run

```bash
uv run python -m menara_core.seed.cli                                 # re-seed: the care tables are new
uv run --package care-mcp python -m care_mcp                          # stdio
uv run --package care-mcp python -m care_mcp --transport streamable-http --port 8115
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `care_get_impact` | `enodeb_names` (1 to 50) | `affected_towers` (down or degraded at the clock), `affected_customers`, `withheld`, `cause` (`FLOOD`, `POWER`, `CONGESTION`), `open_tickets_nearby`, `top_categories[]`, `predicted_extra_tickets_if_silent`, `predicted_extra_tickets_1h`, `notified_customers`, `notices_sent`, `language_mix`, `restoration_eta` |
| `care_draft_notice` | `enodeb_names`, `kind="OUTAGE"` (`OUTAGE`, `RESTORED`, `DEGRADED`), `language="en"` (`ms`, `en`, `zh`, `ta`) | `message` (fields filled), `characters`, `audience_towers`, `recipients_est`, `channel` (`SMS`), `cost_rm`, `expected_deflection_pct`, `restoration_eta`. Nothing is sent or written |
| `care_send_notice` | `enodeb_names`, `language`, `message` (20 to 480 characters), `policy_token`, `reason`, `kind="OUTAGE"` | `notice_id` (`NTC-0001`...), `recipients_est`, `message`, `sent_at`, `approved_by`, `tickets_deflected_est` |
| `care_list_notices` | `limit=50` (1 to 200) | `notices[]` newest first (counts only), `returned` |

`care_send_notice` is a real-world action: it needs a signed `policy_token` for action `comms_send_notice` on exactly those towers, and policy always asks a human for it. A wrong or missing token is `TokenError`.

Errors: a bad kind, language, message length or tower count, an audience with nobody to tell (no affected customers, or under 5), or the same message to the same towers within 30 minutes are `InvalidInputError`; an unknown tower is `NotFoundError`.

## The model

- After an outage a share of the affected customers raise a ticket within the hour: 4.5% for a flood, 3% for a power failure, 2% for congestion.
- A notice that reaches them deflects 55% of those tickets; `care_get_impact` shows the prediction falling as notices go out.
- The cost is a stated synthetic SMS rate. Languages follow a synthetic mix per state (Malay leads on the east coast, Chinese is strong in Penang).
- The restoration time comes from the feeder's restoration estimate when there is one, otherwise "to be confirmed" in the customer's language.

## Flood scenario

At T0 `KKRI-0142` is down: `care_get_impact(["KKRI-0142"])` shows 980 affected customers, the open storm tickets nearby and the extra tickets to expect. `care_draft_notice` writes the message in Malay, English, Chinese or Tamil, and after `care_send_notice` the predicted extra tickets fall.

## Tests

```bash
uv run python -m pytest servers/care-mcp
```
