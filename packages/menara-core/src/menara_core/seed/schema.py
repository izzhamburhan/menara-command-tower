"""DDL for menara.db. The comment above each table names the MCP that owns writes to it.

Base tables are written once by the seed and are read-only for every MCP.
"""

from __future__ import annotations

SCHEMA = """
-- base (seed only)
CREATE TABLE seed_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- scenario clock (written by `menara-scenario` only)
CREATE TABLE scenario_state (id INTEGER PRIMARY KEY CHECK (id = 1), now_min INTEGER NOT NULL);

-- base (seed only): tower domain, served by tower-mcp
CREATE TABLE tower (
    enodeb_name TEXT PRIMARY KEY,
    site_id     TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    town        TEXT NOT NULL,
    state       TEXT NOT NULL,
    lat         REAL NOT NULL,
    lng         REAL NOT NULL,
    tower_type  TEXT NOT NULL,
    vendor      TEXT NOT NULL,
    firmware    TEXT NOT NULL
);
CREATE INDEX idx_tower_geo ON tower (lat, lng);

CREATE TABLE cell (
    cell_id     TEXT PRIMARY KEY,
    enodeb_name TEXT NOT NULL REFERENCES tower (enodeb_name),
    band        TEXT NOT NULL,
    azimuth_deg INTEGER NOT NULL,
    tilt_deg    REAL NOT NULL
);
CREATE INDEX idx_cell_tower ON cell (enodeb_name);

CREATE TABLE tower_neighbour (
    enodeb_name   TEXT NOT NULL REFERENCES tower (enodeb_name),
    neighbour_name TEXT NOT NULL REFERENCES tower (enodeb_name),
    distance_km   REAL NOT NULL,
    PRIMARY KEY (enodeb_name, neighbour_name)
);

CREATE TABLE tower_state (
    enodeb_name TEXT NOT NULL REFERENCES tower (enodeb_name),
    t_min       INTEGER NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('UP', 'DEGRADED', 'DOWN')),
    battery_pct INTEGER NOT NULL,
    mains_ok    INTEGER NOT NULL,
    PRIMARY KEY (enodeb_name, t_min)
);

CREATE TABLE tower_kpi (
    enodeb_name     TEXT NOT NULL REFERENCES tower (enodeb_name),
    t_min           INTEGER NOT NULL,
    prb_util        REAL NOT NULL,
    drop_rate       REAL NOT NULL,
    throughput_mbps REAL NOT NULL,
    PRIMARY KEY (enodeb_name, t_min)
);

CREATE TABLE tower_alarm (
    alarm_id    TEXT PRIMARY KEY,
    enodeb_name TEXT NOT NULL REFERENCES tower (enodeb_name),
    code        TEXT NOT NULL,
    severity    TEXT NOT NULL CHECK (severity IN ('CRITICAL', 'MAJOR', 'MINOR', 'WARNING')),
    message     TEXT NOT NULL,
    raised_min  INTEGER NOT NULL,
    cleared_min INTEGER
);
CREATE INDEX idx_alarm_tower ON tower_alarm (enodeb_name);

-- base (seed only): user domain, served by user-mcp. Only hashed MSISDNs are stored.
CREATE TABLE subscriber (
    msisdn_hash  TEXT PRIMARY KEY,
    serving_cell TEXT NOT NULL REFERENCES cell (cell_id),
    enodeb_name  TEXT NOT NULL REFERENCES tower (enodeb_name),
    cell_lat     REAL NOT NULL,
    cell_lng     REAL NOT NULL,
    plan         TEXT NOT NULL,
    segment      TEXT NOT NULL,
    home_fibre   INTEGER NOT NULL
);
CREATE INDEX idx_subscriber_cell ON subscriber (serving_cell);

CREATE TABLE subscriber_state (
    msisdn_hash TEXT NOT NULL REFERENCES subscriber (msisdn_hash),
    t_min       INTEGER NOT NULL,
    attached    INTEGER NOT NULL,
    PRIMARY KEY (msisdn_hash, t_min)
);

CREATE TABLE subscriber_experience (
    msisdn_hash     TEXT NOT NULL REFERENCES subscriber (msisdn_hash),
    t_min           INTEGER NOT NULL,
    score           REAL NOT NULL,
    throughput_mbps REAL NOT NULL,
    drop_events     INTEGER NOT NULL,
    rsrp_dbm        INTEGER NOT NULL,
    PRIMARY KEY (msisdn_hash, t_min)
);

-- base (seed only): user domain, served by user-mcp. Where a subscriber was over time, at cell level.
-- One row each time the subscriber changes cell; a visit lasts until the next row's start_min.
CREATE TABLE subscriber_cell_visit (
    msisdn_hash  TEXT NOT NULL REFERENCES subscriber (msisdn_hash),
    start_min    INTEGER NOT NULL,
    serving_cell TEXT NOT NULL REFERENCES cell (cell_id),
    enodeb_name  TEXT NOT NULL REFERENCES tower (enodeb_name),
    cell_lat     REAL NOT NULL,
    cell_lng     REAL NOT NULL,
    PRIMARY KEY (msisdn_hash, start_min)
);
CREATE INDEX idx_visit_geo ON subscriber_cell_visit (cell_lat, cell_lng);

-- base (seed only): ticket domain, served by ticket-mcp
CREATE TABLE ticket (
    ticket_id     TEXT PRIMARY KEY,
    created_min   INTEGER NOT NULL,
    service       TEXT NOT NULL,
    category      TEXT NOT NULL,
    status        TEXT NOT NULL,
    location_text TEXT NOT NULL,
    lat           REAL,
    lng           REAL,
    customer_ref  TEXT NOT NULL,
    summary       TEXT NOT NULL,
    language      TEXT NOT NULL
);
CREATE INDEX idx_ticket_time ON ticket (created_min);

-- owned by ticket-mcp: resolutions (the base ticket status is overlaid once resolved)
CREATE TABLE ticket_resolution (
    ticket_id    TEXT PRIMARY KEY REFERENCES ticket (ticket_id),
    resolved_min INTEGER NOT NULL,
    resolved_at  TEXT NOT NULL,
    resolved_by  TEXT NOT NULL,
    note         TEXT NOT NULL
);

-- owned by ticket-mcp: notes added by agents or engineers
CREATE TABLE ticket_note (
    note_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id TEXT NOT NULL REFERENCES ticket (ticket_id),
    at        TEXT NOT NULL,
    author    TEXT NOT NULL,
    text      TEXT NOT NULL
);

-- base (seed only): weather domain, served by weather-mcp
CREATE TABLE weather_station (
    station_id TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    town       TEXT NOT NULL,
    state      TEXT NOT NULL,
    lat        REAL NOT NULL,
    lng        REAL NOT NULL
);
CREATE INDEX idx_weather_geo ON weather_station (lat, lng);

CREATE TABLE weather_obs (
    station_id TEXT NOT NULL REFERENCES weather_station (station_id),
    t_min      INTEGER NOT NULL,
    rain_mm    REAL NOT NULL,
    lightning  INTEGER NOT NULL,
    wind_kmh   REAL NOT NULL,
    PRIMARY KEY (station_id, t_min)
);

-- base (seed only): grid domain, served by grid-mcp
CREATE TABLE grid_feeder (
    feeder_id TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    state     TEXT NOT NULL,
    customers INTEGER NOT NULL
);

CREATE TABLE grid_feeder_tower (
    enodeb_name TEXT PRIMARY KEY REFERENCES tower (enodeb_name),
    feeder_id   TEXT NOT NULL REFERENCES grid_feeder (feeder_id)
);
CREATE INDEX idx_feeder_tower ON grid_feeder_tower (feeder_id);

CREATE TABLE grid_feeder_state (
    feeder_id           TEXT NOT NULL REFERENCES grid_feeder (feeder_id),
    t_min               INTEGER NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('ENERGISED', 'AT_RISK', 'TRIPPED')),
    note                TEXT NOT NULL,
    restoration_eta_min INTEGER,
    PRIMARY KEY (feeder_id, t_min)
);

-- base (seed only): flood domain, served by flood-mcp
CREATE TABLE flood_gauge (
    gauge_id  TEXT PRIMARY KEY,
    river     TEXT NOT NULL,
    station   TEXT NOT NULL,
    state     TEXT NOT NULL,
    lat       REAL NOT NULL,
    lng       REAL NOT NULL,
    warning_m REAL NOT NULL,
    danger_m  REAL NOT NULL
);
CREATE INDEX idx_gauge_geo ON flood_gauge (lat, lng);

CREATE TABLE flood_reading (
    gauge_id TEXT NOT NULL REFERENCES flood_gauge (gauge_id),
    t_min    INTEGER NOT NULL,
    level_m  REAL NOT NULL,
    PRIMARY KEY (gauge_id, t_min)
);

CREATE TABLE flood_extent (
    extent_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    from_min    INTEGER NOT NULL,
    lat         REAL NOT NULL,
    lng         REAL NOT NULL,
    radius_km   REAL NOT NULL,
    max_depth_m REAL NOT NULL
);

-- base (seed only): critical sites, served by sites-mcp
CREATE TABLE critical_site (
    critical_site_id  TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    kind              TEXT NOT NULL CHECK (kind IN ('HOSPITAL', 'CLINIC', 'POLICE', 'FIRE', 'SCHOOL', 'ENTERPRISE', 'MALL')),
    state             TEXT NOT NULL,
    lat               REAL NOT NULL,
    lng               REAL NOT NULL,
    priority          INTEGER NOT NULL,
    emergency_service INTEGER NOT NULL,
    serving_enodeb    TEXT NOT NULL REFERENCES tower (enodeb_name)
);
CREATE INDEX idx_critical_geo ON critical_site (lat, lng);
CREATE INDEX idx_critical_tower ON critical_site (serving_enodeb);

-- base (seed only): estimated attached subscribers per tower, read by ontology-mcp for blast radius
CREATE TABLE tower_subscribers (
    enodeb_name    TEXT PRIMARY KEY REFERENCES tower (enodeb_name),
    subscribers_est INTEGER NOT NULL
);

-- owned by ontology-mcp: the Incident object the agent creates, and its ticket links
CREATE TABLE incident (
    seq              INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id      TEXT UNIQUE,
    enodeb_name      TEXT NOT NULL REFERENCES tower (enodeb_name),
    cause            TEXT NOT NULL CHECK (cause IN ('FLOOD', 'POWER', 'TRANSPORT', 'HARDWARE', 'CONFIG', 'UNKNOWN')),
    cause_confidence REAL NOT NULL,
    summary          TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('OPEN', 'MITIGATING', 'RESOLVED')),
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    evidence         TEXT NOT NULL,
    notes            TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE incident_ticket (
    incident_id TEXT NOT NULL REFERENCES incident (incident_id),
    ticket_id   TEXT NOT NULL REFERENCES ticket (ticket_id),
    PRIMARY KEY (incident_id, ticket_id)
);

-- owned by twin-mcp: every simulation run, so decisions can cite it
CREATE TABLE twin_simulation (
    seq     INTEGER PRIMARY KEY AUTOINCREMENT,
    sim_id  TEXT UNIQUE,
    kind    TEXT NOT NULL,
    at      TEXT NOT NULL,
    params  TEXT NOT NULL,
    result  TEXT NOT NULL
);

-- base (seed only): scripted RAN outcomes, read by ran-mcp
CREATE TABLE ran_script (
    action      TEXT NOT NULL,
    enodeb_name TEXT NOT NULL REFERENCES tower (enodeb_name),
    attempt     INTEGER NOT NULL,
    efficacy    REAL NOT NULL,
    PRIMARY KEY (action, enodeb_name, attempt)
);

-- owned by ran-mcp: sandboxed configuration changes, their per-tower items, and the KPI effect they cause
CREATE TABLE ran_change (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    change_id    TEXT UNIQUE,
    action       TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('ACTIVE', 'REVERTED', 'COMPLETED')),
    applied_min  INTEGER NOT NULL,
    applied_at   TEXT NOT NULL,
    reverted_min INTEGER,
    reverted_at  TEXT,
    approved_by  TEXT NOT NULL,
    reason       TEXT NOT NULL
);

CREATE TABLE ran_change_item (
    change_id      TEXT NOT NULL REFERENCES ran_change (change_id),
    enodeb_name    TEXT NOT NULL REFERENCES tower (enodeb_name),
    cell_id        TEXT NOT NULL,
    tilt_delta_deg REAL NOT NULL,
    efficacy       REAL NOT NULL,
    attempt        INTEGER NOT NULL,
    PRIMARY KEY (change_id, cell_id)
);

CREATE TABLE ran_kpi_effect (
    change_id   TEXT NOT NULL REFERENCES ran_change (change_id),
    enodeb_name TEXT NOT NULL REFERENCES tower (enodeb_name),
    from_min    INTEGER NOT NULL,
    prb_factor  REAL NOT NULL,
    drop_factor REAL NOT NULL,
    thr_factor  REAL NOT NULL,
    PRIMARY KEY (change_id, enodeb_name)
);

-- base (seed only): drones and the canned inspection findings, read by drone-mcp
CREATE TABLE drone (
    drone_id   TEXT PRIMARY KEY,
    depot_id   TEXT NOT NULL,
    depot_name TEXT NOT NULL,
    lat        REAL NOT NULL,
    lng        REAL NOT NULL
);

CREATE TABLE drone_finding (
    enodeb_name TEXT PRIMARY KEY REFERENCES tower (enodeb_name),
    finding     TEXT NOT NULL
);

-- owned by drone-mcp: missions (status is derived from the scenario clock)
CREATE TABLE drone_mission (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id     TEXT UNIQUE,
    drone_id       TEXT NOT NULL REFERENCES drone (drone_id),
    enodeb_name    TEXT NOT NULL REFERENCES tower (enodeb_name),
    dispatched_min INTEGER NOT NULL,
    dispatched_at  TEXT NOT NULL,
    distance_km    REAL NOT NULL,
    eta_min        INTEGER NOT NULL,
    inspect_min    INTEGER NOT NULL,
    approved_by    TEXT NOT NULL,
    reason         TEXT NOT NULL
);

-- owned by policy-mcp: thresholds, the kill switch, approvals
CREATE TABLE policy_setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE approval (
    seq                  INTEGER PRIMARY KEY AUTOINCREMENT,
    approval_id          TEXT UNIQUE,
    action               TEXT NOT NULL,
    target               TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (status IN ('PENDING', 'AUTO_ALLOWED', 'APPROVED', 'REJECTED')),
    confidence           REAL NOT NULL,
    affected_subscribers INTEGER NOT NULL,
    touches_emergency    INTEGER NOT NULL,
    reason               TEXT NOT NULL,
    requested_min        INTEGER NOT NULL,
    requested_at         TEXT NOT NULL,
    decided_by           TEXT,
    decided_min          INTEGER,
    decided_at           TEXT,
    outcome              TEXT,
    outcome_detail       TEXT
);

-- owned by policy-mcp: approvals and the audit trail
CREATE TABLE audit_log (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at     TEXT NOT NULL,
    actor  TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    decision TEXT NOT NULL,
    detail TEXT NOT NULL
);

-- base (seed only): synthetic app usage, served by usage-mcp. Invented numbers; no per-person data.
CREATE TABLE app (
    app_id   TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    category TEXT NOT NULL
);

CREATE TABLE app_hour_factor (
    app_id TEXT NOT NULL REFERENCES app (app_id),
    hour   INTEGER NOT NULL CHECK (hour BETWEEN 0 AND 23),
    factor REAL NOT NULL,
    PRIMARY KEY (app_id, hour)
);

-- user_share: the share of the tower's users who use the app in a day. data_share: the app's share of the tower's data.
CREATE TABLE tower_app_share (
    enodeb_name TEXT NOT NULL REFERENCES tower (enodeb_name),
    app_id      TEXT NOT NULL REFERENCES app (app_id),
    user_share  REAL NOT NULL,
    data_share  REAL NOT NULL,
    PRIMARY KEY (enodeb_name, app_id)
);
"""