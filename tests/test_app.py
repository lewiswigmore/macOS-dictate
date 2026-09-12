from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock


def test_input_device_selection_persists_and_refreshes_menu(monkeypatch) -> None:
    import dictate.app as app_module

    app = object.__new__(app_module.App)
    app.recorder = SimpleNamespace(is_running=False)
    app.config = SimpleNamespace(persist_pref=Mock())
    app.menubar = SimpleNamespace(refresh_input_devices=Mock())
    monkeypatch.setattr(app_module, "select_input_device", Mock(return_value=True), raising=False)

    assert app._on_input_device_select(90) is True
    app_module.select_input_device.assert_called_once_with(90)
    app.config.persist_pref.assert_called_once_with("audio.input_device_id", 90)
    app.menubar.refresh_input_devices.assert_called_once_with()


def test_configured_microphone_is_restored_at_startup(monkeypatch) -> None:
    import dictate.app as app_module

    app = object.__new__(app_module.App)
    app.config = SimpleNamespace(get=Mock(return_value=90))
    monkeypatch.setattr(app_module, "select_input_device", Mock(return_value=True))

    app._apply_configured_input_device()

    app_module.select_input_device.assert_called_once_with(90)


def test_input_device_selection_continues_when_preference_write_fails(monkeypatch) -> None:
    import dictate.app as app_module

    app = object.__new__(app_module.App)
    app.recorder = SimpleNamespace(is_running=False)
    app.config = SimpleNamespace(persist_pref=Mock(side_effect=OSError("read-only")))
    app.menubar = SimpleNamespace(refresh_input_devices=Mock(), set_warning=Mock())
    monkeypatch.setattr(app_module, "select_input_device", Mock(return_value=True))

    assert app._on_input_device_select(90) is True
    app.menubar.refresh_input_devices.assert_called_once_with()
    app.menubar.set_warning.assert_called_once_with("Microphone preference was not saved")


def test_restart_reexecs_when_launch_agent_is_not_installed(monkeypatch) -> None:
    import dictate.app as app_module

    app = object.__new__(app_module.App)
    monkeypatch.setattr(app_module, "launch_agent_installed", Mock(return_value=False))
    execv = Mock()
    monkeypatch.setattr(app_module.os, "execv", execv)

    app._on_restart()

    execv.assert_called_once_with(app_module.sys.executable, [app_module.sys.executable, *app_module.sys.argv])
