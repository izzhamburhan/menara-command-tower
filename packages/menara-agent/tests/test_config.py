from __future__ import annotations

from pathlib import Path

import pytest
from menara_agent.config import SettingsError, load_dotenv, load_settings


def test_missing_key_gives_a_clear_error() -> None:
    with pytest.raises(SettingsError, match=r"DEEPSEEK_API_KEY.*\.env"):
        load_settings({})
    with pytest.raises(SettingsError, match="DEEPSEEK_API_KEY"):
        load_settings({"DEEPSEEK_API_KEY": "   "})


def test_defaults_for_model_and_base_url() -> None:
    settings = load_settings({"DEEPSEEK_API_KEY": "sk-test"})
    assert settings.api_key == "sk-test"
    assert settings.model == "deepseek-chat" and settings.base_url == "https://api.deepseek.com"


def test_overrides_come_from_the_environment() -> None:
    settings = load_settings(
        {"DEEPSEEK_API_KEY": "k", "DEEPSEEK_MODEL": "deepseek-reasoner", "DEEPSEEK_BASE_URL": "http://localhost:9"}
    )
    assert settings.model == "deepseek-reasoner" and settings.base_url == "http://localhost:9"


def test_dotenv_parser_handles_comments_quotes_and_blank_lines(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n\nDEEPSEEK_API_KEY=sk-abc\nQUOTED=\"with space\"\nSINGLE='x'\nEMPTY=\nnot a pair\n  SPACED = v \n",
        encoding="utf-8",
    )
    assert load_dotenv(env) == {
        "DEEPSEEK_API_KEY": "sk-abc",
        "QUOTED": "with space",
        "SINGLE": "x",
        "EMPTY": "",
        "SPACED": "v",
    }


def test_a_missing_dotenv_is_just_empty(tmp_path: Path) -> None:
    assert load_dotenv(tmp_path / ".env") == {}