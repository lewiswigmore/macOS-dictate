from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DICTATE_STATE_DIR", str(tmp_path))
    return tmp_path


def test_status_when_not_running(state_dir, capsys):
    from dictate import daemon

    assert daemon.cmd_status() == 1
    assert "not running" in capsys.readouterr().out


def test_pid_roundtrip(state_dir):
    from dictate import daemon

    daemon.write_pid()
    assert daemon.read_pid() == os.getpid()
    daemon.clear_pid()
    assert daemon.read_pid() is None


def test_stale_pidfile_is_cleared(state_dir):
    from dictate import daemon

    Path(daemon.pid_file()).write_text("999999999\n")
    assert daemon.read_pid() is None
    assert not daemon.pid_file().exists()


def test_stop_when_not_running(state_dir, capsys):
    from dictate import daemon

    assert daemon.cmd_stop() == 1
    assert "not running" in capsys.readouterr().out


def test_start_refuses_when_already_running(state_dir, capsys, monkeypatch):
    from dictate import daemon

    monkeypatch.setattr(daemon, "read_pid", lambda: os.getpid())
    assert daemon.cmd_start() == 1
    assert "already running" in capsys.readouterr().out
