from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("run_mcp", ROOT / "scripts" / "run_mcp.py")
assert spec and spec.loader
run_mcp = importlib.util.module_from_spec(spec)
sys.modules["run_mcp"] = run_mcp  # dataclasses look the module up by name
spec.loader.exec_module(run_mcp)


def test_discover_finds_every_server_and_its_port() -> None:
    servers = run_mcp.discover(ROOT)
    assert len(servers) == 18
    assert servers["tower"].port == 8101 and servers["tower"].module == "tower_mcp"
    assert servers["tower"].package == "tower-mcp"
    assert servers["sites"].port == 8112 and servers["usage"].port == 8113 and servers["care"].port == 8115 and servers["enterprise"].port == 8116 and servers["events"].port == 8119 and servers["exposure"].port == 8117
    assert servers["sites"].port == 8112 and servers["usage"].port == 8113 and servers["energy"].port == 8114 and servers["care"].port == 8115 and servers["enterprise"].port == 8116 and servers["events"].port == 8119 and servers["exposure"].port == 8117
    assert len({s.port for s in servers.values()}) == 18  # no two servers share a port


def test_discover_matches_the_servers_registered_in_mcp_json() -> None:
    registered = set(json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"])
    assert set(run_mcp.discover(ROOT)) == registered


def test_build_command_for_http_and_stdio() -> None:
    server = run_mcp.discover(ROOT)["policy"]
    http = run_mcp.build_command(server, http=True, extra=[])
    assert http[-5:] == ["policy_mcp", "--transport", "streamable-http", "--port", "8109"]
    assert http[:5] == ["uv", "run", "--package", "policy-mcp", "python"]
    stdio = run_mcp.build_command(server, http=False, extra=["--db", "x.db"])
    assert stdio[-4:] == ["-m", "policy_mcp", "--db", "x.db"] and "--transport" not in stdio


def test_list_shows_names_and_ports(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mcp.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "tower" in out and "8101" in out and "drone" in out and "8110" in out


def test_print_shows_the_command_without_running_it(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mcp.main(["tower", "--print"]) == 0
    out = capsys.readouterr().out
    assert "tower_mcp" in out and "--port 8101" in out and "http://127.0.0.1:8101/mcp" in out


def test_stdio_flag_drops_the_http_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mcp.main(["tower", "--stdio", "--print"]) == 0
    assert "--port" not in capsys.readouterr().out


def test_all_prints_one_command_per_server(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mcp.main(["all", "--print"]) == 0
    out = capsys.readouterr().out
    assert out.count("--transport streamable-http") == 18


def test_an_unknown_name_is_an_error_that_lists_the_choices(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mcp.main(["nope", "--print"]) == 2
    err = capsys.readouterr().err
    assert "nope" in err and "tower" in err

def test_no_arguments_asks_which_server_and_keeps_the_window_open(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = iter(["tower", ""])  # the server name, then Enter at "press Enter to close"
    prompts: list[str] = []

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return next(answers)

    ran: list[list[str]] = []
    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(run_mcp.subprocess, "run", lambda command, **_: ran.append(command) or SimpleNamespace(returncode=1))
    assert run_mcp.main([]) == 1
    assert ran and "tower_mcp" in ran[0] and "--port" in ran[0]
    assert "8101" in capsys.readouterr().out  # the list was shown
    assert len(prompts) == 2 and "close" in prompts[1].lower()


def test_no_arguments_and_no_terminal_prints_usage(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def no_input(_: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", no_input)
    assert run_mcp.main([]) == 2
    assert "tower" in capsys.readouterr().err