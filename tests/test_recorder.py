from __future__ import annotations

import numpy as np

from dictate.recorder import _resample


def test_lists_available_microphones_with_default_marker(monkeypatch):
    import dictate.recorder as recorder

    class Device:
        def __init__(self, device_id: int, name: str) -> None:
            self._device_id = device_id
            self._name = name

        def connectionID(self) -> int:
            return self._device_id

        def localizedName(self) -> str:
            return self._name

    devices = [Device(90, "Brio 500"), Device(94, "SteelSeries Arctis 1 Wireless")]
    monkeypatch.setattr(recorder, "_AVFOUNDATION_AVAILABLE", True)
    monkeypatch.setattr(
        recorder,
        "AVCaptureDevice",
        type("CaptureDevices", (), {"devicesWithMediaType_": staticmethod(lambda _media: devices)}),
        raising=False,
    )
    monkeypatch.setattr(recorder, "AVMediaTypeAudio", "audio", raising=False)
    monkeypatch.setattr(recorder, "_default_input_device_id", lambda: 94, raising=False)

    microphones = recorder.list_input_devices()

    assert [(mic.id, mic.name, mic.is_default) for mic in microphones] == [
        (90, "Brio 500", False),
        (94, "SteelSeries Arctis 1 Wireless", True),
    ]


def test_select_input_device_sets_system_default(monkeypatch):
    import struct

    import dictate.recorder as recorder

    calls = []

    def set_property(object_id, address, qualifier_size, qualifier_data, data_size, data):
        calls.append((object_id, address, qualifier_size, qualifier_data, data_size, data))
        return 0

    monkeypatch.setattr(recorder, "AudioObjectSetPropertyData", set_property, raising=False)

    assert recorder.select_input_device(90) is True
    assert calls[0][4] == 4
    assert struct.unpack("I", calls[0][5])[0] == 90


def test_select_input_device_returns_false_without_audio_framework(monkeypatch):
    from unittest.mock import Mock

    import dictate.recorder as recorder

    set_property = Mock()
    monkeypatch.setattr(recorder, "_AVFOUNDATION_AVAILABLE", False)
    monkeypatch.setattr(recorder, "AudioObjectSetPropertyData", set_property, raising=False)

    assert recorder.select_input_device(90) is False
    set_property.assert_not_called()


def test_resample_passthrough_when_rates_equal():
    data = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    out = _resample(data, 16000.0, 16000.0)
    assert out is data  # no-copy fast path


def test_resample_downsamples_length():
    data = np.linspace(-1.0, 1.0, 48000, dtype=np.float32)
    out = _resample(data, 48000.0, 16000.0)
    # 48k → 16k = 1/3 the samples (rounded)
    assert abs(len(out) - 16000) <= 1
    assert out.dtype == np.float32


def test_resample_upsamples_length():
    data = np.zeros(8000, dtype=np.float32)
    out = _resample(data, 8000.0, 16000.0)
    assert abs(len(out) - 16000) <= 1


def test_resample_preserves_signal_shape_roughly():
    # A ramp should remain monotonic after resampling.
    data = np.linspace(0.0, 1.0, 44100, dtype=np.float32)
    out = _resample(data, 44100.0, 16000.0)
    assert np.all(np.diff(out) >= -1e-6)
    assert out[0] == 0.0
    assert abs(out[-1] - 1.0) < 1e-3


def test_wake_notification_resets_engine(monkeypatch):
    from dictate.recorder import MicRecorder

    recorder = MicRecorder()
    calls = []

    def reset() -> None:
        calls.append("wake")

    monkeypatch.setattr(recorder, "_reset_engine_after_wake", reset)
    recorder._handle_wake_notification(None)
    assert calls == ["wake"]


def test_audio_route_change_notification_rebuilds_engine(monkeypatch):
    from dictate.recorder import MicRecorder

    recorder = MicRecorder()
    calls = []

    def rebuild() -> None:
        calls.append("route")

    monkeypatch.setattr(recorder, "_rebuild_engine", rebuild)
    recorder._handle_config_change_notification(None)
    assert calls == ["route"]
