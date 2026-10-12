# TDD Implementation Plan: NTT Support in ticket-mcp

**Spec:** [docs/specs/ntt-ticketing.md](../specs/ntt-ticketing.md)  
**Spec:** [docs/specs/ntt-ticketing.md](../specs/ntt-ticketing.md)  
**Status:** DRAFT (Awaiting Developer Approval)

---

## Global Constraints & Boundaries

- **Table Ownership:** `ticket-mcp` owns `ticket_note`, `ticket_resolution`, `ntt`, `ntt_ctt_link`, and `ntt_note`. All other tables are read-only.
- **Privacy & Synthetic Guard:** All data synthetic (`synthetic: true`).
- **Dependencies:** `ticket-mcp` depends only on `menara-core`. No cross-MCP imports.
- **Edit Boundary:**
  - Files allowed to change:
    - `packages/menara-core/src/menara_core/seed/schema.py`
    - `packages/menara-core/src/menara_core/reset.py`
    - `packages/menara-core/tests/test_reset.py`
    - `servers/ticket-mcp/src/ticket_mcp/models.py`
    - `servers/ticket-mcp/src/ticket_mcp/tools.py`
    - `servers/ticket-mcp/src/ticket_mcp/server.py`
    - `servers/ticket-mcp/tests/test_ntt.py` (new)
    - `servers/ticket-mcp/tests/test_server.py`
    - `servers/ticket-mcp/README.md`
  - Files NOT to touch: all other servers (`tower-mcp`, `ran-mcp`, etc.), demo app, scenario yaml.

---

## Slice 1: Database Schema & Reset Support

### 1. Files
- Modify: `packages/menara-core/src/menara_core/seed/schema.py`
- Modify: `packages/menara-core/src/menara_core/reset.py`
- Modify: `packages/menara-core/tests/test_reset.py`

### 2. Failing Test (Red)
- Test: `packages/menara-core/tests/test_reset.py::test_reset_runtime_state_clears_ntt_tables`
- Command: `uv run python -m pytest packages/menara-core/tests/test_reset.py -k test_reset_runtime_state_clears_ntt_tables`
- Expected Failure: `OperationalError: no such table: ntt`

### 3. Implementation (Green)
- Add `CREATE TABLE ntt`, `CREATE TABLE ntt_ctt_link`, `CREATE TABLE ntt_note` to `schema.py`.
- Add `"ntt_ctt_link"`, `"ntt_note"`, `"ntt"` to `RUNTIME_TABLES` in `reset.py`.
- Run `uv run python -m menara_core.seed.cli` to rebuild `data/menara.db`.

### 4. Validation
- `uv run python -m pytest packages/menara-core/tests/test_reset.py`

---

## Slice 2: Pydantic Response Models

### 1. Files
- Modify: `servers/ticket-mcp/src/ticket_mcp/models.py`
- Test: `servers/ticket-mcp/tests/test_ntt.py`

### 2. Failing Test (Red)
- Test: `servers/ticket-mcp/tests/test_ntt.py::test_ntt_models_importable`
- Command: `uv run python -m pytest servers/ticket-mcp/tests/test_ntt.py -k test_ntt_models_importable`
- Expected Failure: `ImportError: cannot import name 'NttDetail' from 'ticket_mcp.models'`

### 3. Implementation (Green)
- Define `NttSummary`, `NttDetail`, `NttList`, `NttLinkResult`, `NttUnlinkResult`, `NttResolution` in `models.py`.

### 4. Validation
- `uv run python -m pytest servers/ticket-mcp/tests/test_ntt.py -k test_ntt_models_importable`

---

## Slice 3: Tool Logic in `tools.py` (Red -> Green)

### 1. Files
- Modify: `servers/ticket-mcp/src/ticket_mcp/tools.py`
- Add tests to: `servers/ticket-mcp/tests/test_ntt.py`

### 2. Slices & Tests
1. **Creation & Deduplication**:
   - Test: `test_create_ntt_and_deduplicate_active_ne`
   - Command: `uv run python -m pytest servers/ticket-mcp/tests/test_ntt.py -k test_create_ntt_and_deduplicate_active_ne`
   - Expected Failure: `AttributeError: module 'ticket_mcp.tools' has no attribute 'create_ntt'`
   - Implement `create_ntt` in `tools.py`.
2. **Retrieval & Listing**:
   - Test: `test_get_ntt_and_list_ntts`
   - Command: `uv run python -m pytest servers/ticket-mcp/tests/test_ntt.py -k test_get_ntt_and_list_ntts`
   - Expected Failure: `AttributeError: module 'ticket_mcp.tools' has no attribute 'get_ntt'`
   - Implement `get_ntt` and `list_ntts` in `tools.py`.
3. **Linking & Unlinking CTTs**:
   - Test: `test_link_and_unlink_ctts`
   - Command: `uv run python -m pytest servers/ticket-mcp/tests/test_ntt.py -k test_link_and_unlink_ctts`
   - Expected Failure: `AttributeError: module 'ticket_mcp.tools' has no attribute 'link_ctts'`
   - Implement `link_ctts` and `unlink_ctt` in `tools.py`.
4. **Cascading Resolution**:
   - Test: `test_resolve_ntt_cascades_to_linked_ctts`
   - Command: `uv run python -m pytest servers/ticket-mcp/tests/test_ntt.py -k test_resolve_ntt_cascades_to_linked_ctts`
   - Expected Failure: `AttributeError: module 'ticket_mcp.tools' has no attribute 'resolve_ntt'`
   - Implement `resolve_ntt` in `tools.py`.
5. **Validation & Error Handling**:
   - Test: `test_ntt_invalid_inputs_and_not_found`
   - Command: `uv run python -m pytest servers/ticket-mcp/tests/test_ntt.py -k test_ntt_invalid_inputs_and_not_found`
   - Implement input bounds checks and errors.

### 3. Validation
- `uv run python -m pytest servers/ticket-mcp/tests/test_ntt.py`

---

## Slice 4: Server Tool Registration

### 1. Files
- Modify: `servers/ticket-mcp/src/ticket_mcp/server.py`
- Modify: `servers/ticket-mcp/tests/test_server.py`

### 2. Failing Test (Red)
- Test: `servers/ticket-mcp/tests/test_server.py::test_tools_registered`
- Command: `uv run python -m pytest servers/ticket-mcp/tests/test_server.py`
- Expected Failure: `assert 'ticket_create_ntt' in tool_names` fails

### 3. Implementation (Green)
- Register `ticket_create_ntt`, `ticket_get_ntt`, `ticket_list_ntts`, `ticket_link_ctts`, `ticket_unlink_ctt`, `ticket_resolve_ntt` in `server.py`.

### 4. Validation
- `uv run python -m pytest servers/ticket-mcp/tests/test_server.py`

---

## Slice 5: Documentation & Golden Verification

### 1. Files
- Modify: `servers/ticket-mcp/README.md`
- Verify: Full pytest suite, ruff, mypy

### 2. Validation Commands
```bash
uv run python -m pytest servers/ticket-mcp
uv run python -m pytest
uv run python -m ruff check .
uv run python -m mypy
```