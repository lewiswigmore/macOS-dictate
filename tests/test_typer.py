from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dictate import typer as typer_mod
from dictate.typer import Typer


class _Config:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self.values = values or {}

    def get(self, dotted: str, default: object = None) -> object:
        return self.values.get(dotted, default)


class _FakePasteboard:
    def __init__(self, value: str | None = "original") -> None:
        self.value = value
        self.calls: list[tuple[str, str | None]] = []

    def stringForType_(self, pasteboard_type: str) -> str | None:
        self.calls.append(("stringForType", pasteboard_type))
        return self.value

    def clearContents(self) -> None:
        self.calls.append(("clearContents", None))
        self.value = None

    def setString_forType_(self, value: str, pasteboard_type: str) -> None:
        self.calls.append(("setString", value))
        self.value = value


class _FakeTimer:
    def __init__(self, delay: float, fn) -> None:
        self.delay = delay
        self.fn = fn
        self.daemon = False
        self.started = False

    def start(self) -> None:
        self.started = True

    def fire(self) -> None:
        self.fn()


class _TimerFactory:
    def __init__(self) -> None:
        self.timers: list[_FakeTimer] = []

    def __call__(self, delay: float, fn) -> _FakeTimer:
        timer = _FakeTimer(delay, fn)
        self.timers.append(timer)
        return timer


def _install_pyobjc_stubs(monkeypatch: pytest.MonkeyPatch, pb: _FakePasteboard, sequence=None):
    sequence = sequence if sequence is not None else []
    appkit = SimpleNamespace(
        NSPasteboard=SimpleNamespace(generalPasteboard=lambda: pb),
        NSPasteboardTypeString="public.utf8-plain-text",
    )

    quartz = SimpleNamespace(
        kCGEventSourceStateHIDSystemState="hid",
        kCGEventFlagMaskCommand="cmd",
        kCGHIDEventTap="tap",
        CGEventSourceCreate=MagicMock(return_value="src"),
        CGEventCreateKeyboardEvent=MagicMock(side_effect=lambda src, key, down: (src, key, down)),
        CGEventSetFlags=MagicMock(),
        CGEventPost=MagicMock(side_effect=lambda tap, ev: sequence.append(("post", ev[2]))),
    )
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setitem(sys.modules, "Quartz", quartz)
    return quartz


def _typer() -> Typer:
    return Typer(config=_Config({"typer.paste_wait_ms": 0}))


def test_secure_input_refusal(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    pb = _FakePasteboard("original")
    timer_factory = _TimerFactory()
    _install_pyobjc_stubs(monkeypatch, pb)
    monkeypatch.setattr(typer_mod, "_secure_input_active", lambda: True)
    monkeypatch.setattr(typer_mod.threading, "Timer", timer_factory)
    monkeypatch.setattr(typer_mod.time, "sleep", lambda _: None)

    assert _typer().type_text("hi") is False

    assert pb.value == "original"
    assert timer_factory.timers
    assert "secure input active — refusing to paste" in caplog.text


def test_clipboard_restore_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    pb = _FakePasteboard("original")
    _install_pyobjc_stubs(monkeypatch, pb)
    monkeypatch.setattr(typer_mod, "_secure_input_active", lambda: False)
    monkeypatch.setattr(typer_mod.time, "sleep", lambda _: None)
    monkeypatch.setattr(Typer, "_post_cmd_v", MagicMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(Typer, "type_chars", MagicMock(return_value=False))

    assert _typer().type_text("hi") is False

    assert pb.value == "original"


def test_paste_normal_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    pb = _FakePasteboard("original")
    sequence: list[tuple[str, object]] = []
    timer_factory = _TimerFactory()
    _install_pyobjc_stubs(monkeypatch, pb, sequence=sequence)
    monkeypatch.setattr(typer_mod, "_secure_input_active", lambda: False)
    monkeypatch.setattr(typer_mod.threading, "Timer", timer_factory)
    monkeypatch.setattr(typer_mod.time, "sleep", lambda _: None)

    assert _typer().type_text("hi") is True

    assert pb.calls[1] == ("clearContents", None)
    assert pb.calls[2] == ("setString", "hi")
    assert sequence == [("post", True), ("post", False)]
    assert len(timer_factory.timers) == 1
    assert timer_factory.timers[0].delay == 0.2
    assert timer_factory.timers[0].started is True
    assert pb.value == "hi"
    timer_factory.timers[0].fire()
    assert pb.value == "original"
