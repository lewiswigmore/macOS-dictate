from __future__ import annotations

import pytest


def test_is_available_returns_bool() -> None:
    from dictate.asr_mlx import MLXWhisperBackend

    assert isinstance(MLXWhisperBackend.is_available(), bool)


def test_transcribe_raises_when_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "mlx_whisper", None)
    from dictate.asr_mlx import MLXWhisperBackend

    backend = MLXWhisperBackend()
    with pytest.raises(RuntimeError, match="mlx-whisper not installed"):
        backend.transcribe(b"\x00" * 1000)


def test_transcribe_calls_mlx_whisper(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    fake = types.ModuleType("mlx_whisper")

    def transcribe(_audio, **_kwargs):
        return {
            "text": "  hello world  ",
            "segments": [{"avg_logprob": -0.3}],
            "language": "en",
        }

    fake.transcribe = transcribe  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake)
    from dictate.asr_mlx import MLXWhisperBackend

    backend = MLXWhisperBackend()
    result = backend.transcribe(b"\x00" * 1000)
    assert result.text == "hello world"
    assert 0.0 <= result.confidence <= 1.0
    assert result.language == "en"


def test_meets_confidence_threshold() -> None:
    from dictate.asr_mlx import MLXWhisperBackend, TranscriptionResult

    backend = MLXWhisperBackend()
    high = TranscriptionResult(text="ok", confidence=0.9)
    low = TranscriptionResult(text="ok", confidence=0.1)
    empty = TranscriptionResult(text="", confidence=0.9)
    assert backend.meets_confidence(high, 0.5) is True
    assert backend.meets_confidence(low, 0.5) is False
    assert backend.meets_confidence(empty, 0.5) is False
