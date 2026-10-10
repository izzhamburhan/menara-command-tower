## Summary

<!-- Behavior change in plain language, then the technical change. -->

## Server(s) touched

<!-- e.g. tower-mcp, menara-core -->

## Contract changes

<!-- Tool names, arguments, data models, tables, ports, scenario. "None" if none. Teammates' agents depend on these. -->

## Tests and evidence

- [ ] Failing test written first
- [ ] `ruff`, `mypy`, `pytest` pass (paste counts)
- [ ] Real stdio smoke call (new or changed tool or server)
- [ ] Golden trace passes (seed, schema, scenario, or cross-server change)
- [ ] Skill parity passes (skill change)

## Checklist

- [ ] Each MCP still independent; no MCP calls another; writes only to its own tables
- [ ] Responses use the envelope with `synthetic: true` and `evidence[]`
- [ ] Data synthetic; no real or real-looking personal data; location cell-level at most
- [ ] README contract, `CLAUDE.md` and `AGENTS.md` status and port tables, `.mcp.json` current

## Rollout notes

<!-- Re-seed? Restart servers? Anything teammates must do after merging. -->
