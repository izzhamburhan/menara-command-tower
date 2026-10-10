"""Settings from the environment and the repo's .env file (a small parser, so no extra dependency)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "deepseek-chat"
DEFAULT_BASE_URL = "https://api.deepseek.com"


class SettingsError(Exception):
    """A setting is missing or unusable; the message says what to do."""


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL


def load_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_settings(env: Mapping[str, str]) -> Settings:
    key = env.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise SettingsError("DEEPSEEK_API_KEY is not set. Put it in the .env file at the repo root (it is gitignored).")
    return Settings(
        api_key=key,
        model=env.get("DEEPSEEK_MODEL") or DEFAULT_MODEL,
        base_url=env.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL,
    )