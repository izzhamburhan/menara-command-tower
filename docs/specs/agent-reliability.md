# Spec: reliability fixes found by the live DeepSeek runs

Status: approved by the developer in chat ("Yup yup"). Three small changes, one PR.

## 1. ontology-mcp: `ontology_add_incident_note`

Problem: the model could not record progress on an incident without moving its status, and told the user the notes were read-only.

- New tool `ontology_add_incident_note(incident_id, note)`. Returns the updated Incident envelope.
- Appends `{at, text}` to the incident's notes and sets `updated_at`. The status never changes. Allowed in every status, including RESOLVED (a late follow-up note is legitimate).
- `note` is 1 to 500 characters after trimming (the same limit as `ontology_update_incident`), else `InvalidInputError`. An unknown incident is `NotFoundError`.
- Writes only the `incident` table, which ontology-mcp already owns. No schema change.
- Docs: ontology README tool table, status tables in `CLAUDE.md` and `AGENTS.md` (7 tools becomes 8).

## 2. ontology-mcp: the summary error says how long it was

`ontology_create_incident` rejects a bad summary with `summary must be 5-500 characters (got N)`, so a model can shorten it in one step.

## 3. menara-agent: repair a mangled policy token

Problem: a model copied a 200-character token with a small error and the server answered "Policy token signature is invalid".

- `GatedRunner` remembers every token it has seen policy-mcp issue (an `allow` result, or the token from a human approval it performed).
- When a tool call carries a `policy_token` that is not one of those, and one remembered token is at least 0.9 similar to it (`difflib` ratio), the runner replaces it with that remembered token before calling the server. Otherwise the call is left unchanged and the server rejects it as before.
- This never creates or extends authority. Only tokens that policy-mcp itself issued can be substituted, and the server still checks the action, targets and signature.
- The runner prints one line when it repairs a token, so the repair is visible.

## Acceptance

- Tests for each rule above, written first. Full suite, ruff and mypy stay green.
- Boundary: `servers/ontology-mcp/**`, `packages/menara-agent/**`, `CLAUDE.md`, `AGENTS.md`, `docs/**`. Nothing else changes.