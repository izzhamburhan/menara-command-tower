# TDD plan: menara-agent

Spec: `docs/specs/menara-agent.md`. Every slice leaves the suite green. Tests live in `packages/menara-agent/tests/`. Run a slice with `uv run python -m pytest packages/menara-agent`.

## Global constraints

- Allowed to change: `packages/menara-agent/**`, root `pyproject.toml` (workspace dev group and `[tool.uv.sources]`, mypy path), `.env.example`, `CLAUDE.md`, `AGENTS.md`, `docs/**`, `.github/workflows/ci.yml` only if it needs the new package.
- Must not change: anything under `servers/`, `packages/menara-core/`, `.mcp.json`, `tests/golden_trace/`.
- Owns no tables. Writes nothing except the scenario clock through `menara_core.clock`.
- `mcp[cli]>=1.9,<2`. mypy strict. No network in tests.

## Slice 1: tool schemas and the hidden list

- Files: `src/menara_agent/tools.py`, `tests/test_tools.py`.
- Produces: `HIDDEN_TOOLS: frozenset[str]`, `to_openai_tool(name, description, input_schema) -> dict`, `visible(tools) -> list`.
- Red test first: `test_tools.py::test_schema_conversion_keeps_name_description_parameters` and `::test_approver_tools_are_hidden`. Expected red: `ModuleNotFoundError: menara_agent.tools`.
- Green: the pure conversion and the filter.

## Slice 2: the loop with a fake model

- Files: `src/menara_agent/loop.py`, `tests/test_loop.py`.
- Produces: `ChatClient` Protocol (`complete(messages, tools) -> Reply`), `ToolRunner` Protocol (`call(name, args) -> str`), `run_agent(llm, runner, task, tools, max_steps) -> str`.
- Red tests: `test_loop.py::test_finishes_when_the_model_stops_calling_tools`, `::test_stops_at_the_step_cap`, `::test_a_tool_error_is_reported_to_the_model_and_the_loop_continues`. Expected red: `ModuleNotFoundError: menara_agent.loop`.
- Green: the loop with a scripted fake client.

## Slice 3: the human approval gate

- Files: `src/menara_agent/gate.py`, `tests/test_gate.py`. Read `servers/policy-mcp/README.md` first to get the exact shape of an `ask` result and the approve and reject arguments.
- Produces: `GatedRunner(inner, approver_key, ask_human)` wrapping a `ToolRunner`.
- Red tests: `test_gate.py::test_an_ask_prompts_the_human_and_approves_with_the_key`, `::test_a_no_rejects`, `::test_the_model_cannot_call_approver_tools`, `::test_allow_and_deny_pass_through`. Expected red: `ModuleNotFoundError: menara_agent.gate`.
- Green: wrapper that detects `ask`, prompts, calls `policy_approve` or `policy_reject`, and refuses hidden names.

## Slice 4: real MCP connection

- Files: `src/menara_agent/servers.py`, `tests/test_servers.py`, `packages/menara-agent/pyproject.toml`, root `pyproject.toml` (workspace source and dev group, mypy path).
- Produces: `load_config(path) -> dict[str, ServerSpec]`, `McpHub` (async context manager) with `list_tools()` and `call(name, args) -> str`, built from `.mcp.json`, with a scrubbed subprocess environment.
- Red tests: `test_servers.py::test_the_environment_for_servers_drops_the_secrets`, `::test_hub_lists_tower_tools_and_answers_a_call` (real stdio against the tower server and a temporary seeded DB). Expected red: `ModuleNotFoundError: menara_agent.servers`.
- Green: connect each server with `stdio_client`, map tool name to session, return the first text block.

## Slice 5: DeepSeek client, clock tool and CLI

- Files: `src/menara_agent/llm.py`, `src/menara_agent/config.py`, `src/menara_agent/cli.py`, `src/menara_agent/__main__.py`, `tests/test_config.py`, `tests/test_cli.py`.
- Produces: `Settings` from the environment and `.env` (a tiny parser, no extra dependency), `DeepSeekClient(ChatClient)` over the `openai` SDK, `demo_advance_clock` tool, `main(argv)`.
- Red tests: `test_config.py::test_missing_key_gives_a_clear_error`, `::test_defaults_for_model_and_base_url`, `test_cli.py::test_advance_clock_tool_moves_the_scenario_clock`, `::test_main_wires_a_fake_model_end_to_end` (fake client injected, real tower stdio). Expected red: `ModuleNotFoundError`.
- Green: wire everything, with the live client constructed only when no fake is injected.

## Slice 6: docs and the real-model run

- Files: `.env.example`, `CLAUDE.md`, `AGENTS.md`, `packages/menara-agent/README.md`.
- Steps: document the runner and variables, note in CLAUDE.md that the agent here is a test driver. Run `doc-drift`. Then run the Kuala Krai task once with the developer's token and report what DeepSeek did, step by step.
- Validation for the whole change: `uv run python -m pytest`, `uv run python -m ruff check .`, `uv run python -m mypy`, `uv run python scripts/check_skill_parity.py`.

## Review checkpoint

After slice 4 (real connection works) and after slice 6 (full validation and the live run).