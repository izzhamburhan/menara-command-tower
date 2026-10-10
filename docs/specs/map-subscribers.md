# Spec: towers and subscribers around a point, and a subscriber's trail

Status: approved by the developer in chat ("Approve"). Defaults chosen by me and accepted with the approval: small-group minimum 5, roughly half of eligible subscribers commute (the 40% in the first draft became about 47%, because it is applied to those with a work tower), 48-hour trail cap.

## Goal

A map UI needs to: (1) circle a place and list the towers in it, (2) show the subscribers attached to those towers, (3) pick one subscriber and see which towers they were connected to over time. Today the MCPs only offer a rectangular tower search, tower subscriber *counts*, and one fixed serving cell per subscriber.

Non-goals: no UI, no REST layer, no new MCP server or port, no real data, no change to ticket, policy, ran or drone behaviour. Individual-level data stays hashed and cell-level.

## Findings that shape the design

- `tower-mcp` already reads through a `TowerSource` (SQLite or HTTP). A radius search built on `source.list_towers` (box prefilter, then exact distance in `tools.py`) works for both sources with no source change.
- The seed holds about 6 to 14 synthetic subscribers per tower (about 12,400 in all). They are a **sample**. The population estimate per tower is in `tower_subscribers.subscribers_est` (for example 820 for `KKRI-0143`). Responses must say which is which.
- A subscriber has one fixed `serving_cell`. There is no location history, so a trail needs new data.
- `ontology-mcp`, `twin-mcp` and `policy-mcp` already read `tower_subscribers`; `user-mcp` reading it is a new, read-only, documented exception.

## Acceptance criteria

### tower-mcp: `tower_list_in_radius`

1. Returns every tower whose distance from the centre is at most `radius_km`, nearest first, each with `distance_km` (3 decimals), plus the same fields as `tower_list_in_bbox`.
2. A tower exactly outside the radius is excluded even when it is inside the circle's bounding box (a corner case the box search cannot answer).
3. `status` filter and `limit` behave as in `tower_list_in_bbox`. `limit` is 1 to 2000. Over the limit sets `truncated` and a warning, keeping the nearest.
4. If the bounding-box prefetch itself overflows the source's maximum, the response carries a warning that distant towers may be missing, never silently wrong results.
5. Invalid input raises `InvalidInputError`: latitude outside -90..90, longitude outside -180..180, `radius_km` outside 0.1..200, unknown status.
6. The same behaviour on the SQLite source and on the HTTP source (the existing fake API, which needs no change).
7. `evidence[]` names `tower_list_in_radius`; envelope `synthetic` follows the source.

### user-mcp: `user_list_in_area`, `user_list_on_tower`

8. `user_list_in_area(lat, lng, radius_km, limit=200)` lists subscribers whose serving tower **at the current scenario time** is inside the circle. `radius_km` 0.1..100, `limit` 1..500, same coordinate checks as above.
9. `user_list_on_tower(enodeb_name, limit=200)` does the same for one tower. A bad id is `InvalidInputError`, an unknown tower is `NotFoundError`.
10. Each subscriber row has `msisdn_hash`, `serving_cell`, `enodeb_name`, `cell_lat`, `cell_lng` (cell level), `attached`, and `latest_label` (GOOD, FAIR, POOR, NO_SERVICE or null).
11. The response also has `towers[]` (one entry per tower that has subscribers: `enodeb_name`, `cell_lat`, `cell_lng`, `subscribers_sampled`, `subscribers_est`), `subscribers_total` (sampled subscribers matching, before `limit`), and `truncated`.
12. **Small-group rule (privacy).** If 1 to 4 sampled subscribers match, the response has `withheld: true`, empty `subscribers` and `towers`, `subscribers_total: null`, and a warning. Five or more are returned in full. No match at all is an ordinary empty result (`withheld: false`, `subscribers_total: 0`). The rule uses `menara_core.privacy.MIN_AGGREGATE_COUNT`.
13. During the flood scenario at clock 12, listing around `KKRI-0142` shows its subscribers with `attached: false` and `latest_label: NO_SERVICE`; listing `KKRI-0143` shows `POOR` or `FAIR` rather than `NO_SERVICE`.
14. A subscriber's tower is the cell they are on at the current clock (criterion 17), so movers appear on their new tower once the clock passes their move.

### user-mcp: `user_get_trail`

15. `user_get_trail(msisdn_hash, window_min=1440)`, `window_min` 5..2880. Returns `segments[]` for the window ending at the current clock, oldest first. Each segment: `serving_cell`, `enodeb_name`, `cell_lat`, `cell_lng`, `arrived_at`, `left_at` (null if still there), `duration_min` (minutes inside the window, up to the current clock), `current` (true for the last one). Also `moves` (cell changes in the window), `distinct_towers`, and `location_precision: "cell"`.
16. Segments never extend past the current clock: at clock 0 the trail has nothing after minute 0, and a subscriber who has not moved yet has one segment.
17. **Consistency.** At scenario minute 0 every subscriber's trail cell equals their `subscriber.serving_cell`. `user_get_serving_cell` now reports the cell from the trail at the current clock and falls back to the `subscriber` row when there is none. All existing `user_get_serving_cell` tests and the golden trace still pass unchanged.
18. Unknown hash is `NotFoundError`; a malformed hash or out-of-range window is `InvalidInputError`.
19. Subscribers on the Kuala Krai cluster towers do not move (they stay in the flood area, offline). At least 30% of the other subscribers move at some point in the seeded period, tested on the small test seed and on the full default seed (about 47% there), and every move is between existing towers, 5 to 25 km from home.

### Seed

20. `uv run menara-seed` is deterministic: the same seed gives the same trails. Every previously seeded table has the same rows and counts as before this change (movement uses its own random stream and is generated last).
21. The seed summary lists the new table's row count.

## Tool contract

New tools (domain-prefixed, all read-only, all return `Envelope`):

| Tool | Arguments | `data` |
| --- | --- | --- |
| `tower_list_in_radius` | `lat, lng, radius_km, status?, limit=500` | `center`, `radius_km`, `towers[]` (pin fields plus `distance_km`), `returned`, `truncated` |
| `user_list_in_area` | `lat, lng, radius_km, limit=200` | `center`, `radius_km`, `towers[]`, `subscribers[]`, `subscribers_total`, `returned`, `truncated`, `withheld` |
| `user_list_on_tower` | `enodeb_name, limit=200` | the same shape without `center` and `radius_km` |
| `user_get_trail` | `msisdn_hash, window_min=1440` | `msisdn_hash`, `window_min`, `segments[]`, `moves`, `distinct_towers`, `location_precision` |

Errors come from `menara_core.errors` (`InvalidInputError`, `NotFoundError`). Evidence names the producing tool and the key (`ref` is the tower, the hash, or the centre `"lat,lng"`).

`user_get_serving_cell` keeps its arguments and fields; only the source of the cell changes (criterion 17). Tool counts: tower 4 to 5, user 2 to 5.

## Data

- **New table** `subscriber_cell_visit(msisdn_hash, start_min, serving_cell, enodeb_name, cell_lat, cell_lng)`, primary key `(msisdn_hash, start_min)`, indexed by `msisdn_hash`. A visit lasts until the next row's `start_min`. Base (seed-only) table, served by `user-mcp`, which only reads it. Coordinates are the coarsened cell coordinates already used by `subscriber`, so `user-mcp` needs no read of `tower`.
- **Generated** by a new `seed/movement.py`, called last in `build`, with its own `random.Random(f"{seed}:movement")`. Period: minute -1440 to 480, the same as the experience data. Model: the home tower is the subscriber's tower at minute 0; a mover has a work tower 5 to 25 km away (never a flood-cluster tower), leaves home about 08:00 (minute 60) and again the day before, stops 30 minutes at the tower nearest the midpoint, then is at work until about 17:30. Times get a per-subscriber jitter of up to 45 minutes. About half of the subscribers who have such a work tower commute (about 47% of all subscribers in the default seed).
- **Read** by `user-mcp`: `subscriber`, `subscriber_state`, `subscriber_experience`, `subscriber_cell_visit`, and (new, read-only, documented in CLAUDE.md and the contract guard skill) `tower_subscribers`.
- **Known limitation.** Experience samples are generated at the home tower, so a mover's `user_get_experience` after they move still reflects the home tower. Documented in the user-mcp README; not fixed here.
- Other servers: ontology, twin and policy read `subscriber`-family tables only for counts and are not affected; their tests are re-run to prove it.

## Scenario impact

None to `kuala_krai.yaml`. At T0 and clock 12 everything the scenario and the golden trace rely on is unchanged (criteria 17, 19, 20). Movers start to move after minute 60, which only shows when the demo clock is advanced.

## Privacy

- Identifiers: hashed MSISDN only. Location: cell level at most, never a point for one person.
- Lists and counts follow the small-group rule (criterion 12). A trail is only available for a hash the caller already has, and the window is capped at 48 hours.
- All of it is synthetic and labelled so. **For real data this feature needs legal and data-protection sign-off first**: a person's movement history is personal data under PDPA and would normally need aggregation, consent or another lawful basis. The README says so in one line.

## Ports and registration

No new server. No port, `.mcp.json` or root `pyproject.toml` change. Docs: tower and user READMEs, the status table and rule 2 in `CLAUDE.md` and `AGENTS.md`, and the `mcp-contract-guard` skill's list of cross-domain reads (then `sync_codex_skills.py`).

## Alternatives considered

- **Put the area search in ontology-mcp.** It already reads subscriber tables, but the question is a tower and a subscriber question, and putting it there would blur domains. Rejected.
- **One tool returning towers and subscribers together.** It would make `tower-mcp` read subscriber data or make `user-mcp` read tower data. The UI composes the two calls instead.
- **Store a position every few minutes.** Much more data for the same trail. Storing only cell changes gives arrival and leave times directly.
- **Trail through the experience table.** It has no cell column, and the sampling is too coarse.

## Rollout

After merging, everyone runs `uv sync` and `uv run python -m menara_core.seed.cli` (stop all servers first), and restarts any running servers. Teammates' agents see three new user tools and one new tower tool. `user_get_serving_cell` can now change over time for movers.