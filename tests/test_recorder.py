from __future__ import annotations

import numpy as np

from dictate.recorder import _resample


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
