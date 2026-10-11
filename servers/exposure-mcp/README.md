# exposure-mcp

Selling network quality as a product: **quality on demand**. A catalogue of profiles, a feasibility quote from the spare capacity of each tower, and a booking. **All data is synthetic**: invented products, prices and capacity, not a real offer. Track 6 (potential revenue streams).

Owns `qod_booking` (bookings that were approved and made). Reads, read-only: `qod_profile`, `crowd_event`, `tower`, `tower_state`, `tower_kpi` (with the effect of RAN changes through `menara_core.kpi_overlay`).

## Run

```bash
uv run python -m menara_core.seed.cli                                 # re-seed: the exposure tables are new
uv run --package exposure-mcp python -m exposure_mcp                  # stdio
uv run --package exposure-mcp python -m exposure_mcp --transport streamable-http --port 8117
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `exposure_list_profiles` | none | `profiles[]`: `BROADCAST_UPLINK`, `ESPORTS_LOW_LATENCY`, `FLEET_TELEMATICS`, `AR_EXPERIENCE`, each with what is guaranteed, the capacity it reserves (`headroom_prb`) and its price (`price_rm_per_hour_per_tower`) |
| `exposure_quote` | `profile_id`, `enodeb_names` (1 to 20), `duration_min` (15 to 720), `start_in_min=0` (0 to 4320) | per tower: `status`, `current_prb`, `event_uplift_prb`, `reserved_prb`, `headroom_available_prb`, `feasible`, `reason`; `feasible_towers`, `all_feasible`, `price_rm`. Nothing is written |
| `exposure_book` | `profile_id`, `enodeb_names`, `duration_min`, `customer` (a fictional name, 3 to 60 characters), `policy_token`, `reason`, `start_in_min=0` | `booking_id` (`BKG-0001`...), `from_min`, `to_min`, `price_rm`, `approved_by` |

`exposure_book` sells a service: it needs a signed `policy_token` for action `exposure_book_qod` on exactly those towers, and policy always asks a human for it. A wrong or missing token is `TokenError`.

Errors: a bad window or tower count, a customer name out of range, or a booking on a tower that is not feasible (the message says why) are `InvalidInputError`; an unknown profile or tower is `NotFoundError`.

## The model

- A tower can be sold a profile when it is **up** and its **spare capacity** covers the profile's headroom plus a 5-point margin. Spare capacity = 100 - the PRB now (after any RAN change) - the crowd of an event in the window (the same crowd model as events-mcp) - the headroom of earlier bookings that overlap the window.
- Price = hours x the profile's rate x the number of feasible towers.
- A booking reserves its headroom, so the next quote for the same window shows it.

## Flood scenario

The flood neighbours `KKRI-0143` and `KKRI-0144` sit at 91% PRB, so they cannot be sold anything; after the second tilt brings them to 63% they can. On the day of the Kota Bharu derby, the towers beside the stadium lose headroom to the crowd, and a broadcast crew's booking has to be spread across towers that still have it.

## Tests

```bash
uv run python -m pytest servers/exposure-mcp
```
