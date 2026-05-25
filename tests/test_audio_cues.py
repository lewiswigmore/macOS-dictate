from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dictate import audio_cues
from dictate.audio_cues import SOUNDS, AudioCues
from dictate.config import Config


@pytest.fixture
def cfg_enabled(tmp_path):
    return Config(root=tmp_path, settings={"ui": {"audio_cues": True}})


@pytest.fixture
def cfg_disabled(tmp_path):
    return Config(root=tmp_path, settings={"ui": {"audio_cues": False}})


def test_catalog_has_start_end_cancel():
    assert {"start", "end", "cancel"} <= SOUNDS.keys()
    for v in SOUNDS.values():
        assert isinstance(v, str) and v


def test_disabled_when_setting_false(cfg_disabled):
    c = AudioCues(cfg_disabled)
    assert c.enabled is False
    assert c.play("start") is False


def test_default_enabled_when_setting_missing(tmp_path):
    cfg = Config(root=tmp_path, settings={})
    c = AudioCues(cfg)
    assert c.enabled is True


def test_play_returns_false_without_appkit(cfg_enabled):
    with patch.object(audio_cues, "_AVAILABLE", False):
        c = AudioCues(cfg_enabled)
        assert c.play("start") is False
        assert c.play("end") is False
        assert c.play("unknown_key") is False


def test_play_invokes_nssound(cfg_enabled):
    fake = MagicMock()
    fake.play.return_value = True
    with patch.object(audio_cues, "_AVAILABLE", True):
        c = AudioCues(cfg_enabled)
        c._sounds = {"start": fake, "end": fake, "cancel": fake}
        assert c.play("start") is True
        fake.stop.assert_called_once()  # rewind before re-fire
        fake.play.assert_called_once()


def test_play_unknown_key_is_silent_noop(cfg_enabled):
    with patch.object(audio_cues, "_AVAILABLE", True):
        c = AudioCues(cfg_enabled)
        c._sounds = {}  # nothing loaded
        assert c.play("start") is False  # no exception, just False


def test_play_swallows_exceptions(cfg_enabled):
    bad = MagicMock()
    bad.play.side_effect = RuntimeError("driver")
    with patch.object(audio_cues, "_AVAILABLE", True):
        c = AudioCues(cfg_enabled)
        c._sounds = {"start": bad}
        assert c.play("start") is False


def test_set_enabled_round_trip(cfg_enabled):
    with patch.object(audio_cues, "_AVAILABLE", True):
        c = AudioCues(cfg_enabled)
        c.set_enabled(False)
        assert c.enabled is False
        assert c.play("start") is False
        c.set_enabled(True)
        assert c.enabled is True


def test_set_enabled_preloads_when_re_enabled(cfg_disabled):
    """Toggling on after starting disabled should still load sounds."""
    with (
        patch.object(audio_cues, "_AVAILABLE", True),
        patch.object(AudioCues, "_preload") as preload,
    ):
        c = AudioCues(cfg_disabled)  # disabled → no initial preload
        preload.assert_not_called()
        c.set_enabled(True)
        preload.assert_called_once()
