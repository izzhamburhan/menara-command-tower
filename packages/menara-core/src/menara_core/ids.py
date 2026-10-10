"""ID formats shared by every MCP. The shared keys are enodeb_name, site_id and msisdn_hash."""

from __future__ import annotations

import re

from menara_core.errors import InvalidInputError

ENODEB_RE = re.compile(r"^[A-Z]{4}-\d{4}$")
CELL_RE = re.compile(r"^[A-Z]{4}-\d{4}-B\d{1,2}$")
SITE_RE = re.compile(r"^SITE-[A-Z]{4}-\d{4}$")
TICKET_RE = re.compile(r"^TK-\d{5,}$")
MSISDN_HASH_RE = re.compile(r"^[0-9a-f]{16}$")
FEEDER_RE = re.compile(r"^FDR-[A-Z]{4}-\d{2}$")
GAUGE_RE = re.compile(r"^GAUGE-[A-Z]{4}-\d{2}$")
STATION_RE = re.compile(r"^WX-[A-Z]{4}-\d{2}$")
CRITICAL_SITE_RE = re.compile(r"^CS-[A-Z]{4}-\d{2}$")
INCIDENT_RE = re.compile(r"^INC-\d{4,}$")
APPROVAL_RE = re.compile(r"^APR-\d{4,}$")
CHANGE_RE = re.compile(r"^CHG-\d{4,}$")
MISSION_RE = re.compile(r"^MIS-\d{4,}$")
SIMULATION_RE = re.compile(r"^SIM-\d{4,}$")
DRONE_RE = re.compile(r"^DRN-\d{2}$")


def _check(value: str, pattern: re.Pattern[str], label: str, example: str) -> str:
    cleaned = value.strip()
    if not pattern.match(cleaned):
        raise InvalidInputError(f"Invalid {label} {value!r}; expected a value like {example}")
    return cleaned


def parse_enodeb(value: str) -> str:
    return _check(value, ENODEB_RE, "enodeb_name", "KKRI-0142")


def parse_cell_id(value: str) -> str:
    return _check(value, CELL_RE, "cell_id", "KKRI-0142-B1")


def parse_site_id(value: str) -> str:
    return _check(value, SITE_RE, "site_id", "SITE-KKRI-0142")


def parse_ticket_id(value: str) -> str:
    return _check(value, TICKET_RE, "ticket id", "TK-88213")


def parse_msisdn_hash(value: str) -> str:
    return _check(value, MSISDN_HASH_RE, "msisdn_hash", "9f2c4a1be07d3c55")


def parse_feeder_id(value: str) -> str:
    return _check(value, FEEDER_RE, "feeder_id", "FDR-KKRI-01")


def parse_gauge_id(value: str) -> str:
    return _check(value, GAUGE_RE, "gauge_id", "GAUGE-KKRI-01")


def parse_station_id(value: str) -> str:
    return _check(value, STATION_RE, "station_id", "WX-KKRI-01")


def parse_critical_site_id(value: str) -> str:
    return _check(value, CRITICAL_SITE_RE, "critical_site_id", "CS-KKRI-01")


def parse_incident_id(value: str) -> str:
    return _check(value, INCIDENT_RE, "incident_id", "INC-0001")


def parse_approval_id(value: str) -> str:
    return _check(value, APPROVAL_RE, "approval_id", "APR-0001")


def parse_change_id(value: str) -> str:
    return _check(value, CHANGE_RE, "change_id", "CHG-0001")


def parse_mission_id(value: str) -> str:
    return _check(value, MISSION_RE, "mission_id", "MIS-0001")


def parse_simulation_id(value: str) -> str:
    return _check(value, SIMULATION_RE, "simulation_id", "SIM-0001")


def parse_drone_id(value: str) -> str:
    return _check(value, DRONE_RE, "drone_id", "DRN-01")


def target_key(targets: list[str]) -> str:
    """Canonical token target for a multi-target action: sorted, de-duplicated, comma-joined."""
    return ",".join(sorted(set(targets)))


def site_id_for(enodeb_name: str) -> str:
    return f"SITE-{parse_enodeb(enodeb_name)}"


def cell_id_for(enodeb_name: str, band: str) -> str:
    return parse_cell_id(f"{parse_enodeb(enodeb_name)}-{band}")


def enodeb_of_cell(cell_id: str) -> str:
    return parse_cell_id(cell_id).rsplit("-", 1)[0]
