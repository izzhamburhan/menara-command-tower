# menara-agent

A small test driver, **not the real agent**. It lets DeepSeek call the 12 Menara MCP servers so you can watch the Kuala Krai flow and spot tool descriptions a real model misreads. The team's agent and UI replace it. **All data is synthetic.**

## Run

```bash
# .env at the repo root (gitignored): DEEPSEEK_API_KEY=...
uv run menara-seed          # once, if data/menara.db does not exist
uv run python -m menara_agent "Support ticket TK-88213 just arrived. Find the cause, the blast radius, and record an Incident."
```

Options: `--clock N` (start minute, default 12 = storm complete), `--max-steps N` (default 40), `--servers tower,ticket` (a subset), `--mcp-config FILE`.

Environment: `DEEPSEEK_API_KEY` (required), `DEEPSEEK_MODEL` (default `deepseek-chat`), `DEEPSEEK_BASE_URL` (default `https://api.deepseek.com`). Every tool call and result is printed.

## What it does

1. Starts every server in `.mcp.json` as its own stdio process (secrets `DEEPSEEK_API_KEY` and `MENARA_APPROVER_KEY` are removed from their environment).
2. Sets the scenario clock to `--clock`, then loops: model, tool calls, tool results, until the model answers or hits the step cap.
3. A tool error goes back to the model as text; it does not stop the run.

## Safety

- The model never sees `policy_approve`, `policy_reject`, `policy_update_setting` or `policy_set_kill_switch`, and calling them is refused.
- When `policy_check_action` answers `ask`, the runner prompts **you** in the terminal. `y` makes the runner (not the model) call `policy_approve` with `MENARA_APPROVER_KEY`; anything else, including no terminal, rejects it.
- Policy tokens are long, and models sometimes garble a character when copying one. The runner remembers the tokens policy-mcp issued and swaps in the real one when the model's copy is at least 90% identical (it prints a line when it does). It never invents or widens a token; the server still checks the signature, action and targets.
- `demo_advance_clock(minutes)` is a runner-side demo tool that moves the scenario clock so the model can wait for a drone. The servers never move it.

## Layout

`tools.py` schema conversion and the hidden list, `loop.py` the agent loop and its protocols, `gate.py` the approval gate, `servers.py` the MCP hub, `llm.py` the DeepSeek client, `config.py` settings and `.env`, `cli.py` the entry point. Tests use a scripted fake model and need no network or token.