"""`make serve` runs Kokoro-FastAPI on the host, beside the containers.

Compose starts containers only, and Kokoro-FastAPI runs on the Mac's GPU,
which Docker cannot reach; so serve starts it (``make kokoro``'s command)
where SPEECH_SERVER_DIR (or its default, ~/Kokoro-FastAPI) holds a
checkout, and stop stops it.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

import pytest

from scripts import dev_tasks

KOKORO = ["uv", "run", "aegis-steward", "inference", "kokoro"]


class _Started:
    pid = 4242


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """What serve and stop ran: compose commands under ``ran``, the process
    started under ``started``, the process groups signalled under
    ``killed``. A Kokoro-FastAPI checkout is at ``folder``, unnamed until a
    test names it in ``.env``; the home holds none."""
    seen: dict[str, Any] = {"ran": [], "started": [], "killed": []}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(dev_tasks, "_DOTENV", tmp_path / ".env")
    monkeypatch.delenv("AEGIS_STACK_ENV_FILE", raising=False)
    monkeypatch.setattr(dev_tasks, "resolve_ports", lambda **_: {})
    monkeypatch.setattr(dev_tasks, "_deploy_agent_ready", lambda env: None)
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen["ran"].append(cmd))

    def popen(cmd: list[str], **kw: Any) -> _Started:
        seen["started"].append(cmd)
        return _Started()

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(
        dev_tasks, "_signal_group", lambda pid: seen["killed"].append(pid)
    )
    seen["folder"] = tmp_path / "Kokoro-FastAPI"
    seen["folder"].mkdir()
    return seen


def _named(host: dict[str, Any]) -> None:
    Path(".env").write_text(f"SPEECH_SERVER_DIR={host['folder']}\n")


def test_serve_starts_kokoro_and_stops_it_when_compose_exits(
    host: dict[str, Any],
) -> None:
    _named(host)

    dev_tasks.serve()

    assert host["started"] == [KOKORO]
    assert host["killed"] == [_Started.pid]


def test_serve_in_the_background_leaves_it_to_stop(host: dict[str, Any]) -> None:
    _named(host)

    dev_tasks.serve(detach=True)
    assert host["killed"] == []
    dev_tasks.stop()

    assert host["killed"] == [_Started.pid]
    assert host["ran"][-1][-3:] == ["dev", "down", "--remove-orphans"]


def test_no_checkout_no_kokoro(host: dict[str, Any]) -> None:
    dev_tasks.serve()
    dev_tasks.stop()

    assert host["started"] == []
    assert host["killed"] == []


def test_the_default_checkout_is_found(
    host: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Unnamed, it is looked for where ``make kokoro`` looks."""
    monkeypatch.setenv("HOME", str(tmp_path))

    dev_tasks.serve(detach=True)

    assert host["started"] == [KOKORO]


def test_one_already_up_is_kept(
    host: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second could not bind the port, and its pid would hide the first
    from stop."""
    _named(host)
    dev_tasks.serve(detach=True)
    monkeypatch.setattr(dev_tasks.os, "kill", lambda pid, sig: None)  # alive

    dev_tasks.serve(detach=True)
    dev_tasks.stop()

    assert host["started"] == [KOKORO]
    assert host["killed"] == [_Started.pid]
