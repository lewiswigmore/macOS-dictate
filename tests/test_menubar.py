from __future__ import annotations

import sys
import types
from unittest.mock import Mock

sys.modules.setdefault("rumps", types.ModuleType("rumps"))

from dictate.menubar import MenuBar


def test_restart_menu_item_invokes_restart_callback() -> None:
    callback = Mock()
    menubar = object.__new__(MenuBar)
    menubar._callbacks = {"on_restart": callback}

    menubar._on_restart(None)

    callback.assert_called_once_with()


def test_microphone_menu_item_invokes_selection_callback() -> None:
    callback = Mock()
    menubar = object.__new__(MenuBar)
    menubar._callbacks = {"on_input_device_select": callback}

    menubar._on_input_device_select(90)

    callback.assert_called_once_with(90)
