from __future__ import annotations

import logging
from unittest.mock import Mock

from dictate.url_scheme import AppController, dispatch


def test_dispatch_record_calls_start_recording():
    controller = Mock(spec=AppController)

    assert dispatch("dictate://record", controller) is True

    controller.start_recording.assert_called_once_with()


def test_dispatch_unknown_returns_false():
    controller = Mock(spec=AppController)

    assert dispatch("dictate://nonsense", controller) is False

    controller.start_recording.assert_not_called()
    controller.stop_recording.assert_not_called()
    controller.toggle_recording.assert_not_called()
    controller.open_webui.assert_not_called()


def test_dispatch_wrong_scheme_returns_false():
    controller = Mock(spec=AppController)

    assert dispatch("https://record", controller) is False


def test_dispatch_history_with_id_passes_id():
    controller = Mock(spec=AppController)

    assert dispatch("dictate://history/abc123", controller) is True

    controller.open_webui.assert_called_once_with(entry_id="abc123")


def test_dispatch_logs_action(caplog):
    controller = Mock(spec=AppController)

    with caplog.at_level(logging.INFO):
        dispatch("dictate://record", controller)

    assert "url scheme: dictate://record -> start_recording" in caplog.text
