# Menara Command Center (MCP side)

A Palantir-style **network command center for Malaysia**, built for the TM AI Elevate hackathon. This repo holds the **MCP side**: twelve small, independent MCP servers that give an AI agent (and later a map UI) eyes and hands over a mobile network: towers, subscribers, tickets, weather, power, floods, critical sites, a digital twin, a policy engine, a drone and a RAN control sandbox.

**All data is synthetic.** Nothing here is TM's real data, systems, prices or coverage, and no real subscriber is involved. Owner: Izzham Burhan, TMRND.

## The idea in one minute

- **One MCP server per domain.** Each server does one job, has its own tools and its own tests, and can run alone.
- **No server calls another.** The *agent* is the orchestrator: it asks `ticket` what is wrong, `tower` what is down, `grid` and `flood` why, `ontology` who is affected, and so on. Each answer carries `evidence[]` saying which call produced it.
- **Reading is free, acting is gated.** Anything that changes the world (send a drone, retilt antennas) needs a signed token from `policy`, and some actions need a **human** to approve first. The agent can ask, but it can never approve its own request.
- **Everything is replayable.** A scripted clock moves a flood scenario forward in time, so the same story plays out the same way every run.

```
 Map UI / people          LLM agent (your team's)           this repo
┌────────────────┐      ┌──────────────────────┐      ┌────────────────────────────────────────┐
│ draws towers,  │      │ reasons, plans, calls │ MCP  │ tower  ticket  user  ontology  weather │
│ circles, trails│◄────►│ tools, asks policy    │◄────►│ grid   flood   sites twin  policy       │
│ approves risky │      │ before acting         │      │ ran    drone                            │
│ actions        │      └──────────────────────┘      └───────────────────┬────────────────────┘
└────────────────┘                                                         │ read (and own-table writes)
                                                                  data/menara.db  (synthetic SQLite)
```

## Quick start

You need [uv](https://docs.astral.sh/uv/) and Python 3.13.

```bash
uv sync                                       # install everything
uv run python -m menara_core.seed.cli         # build data/menara.db (about 3 seconds)
uv run python -m pytest                       # run the whole test suite
uv run python scripts/run_mcp.py list         # see every server and its port
uv run python scripts/run_mcp.py tower        # run one server (HTTP on its port)
```

Prefer `python -m ...` over console scripts such as `uv run menara-seed`: some Windows machines block the `.venv\Scripts\*.exe` shims.

**Try it with a real model.** Put your own `DEEPSEEK_API_KEY` in a `.env` file at the repo root (copy `.env.example`; `.env` is gitignored, never commit it), then:

```bash
uv run python -m menara_agent "Ticket TK-88213 just arrived. Find the cause and blast radius, and record an Incident."
```

`menara_agent` is a small **test driver**, not the team's real agent. It lets a model call all twelve servers so you can watch the flow. When policy says a human must decide, it stops and asks you in the terminal (`Approve? [y/N]`). See [`packages/menara-agent/README.md`](packages/menara-agent/README.md).

**See it in a browser.** `uv run python -m menara_demo` starts the servers and a simple demo page at http://127.0.0.1:8200: a map of Malaysia where you click to circle a place, see its towers and subscribers, and open a subscriber's trail, plus a console to run any tool and read the raw output. It is a demo aid, not the real UI. See [`packages/menara-demo/README.md`](packages/menara-demo/README.md).

**Or use the servers from your own MCP client** (Claude Code, Codex, an inspector): [`.mcp.json`](.mcp.json) already registers all twelve over stdio. For a browser-style tool such as `npx @modelcontextprotocol/inspector`, run a server over HTTP with `scripts/run_mcp.py` and connect to `http://127.0.0.1:<port>/mcp`.

## The twelve MCP servers

Port is for streamable HTTP; stdio (the default) needs none. 56 tools in total. Each server's full contract (arguments, response shapes, errors) is in `servers/<name>-mcp/README.md`.

| Server | Port | What it is for | Tools | Writes |
| --- | --- | --- | --- | --- |
| `tower` | 8101 | Tower status, KPIs, alarms, neighbours; search by box or circle | `tower_get_status`, `tower_list_in_bbox`, `tower_list_in_radius`, `tower_get_kpi`, `tower_get_alarms` | nothing |
| `ticket` | 8102 | Customer tickets, clustered by place | `ticket_get_ticket`, `ticket_cluster_by_location`, `ticket_add_note`, `ticket_resolve` | notes, resolutions |
| `user` | 8103 | Subscriber serving cell and experience; who is on a tower or in a circle; a subscriber's trail | `user_get_serving_cell`, `user_get_experience`, `user_list_in_area`, `user_list_on_tower`, `user_get_trail` | nothing |
| `ontology` | 8104 | Linked objects: blast radius, neighbours, upstream dependencies, and the **Incident** | `ontology_blast_radius`, `ontology_neighbours`, `ontology_upstream_of`, `ontology_create_incident`, `ontology_get_incident`, `ontology_list_incidents`, `ontology_update_incident`, `ontology_add_incident_note` | incidents |
| `weather` | 8105 | Rainfall and lightning near a point | `weather_get_rainfall`, `weather_get_lightning` | nothing |
| `grid` | 8106 | Power feeders and outages behind each tower | `grid_get_tower_power`, `grid_get_feeder_status`, `grid_list_outages` | nothing |
| `flood` | 8107 | River gauges and flood extent | `flood_get_gauge`, `flood_list_gauges`, `flood_check_point` | nothing |
| `twin` | 8108 | Digital twin: simulate a failure or an antenna tilt *before* acting | `twin_simulate_failure`, `twin_simulate_tilt`, `twin_get_simulation` | its own simulation log |
| `policy` | 8109 | The gate for real-world actions: allow, ask a human, or deny; audit log; kill switch | `policy_check_action`, `policy_get_approval`, `policy_list_approvals`, `policy_approve`\*, `policy_reject`\*, `policy_record_outcome`, `policy_get_status`, `policy_set_kill_switch`\*, `policy_update_setting`\*, `policy_get_audit` | settings, approvals, audit log |
| `drone` | 8110 | A simulated drone that inspects a tower | `drone_list_drones`, `drone_dispatch`, `drone_get_mission`, `drone_list_missions` | missions |
| `ran` | 8111 | A sandboxed RAN control: tilt cells, reset, roll back | `ran_get_config`, `ran_tilt_cells`, `ran_reset_cell`, `ran_revert_change`, `ran_get_change`, `ran_list_changes` | changes and their KPI effects |
| `sites` | 8112 | Critical sites (hospitals, clinics, police, schools, enterprise) and their tower | `sites_get_site`, `sites_list_in_bbox`, `sites_for_tower` | nothing |

\* Human-only: needs `MENARA_APPROVER_KEY`, which the command-center UI holds and the agent must never have.

### A few things every server shares

- **The envelope.** Every tool returns `{synthetic, as_of, data, evidence[], warnings[]}`. `synthetic: true` is always set for demo data; `evidence[]` names the call, the source and the key it came from; `warnings[]` flags truncation or withheld data.
- **Domain-prefixed tool names** (`tower_get_status`) and typed, tested responses (pydantic, mypy strict).
- **Own tables only.** Everyone reads `data/menara.db`, but a server writes only the tables it owns. This is enforced by a SQLite authorizer, not by convention.

## The demo story: the Kuala Krai flood

The scenario lives in [`data/scenario/kuala_krai.yaml`](data/scenario/kuala_krai.yaml). Time is `t_min`, minutes since **T0 = 07:00 on 2026-11-14**.

| t_min | What happens |
| --- | --- |
| -240 | Mains fails at tower `KKRI-0142`; its power feeder trips |
| -5 | `KKRI-0142` goes DOWN; neighbours `KKRI-0143` and `KKRI-0144` hit 91% PRB |
| 0 | Ticket `TK-88213` arrives ("no data, flood") |
| 12 | The ticket storm is complete (37 tickets) |
| 12 to 75 | An approved drone flies in (arrives about 57, finishes about 72) |
| 360 | Power is restored; the tower is back up |

The agent's path, which `tests/golden_trace/` replays across separate server processes: read the ticket, cluster the tickets, find the serving cell and tower, check weather, power and flood in parallel to find the **cause**, compute the **blast radius**, record an **Incident**, simulate a fix in the twin, ask policy (a human approves the drone), inspect with the drone, try a tilt that **fails** (scripted on purpose), verify with KPIs, **roll back**, try a better tilt that works, watch power return, and close the tickets. Everything it did is in the audit log.

**The clock.** The servers never move time; whoever drives the demo does:

```bash
uv run python -m menara_core.scenario_cli show        # where are we?
uv run python -m menara_core.scenario_cli set 12      # jump to minute 12
uv run python -m menara_core.scenario_cli advance 60  # move forward an hour
uv run python -m menara_core.scenario_cli reset       # back to T0
```

## Safety, privacy and honesty

- **Policy gate.** `policy_check_action` answers *allow*, *ask* or *deny*. By default it allows automatically only when fewer than 500 subscribers are affected, confidence is at least 0.9, it is off-peak (18:00 to 23:00 is peak), no emergency-service site is touched, and fewer than 10 actions ran in the last hour. Drone dispatch, work orders, customer notices and hardware replacement always ask a human (work orders, notices and hardware have rules ready but no MCP behind them yet). A kill switch makes policy deny every action.
- **Signed tokens.** An *allow* (or a human approval) returns a short-lived HMAC token. `drone` and `ran` verify it locally for that exact action and set of towers, so an agent cannot act without going through policy.
- **Human approval.** `policy_approve` and friends need `MENARA_APPROVER_KEY`. The dev defaults are public, so this stops an agent approving itself; it is **not** production security. Set private values in `.env` for any shared demo.
- **Privacy by design.** Subscribers are hashed MSISDNs, locations are cell-level (a tower position, never a point), and groups of fewer than 5 are withheld. The subscribers in the data are a **synthetic sample**; the per-tower population estimate is a separate number. A person's movement trail is personal data under PDPA, so using these tools on real data would need legal and data-protection sign-off first.
- **Label demo data as synthetic.** No claims about TM's real systems; no real organisation branding in any UI.

## Maps, areas and trails

For a map UI: `tower_list_in_radius` returns the towers inside a circle (nearest first, with distance and status); `user_list_in_area` and `user_list_on_tower` return the subscribers on them with sampled and estimated counts, attach state, experience label and recent cell changes; `user_get_trail` returns one subscriber's sequence of cells with arrival and leave times. About half of the subscribers commute in the seed, so trails have movement, except around the flood towers where people stay put on purpose.

## From synthetic to real data

Only **`tower-mcp`** is ready for it so far: it reads through a `TowerSource` interface with a SQLite implementation and an HTTP implementation (`--source http --api-url ...`), and marks responses `synthetic: false` when the data is real. The HTTP contract ("Tower API v1") is ours, so a real system would need a thin gateway in front. The other servers still query SQLite directly; copy the pattern when one needs a real source. The scenario clock, the cross-domain reads and the KPI overlay do not carry over to real APIs.

## Repo layout

```
packages/menara-core/    shared library, not an MCP: envelope, IDs, privacy, clock, audit, tokens, seed
packages/menara-agent/   the DeepSeek test driver (python -m menara_agent)
packages/menara-demo/    a simple local demo page: map, circle search, trails, tool console (python -m menara_demo)
servers/<name>-mcp/      one runnable MCP per folder: pyproject, README contract, src/, tests/
data/scenario/           scripted scenarios (kuala_krai.yaml); data/menara.db is generated, gitignored
tests/golden_trace/      the whole flood story, walked across separate server processes
scripts/                 run_mcp.py, new_mcp.py, worktree and skill tooling
.claude/ and .codex/     process skills for Claude Code and Codex (kept identical by a CI check)
.mcp.json                registers the twelve servers for MCP clients
docs/                    specs and test plans for the larger changes
CLAUDE.md, AGENTS.md     the handbook for AI coding agents and people (same rules, two audiences)
playbook.md              the working process: gates, git rules, definition of done
```

The server folder is `servers/`, not `mcp/`, on purpose: with pytest's importlib mode a folder named `mcp` would shadow the real `mcp` library. Also keep `mcp[cli]` pinned to `>=1.9,<2` (2.x renamed `FastMCP`).

## Working in this repo

```bash
uv run python -m pytest            # tests
uv run python -m ruff check .      # lint
uv run python -m mypy              # strict typing
```

- **Process.** Read [`playbook.md`](playbook.md) and [`CLAUDE.md`](CLAUDE.md) (or [`AGENTS.md`](AGENTS.md)). Work happens in a git worktree (`sh scripts/worktree-add.sh <branch>`), with a spec and a test-first plan for anything non-trivial, and fresh test output before anyone says "done". Nothing is committed or pushed without the developer's say-so.
- **Adding a server.** `uv run python scripts/new_mcp.py <name> --port <port> --description "..." [--owns table1,table2]` scaffolds it and registers it; then replace the placeholder tool, tests first.
- **After you change the seed or the scenario**, re-seed with all MCP servers stopped (they hold the database open): `uv run python -m menara_core.seed.cli`.
- **Secrets** live in `.env` (see `.env.example`): `DEEPSEEK_API_KEY` for the test driver, `MENARA_SIGNING_KEY` for policy tokens, `MENARA_APPROVER_KEY` for human approval, `MENARA_PII_SALT` for hashing. Never commit them.

## Where to read next

| If you want to... | Read |
| --- | --- |
| understand the rules every server follows | [`CLAUDE.md`](CLAUDE.md) |
| know one server's exact tools and errors | `servers/<name>-mcp/README.md` |
| see the policy rules in detail | [`servers/policy-mcp/README.md`](servers/policy-mcp/README.md) |
| run a model against the servers | [`packages/menara-agent/README.md`](packages/menara-agent/README.md) |
| see the servers in a browser | [`packages/menara-demo/README.md`](packages/menara-demo/README.md) |
| see why a larger change was built the way it is | `docs/specs/` and `docs/plans/` |
| follow the team process | [`playbook.md`](playbook.md) |
