# Spec: eight new MCPs and a six-track story

Owner: Izzham Burhan, TMRND. Branch `feat/tracks-mcps`. All data is synthetic.

The hackathon has six challenge tracks: (1) AI for Industry and Operations, (2) AI for Workforce Productivity, (3) AI for Customer Experience, (4) AI for Networks and Infrastructure, (5) AI for Sustainability and Smart Nation, (6) Potential Revenue Streams. The platform already covers track 4. This change adds eight MCP servers and one story, so **the same Kuala Krai flood plays across all six tracks**, and gives the team more building blocks.

## 1. Goal and non-goals

**Goal.**
- Eight new read-mostly MCP servers, each small (3 or 4 tools), each with its own synthetic data, tests and README contract, each runnable on its own:

| # | Server | Port | Track | What it answers |
| --- | --- | --- | --- | --- |
| 1 | `energy-mcp` | 8114 | 5, 4 | How much power a tower uses, how long its battery or generator lasts, and where night-time "sleep" modes save energy and CO2 |
| 2 | `care-mcp` | 8115 | 3 | Who is affected by an outage, how many tickets will follow, a drafted customer notice, and sending it |
| 3 | `enterprise-mcp` | 8116 | 6, 1 | Business customers on a tower, revenue and SLA penalty at risk, issuing a service credit |
| 4 | `exposure-mcp` | 8117 | 6 | Selling network quality as a product (quality on demand): profiles, a feasibility quote, a booking |
| 5 | `field-mcp` | 8118 | 2, 1 | Which technician to send (road or boat), parts, safety, and dispatching them |
| 6 | `events-mcp` | 8119 | 4 | Crowd events ahead, and the load they will put on nearby towers |
| 7 | `sensors-mcp` | 8120 | 5 | Smart-city sensors (water level, rain, air quality) and early-warning alerts |
| 8 | `scam-mcp` | 8121 | 3 | Where scam calls and messages are spiking, and how many customers a shield would protect |

- A **Tracks** tab in the demo: a scorecard with one card per track, filled from the servers as the story runs, and a **six-track Replay** that continues the flood incident through all of them, with the human approving each real-world action.

**Non-goals.**
- No real organisation, brand, product price, regulator figure, phone number or customer. Everything is invented and labelled "synthetic" (customers, companies, events and scam patterns are fictional).
- No change to `kuala_krai.yaml`, the golden trace flow, or the existing 13 servers' behavior (the policy server only gains three action names).
- No per-person data: nothing new carries a subscriber hash, a phone number or a message recipient list. Counts only, and groups under 5 are withheld.
- No model-in-the-loop requirement: every new tool is plain data and arithmetic. The agent (or the Replay) decides what to call.

## 2. Acceptance criteria

### A. Rules every new server follows

1. Each server is `servers/<name>-mcp/` with its own `pyproject.toml`, README contract, `src`, `tests`, registered in `.mcp.json` and the root `pyproject.toml` (created with `scripts/new_mcp.py`), depends only on `menara-core`, tool names carry the domain prefix, and every tool returns an `Envelope` with `synthetic: true` and `evidence[]`.
2. Tool logic is in `tools.py` as plain functions; `server.py` only registers them. mypy strict, ruff, `mcp[cli]>=1.9,<2`.
3. A server writes only the tables it owns (enforced by `menara_core.db.connect`); every other table it uses is read-only and listed in its README.
4. Every write that touches the real world needs a signed policy token for the stated action and target (`verify_token`, targets are towers, `target_key(towers)`); a missing, wrong, expired or reused-for-another-target token is `TokenError`. Read tools need no token.
5. Everything depends on the scenario clock (`menara_core.clock`); at T0 only what exists at T0 is visible, and a server never moves the clock.
6. Bad input is `InvalidInputError`, an unknown id is `NotFoundError`; ranges are stated in the README. An empty result is not an error.
7. Seed: new data comes from `seed/<domain>.py`, drawn from its own random stream `f"{seed}:<domain>"`, so every older table is unchanged (the existing hash checks still pass). The same seed gives the same data.

### B. energy-mcp (port 8114, owns `energy_action`)

8. Base table `tower_energy` (one row per tower: base power in kW by tower type and urban or not, battery capacity in kWh, whether it has a generator, generator fuel in litres and burn rate in l/h). The flooded tower `KKRI-0142` has a generator with limited fuel.
9. `energy_get_tower(enodeb_name)`: power draw now (kW, higher with load, lower when asleep), supply state (`MAINS`, `BATTERY`, `GENERATOR`, `NONE` from `tower_state`), battery hours left at the current draw, generator hours left, and the `energy_action` in force. The flooded tower at T0 shows `BATTERY` or `GENERATOR` with a finite time left and a warning.
10. `energy_find_savings(lat, lng, radius_km=15, hour=None)`: towers in the circle that can sleep some capacity layers now: at least 2 cells, PRB under 25% in the last hour, every neighbour UP, no `emergency_service` site served, not in a flood extent; each with kWh and CO2 (kg) saved over the sleep window and the risk. The CO2 factor is a stated synthetic constant (`0.585 kg per kWh`, returned in the data). Candidates are empty during the day peak (the sleep window is 00:00 to 06:00).
11. `energy_apply_sleep(enodeb_names, policy_token, reason)` (token for action `energy_sleep_cells` on those towers; 1 to 20 towers): writes one `energy_action` per tower (`kind: SLEEP`, `from_min`, `to_min` = the end of the window, `kwh_saved`, `co2_kg_saved`, `approved_by`), and returns the totals. A tower that is not a candidate is `InvalidInputError`. Applying twice to the same tower in the same window is `InvalidInputError`.
12. After an action, `energy_get_tower` shows the lower draw until `to_min`; the saving never exceeds the tower's sleepable share of its draw.

### C. care-mcp (port 8115, owns `care_notice`)

13. Base table `care_template` (a notice template per kind `OUTAGE`, `RESTORED`, `DEGRADED` and per language `ms`, `en`, `zh`, `ta`, with placeholders). Languages in an area follow a synthetic mix by town.
14. `care_get_impact(enodeb_names)`: affected customers (`tower_subscribers` of the towers that are DOWN or DEGRADED at the clock), tickets open from those towers, the **predicted extra tickets in the next hour if nobody is told** (a stated model: affected customers times a rate by cause, capped), top ticket categories, the language mix, and `notices_sent` already.
15. `care_draft_notice(enodeb_names, kind="OUTAGE", language="en")`: returns the message text with the fields filled (area, cause, expected restoration time from `grid` or a stated default, a care-line placeholder that is not a real number), recipients (an estimate, a count), channel `SMS`, the cost estimate in RM (a stated synthetic rate), and the expected ticket deflection percentage. Nothing is sent or written.
16. `care_send_notice(enodeb_names, language, message, policy_token, reason)` (token for action `comms_send_notice`, which policy always asks a human about): writes a `care_notice` row (`notice_id`, towers, language, recipients_est, message, `sent_min`, `approved_by`, `tickets_deflected_est`) and returns it. The message must be 20 to 480 characters; an empty audience is `InvalidInputError`. Sending the same message to the same towers twice within 30 minutes is `InvalidInputError`.
17. `care_list_notices(limit=50)`: the notices sent, newest first. No recipient list exists anywhere; only counts.
18. After a notice, `care_get_impact` for the same towers shows a lower predicted extra ticket count (the deflection applied).

### D. enterprise-mcp (port 8116, owns `sla_credit`)

19. Base table `enterprise_account` (fictional companies; `account_id`, `name` ending in `(synthetic)`, sector, serving tower, plan, monthly value in RM, SLA availability %, penalty in RM per hour of outage). One account per `ENTERPRISE` site, plus fictional accounts on the flood-cluster towers (including the DOWN tower `KKRI-0142`), plus a few per town.
20. `enterprise_get_revenue_at_risk(enodeb_names=None, lat=None, lng=None, radius_km=15)`: the accounts served by towers that are DOWN or DEGRADED at the clock, with the outage minutes so far, revenue per hour at risk, the penalty accrued so far and projected for the next 2 hours, and totals. Accounts on healthy towers are not listed.
21. `enterprise_list_accounts(lat, lng, radius_km=15, limit=50)`: accounts in a circle with their current service state.
22. `enterprise_issue_credit(account_id, hours, policy_token, reason)` (token for action `enterprise_issue_credit` on the account's tower; `hours` 0.5 to 72): writes an `sla_credit` row (`credit_id`, account, hours, `amount_rm` = hours times the account's penalty rate, capped at the monthly value, `issued_min`, `approved_by`); a credit for an account whose tower is not (or was not) affected is `InvalidInputError`; two credits for the same account and overlapping hours are `InvalidInputError`.
23. After a credit, `enterprise_get_revenue_at_risk` shows the credit against the account and the net exposure.

### E. exposure-mcp (port 8117, owns `qod_booking`)

24. Base table `qod_profile` (4 profiles: `BROADCAST_UPLINK`, `ESPORTS_LOW_LATENCY`, `FLEET_TELEMATICS`, `AR_EXPERIENCE`; each with a guaranteed uplink or latency, a headroom needed in PRB points, and a price in RM per hour per tower, all synthetic).
25. `exposure_list_profiles()`: the catalogue.
26. `exposure_quote(profile_id, enodeb_names, duration_min, start_in_min=0)`: feasibility from the PRB headroom of each tower at the clock (and, if a crowd event is on a tower, its forecast uplift): `feasible` per tower with the reason, the quote in RM, and the capacity that would be reserved.
27. `exposure_book(profile_id, enodeb_names, duration_min, customer, policy_token, reason)` (token for action `exposure_book_qod`; `customer` is a free-text fictional name, 3 to 60 characters): writes a `qod_booking` (`booking_id`, profile, towers, customer, `from_min`, `to_min`, `price_rm`, `approved_by`); a booking on a tower that is not feasible is `InvalidInputError`; the reserved headroom is visible in `exposure_quote` for the same window.

### F. field-mcp (port 8118, owns `field_job`)

28. Base tables `technician` (fictional names, home depot lat/lng, skills such as `POWER`, `RAN`, `FIBRE`, `CIVIL`, shift hours) and `spare_part` (part stock per depot: generator, rectifier, battery, antenna). Depots reuse the drone depots.
29. `field_find_crew(enodeb_name, skill)`: technicians with that skill on shift at the clock, ranked by ETA: distance over a stated road speed, and if the tower is inside a flood extent or its access is flooded (from `flood_extent` and the drone finding), the **access mode is `BOAT`** with extra time and a safety note; parts available for the skill; `safe_to_dispatch` false when the flood depth is over a stated limit and the mode is ROAD.
30. `field_dispatch(enodeb_name, tech_id, task, policy_token, reason)` (token for action `workforce_create_order`, which policy always asks about): writes a `field_job` (`job_id`, technician, tower, task, `dispatched_min`, `eta_min`, `access`, `approved_by`); a technician already on a job, off shift, or without the needed skill is `InvalidInputError`; dispatching ROAD into a tower with `safe_to_dispatch` false is `InvalidInputError` (BOAT is allowed).
31. `field_list_jobs(status=None, limit=50)`: jobs with a status derived from the clock (`EN_ROUTE`, `ON_SITE`, `DONE`), the technician and the ETA left.

### G. events-mcp (port 8119, read-only, owns nothing)

32. Base table `crowd_event` (about 25 fictional events by town: festivals, matches, concerts, the `balik kampung` exodus; start and end in scenario minutes (from a few hours to several days after T0), expected attendance, venue lat/lng and radius).
33. `events_list_upcoming(lat, lng, radius_km=30, within_min=4320)`: events in the circle starting within the window, soonest first, with the serving towers (the nearest to the venue).
34. `events_forecast_load(event_id)`: for each serving tower the predicted PRB at the event peak (baseline from `tower_kpi` plus a stated per-attendee data load spread across the towers by distance), the overload risk (`LOW`, `MEDIUM`, `HIGH` at 70% and 85% PRB), and the subscribers affected.
35. `events_capacity_plan(event_id)`: recommended actions as data (not executed): which towers to pre-stage, which `exposure` profile fits, and the tilt or sleep towers to leave alone; each recommendation names the tool an agent would call next.

### H. sensors-mcp (port 8120, read-only, owns nothing)

36. Base tables `iot_sensor` (id, kind `WATER_LEVEL`, `RAIN`, `AIR_QUALITY`, `SOIL_MOISTURE`, location, a fictional owner such as a council, the tower that carries it) and `iot_reading` (a reading every 15 minutes over the scenario, consistent with the flood gauge: the sensors near Kuala Krai rise with the river). 
37. `sensors_list_in_area(lat, lng, radius_km=20, kind=None)`; `sensors_get_readings(sensor_id, window_min=360)` (5 to 1440).
38. `sensors_get_alerts(lat, lng, radius_km=20, kind=None)`: sensors above their threshold at the clock with the trend and a **projected time to reach the danger level** (linear on the last hour, `null` when falling), sorted most urgent first; at T0 the Kuala Krai water sensors alert and quiet places do not.

### I. scam-mcp (port 8121, read-only, owns nothing)

39. Base tables `scam_pattern` (about 10 fictional patterns such as a fake parcel SMS, a fake bank call, a prize message; kind `VOICE`, `SMS`, `MESSAGING`; severity; an example text in generic words with no real brand) and `scam_signal` (counts of reports and blocked attempts per pattern, per town, per hour of the scenario). Counts only: no number, no sender, no recipient.
40. `scam_get_hotspots(lat, lng, radius_km=30, window_min=360)`: patterns ranked by reports in the circle with a trend (rising or falling), and `blocked` counts; groups under 5 reports are withheld.
41. `scam_get_pattern(pattern_id)`: the pattern, its severity, its example text, the advice line.
42. `scam_estimate_protection(lat, lng, radius_km=30)`: for the circle, the customers who would be protected by a shield, messages it would have blocked in the window, and an estimated loss avoided in RM (a stated synthetic average); labelled as an estimate.

### J. policy-mcp

43. `policy_check_action` knows three new actions: `energy_sleep_cells` (normal rules: auto-allow under the subscriber and confidence limits, ask in the peak window), `exposure_book_qod` (always asks: it sells a service) and `enterprise_issue_credit` (always asks: it moves money). `comms_send_notice` and `workforce_create_order` already exist (always ask). The kill switch and the hourly cap apply to all five. `known_actions` lists them.

### K. Reset

44. The five new owned tables (`energy_action`, `care_notice`, `sla_credit`, `qod_booking`, `field_job`) are in `RUNTIME_TABLES`: Reset clears them and restarts their counters, and the ids start again from 1 (`NTC-0001`, `CRD-0001`, `BKG-0001`, `JOB-0001`, `ENA-0001`). Nothing else changes in reset.

### L. Demo: the Tracks tab and the six-track Replay

45. A 5th tab **Tracks** shows six cards (one per track) filled by calls to the servers through `/api/tracks/state`, which reads (hub only): operations (incident status and the loop result from the heal state), workforce (jobs and the crew ETA), customer (notices sent, tickets deflected, a scam hotspot count), network (towers overloaded or down, the next crowd event risk), sustainability (kWh and CO2 saved, generator hours left, water-level alert), revenue (revenue at risk, credits issued, quality-on-demand bookings in RM). It shows only what has happened by the scenario clock; before anything is done every card says what is waiting.
46. `POST /api/agent/run` accepts `"script": "incident"` (default, unchanged) or `"script": "tracks"`. The tracks script plays the whole incident script first, then continues: care impact, draft, policy, send; enterprise revenue at risk, policy, credit; field find crew, policy, dispatch; energy tower, savings, policy, apply; exposure quote, policy, book; events forecast; sensors alerts; scam hotspots. Each real-world action goes through the policy gate and waits for the human's Approve, like the incident script. The script reads ids and tokens out of earlier results; it decides nothing.
47. Each finished call in a run that belongs to a track adds `{"type": "track", "step", "track": 1 to 6, "name", "label"}` after the result event, from `tracks.py` (a tool-to-track table: energy 5, care 3, enterprise 6, exposure 6, field 2, events 4, sensors 5, scam 3, and the existing network, heal and incident tools 4 or 1). The Tracks cards light up as their events arrive.
48. `map_effects.py` gains effects for the new tools: a `link` from the depot to the tower for `field_dispatch` (and a `pin` with the access mode), a quiet `focus` for energy sleep towers, an `area` for an exposure booking, `pin`s for sensor alerts and events. Positions come from the database or the server's own result. Unknown shapes give no effects.
49. The Tracks tab and the six-track Replay work with no model key. The page keeps its guard tests (hosts, hooks, contrast, no logos, valid JS) and gets the Tracks hooks.
50. Console: every new tool is listed with a pre-filled example.

### M. Regression

51. The counts of servers change from 13 to 21 (`test_servers.py`, `tests/test_run_mcp.py`, docs, `__main__` help), the Console says 80 tools. The golden trace, the Replay end-to-end tests and every existing test pass. ruff, mypy strict, pytest, skill parity: clean.

## 3. Tool contract

New tools (25), all `Envelope` responses:

| Server | Tools (writes marked W, needing a policy token) |
| --- | --- |
| energy | `energy_get_tower`, `energy_find_savings`, `energy_apply_sleep` (W) |
| care | `care_get_impact`, `care_draft_notice`, `care_send_notice` (W), `care_list_notices` |
| enterprise | `enterprise_get_revenue_at_risk`, `enterprise_list_accounts`, `enterprise_issue_credit` (W) |
| exposure | `exposure_list_profiles`, `exposure_quote`, `exposure_book` (W) |
| field | `field_find_crew`, `field_dispatch` (W), `field_list_jobs` |
| events | `events_list_upcoming`, `events_forecast_load`, `events_capacity_plan` |
| sensors | `sensors_list_in_area`, `sensors_get_readings`, `sensors_get_alerts` |
| scam | `scam_get_hotspots`, `scam_get_pattern`, `scam_estimate_protection` |

Argument ranges and the `data` shapes are in each server's README (written with its tests). Errors are `menara_core.errors` types. New demo route: `GET /api/tracks/state`; new run option `script`; new event type `track`.

## 4. Data

| Table | Written by | Read by | Notes |
| --- | --- | --- | --- |
| `tower_energy`, `care_template`, `enterprise_account`, `qod_profile`, `technician`, `spare_part`, `crowd_event`, `iot_sensor`, `iot_reading`, `scam_pattern`, `scam_signal` | seed only | their own server | new base tables |
| `energy_action` | energy-mcp | energy-mcp, demo (via the tools) | runtime |
| `care_notice` | care-mcp | care-mcp | runtime |
| `sla_credit` | enterprise-mcp | enterprise-mcp | runtime |
| `qod_booking` | exposure-mcp | exposure-mcp, events-mcp does not read it | runtime |
| `field_job` | field-mcp | field-mcp | runtime |

Cross-domain reads (read-only, listed in each README): energy reads `tower`, `cell`, `tower_state`, `tower_kpi`, `tower_neighbour`, `critical_site`, `flood_extent`; care reads `tower_subscribers`, `tower`, `tower_state`, `ticket`, `grid_feeder_state`; enterprise reads `tower_state`, `critical_site`, `tower`; exposure reads `tower_kpi`, `tower`, `crowd_event`; field reads `tower`, `flood_extent`, `drone`, `drone_finding`; events reads `tower`, `tower_kpi`, `tower_subscribers`; sensors reads `tower`, `flood_reading`; scam reads `tower`, `tower_subscribers`. No server calls another server.

**Existing tests that change (approved contract change):** `packages/menara-agent/tests/test_servers.py` (21 servers), `tests/test_run_mcp.py` (21 servers, 21 ports, 21 flags), `packages/menara-core/tests/test_reset.py` (the runtime table list), `packages/menara-demo/tests` that assert event type lists for a run (a `track` event can follow a result), and `policy-mcp` tests that list the known actions.

## 5. Scenario impact

None to `kuala_krai.yaml`. The new seed modules read the scenario's cluster towers and sites (as `sites.py` does) to place the flood-linked data: generator and fuel for `KKRI-0142`, enterprise accounts on the cluster towers, water sensors near the gauge, a field depot near Kota Bharu. The clock decides what is visible: at T0 the flood is on, so the alerts and the revenue at risk exist; the new action tables are empty.

## 6. Privacy and honesty

- No subscriber hash, phone number, message text to a person, or recipient list in any response or table: care and scam use counts only; customers are fictional companies; technicians are fictional names.
- Aggregates under 5 are withheld (care impact, scam hotspots, usage already).
- Every response says it is synthetic; prices, rates, penalties, CO2 factors and loss figures are stated constants labelled as invented. No claim about TM's real systems, customers, prices or coverage. App, company and event names are fictional or generic; no real organisation branding in the UI.
- Every action that commits money, staff, customers or capacity needs a human through the policy gate; the agent never holds the approver key.

## 7. Ports and registration

Ports 8114 to 8121 (the next free ones after 8113), created with `uv run python scripts/new_mcp.py <name> --port <port> --description "..." [--owns ...]`, which registers each in `.mcp.json` and the root `pyproject.toml`. `CLAUDE.md` and `AGENTS.md` get eight port rows and eight status rows.

## 8. Alternatives considered

- **One big "business" MCP.** Rejected: separate servers are what the team can pick up independently, and the rule is one domain per server.
- **Live data or an LLM inside the servers.** Rejected: deterministic arithmetic is testable and keeps the story repeatable; the agent supplies the intelligence.
- **A different story per track.** Rejected: one incident across six tracks is easier to demo and to remember, and it reuses the clock, the twin and the policy gate.
- **Only the two headline MCPs.** The developer asked for the others too, so the team can reuse them; each is small and independent.

## 9. Rollout

Delivery is in slices (energy and care first, then enterprise, field and exposure, then events, sensors and scam, then the Tracks tab and the six-track Replay), each leaving the suite green. After merging, teammates stop the servers, re-seed, restart the demo, and see 21 servers and 80 tools. `Reset demo` clears the new runtime tables too.
## 10. As built (differences from the plan above)

- **Order.** `events-mcp` was built before `exposure-mcp`, because exposure reads `crowd_event` and the shared crowd model (`menara_core/crowd.py`: attendance times 0.004 PRB points spread over the five nearest towers by inverse distance; risk LOW, MEDIUM from 70, HIGH from 85).
- **care.** `care_language_mix` is per state, not per town. `care_notice` has a `kind` column and `care_send_notice` takes an optional `kind` (default `OUTAGE`).
- **field.** `field_dispatch` has two extra optional arguments, `skill` (default `POWER`) and `access` (default `AUTO`; `ROAD` into floodwater is refused).
- **exposure.** `exposure_quote` and `exposure_book` take an optional `start_in_min` (0 to 4320); `exposure_list_profiles` is the third read tool.
- **enterprise.** Outage minutes start from the first non-UP state (`KKRI-0142` is DEGRADED from -240 and DOWN from -5); a DEGRADED hour counts a quarter of a DOWN hour for the penalty. Credits for the demo are read by the Tracks tab from `sla_credit` because the at-risk list only shows towers that are affected at the clock.
- **energy.** The sleep window is 00:00 to 06:00 local time, which is before T0 (minute -420 to -60), so the six-track Replay starts at minute -300 (02:00 the night before), applies the sleep there, then advances to the incident. Savings use the night draw, not the base draw.
- **Tracks state.** `tracks_state` takes the database file as well as the hub: the energy and quality-on-demand totals have no read tool, so they are summed from `energy_action` (what has happened by the clock) and `qod_booking` (all bookings) through a read-only connection, as `map_effects` already reads the database.
- **Six-track script.** It is not "the whole incident, then the tracks": the care, enterprise, field, sensors and scam steps run in the middle of the incident (right after the drone's report, while `KKRI-0142` is still down) because their answers are empty once power is back. The incident script runs unchanged around them; events and exposure come at the end. Eight actions wait for a human (energy sleep asks because more than 500 customers are on the chosen towers, then the drone, two tilts, the notice, the credit, the crew and the booking).
- **Run options.** `script: "tracks"` defaults the start minute to -300 and `max_steps` to 80; an unknown `script` is a 400.
- **Counts.** 21 servers, 84 tools (80 in the Console; four are human-only), five new runtime tables in the reset list.
