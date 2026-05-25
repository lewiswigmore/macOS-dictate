from __future__ import annotations

import subprocess
from collections.abc import Callable

from dictate import conflicts


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _patch_run(
    monkeypatch, handler: Callable[[list[str]], subprocess.CompletedProcess[str]]
) -> None:
    def fake_run(command, **kwargs):  # noqa: ANN001
        assert kwargs["stdout"] == subprocess.PIPE
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["timeout"] == 2
        assert kwargs["check"] is False
        return handler(list(command))

    monkeypatch.setattr(conflicts.subprocess, "run", fake_run)


def test_macos_dictation_enabled_returns_warning(monkeypatch):
    _patch_run(monkeypatch, lambda _command: _completed("1\n"))

    conflict = conflicts.macos_dictation_enabled()

    assert conflict is not None
    assert conflict.name == "macOS Dictation enabled"
    assert conflict.severity == "warning"
    assert "Keyboard → Dictation" in conflict.suggestion


def test_macos_dictation_disabled_returns_none(monkeypatch):
    _patch_run(monkeypatch, lambda _command: _completed("0\n"))

    assert conflicts.macos_dictation_enabled() is None


def test_voice_control_running_from_pgrep_returns_warning(monkeypatch):
    def handler(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["defaults", "read"]:
            return _completed("", returncode=1)
        if command == ["pgrep", "-x", "VoiceControlAgent"]:
            return _completed("", returncode=1)
        if command == ["pgrep", "-fl", "Voice Control"]:
            return _completed("123 Voice Control\n")
        return _completed("", returncode=1)

    _patch_run(monkeypatch, handler)

    conflict = conflicts.voice_control_running()

    assert conflict is not None
    assert conflict.name == "Voice Control running"
    assert conflict.severity == "warning"


def test_other_dictation_apps_running_returns_one_per_match(monkeypatch):
    def handler(command: list[str]) -> subprocess.CompletedProcess[str]:
        name = command[-1]
        if name in {"Superwhisper", "Aiko"}:
            return _completed("123\n")
        return _completed("", returncode=1)

    _patch_run(monkeypatch, handler)

    found = conflicts.other_dictation_apps_running()

    assert [conflict.name for conflict in found] == ["Superwhisper running", "Aiko running"]
    assert all(conflict.severity == "warning" for conflict in found)


def test_hotkey_interceptors_are_info(monkeypatch):
    def handler(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[-1] == "Keyboard Maestro":
            return _completed("456\n")
        return _completed("", returncode=1)

    _patch_run(monkeypatch, handler)

    conflict = conflicts.hotkey_likely_intercepted()

    assert conflict is not None
    assert conflict.severity == "info"
    assert "Keyboard Maestro" in conflict.detail


def test_check_all_aggregates_conflicts(monkeypatch):
    def handler(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["defaults", "read"] and command[-1] == "Dictation Enabled":
            return _completed("1\n")
        if command == ["pgrep", "-x", "VoiceControlAgent"]:
            return _completed("", returncode=1)
        if command == ["pgrep", "-fl", "Voice Control"]:
            return _completed("", returncode=1)
        if command[-1] == "MacWhisper":
            return _completed("22\n")
        if command[-1] == "BetterTouchTool":
            return _completed("33\n")
        return _completed("", returncode=1)

    _patch_run(monkeypatch, handler)

    found = conflicts.check_all()

    assert [conflict.name for conflict in found] == [
        "macOS Dictation enabled",
        "MacWhisper running",
        "Global hotkey tools running",
    ]


def test_subprocess_timeout_and_missing_binary_are_graceful(monkeypatch):
    def timeout_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="pgrep", timeout=2)

    monkeypatch.setattr(conflicts.subprocess, "run", timeout_run)
    assert conflicts.check_all() == []

    def missing_run(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(conflicts.subprocess, "run", missing_run)
    assert conflicts.check_all() == []
