from __future__ import annotations

import plistlib
from unittest.mock import patch

import pytest

from dictate import launch_agent
from dictate.config import Config


@pytest.fixture
def cfg(tmp_path):
    (tmp_path / "run.sh").write_text("#!/usr/bin/env bash\n")
    return Config(root=tmp_path, settings={"logging": {"file": str(tmp_path / "logs/d.log")}})


@pytest.fixture
def fake_plist(tmp_path, monkeypatch):
    p = tmp_path / "LaunchAgents" / "com.dictate.app.plist"
    monkeypatch.setattr(launch_agent, "PLIST_PATH", p)
    return p


def test_is_installed_reflects_plist_presence(fake_plist):
    assert launch_agent.is_installed() is False
    fake_plist.parent.mkdir(parents=True, exist_ok=True)
    fake_plist.write_bytes(b"")
    assert launch_agent.is_installed() is True


def test_install_writes_correct_plist(cfg, fake_plist):
    with (
        patch("dictate.launch_agent.subprocess.run") as run_mock,
        patch("dictate.launch_agent.subprocess.check_output", return_value="501\n"),
    ):
        path = launch_agent.install(cfg)
    assert path == fake_plist
    assert fake_plist.exists()
    with fake_plist.open("rb") as f:
        data = plistlib.load(f)
    assert data["Label"] == "com.dictate.app"
    assert data["RunAtLoad"] is True
    assert data["KeepAlive"] is True
    assert data["ProcessType"] == "Interactive"
    assert data["ProgramArguments"][:2] == ["/bin/bash", "-lc"]
    assert data["ProgramArguments"][2].endswith("run.sh")
    assert "stdout" in data["StandardOutPath"]
    assert "stderr" in data["StandardErrorPath"]
    # Two launchctl invocations: bootout (cleanup) then bootstrap.
    cmds = [c.args[0] for c in run_mock.call_args_list]
    assert ["launchctl", "bootout", "gui/501", str(fake_plist)] in cmds
    assert ["launchctl", "bootstrap", "gui/501", str(fake_plist)] in cmds


def test_uninstall_when_not_installed_returns_false(fake_plist):
    assert launch_agent.uninstall() is False


def test_uninstall_removes_plist(fake_plist):
    fake_plist.parent.mkdir(parents=True, exist_ok=True)
    fake_plist.write_bytes(b"\x00")
    with (
        patch("dictate.launch_agent.subprocess.run"),
        patch("dictate.launch_agent.subprocess.check_output", return_value="501\n"),
    ):
        assert launch_agent.uninstall() is True
    assert not fake_plist.exists()


def test_install_replaces_existing_plist(cfg, fake_plist):
    fake_plist.parent.mkdir(parents=True, exist_ok=True)
    fake_plist.write_bytes(b"old")
    with (
        patch("dictate.launch_agent.subprocess.run"),
        patch("dictate.launch_agent.subprocess.check_output", return_value="501\n"),
    ):
        launch_agent.install(cfg)
    # File is now a valid plist, not the old bytes.
    with fake_plist.open("rb") as f:
        data = plistlib.load(f)
    assert data["Label"] == "com.dictate.app"
