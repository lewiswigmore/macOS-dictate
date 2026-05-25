"""Smoke tests for the VAD wrapper.

These tests run against the real ``models/silero_vad.onnx`` file if present
(it lives in the user's models dir, downloaded once at first launch). When the
model isn't available — e.g. on CI — the tests are skipped rather than failed.
"""

from __future__ import annotations

import numpy as np
import pytest

from dictate.config import load_config
from dictate.vad import _MODEL_FILENAME, VAD


@pytest.fixture
def vad():
    cfg = load_config()
    if not (cfg.models_dir / _MODEL_FILENAME).exists():
        pytest.skip("silero_vad.onnx not downloaded yet")
    v = VAD(cfg)
    v.load()
    return v


def test_schema_detected(vad):
    assert vad._schema in {"v1", "v2"}
    # Both known schemas use power-of-two hidden sizes; v2 is 128, v1 is 64.
    assert vad._hidden in {64, 128}


def test_trim_silence_drops_pure_silence(vad):
    silence = np.zeros(16_000, dtype=np.float32)
    assert len(vad.trim_silence(silence)) == 0


def test_trim_silence_drops_sine_tone(vad):
    # Sine is not speech — silero should reject it as well.
    t = np.linspace(0, 1.0, 16_000, dtype=np.float32)
    tone = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    assert len(vad.trim_silence(tone)) == 0


def test_process_chunk_returns_status_dict(vad):
    silence = np.zeros(1024, dtype=np.float32)
    status = vad.process_chunk(silence)
    assert set(status) == {"prob", "speech", "endpoint"}
    assert status["endpoint"] is False
    assert isinstance(status["prob"], float)


def test_reset_clears_state(vad):
    silence = np.zeros(4096, dtype=np.float32)
    vad.process_chunk(silence)
    vad.reset()
    assert vad._speech_ms == 0
    assert vad._silence_ms == 0
    assert vad._utterance_started is False
