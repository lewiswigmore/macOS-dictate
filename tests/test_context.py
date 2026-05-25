from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from dictate.config import Config
from dictate.context import ContextProbe


def _make_config(app_map: dict | None = None) -> Config:
    c = Config(root=Path("/nonexistent/dictate-test"))
    c.app_map = app_map or {
        "com.tinyspeck.slackmacgap": "chat",
        "com.apple.Terminal": "code",
        "com.apple.mail": "prose",
    }
    return c


def _mock_appkit_module(
    bundle_id: str = "com.apple.Terminal", name: str = "Terminal", pid: int = 1234
) -> ModuleType:
    mock_app = MagicMock()
    mock_app.bundleIdentifier.return_value = bundle_id
    mock_app.localizedName.return_value = name
    mock_app.processIdentifier.return_value = pid

    mock_ws = MagicMock()
    mock_ws.sharedWorkspace.return_value.frontmostApplication.return_value = mock_app

    mod = MagicMock()
    mod.NSWorkspace = mock_ws
    return mod


class TestPresetFor:
    def test_slack_resolves_to_chat(self) -> None:
        probe = ContextProbe(_make_config())
        assert probe.preset_for({"bundle_id": "com.tinyspeck.slackmacgap"}) == "chat"

    def test_terminal_resolves_to_code(self) -> None:
        probe = ContextProbe(_make_config())
        assert probe.preset_for({"bundle_id": "com.apple.Terminal"}) == "code"

    def test_mail_resolves_to_prose(self) -> None:
        probe = ContextProbe(_make_config())
        assert probe.preset_for({"bundle_id": "com.apple.mail"}) == "prose"

    def test_unknown_resolves_to_default(self) -> None:
        probe = ContextProbe(_make_config())
        assert probe.preset_for({"bundle_id": "com.example.unknown"}) == "default"

    def test_none_bundle_resolves_to_default(self) -> None:
        probe = ContextProbe(_make_config())
        assert probe.preset_for({"bundle_id": None}) == "default"


class TestReadSelection:
    def test_returns_none_when_ax_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Setting a module entry to None causes `from mod import …` to raise ImportError.
        monkeypatch.setitem(sys.modules, "ApplicationServices", None)  # type: ignore[arg-type]
        probe = ContextProbe(_make_config())
        # Also inject a fake AppKit so frontmost() succeeds and yields a real PID
        monkeypatch.setitem(sys.modules, "AppKit", _mock_appkit_module())
        result = probe.read_selection()
        assert result is None

    def test_returns_none_when_ax_copy_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_as = MagicMock()
        mock_as.kAXFocusedUIElementAttribute = "AXFocusedUIElement"
        mock_as.kAXSelectedTextAttribute = "AXSelectedText"
        mock_as.kAXValueAttribute = "AXValue"
        mock_as.AXUIElementCreateApplication.return_value = MagicMock()
        mock_as.AXUIElementCopyAttributeValue.side_effect = OSError("AX permission denied")

        monkeypatch.setitem(sys.modules, "ApplicationServices", mock_as)
        monkeypatch.setitem(sys.modules, "AppKit", _mock_appkit_module())

        probe = ContextProbe(_make_config())
        result = probe.read_selection()
        assert result is None

    def test_returns_none_when_ax_returns_error_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        focused_elem = MagicMock()

        def _copy_attr(elem: object, attr: str, _: object) -> tuple[int, object]:
            if attr == "AXFocusedUIElement":
                return (0, focused_elem)
            return (-25212, None)  # kAXErrorNoValue

        mock_as = MagicMock()
        mock_as.kAXFocusedUIElementAttribute = "AXFocusedUIElement"
        mock_as.kAXSelectedTextAttribute = "AXSelectedText"
        mock_as.kAXValueAttribute = "AXValue"
        mock_as.AXUIElementCreateApplication.return_value = MagicMock()
        mock_as.AXUIElementCopyAttributeValue.side_effect = _copy_attr

        monkeypatch.setitem(sys.modules, "ApplicationServices", mock_as)
        monkeypatch.setitem(sys.modules, "AppKit", _mock_appkit_module())

        probe = ContextProbe(_make_config())
        assert probe.read_selection() is None

    def test_returns_trimmed_selection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        focused_elem = MagicMock()

        def _copy_attr(elem: object, attr: str, _: object) -> tuple[int, object]:
            if attr == "AXFocusedUIElement":
                return (0, focused_elem)
            if attr == "AXSelectedText":
                return (0, "  hello world  ")
            return (-25212, None)

        mock_as = MagicMock()
        mock_as.kAXFocusedUIElementAttribute = "AXFocusedUIElement"
        mock_as.kAXSelectedTextAttribute = "AXSelectedText"
        mock_as.kAXValueAttribute = "AXValue"
        mock_as.AXUIElementCreateApplication.return_value = MagicMock()
        mock_as.AXUIElementCopyAttributeValue.side_effect = _copy_attr

        monkeypatch.setitem(sys.modules, "ApplicationServices", mock_as)
        monkeypatch.setitem(sys.modules, "AppKit", _mock_appkit_module())

        probe = ContextProbe(_make_config())
        assert probe.read_selection() == "hello world"

    def test_respects_max_chars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        focused_elem = MagicMock()
        long_text = "x" * 500

        def _copy_attr(elem: object, attr: str, _: object) -> tuple[int, object]:
            if attr == "AXFocusedUIElement":
                return (0, focused_elem)
            if attr == "AXSelectedText":
                return (0, long_text)
            return (-25212, None)

        mock_as = MagicMock()
        mock_as.kAXFocusedUIElementAttribute = "AXFocusedUIElement"
        mock_as.kAXSelectedTextAttribute = "AXSelectedText"
        mock_as.kAXValueAttribute = "AXValue"
        mock_as.AXUIElementCreateApplication.return_value = MagicMock()
        mock_as.AXUIElementCopyAttributeValue.side_effect = _copy_attr

        monkeypatch.setitem(sys.modules, "ApplicationServices", mock_as)
        monkeypatch.setitem(sys.modules, "AppKit", _mock_appkit_module())

        probe = ContextProbe(_make_config())
        result = probe.read_selection(max_chars=100)
        assert result is not None
        assert len(result) == 100
