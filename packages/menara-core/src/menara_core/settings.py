"""Locate the repo root, the SQLite file, and the dev secrets. Everything has a safe dev default."""

from __future__ import annotations

import os
from pathlib import Path

DEV_PII_SALT = "dev-only-salt"
DEV_SIGNING_KEY = "dev-only-signing-key"
DEV_APPROVER_KEY = "dev-only-approver-key"


def repo_root() -> Path:
    """Nearest ancestor of this file or the cwd that holds data/scenario. Override: MENARA_ROOT."""
    override = os.environ.get("MENARA_ROOT")
    if override:
        return Path(override).resolve()
    for start in (Path(__file__).resolve(), Path.cwd().resolve()):
        for candidate in (start, *start.parents):
            if (candidate / "data" / "scenario").is_dir():
                return candidate
    return Path.cwd().resolve()


def db_path() -> Path:
    override = os.environ.get("MENARA_DB")
    if override:
        return Path(override).resolve()
    return repo_root() / "data" / "menara.db"


def default_scenario_path() -> Path:
    return repo_root() / "data" / "scenario" / "kuala_krai.yaml"


def pii_salt() -> str:
    return os.environ.get("MENARA_PII_SALT", DEV_PII_SALT)


def approver_key() -> str:
    """Credential only a human (the command-center UI) should hold. Gates approve, reject and kill-switch off."""
    return os.environ.get("MENARA_APPROVER_KEY", DEV_APPROVER_KEY)


def signing_key() -> bytes:
    return os.environ.get("MENARA_SIGNING_KEY", DEV_SIGNING_KEY).encode()
