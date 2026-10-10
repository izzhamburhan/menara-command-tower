# Spec: menara-agent, a small DeepSeek test driver

Status: approved by the developer in chat (small runner, not the real agent).

## Goal

A minimal client that lets DeepSeek call the 12 Menara MCP servers so the developer can watch the Kuala Krai flow end to end and find tool descriptions a real model misreads. It is a test driver. The teammates' real agent and UI replace it later. All data stays synthetic.

## Non-goals

No UI, no memory across runs, no retries or planning logic, no new MCP tools, no server, table or port changes, no real-world actions.

## Package

`packages/menara-agent/` (workspace member, import name `menara_agent`). Depends on `mcp[cli]>=1.9,<2` and `openai`. It does not depend on any server package.

## Behaviour

1. `uv run python -m menara_agent "<task>" [--clock N] [--max-steps N] [--servers a,b]` loads `.env`.
2. Environment: `DEEPSEEK_API_KEY` (required), `DEEPSEEK_MODEL` (default `deepseek-chat`), `DEEPSEEK_BASE_URL` (default `https://api.deepseek.com`).
3. It starts every server in `.mcp.json` as its own stdio subprocess. The subprocess environment does not include `DEEPSEEK_API_KEY` or `MENARA_APPROVER_KEY`.
4. It sets the scenario clock to `--clock` (default 12) before the run, with `menara_core.clock`. The servers never move the clock.
5. MCP tool schemas become OpenAI function definitions. The loop runs model, tool calls, tool results, until the model answers without tool calls or `--max-steps` (default 40) is reached. Every call and result is printed.
6. A tool error goes back to the model as text. It does not crash the loop.
7. Hidden from the model: `policy_approve`, `policy_reject`, `policy_update_setting`, `policy_set_kill_switch`.
8. When `policy_check_action` returns an `ask`, the runner prints the request and prompts the human in the terminal. On `y` it calls `policy_approve` itself with `MENARA_APPROVER_KEY` from the runner's own environment, and the outcome goes back to the model as that tool result. On `n` it calls `policy_reject`. The model never approves its own request.
9. One runner-side tool, `demo_advance_clock(minutes)`, advances the scenario clock so the model can wait for the drone. It is labelled demo-only in its description.

## Acceptance criteria

- Schema conversion keeps name, description and parameters for every tool.
- The four approver tools are absent from the tool list sent to the model.
- A scripted fake model finishes the loop, and the loop stops at the step cap.
- A tool that raises is reported to the model and the loop continues.
- An `ask` triggers the human prompt. Approval and rejection use the approver key, and the model gets the result.
- Real stdio connection to `tower-mcp` lists its 4 tools and answers one call.
- No test uses the network or a real token.

## Contract and scenario impact

No MCP contract changes. No tables. No scenario changes. The runner reads `data/menara.db` only through the servers, except for setting the clock.

## Risks

- DeepSeek tool-calling differs from Claude's, so some schemas may need simplifying. Found during the real-model run, fixed in the descriptions only if clearly needed.
- The approver key sits in the same `.env` as the DeepSeek key. The runner process uses it only for the human's terminal approval, and never exposes it to the model or to the server subprocesses.