"""Tests for the ASR backend dispatcher (faster-whisper vs apple).

These tests fake both the WhisperModel and the AppleASR so they run on any
platform and without any model downloads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from dictate.asr import ASR
from dictate.config import load_config


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.yaml").write_text(
        yaml.safe_dump(
            {
                "asr": {
                    "backend": "faster-whisper",
                    "model": "tiny.en",
                    "compute_type": "int8",
                    "language": "en",
                    "confidence_min": -1.0,
                },
                "audio": {"sample_rate": 16000},
                "logging": {"level": "INFO"},
            }
        )
    )
    monkeypatch.setenv("DICTATE_HOME", str(tmp_path))
    return load_config(tmp_path)


class FakeWhisperModel:
    instances: list[FakeWhisperModel] = []

    def __init__(self, name: str, **_kwargs: Any) -> None:
        self.name = name
        FakeWhisperModel.instances.append(self)

    def transcribe(self, _audio, **_kwargs):
        class _Seg:
            start = 0.0
            end = 1.0
            text = " hello world"
            avg_logprob = -0.2

        return iter([_Seg()]), object()


class FakeAppleASR:
    def __init__(self, _config) -> None:  # noqa: ARG002
        self.calls: list[np.ndarray] = []

    def load(self) -> None:
        pass

    def reload(self) -> None:
        pass

    def transcribe_final(self, audio, initial_prompt=None, language=None):  # noqa: ARG002
        self.calls.append(audio)
        return {
            "text": "apple says hi",
            "confidence": 0.95,
            "segments": [],
            "duration_ms": 12.0,
        }

    def transcribe_partial(self, audio, initial_prompt=None):  # noqa: ARG002
        return ""

    def meets_confidence(self, result):
        return bool(result.get("text"))


@pytest.fixture(autouse=True)
def _patch_backends(monkeypatch: pytest.MonkeyPatch):
    FakeWhisperModel.instances.clear()
    import faster_whisper

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeWhisperModel, raising=False)
    import dictate.asr_apple as apple_mod

    monkeypatch.setattr(apple_mod, "AppleASR", FakeAppleASR, raising=True)
    yield


def test_faster_whisper_dispatch(cfg) -> None:
    asr = ASR(cfg)
    assert asr.backend == "faster-whisper"
    out = asr.transcribe_final(np.zeros(16000, dtype=np.float32))
    assert "hello world" in out["text"]
    # One whisper model instantiated (lazy via _whisper property).
    assert len(FakeWhisperModel.instances) == 1
    assert FakeWhisperModel.instances[0].name == "tiny.en"


def test_apple_dispatch(cfg) -> None:
    cfg.set("asr.backend", "apple")
    asr = ASR(cfg)
    asr.reload()
    out = asr.transcribe_final(np.zeros(16000, dtype=np.float32))
    assert out["text"] == "apple says hi"
    # Apple path must not instantiate any WhisperModel.
    assert FakeWhisperModel.instances == []


def test_reload_switches_backends(cfg) -> None:
    asr = ASR(cfg)
    asr.transcribe_final(np.zeros(8000, dtype=np.float32))
    cfg.set("asr.backend", "apple")
    asr.reload()
    out = asr.transcribe_final(np.zeros(8000, dtype=np.float32))
    assert out["text"] == "apple says hi"
    cfg.set("asr.backend", "faster-whisper")
    asr.reload()
    out = asr.transcribe_final(np.zeros(8000, dtype=np.float32))
    assert "hello world" in out["text"]


def test_meets_confidence_apple_returns_true_for_any_text(cfg) -> None:
    cfg.set("asr.backend", "apple")
    asr = ASR(cfg)
    assert asr.meets_confidence({"text": "x", "confidence": 0.0}) is True
    assert asr.meets_confidence({"text": "", "confidence": 0.9}) is False


def test_meets_confidence_whisper_uses_threshold(cfg) -> None:
    cfg.set("asr.confidence_min", -0.5)
    asr = ASR(cfg)
    assert asr.meets_confidence({"confidence": -0.2}) is True
    assert asr.meets_confidence({"confidence": -0.9}) is False
