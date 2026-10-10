# Spec and plan: Story tab (live agent) and trail narration in the demo page

Status: approved in chat. The developer chose "page works, wrong content" and said the live model must be used ("we utilize it so to get real output"). Mid-build the developer also asked for trail narration ("goes to a school, then a hospital, then a mall").

## Goal

1. A **Story** tab in the demo page that runs the incident flow with DeepSeek live (investigate, Incident, drone, tilt, verify, roll back, recover), showing every tool call and result as a timeline, with **Approve / Reject buttons** where policy asks for a human.
2. A **Replay** button on the same tab: the same flow driven by a fixed script instead of a model. It needs no API key and is repeatable, for when the key or network is unavailable. It uses the same real MCP servers, the same gate and the same human approval buttons.
3. An **Explain trail** button in the trail panel: a model writes a short story of the subscriber's day from the trail plus the known places near each tower, for example "overnight at KLNG-0005, then near Kluang School 17, then the clinic".

Non-goals: no authentication, no multi-user runs, no data reset button (re-seed with servers stopped), no real map or place-name lookup, no new MCP tool, nothing under `servers/` changes.

## Trail narration: what it can and cannot honestly say

- The trail is cell level: a tower position, accurate to about a kilometre or more. A model given only latitude and longitude would invent place names ("SMK ...", "Aeon Mall"). So the model is **not** asked to know the world. The backend gathers the facts and the model only writes them up.
- Facts given to the model: each trail segment (tower, arrival, leave, minutes, hour of day, town) and, per tower, the known sites within about 2.5 km from `sites_list_in_bbox` (name, kind, distance). In the demo data these are synthetic sites: hospital, clinic, police, school, enterprise. There are no malls.
- Rules in the prompt: use only the listed sites; say "near" never "at"; label a place as likely, not certain; an overnight stay on one tower is "probably home"; if no site is known near a tower say so instead of guessing; everything is synthetic.
- The response shows the story and the facts it was built from, so a viewer can check it.
- Real place names (schools, malls) need an external map-data lookup (for example OpenStreetMap). That is a separate decision: it sends tower coordinates to a third party, and for real subscribers the whole feature needs PDPA sign-off. Not built here.

## Design

`menara-agent` (small, backward compatible changes):
- `GatedRunner` accepts an `ask_human` that returns a bool **or an awaitable bool**, so a web page can wait for a button.
- `run_agent` takes an optional `on_event(dict)` callback and emits `say` (model text next to tool calls), `call` and `result` events in addition to the existing `log` lines.

`menara-demo`:
- `runs.py`: one run at a time. `RunManager.start(mode, task, clock, max_steps)` runs `run_agent` in a background task with `ClockRunner(GatedRunner(hub, approver_key, ask))`, stores events, and holds at most one pending approval (an `asyncio.Future`). Run ends with a `final` event (answer, step limit, error or cancelled).
- `scripted.py`: `ReplayModel`, a `ChatClient` that returns the next scripted tool call and reads earlier results (ids, tokens) from the conversation. If the human rejects an approval it stops with a closing message.
- `trail_story.py`: builds the facts and calls the model once, without tools.
- Routes: `GET /api/agent/status`, `POST /api/agent/run`, `GET /api/agent/events?since=N` (polling), `POST /api/agent/decision`, `POST /api/agent/cancel`, `POST /api/trail/story`.
- The server holds the DeepSeek key (from `.env`) and the approver key. Neither is ever sent to the browser or to the servers' environment. The model cannot call the four approver tools; only the Approve button, pressed by the human, triggers `policy_approve`. The console and `/api/call` still refuse them.
- Without a key: `status.live_available` is false, live run and trail story return 503 with a clear message, Replay still works.

## Acceptance criteria

1. `GatedRunner` works with a synchronous and with an awaitable `ask_human`; existing gate tests unchanged and passing.
2. `run_agent` emits `call` and `result` events in order with step numbers, a `say` event when the model sends text with tool calls, and tool errors appear as `result` with `ok: false`. With no callback it behaves as before.
3. `POST /api/agent/run` returns a run id; a second run while one is active is 409; unknown mode, bad clock (not an integer in -1440..720) or bad `max_steps` (1..80) is 400; live mode without a key is 503.
4. `GET /api/agent/events?since=N` returns only events from N, the status, and the next index. Events end with exactly one `final`.
5. An approval event pauses the run until `POST /api/agent/decision` with `approve: true|false`; the decision call is 409 when nothing is pending. Approve makes the runner call `policy_approve` with the approver key and the model receives the token; reject makes it call `policy_reject`. The approver key and the model key never appear in any API response.
6. `POST /api/agent/cancel` ends the run (pending approval is rejected) and the next run can start.
7. Replay, through real stdio servers on a scratch database and with the approvals auto-pressed by the test, reaches: incident created or found, drone dispatched, mission COMPLETE, first tilt rolled back, second tilt applied, incident updated, tower UP after recovery, and a final event.
8. `POST /api/trail/story` returns `story`, `facts` (segments and nearby sites per tower) and 400 for a bad hash, 404 for an unknown subscriber, 503 without a key. The prompt contains the facts and the rules above (tested with a fake model that records its input). Known sites come from `sites_list_in_bbox`; a tower with none says so in the facts.
9. The page has a Story tab (task box with two presets, clock start, Run live, Replay, Cancel, timeline with Approve/Reject) and an Explain trail button; the timeline and story are readable in the existing light and dark styles.
10. Full suite, ruff, mypy stay green. Nothing under `servers/` or `menara-core` changes.

## Rollout

Merge, then `uv run python -m menara_demo`. Re-seed (servers stopped) for a clean story run, because the Incident, drone mission and tilts persist in the database.

## Test-first slices

1. `menara-agent`: gate with awaitable ask, `run_agent` events (tests in `test_gate.py`, `test_loop.py`).
2. `menara-demo` runs: `RunManager`, routes, approval, cancel (fake hub and fake model, tests in `test_runs.py`).
3. Replay model and the end-to-end replay test (`test_replay.py`, real stdio servers on a scratch database).
4. Trail story (`test_story.py`).
5. Page: Story tab and Explain trail, then a headless-browser look; docs.