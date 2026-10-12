# Spec: NTT (Network Trouble Ticket) Support in ticket-mcp

**Owner:** Akmal Izudin (TMRND)  
**Status:** DRAFT (Awaiting Developer Approval)  
**Related Systems:** TM iNTT (`/Users/akmalizudin/Developer/Code/INTT`)

---

## 1. Goal and Non-Goals

### Goal
- Elevate `ticket-mcp` to support **Network Trouble Tickets (NTT)** alongside Customer Trouble Tickets (CTT).
- Enable NOC agents to create infrastructure tickets bound to a Root Network Element (e.g. Tower `KKRI-0142` or Feeder `FDR-0812`).
- Support CTT-to-NTT association and deduplication (auto-link incoming CTTs to existing open NTT for the same Network Element).
- Support cascading lifecycle resolution (resolving NTT resolves all child CTTs with resolution notes).

### Non-Goals
- TMF Work Order dispatch orchestration (belongs to field dispatch / separate workflow).
- External REST synchronization to real INTT production servers (data is synthetic).
- Replacing `ontology-mcp` Incident (Incident is cross-domain blast-radius event; NTT is NOC infrastructure trouble ticket).

---

## 2. Acceptance Criteria

1. **AC-1 (Root NE Validation & NTT Creation):** Calling `ticket_create_ntt` with valid `network_element_id`, `fault_type`, `severity`, and `summary` creates an NTT in status `IN_PROGRESS` with generated ID (e.g. `NTT-0001`).
2. **AC-2 (Duplicate NE Deduplication):** If an active NTT (`IN_PROGRESS`) already exists for the same `network_element_id`, calling `ticket_create_ntt` does NOT create a duplicate; it returns the existing NTT and links any newly supplied CTT IDs.
3. **AC-3 (CTT Linking):** Calling `ticket_link_ctts` links one or more visible CTT IDs to an existing NTT. Linking updates `ctt_count` and prevents duplicate link rows.
4. **AC-4 (CTT Unlinking):** Calling `ticket_unlink_ctt` removes the link between a CTT and an NTT.
5. **AC-5 (NTT Retrieval & Listing):** `ticket_get_ntt` returns full details including root NE, fault type, severity, status, `ctt_count`, linked CTT IDs, notes, and resolution info. `ticket_list_ntts` supports filtering by `status` and `network_element_id`.
6. **AC-6 (Cascading Resolution):** Calling `ticket_resolve_ntt` moves NTT to status `RESOLVED` and cascades resolution to all linked CTTs (inserting into `ticket_resolution` and `ticket_note`). Already resolved CTTs are safely skipped.
7. **AC-7 (Input Validation):** Invalid `fault_type` (not in `POWER`, `FLOOD`, `FIBER`, `RAN`, `HARDWARE`, `OTHER`) or `severity` (not in `CRITICAL`, `MAJOR`, `MINOR`) raises `InvalidInputError`. Non-existent NTT or CTT raises `NotFoundError`. Resolving already-resolved NTT raises `InvalidInputError`.
8. **AC-8 (Demo Reset Support):** `menara-core` reset clears all NTT rows (`ntt_ctt_link`, `ntt_note`, `ntt`) cleanly without violating foreign key constraints.
9. **AC-9 (MCMC Regulatory Compliance & Auto-Reporting):** If an NTT outage duration is >= 120 minutes with service-impacting severity (`CRITICAL`/`MAJOR`), `ticket_check_mcmc` returns `can_send = True`. Resolving such an NTT auto-flags MCMC Closure Notification, records audit notice, and schedules MCMC Comprehensive Report due within 3 days.

---

## 3. Tool Contract

All tools return `Envelope[T]` with `synthetic: true`.

### 3.1 `ticket_create_ntt`
- **Arguments:**
  - `network_element_id: str` (e.g. `"KKRI-0142"`, 1-60 chars)
  - `fault_type: str` (`"POWER" | "FLOOD" | "FIBER" | "RAN" | "HARDWARE" | "OTHER"`)
  - `severity: str` (`"CRITICAL" | "MAJOR" | "MINOR"`)
  - `summary: str` (5-500 chars)
  - `ctt_ticket_ids: list[str] | None = None` (optional CTTs to link on create)
- **Data Model:** `NttDetail`
- **Errors:** `InvalidInputError`, `NotFoundError` (if any CTT does not exist at current scenario clock).

### 3.2 `ticket_get_ntt`
- **Arguments:**
  - `ntt_id: str` (e.g. `"NTT-0001"`)
- **Data Model:** `NttDetail`
- **Errors:** `NotFoundError`, `InvalidInputError`.

### 3.3 `ticket_list_ntts`
- **Arguments:**
  - `status: str | None = None` (`"IN_PROGRESS" | "RESOLVED" | "CLOSED" | "CANCELLED"`)
  - `network_element_id: str | None = None`
  - `limit: int = 50` (1-200)
- **Data Model:** `NttList` (contains `ntts: list[NttSummary]`, `total: int`, `truncated: bool`)
- **Errors:** `InvalidInputError`.

### 3.4 `ticket_link_ctts`
- **Arguments:**
  - `ntt_id: str`
  - `ctt_ticket_ids: list[str]` (1-200 items)
- **Data Model:** `NttLinkResult` (`ntt_id`, `linked: list[str]`, `already_linked: list[str]`, `ctt_count: int`)
- **Errors:** `NotFoundError`, `InvalidInputError`.

### 3.5 `ticket_unlink_ctt`
- **Arguments:**
  - `ntt_id: str`
  - `ctt_ticket_id: str`
- **Data Model:** `NttUnlinkResult` (`ntt_id`, `unlinked_ticket_id: str`, `ctt_count: int`)
- **Errors:** `NotFoundError`, `InvalidInputError`.

### 3.6 `ticket_resolve_ntt`
- **Arguments:**
  - `ntt_id: str`
  - `resolution_note: str` (1-1000 chars)
  - `resolved_by: str = "agent"`
- **Data Model:** `NttResolution` (`ntt_id`, `status: "RESOLVED"`, `resolved_ctts: list[str]`, `resolution_note: str`, `resolved_by: str`)
- **Errors:** `NotFoundError`, `InvalidInputError`.

---

## 4. Data & Ownership

### Owning Server
**`ticket-mcp`** owns:
- `ticket_note` (existing)
- `ticket_resolution` (existing)
- `ntt` (new)
- `ntt_ctt_link` (new)
- `ntt_note` (new)

### Schema (`packages/menara-core/src/menara_core/seed/schema.py`)
```sql
-- owned by ticket-mcp: Network Trouble Tickets (NTT) for infrastructure elements
CREATE TABLE ntt (
    seq                INTEGER PRIMARY KEY AUTOINCREMENT,
    ntt_id             TEXT UNIQUE,
    created_min        INTEGER NOT NULL,
    created_at         TEXT NOT NULL,
    network_element_id TEXT NOT NULL,
    fault_type         TEXT NOT NULL CHECK (fault_type IN ('POWER', 'FLOOD', 'FIBER', 'RAN', 'HARDWARE', 'OTHER')),
    severity           TEXT NOT NULL CHECK (severity IN ('CRITICAL', 'MAJOR', 'MINOR')),
    status             TEXT NOT NULL CHECK (status IN ('IN_PROGRESS', 'RESOLVED', 'CLOSED', 'CANCELLED')),
    summary            TEXT NOT NULL,
    resolved_min       INTEGER,
    resolved_at        TEXT,
    resolved_by        TEXT,
    resolution_note    TEXT
);

CREATE TABLE ntt_ctt_link (
    ntt_id     TEXT NOT NULL REFERENCES ntt (ntt_id),
    ticket_id  TEXT NOT NULL REFERENCES ticket (ticket_id),
    linked_min INTEGER NOT NULL,
    linked_at  TEXT NOT NULL,
    PRIMARY KEY (ntt_id, ticket_id)
);

CREATE TABLE ntt_note (
    note_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ntt_id    TEXT NOT NULL REFERENCES ntt (ntt_id),
    at        TEXT NOT NULL,
    author    TEXT NOT NULL,
    text      TEXT NOT NULL
);
```

### Reset Integration (`packages/menara-core/src/menara_core/reset.py`)
Add to `RUNTIME_TABLES`:
- `"ntt_ctt_link"`, `"ntt_note"`, `"ntt"` (children first).

---

## 5. Scenario Impact
- No breaking change to `data/scenario/kuala_krai.yaml`.
- During flood incident replay, agent can open `NTT` for `KKRI-0142` (power/flood), link 37 cluster CTTs, and resolve all in one cascade call.

---

## 6. Privacy & Synthetic Guard
- All data synthetic (`synthetic: true`).
- No claims about real TM systems or live customers.
- Customer references remain hashed MSISDNs.

---

## 7. Ports & Registration
- Server: `ticket-mcp`.
- Port: `8102` (HTTP) / stdio default.
- No changes to `.mcp.json` or ports.

---

## 8. Alternatives Considered
- **Putting NTT in `ontology-mcp`:** Rejected because `ontology-mcp` owns graph relationships and blast-radius Incident, while trouble ticketing (both CTT and NTT) cleanly belongs to `ticket-mcp`.
- **Modifying base `ticket` table:** Rejected because `ticket` table is seeded base table; NTT is runtime ticket entity created by agents/NOC.

---

## 9. Rollout
- Re-run `uv run menara-seed` to update database schema.
- Run `uv run python -m pytest servers/ticket-mcp` to verify all tests.
- Run full test suite `uv run python -m pytest`.
