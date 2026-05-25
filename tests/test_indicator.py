from __future__ import annotations

from unittest.mock import patch

import pytest

from dictate import indicator as ind_mod
from dictate.config import Config
from dictate.indicator import _COLORS, Indicator


@pytest.fixture
def cfg_on(tmp_path):
    return Config(root=tmp_path, settings={"ui": {"indicator": True}})


@pytest.fixture
def cfg_off(tmp_path):
    return Config(root=tmp_path, settings={"ui": {"indicator": False}})


def test_color_map_has_three_states():
    assert {"activated", "deactivated", "cancelled"} <= _COLORS.keys()
    for rgb in _COLORS.values():
        assert len(rgb) == 3
        for c in rgb:
            assert 0.0 <= c <= 1.0


def test_default_enabled_when_setting_missing(tmp_path):
    cfg = Config(root=tmp_path, settings={})
    assert Indicator(cfg).enabled is True


def test_disabled_when_setting_false(cfg_off):
    assert Indicator(cfg_off).enabled is False


def test_flash_noop_when_disabled(cfg_off):
    with patch("dictate.indicator._on_main") as on_main:
        Indicator(cfg_off).flash("activated")
        on_main.assert_not_called()


def test_flash_noop_when_appkit_missing(cfg_on):
    with patch.object(ind_mod, "_AVAILABLE", False), patch("dictate.indicator._on_main") as on_main:
        Indicator(cfg_on).flash("activated")
        on_main.assert_not_called()


def test_flash_unknown_state_does_not_call_panel(cfg_on):
    """Unknown state -> _flash_impl bails before touching panel APIs."""
    with patch.object(ind_mod, "_AVAILABLE", True):
        i = Indicator(cfg_on)
        # Call _flash_impl directly so we bypass main-thread marshalling.
        i._flash_impl("ghost-state")
        assert i._panel is None


def test_set_enabled_round_trip(cfg_on):
    i = Indicator(cfg_on)
    i.set_enabled(False)
    assert i.enabled is False
    i.set_enabled(True)
    assert i.enabled is True


def test_flash_when_enabled_calls_main_thread(cfg_on):
    """When enabled and AppKit available, the work is dispatched via _on_main."""
    with patch.object(ind_mod, "_AVAILABLE", True), patch("dictate.indicator._on_main") as on_main:
        Indicator(cfg_on).flash("activated")
        on_main.assert_called_once()
